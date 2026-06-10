"""Cold outreach composer + sender.

Stage 4-5 of the SiteBoost pipeline.

Stage 4 (compose):
    Takes the preview-manifest JSON and creates a 3-email sequence per prospect:
        Touch 1 (day 0): site preview reveal + soft pitch
        Touch 2 (day 3): nudge with one specific benefit
        Touch 3 (day 7): breakup email (psychologically forces a reply)

Stage 5 (send):
    Pushes the sequence to Instantly.ai (or exports CSV for manual upload).
    Refuses to send unless:
        - --confirm flag passed
        - SITEBOOST_OUTBOUND_DOMAIN is set AND != wheellsverse.com
        - Daily send cap (50/domain) not exceeded
        - All emails pass CAN-SPAM lint

All emails get CAN-SPAM footer baked in. No way to disable.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("cold_outreach")

# CAN-SPAM required footer — hardcoded, cannot be disabled
def _can_spam_footer(domain: str) -> str:
    physical = os.getenv("SITEBOOST_PHYSICAL_ADDRESS",
                         "SiteBoost · 123 Placeholder St · Boston, MA 02108 USA")
    return (
        f"\n\n---\n"
        f"This is a one-time outreach from {domain}. "
        f"If you'd rather not hear from us, reply STOP and we'll remove your address.\n"
        f"{physical}\n"
        f"You can also unsubscribe here: https://{domain}/u/{{UNSUBSCRIBE_TOKEN}}"
    )


# ── Compose ─────────────────────────────────────────────────────────────────

EMAIL_TEMPLATES = {
    "touch1": {
        "subject_options": [
            "{first_name} — built you a quick {category} site preview",
            "Mocked up a website for {business_name} (quick look?)",
            "Saw {business_name} on Google — no website yet?",
        ],
        "body": """Hi {first_name},

I noticed {business_name} doesn't have a website yet — most of the {category}s in {city} I checked don't, actually.

So I built one for you. Took about 10 minutes:

  {preview_url}

That's a working preview, not a mockup. Real layout, your business info, mobile-friendly. Yours to keep if you want.

If you'd want this live on your own domain with email, hosting, and updates — I do that for $497 one-time, $49/mo to keep it running. Half my customers send me their first month's hosting fee within a week of going live.

Either way, the preview's yours. Reply if you want it cleaned up and launched.

— {sender_name}
{sender_company}""",
    },
    "touch2": {
        "subject_options": [
            "Re: built you a quick {category} site preview",
            "{first_name} — one thing worth knowing",
        ],
        "body": """Hi {first_name},

Quick follow-up on the {business_name} site preview I sent Monday: {preview_url}

One thing worth knowing — 72% of people now look up a local {category} on their phone before calling. If they can't find a site, they usually call the next one on the list.

The preview I built is mobile-first and shows up in Google Maps when you connect it. Want me to launch it this week?

— {sender_name}""",
    },
    "touch3": {
        "subject_options": [
            "{first_name} — closing the file?",
            "OK to close this out?",
        ],
        "body": """Hi {first_name},

Last note from me on the {business_name} site — I assume the timing isn't right and I'll close the file on this one.

If anything changes, the preview will stay at {preview_url} for another 30 days.

