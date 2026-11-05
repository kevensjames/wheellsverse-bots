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

list_replies reads one campaign's received emails for the daily numbers board
(core/board/connectors/instantly_sync.py). It only reads: it never changes the
inbox.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Optional

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


# ─── Received emails, for the daily numbers board (read only) ───────────────
#
# GET /api/v2/emails, one campaign at a time: its received emails in every
# Unibox tab, created in a window, 100 a page, following next_starting_after
# exactly as Instantly sends it. Instantly allows this endpoint 20 calls a
# minute, so every call goes through one pacer for the whole process: one call
# per 3.5 seconds at most. A 429 waits for Retry-After, else a short backoff,
# never more than 30 seconds and at most 3 times. A 5xx or a network error is
# retried after 2, 4 and 8 seconds. Nothing here changes the inbox: no PATCH,
# no DELETE, no mark-as-read.

EMAILS_URL = f"{INSTANTLY_V2_BASE}/emails"
EMAILS_EVERY = 3.5        # seconds between two /emails calls (Instantly allows 20 a minute)
PAGE_SIZE = 100           # Instantly's largest page
MAX_PAGES = 100           # per campaign and window; more means the filters were not applied
READ_TIMEOUT = 30.0       # seconds, each call
READ_RETRIES = 3          # retries after a 429, a 5xx or a network error
RETRY_AFTER_CAP = 30.0    # seconds: the longest wait after a 429
_RATE_LIMIT_WAITS = (15.0, 30.0, 30.0)   # after a 429 that names no wait
_SERVER_WAITS = (2.0, 4.0, 8.0)          # after a 5xx, a timeout or a lost connection

# Tests mount a fake requests adapter here and replace the clock; None means the real network.
_adapter = None
_sleep = time.sleep
_clock = time.monotonic
_pace_lock = threading.Lock()
_last_call: Optional[float] = None       # _clock() at the last /emails call from this process

_KEY_RE = re.compile(r"[A-Za-z0-9+/=_.:-]{16,512}")
_CAMPAIGN_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ADDRESS_RE = re.compile(r"[^@\s<>,;]{1,256}@[^@\s<>,;]{1,255}")


class InstantlyError(Exception):
    """A read from Instantly failed. The message is a short plain sentence with
    the HTTP status. It never holds the key, a URL or Instantly's own answer,
    which can quote what it was sent."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def api_key() -> Optional[str]:
    """INSTANTLY_API_KEY when it can go in a Bearer header as it is (16 to 512
    letters, digits and + / = _ . : -); None otherwise."""
    key = os.getenv("INSTANTLY_API_KEY", "").strip()
    return key if _KEY_RE.fullmatch(key) else None


def campaign_uuid(value) -> str:
    """An Instantly campaign id (a UUID), lower-cased. ValueError otherwise; the
    message never quotes the value."""
    text = value.strip() if isinstance(value, str) else ""
    if not _CAMPAIGN_RE.fullmatch(text):
        raise ValueError("not an Instantly campaign id (a UUID)")
    return text.lower()


def _pace() -> None:
    """Wait until EMAILS_EVERY seconds have passed since this process's last
    /emails call, then take the slot. One lock for the process, so two syncs
    never share Instantly's limit without knowing it."""
    global _last_call
    with _pace_lock:
        if _last_call is not None:
            wait = _last_call + EMAILS_EVERY - _clock()
            if wait > 0:
                _sleep(wait)
        _last_call = _clock()


def _retry_after(r: requests.Response, attempt: int) -> float:
    """Seconds to wait after a 429: Retry-After (seconds or a date) when it is
    readable, else a short backoff; at least 1 second, at most 30."""
    value = (r.headers.get("Retry-After") or "").strip()
    seconds: Optional[float] = None
    if value:
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, IndexError, OverflowError):
                seconds = None
    if seconds is None or math.isnan(seconds):      # absent or unreadable
        seconds = _RATE_LIMIT_WAITS[min(attempt, len(_RATE_LIMIT_WAITS) - 1)]
    return min(max(seconds, 1.0), RETRY_AFTER_CAP)


def _refusal(status: int, campaign: str) -> str:
    if status == 401:
        return "Instantly refused the API key (HTTP 401): check INSTANTLY_API_KEY"
    if status == 402:
        return "Instantly refused the request (HTTP 402): the plan may not include API access"
    if status == 403:
        return "Instantly refused the request (HTTP 403): the API key needs the emails:read scope"
    if status == 404:
        return f"Instantly does not know campaign {campaign[:8]} (HTTP 404)"
    return f"Instantly answered the reply list with HTTP {status}"


