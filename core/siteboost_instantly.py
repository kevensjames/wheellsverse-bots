"""Auto-create + manage SiteBoost's Instantly campaign via the v2 API.

Eliminates the manual UI step where the operator has to:
    1. Create a campaign in Instantly's dashboard
    2. Write 3-touch templates from scratch (or copy from our docs)
    3. Find the campaign UUID in the URL
    4. Set INSTANTLY_CAMPAIGN_ID env var
    5. Redeploy

Now they just hit a button and we do all of that for them. The auto-created
campaign has SiteBoost-specific templates that use {{first_name}}, {{company_name}},
and {{personalization}} (where personalization carries the issue-aware opener
+ preview URL packed together by compose_sequences).

Active campaign UUID is stored in active_campaign.json on the persistent volume,
read by send_sequences as a override over INSTANTLY_CAMPAIGN_ID env var. This
removes the need to ever set the env var manually.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import requests

logger = logging.getLogger("siteboost_instantly")

ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ACTIVE = ROOT / "data" / "launches" / "siteboost" / "active_campaign.json"
ACTIVE_PATH = Path(os.getenv("SITEBOOST_ACTIVE_CAMPAIGN_PATH", str(_DEFAULT_ACTIVE)))

INSTANTLY_V2_BASE = "https://api.instantly.ai/api/v2"


def get_active_campaign_id() -> str:
    """Return the campaign UUID send_sequences should use.

    Priority: file override > INSTANTLY_CAMPAIGN_ID env var > empty.
    File override is set by /instantly/auto-create-campaign; env var is the legacy
    operator-set value. File wins so auto-created campaigns immediately become active.
    """
    if ACTIVE_PATH.exists():
        try:
            data = json.loads(ACTIVE_PATH.read_text())
            cid = data.get("id", "")
            if cid:
                return cid
        except Exception:
            pass
    return os.getenv("INSTANTLY_CAMPAIGN_ID", "").strip()


def get_active_campaign_info() -> dict:
    """Return the active campaign's full metadata if file-overridden, else {} ."""
    if ACTIVE_PATH.exists():
        try:
            return json.loads(ACTIVE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_active(campaign: dict) -> None:
    ACTIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(campaign, indent=2))
    tmp.replace(ACTIVE_PATH)


def _siteboost_sequences() -> list[dict]:
    """The SiteBoost 3-touch sequence definition Instantly will execute.

    Uses Instantly lead variables: {{first_name}}, {{company_name}}, {{personalization}}.
    The {{personalization}} variable is set per-lead by compose_sequences and carries
    the issue-aware opener + preview URL — that's how each business gets uniquely
    relevant copy without us needing a separate campaign per issue type.
    """
    touch1_body = (
        "Hi {{first_name}},\n\n"
        "{{personalization}}\n\n"
        "If you'd want me to put this live on your own domain with email + hosting "
        "included, I do the fix for $297 one-time, $49/mo to keep it running. Most "
        "customers see a noticeable bounce-rate drop within a week.\n\n"
        "No pressure — the preview is yours regardless. Reply if you want to talk.\n\n"
        "— Jay\nSiteBoost AI"
    )
    touch2_body = (
        "Hi {{first_name}},\n\n"
        "Quick follow-up on the {{company_name}} site preview I sent earlier this "
        "week.\n\n"
        "One thing worth knowing — sites with technical issues lose 13-50% of "
        "would-be customers depending on the problem.\n\n"
        "Want me to launch the fix this week?\n\n"
        "— Jay"
    )
    touch3_body = (
        "Hi {{first_name}},\n\n"
        "Last note from me on the {{company_name}} site — I assume the timing isn't "
        "right and I'll close the file on this one.\n\n"
        "If anything changes, the preview will stay live for another 30 days.\n\n"
        "All the best,\n— Jay\nSiteBoost AI"
    )
    return [{
        "steps": [
            {
                "type": "email",
                "delay": 0,
                "delay_unit": "days",
                "pre_delay_unit": "days",
                "variants": [{
                    "subject": "{{first_name}} — quick fix idea for {{company_name}}",
                    "body": touch1_body,
                }],
            },
            {
                "type": "email",
                "delay": 3,
                "delay_unit": "days",
                "pre_delay_unit": "days",
                "variants": [{
                    "subject": "",  # empty = thread reply (Instantly auto-prefixes Re:)
                    "body": touch2_body,
                }],
            },
            {
                "type": "email",
                "delay": 4,
                "delay_unit": "days",
                "pre_delay_unit": "days",
                "variants": [{
                    "subject": "{{first_name}} — closing the file?",
                    "body": touch3_body,
                }],
            },
        ]
    }]