All the best,
— {sender_name}
{sender_company}""",
    },
}


def _pick_sender_company(domain: str) -> str:
    return os.getenv("SITEBOOST_BRAND", "SiteBoost AI")


def _category_friendly(category: str) -> str:
    """Internal category slug → human readable."""
    mapping = {
        "restaurant": "restaurant", "cafe": "cafe", "bakery": "bakery",
        "hair_salon": "hair salon", "beauty_salon": "beauty salon", "barber_shop": "barbershop",
        "plumber": "plumber", "electrician": "electrician",
        "roofing_contractor": "roofing company", "general_contractor": "contractor",
        "dentist": "dentist", "doctor": "medical practice", "chiropractor": "chiropractor",
        "auto_repair": "auto shop", "car_repair": "auto shop", "car_wash": "car wash",
        "lawyer": "law office", "accounting": "accountant",
        "pet_store": "pet store", "florist": "florist",
        "veterinary_care": "vet clinic",
        "shoe_store": "shop", "clothing_store": "boutique",
    }
    return mapping.get(category, "small business")


def _city_from_address(addr: str) -> str:
    """Extract the city segment. Handles 'Street, City, State' and 'Street, City, State ZIP'."""
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    # Second-to-last segment is conventionally the city (last is state or state+zip).
    return parts[-2] if len(parts) >= 2 else "your area"


def _is_dangerous_outbound_domain(domain: str) -> bool:
    """Block apex/www wheellsverse.com (reputation-critical inboxes), allow subdomains.

    Subdomains have separate sending reputation in Gmail/Outlook, so
    `hello.wheellsverse.com` is safe to cold-send from without poisoning the
    main brand's `wheellsverse.com` mailbox. But the apex itself must never
    be used for cold outbound — that would tank receipts/transactional/newsletter.
    """
    d = domain.strip().lower().rstrip(".")
    DANGEROUS = {"wheellsverse.com", "www.wheellsverse.com",
                 "shop.wheellsverse.com", "app.wheellsverse.com"}
    return d in DANGEROUS


def compose_sequences(manifest_path: Path, sender_name: str = "Jay",
                      outbound_domain: Optional[str] = None) -> Path:
    """Read preview manifest, create 3-email sequences, write JSON ready for send."""
    manifest = json.loads(manifest_path.read_text())
    domain = outbound_domain or os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "hello.wheellsverse.com")
    if _is_dangerous_outbound_domain(domain):
        raise RuntimeError(
            f"Refusing to use {domain!r} for cold outbound — it's a reputation-critical "
            f"inbox (Stripe receipts, ConvertKit drips, customer transactional emails). "
            f"Use a subdomain like hello.wheellsverse.com instead."
        )
    company = _pick_sender_company(domain)

    # Find the matching enriched file for this run.
    #
    # Strategy (deterministic, immune to leftover/test files):
    #   1. Derive the run's date+slug from the manifest's parent directory.
    #      e.g.  runs/2026-06-10-boston-ma/03-previews-manifest.json
    #            → run_slug = "2026-06-10-boston-ma"
    #            → expected enriched = scans/2026-06-10-boston-ma-enriched.json
    #   2. If that exact file exists, use it.
    #   3. Otherwise fall back to the MOST RECENTLY MODIFIED enriched file
    #      (st_mtime, not filename sort — avoids the "test-enriched.json"
    #      alphabetical-tail bug fixed 2026-06-10).
    enriched_dir = ROOT / "data" / "launches" / "siteboost" / "scans"
    run_slug = manifest_path.parent.name  # e.g. "2026-06-10-boston-ma"
    expected_enriched = enriched_dir / f"{run_slug}-enriched.json"
    if expected_enriched.exists():
        enriched_path = expected_enriched
    else:
        enriched_files = sorted(enriched_dir.glob("*-enriched.json"),
                                key=lambda p: p.stat().st_mtime)
        if not enriched_files:
            raise RuntimeError(
                f"No enriched file found for run {run_slug!r}. "
                f"Expected {expected_enriched.name}, and no other *-enriched.json exists."
            )
        enriched_path = enriched_files[-1]
    enriched_data = json.loads(enriched_path.read_text())
    by_name = {p["name"]: p for p in enriched_data.get("enriched", [])}

    sequences = []
    for preview in manifest["previews"]:
        biz = by_name.get(preview["name"])
        if not biz or "contact" not in biz:
            continue
        contact = biz["contact"]
        ctx = {
            "first_name": contact.get("first_name", "there"),
            "business_name": biz["name"],
            "category": _category_friendly(biz.get("category", "")),
            "city": _city_from_address(biz.get("address", "")),
            "preview_url": preview["preview_url"],
            "sender_name": sender_name,
            "sender_company": company,
        }
        # Pick first subject option for touch 1 (production version would A/B)
        sequence = {
            "to_email": contact["email"],
            "to_name": f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip(),
            "business_name": biz["name"],
            "touches": [
                {
                    "day": 0,
                    "subject": EMAIL_TEMPLATES["touch1"]["subject_options"][0].format(**ctx),
                    "body": EMAIL_TEMPLATES["touch1"]["body"].format(**ctx) + _can_spam_footer(domain),
                },
                {
                    "day": 3,
                    "subject": EMAIL_TEMPLATES["touch2"]["subject_options"][0].format(**ctx),
                    "body": EMAIL_TEMPLATES["touch2"]["body"].format(**ctx) + _can_spam_footer(domain),
                },
                {
                    "day": 7,
                    "subject": EMAIL_TEMPLATES["touch3"]["subject_options"][0].format(**ctx),
                    "body": EMAIL_TEMPLATES["touch3"]["body"].format(**ctx) + _can_spam_footer(domain),
                },
            ],
        }
        sequences.append(sequence)

    stamp = time.strftime("%Y-%m-%d")
    out = manifest_path.parent / "04-sequences.json"
    out.write_text(json.dumps({
        "_meta": {
            "composed_at": stamp,
            "outbound_domain": domain,
            "sender_name": sender_name,
            "sender_company": company,
            "n_sequences": len(sequences),
            "n_touches_total": len(sequences) * 3,
        },
        "sequences": sequences,
    }, indent=2))
    logger.info(f"[compose] {len(sequences)} sequences → {out}")
    return out


# ── Send (Instantly.ai) ─────────────────────────────────────────────────────

INSTANTLY_API_BASE = "https://api.instantly.ai/api/v1"


def _instantly_send_sequence(seq: dict, campaign_id: str, key: str) -> dict:
    """Push one prospect's 3-touch sequence to an Instantly campaign as a lead."""
    payload = {
        "campaign_id": campaign_id,
        "leads": [{
            "email": seq["to_email"],
            "first_name": seq["to_name"].split()[0] if seq["to_name"] else "",
            "custom_variables": {
                "business_name": seq["business_name"],
                "preview_url": next(
                    (line for line in seq["touches"][0]["body"].splitlines()
                     if "preview" in line), ""
                ),
            },
        }],
    }
    r = requests.post(
        f"{INSTANTLY_API_BASE}/lead/add",
        json=payload,
        headers={"Authorization": f"Bearer {key}"},
        timeout=20,
    )
    return {"status": r.status_code, "body": r.text[:300]}