def _get_page(session: requests.Session, params: list, campaign: str) -> dict:
    """One /emails page: paced, with bounded retries. Raises InstantlyError."""
    for attempt in range(READ_RETRIES + 1):
        _pace()
        try:
            r = session.get(EMAILS_URL, params=params, timeout=READ_TIMEOUT, allow_redirects=False)
        except requests.RequestException as e:
            # The exception's own text can hold the URL; only its type is kept.
            if attempt == READ_RETRIES:
                raise InstantlyError(f"Instantly unreachable ({type(e).__name__}); "
                                     "the next run tries again") from None
            _sleep(_SERVER_WAITS[attempt])
            continue
        status = r.status_code
        if status == 429 or status >= 500:
            if attempt == READ_RETRIES:
                if status == 429:
                    raise InstantlyError("Instantly kept limiting the reply list (HTTP 429); "
                                         "the next run tries again", status)
                raise InstantlyError(f"Instantly failed (HTTP {status}); the next run tries again", status)
            _sleep(_retry_after(r, attempt) if status == 429 else _SERVER_WAITS[attempt])
            continue
        if status != 200:
            raise InstantlyError(_refusal(status, campaign), status)
        try:
            body = r.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise InstantlyError("Instantly answered the reply list without JSON", status)
        return body
    raise InstantlyError("Instantly failed")         # not reached


def _iso_ms(value: datetime) -> str:
    """UTC with milliseconds and a Z, as Instantly writes times: 2026-11-02T11:55:00.000Z."""
    utc = value.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def _text(value, longest: int = 255) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.replace("\x00", "").strip()
    return value[:longest] if value else None


def _address(value) -> Optional[str]:
    """One email address, lower-cased, from 'a@b.example' or 'Name <a@b.example>'."""
    if not isinstance(value, str):
        return None
    _, found = parseaddr(value.replace("\x00", ""))
    found = found.strip().lower()
    return found if _ADDRESS_RE.fullmatch(found) else None


def _addresses(value) -> tuple:
    """The addresses in a comma-separated list (or a list of strings), lower-cased."""
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = [v for v in value if isinstance(v, str)]
    else:
        return ()
    found: list[str] = []
    for _, addr in getaddresses([v.replace("\x00", "") for v in values]):
        addr = addr.strip().lower()
        if _ADDRESS_RE.fullmatch(addr) and addr not in found:
            found.append(addr)
    return tuple(found)


def _json_address(value) -> Optional[str]:
    """The first address of a *_json field ([{"address": ..., "name": ...}])."""
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return _address(value[0].get("address"))
    if isinstance(value, dict):
        return _address(value.get("address"))
    return None