def create_siteboost_campaign(name: str = "SiteBoost Outbound (auto)") -> dict:
    """Create the campaign in Instantly + save its UUID to the active file.

    Returns the full Instantly response on success. On failure, returns a dict
    with status=failed + error detail (never raises — caller controls UX).
    """
    key = os.getenv("INSTANTLY_API_KEY", "").strip()
    if not key:
        return {"status": "failed", "error": "INSTANTLY_API_KEY not set"}

    # Step 1: create the campaign (just metadata + schedule — sequences come next)
    create_payload = {
        "name": name,
        "campaign_schedule": {
            "schedules": [{
                "name": "Weekdays",
                "timing": {"from": "09:00", "to": "17:00"},
                "days": {"0": False, "1": True, "2": True, "3": True, "4": True,
                         "5": True, "6": False},
                "timezone": "Etc/GMT+12",  # Etc/GMT+12 is one of Instantly's allowed values
            }]
        },
        "daily_limit": 5,  # Conservative start; operator can raise after warmup
        "stop_on_reply": True,
        "open_tracking": True,
    }
    try:
        r = requests.post(
            f"{INSTANTLY_V2_BASE}/campaigns",
            json=create_payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
    except Exception as e:
        return {"status": "failed", "error": f"create POST failed: {e!s}"}
    if r.status_code not in (200, 201):
        return {"status": "failed", "http": r.status_code, "body": r.text[:400]}

    body = r.json()
    campaign_id = body.get("id", "")
    if not campaign_id:
        return {"status": "failed", "error": "Instantly returned no id"}

    # Step 2: patch the campaign with the SiteBoost sequence templates
    try:
        patch_resp = requests.patch(
            f"{INSTANTLY_V2_BASE}/campaigns/{campaign_id}",
            json={"sequences": _siteboost_sequences()},
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
    except Exception as e:
        return {"status": "partial", "campaign_id": campaign_id,
                "error": f"created but sequence PATCH failed: {e!s}"}
    if patch_resp.status_code not in (200, 201):
        return {"status": "partial", "campaign_id": campaign_id,
                "error": f"created but sequence PATCH HTTP {patch_resp.status_code}: {patch_resp.text[:200]}"}

    # Step 3: persist the active campaign on disk so send_sequences uses it
    info = {
        "id": campaign_id,
        "name": name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "url": f"https://app.instantly.ai/app/campaign/{campaign_id}",
    }
    _save_active(info)
    logger.info(f"[instantly] auto-created campaign {campaign_id} ({name!r})")
    return {"status": "ok", **info, "instantly_response": body}


def clear_active_campaign() -> bool:
    """Forget the auto-created campaign override; fall back to env var."""
    if ACTIVE_PATH.exists():
        ACTIVE_PATH.unlink()
        return True
    return False


def refresh_active_campaign_templates() -> dict:
    """PATCH the live active campaign with the latest sequences from code.

    Use when _siteboost_sequences() has been updated but you don't want to
    create a NEW campaign (which would orphan existing leads + send history).
    Mutates the campaign in Instantly in-place — same UUID, same leads,
    refreshed copy.

    Returns {"status":"ok", "campaign_id": ...} on success, or {"status":"failed",
    "error": ...} otherwise. Never raises.
    """
    key = os.getenv("INSTANTLY_API_KEY", "").strip()
    if not key:
        return {"status": "failed", "error": "INSTANTLY_API_KEY not set"}
    cid = get_active_campaign_id()
    if not cid:
        return {"status": "failed",
                "error": "no active campaign — run /instantly/auto-create-campaign first"}
    try:
        resp = requests.patch(
            f"{INSTANTLY_V2_BASE}/campaigns/{cid}",
            json={"sequences": _siteboost_sequences()},
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
    except Exception as e:
        return {"status": "failed", "campaign_id": cid,
                "error": f"PATCH failed: {e!s}"}
    if resp.status_code not in (200, 201):
        return {"status": "failed", "campaign_id": cid,
                "http": resp.status_code, "body": resp.text[:400]}
    logger.info(f"[instantly] refreshed templates on campaign {cid}")
    return {"status": "ok", "campaign_id": cid,
            "url": f"https://app.instantly.ai/app/campaign/{cid}"}


def set_campaign_daily_limit(limit: int) -> dict:
    """PATCH the live active campaign's daily_limit field.

    Drives the warmup ramp (siteboost_warmup) — each ramp step calls this
    to raise the cap. Capped at [1, 500] to prevent typos hitting Instantly's
    upper bounds. Never raises.
    """
    if not isinstance(limit, int) or limit < 1 or limit > 500:
        return {"status": "failed", "error": f"limit must be int in [1, 500], got {limit!r}"}
    key = os.getenv("INSTANTLY_API_KEY", "").strip()
    if not key:
        return {"status": "failed", "error": "INSTANTLY_API_KEY not set"}
    cid = get_active_campaign_id()
    if not cid:
        return {"status": "failed", "error": "no active campaign"}
    try:
        resp = requests.patch(
            f"{INSTANTLY_V2_BASE}/campaigns/{cid}",
            json={"daily_limit": limit},
            headers={"Authorization": f"Bearer {key}"},
            timeout=20,
        )
    except Exception as e:
        return {"status": "failed", "campaign_id": cid, "error": f"PATCH failed: {e!s}"}
    if resp.status_code not in (200, 201):
        return {"status": "failed", "campaign_id": cid,
                "http": resp.status_code, "body": resp.text[:400]}
    logger.info(f"[instantly] set daily_limit={limit} on campaign {cid}")
    return {"status": "ok", "campaign_id": cid, "daily_limit": limit}