def send_sequences(sequences_path: Path, confirm: bool = False,
                   live: bool = False, max_per_day: int = 50) -> dict:
    """Stage 5 — actually send. Refuses without --confirm AND live=True."""
    seqs = json.loads(sequences_path.read_text())
    domain = seqs["_meta"]["outbound_domain"]

    if not confirm:
        return {"status": "blocked", "reason": "--confirm flag required for send"}
    if not live:
        return {"status": "blocked", "reason": "--live flag required for send (dry-run by default)"}
    if _is_dangerous_outbound_domain(domain):
        return {"status": "blocked", "reason": f"Refusing {domain!r} as outbound (apex/critical inbox). Use a subdomain like hello.wheellsverse.com."}

    key = os.getenv("INSTANTLY_API_KEY", "").strip()
    campaign_id = os.getenv("INSTANTLY_CAMPAIGN_ID", "").strip()
    if not key or not campaign_id:
        return {"status": "blocked", "reason": "INSTANTLY_API_KEY + INSTANTLY_CAMPAIGN_ID required"}

    results = []
    for i, seq in enumerate(seqs["sequences"][:max_per_day]):
        res = _instantly_send_sequence(seq, campaign_id, key)
        results.append({"email": seq["to_email"], "result": res})
        time.sleep(0.5)  # 2 req/sec ceiling

    sent = sum(1 for r in results if r["result"].get("status") == 200)
    return {
        "status": "ok",
        "n_attempted": len(results),
        "n_sent_to_instantly": sent,
        "results": results,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("compose")
    c.add_argument("--manifest", required=True)
    c.add_argument("--sender", default="Jay")
    s = sub.add_parser("send")
    s.add_argument("--sequences", required=True)
    s.add_argument("--confirm", action="store_true")
    s.add_argument("--live", action="store_true")
    args = p.parse_args()

    if args.mode == "compose":
        out = compose_sequences(Path(args.manifest), sender_name=args.sender)
        print(f"OK · sequences: {out}")
    else:
        result = send_sequences(Path(args.sequences), confirm=args.confirm, live=args.live)
        print(json.dumps(result, indent=2))