def _when(value) -> Optional[datetime]:
    """An ISO 8601 time as an aware UTC datetime; a time with no offset is UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        ts = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _code(value) -> Optional[int]:
    """A numeric type code (ue_type, i_status) as an int; None when absent or not whole."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _flag(value) -> Optional[bool]:
    """A 0/1 flag (is_auto_reply): True, False, or None when absent or unclear."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("0", "1", "true", "false"):
        return value.strip().lower() in ("1", "true")
    return None


def _reply(item) -> Optional[dict]:
    """The fields of one listed email that the board needs, as plain values;
    None without a usable id. The body is not kept."""
    if not isinstance(item, dict):
        return None
    eid = item.get("id")
    if not isinstance(eid, str) or not eid.strip() or len(eid) > 255 or "\x00" in eid:
        return None
    return {"id": eid,
            "campaign_id": _text(item.get("campaign_id")),
            "lead": _address(item.get("lead")),
            "lead_id": _text(item.get("lead_id")),
            "from_address": _address(item.get("from_address_email")) or _json_address(item.get("from_address_json")),
            "to_addresses": _addresses(item.get("to_address_email_list")),
            "eaccount": _address(item.get("eaccount")),
            "subject": _text(item.get("subject"), 998),
            "timestamp_created": _when(item.get("timestamp_created")),
            "timestamp_email": _when(item.get("timestamp_email")),
            "message_id": _text(item.get("message_id")),
            "thread_id": _text(item.get("thread_id")),
            "ue_type": _code(item.get("ue_type")),
            "i_status": _code(item.get("i_status")),
            "is_auto_reply": _flag(item.get("is_auto_reply"))}


def _sent_by_us(item: dict, reply: dict) -> bool:
    """Whether a listed email is one we sent: marked sent, or from our own
    mailbox to someone else. The list asks for received emails only; this
    keeps a sent one out if Instantly mixes it in anyway."""
    kind = item.get("email_type")
    if isinstance(kind, str) and kind.strip().lower() == "sent":
        return True
    ours, to = reply["eaccount"], reply["to_addresses"]
    return bool(ours) and reply["from_address"] == ours and bool(to) and ours not in to


def list_replies(campaign_id: str, since: datetime, until: datetime,
                 stats: Optional[dict] = None) -> list[dict]:
    """The received emails of one Instantly campaign created in [since, until),
    across all pages, as plain dicts:

      id, campaign_id, lead_id, message_id, thread_id, subject   strings or None
      lead, from_address, eaccount       addresses, lower-cased, or None
      to_addresses                       a tuple of addresses
      timestamp_created, timestamp_email aware UTC datetimes or None
      ue_type, i_status                  ints or None
      is_auto_reply                      True, False, or None when Instantly does not say

    Read only: GET /api/v2/emails with campaign_id, email_type=received,
    mode=emode_all (every Unibox tab), limit=100 and the window as
    min_timestamp_created and max_timestamp_created, then each
    next_starting_after exactly as sent, until a page is empty or brings no
    new cursor. Paced for the whole process: one call per 3.5 seconds at most.

    Instantly does not document everything, so these are left out: an email we
    sent, another campaign's email, one created outside [since, until) by its
    timestamp_created, and a repeat. An email without a timestamp_created is
    kept, since Instantly applied the window. When `stats` is a dict it gets
    the counts: pages, listed, kept, sent_by_us, other_campaign,
    outside_window, undated, no_id, duplicates.

    Raises InstantlyError when Instantly refuses or fails (a plain sentence,
    never the key) and ValueError for a campaign id that is not a UUID or a
    time without a zone."""
    cid = campaign_uuid(campaign_id)
    for name, value in (("since", since), ("until", until)):
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError(f"{name} must be a datetime with a time zone")
    key = api_key()
    if key is None:
        raise InstantlyError("INSTANTLY_API_KEY is not set or not usable")
    since_utc, until_utc = since.astimezone(timezone.utc), until.astimezone(timezone.utc)
    counts = dict.fromkeys(("pages", "listed", "kept", "sent_by_us", "other_campaign", "outside_window",
                            "undated", "no_id", "duplicates"), 0)
    base = [("campaign_id", cid), ("email_type", "received"), ("mode", "emode_all"),
            ("limit", str(PAGE_SIZE)), ("min_timestamp_created", _iso_ms(since_utc)),
            ("max_timestamp_created", _iso_ms(until_utc))]
    found: list[dict] = []
    seen_ids: set[str] = set()
    used: set[str] = set()
    cursor: Optional[str] = None
    with requests.Session() as session:
        if _adapter is not None:
            session.mount("https://", _adapter)
            session.mount("http://", _adapter)
        session.headers.update({"Authorization": f"Bearer {key}", "Accept": "application/json"})
        for _ in range(MAX_PAGES):
            body = _get_page(session, base + ([("starting_after", cursor)] if cursor is not None else []), cid)
            counts["pages"] += 1
            items = body.get("items")
            if not isinstance(items, list):
                raise InstantlyError("Instantly answered the reply list without a list of emails")
            for item in items:
                counts["listed"] += 1
                reply = _reply(item)
                if reply is None:
                    counts["no_id"] += 1
                    continue
                if reply["id"] in seen_ids:
                    counts["duplicates"] += 1
                    continue
                seen_ids.add(reply["id"])
                if _sent_by_us(item, reply):
                    counts["sent_by_us"] += 1
                    continue
                if (reply["campaign_id"] or "").lower() != cid:
                    counts["other_campaign"] += 1
                    continue
                created = reply["timestamp_created"]
                if created is None:
                    counts["undated"] += 1
                elif not since_utc <= created < until_utc:
                    counts["outside_window"] += 1
                    continue
                found.append(reply)
                counts["kept"] += 1
            nxt = body.get("next_starting_after")
            if isinstance(nxt, int) and not isinstance(nxt, bool):
                nxt = str(nxt)
            if not items or not isinstance(nxt, str) or not nxt.strip() or nxt in used:
                break
            used.add(nxt)
            cursor = nxt
        else:
            raise InstantlyError(f"Instantly kept sending pages for campaign {cid[:8]}: "
                                 f"stopped after {MAX_PAGES}")
    if stats is not None:
        stats.update(counts)
    return found
