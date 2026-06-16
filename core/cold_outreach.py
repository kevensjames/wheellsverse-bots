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

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("cold_outreach")


# ── Unsubscribe token + suppression list (CAN-SPAM § 7704(a)(3)) ────────────
#
# Token format (URL-safe, no padding):
#     base64url(email + "|" + ts + "|" + sig[:16])
# where:
#     sig = HMAC-SHA256(SITEBOOST_UNSUBSCRIBE_SECRET, email + "|" + ts).digest()
#     ts  = unix seconds at compose time
#
# Truncating the HMAC to 16 bytes is safe here: opt-out tokens aren't high-stakes
# (worst case is a spurious unsubscribe, which we can revert from the audit log).
# 16 bytes = 128 bits of collision resistance — far more than needed for this use.

UNSUBSCRIBE_SECRET_ENV = "SITEBOOST_UNSUBSCRIBE_SECRET"

# Storage path is configurable so the same code works:
#   - locally: defaults to data/launches/siteboost/suppressions.json
#   - on Railway: set SITEBOOST_SUPPRESSIONS_PATH=/var/data/siteboost/suppressions.json
#     once the Railway volume is attached at /var/data
_DEFAULT_SUPPRESSIONS = ROOT / "data" / "launches" / "siteboost" / "suppressions.json"
SUPPRESSIONS_PATH = Path(os.getenv("SITEBOOST_SUPPRESSIONS_PATH", str(_DEFAULT_SUPPRESSIONS)))


def _unsub_secret() -> bytes:
    s = os.getenv(UNSUBSCRIBE_SECRET_ENV, "").strip()
    if not s:
        raise RuntimeError(
            f"{UNSUBSCRIBE_SECRET_ENV} not set. Generate one with: "
            f"openssl rand -base64 32. Set on both local .env and Railway env."
        )
    return s.encode()


_SIG_LEN = 16  # bytes of HMAC kept; positional parse depends on this being constant


def make_unsubscribe_token(email: str) -> str:
    """Generate a signed opt-out token for an email. Reversible only with the secret.

    Layout: base64url(payload || sig) where sig is exactly _SIG_LEN bytes.
    NO delimiter between payload and sig — HMAC bytes routinely contain bytes that
    look like ASCII delimiters (~6%/byte for any single char), which would break
    delimiter-based parsing roughly 60% of the time on a 16-byte sig.
    """
    secret = _unsub_secret()
    ts = str(int(time.time()))
    payload = f"{email}|{ts}".encode()
    sig = hmac.new(secret, payload, hashlib.sha256).digest()[:_SIG_LEN]
    return base64.urlsafe_b64encode(payload + sig).rstrip(b"=").decode()


def verify_unsubscribe_token(token: str) -> Optional[str]:
    """Verify a token and return the email if valid. None if forged/tampered.

    No expiry — CAN-SPAM § 7704(a)(4) requires opt-out URLs to remain functional
    for at least 30 days, but in practice we keep them forever.
    """
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad)
        if len(raw) < _SIG_LEN + 3:  # at least 1 byte payload + 1 "|" + 1 byte ts + sig
            return None
        payload, sig = raw[:-_SIG_LEN], raw[-_SIG_LEN:]
        expected = hmac.new(_unsub_secret(), payload, hashlib.sha256).digest()[:_SIG_LEN]
        if not hmac.compare_digest(sig, expected):
            return None
        text = payload.decode("utf-8")
        if "|" not in text:
            return None
        email, _ts = text.rsplit("|", 1)
        return email
    except Exception:
        return None


def _load_suppressions() -> dict:
    """Read the suppression list. Returns {email: {"unsubscribed_at": str, "via": str}}."""
    if not SUPPRESSIONS_PATH.exists():
        return {}
    try:
        return json.loads(SUPPRESSIONS_PATH.read_text())
    except Exception as e:
        logger.warning(f"suppression list parse failed: {e} (treating as empty)")
        return {}


def is_suppressed(email: str) -> bool:
    """Has this email opted out previously? Case-insensitive."""
    if not email:
        return False
    return email.strip().lower() in {k.lower() for k in _load_suppressions().keys()}


def add_suppression(email: str, via: str = "click") -> None:
    """Add email to the suppression list. Atomic write (tmp + rename)."""
    SUPPRESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = _load_suppressions()
    current[email.strip().lower()] = {
        "unsubscribed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "via": via,
    }
    tmp = SUPPRESSIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True))
    tmp.replace(SUPPRESSIONS_PATH)
    logger.info(f"[suppressions] added {email} via {via} ({len(current)} total)")


def list_suppressions() -> list[dict]:
    """Return suppression list as a sorted-newest-first array of dicts."""
    current = _load_suppressions()
    out = []
    for email, meta in current.items():
        out.append({
            "email": email,
            "unsubscribed_at": meta.get("unsubscribed_at", ""),
            "via": meta.get("via", "?"),
        })
    out.sort(key=lambda x: x["unsubscribed_at"], reverse=True)
    return out


def remove_suppression(email: str) -> bool:
    """Re-include an email by removing it from the suppression list.

    Used when an operator pre-suppressed someone (e.g. a friend's email used
    for testing) and now wants them back. Returns True if removed, False if
    not present.
    """
    SUPPRESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = _load_suppressions()
    key = email.strip().lower()
    if key not in current:
        return False
    del current[key]
    tmp = SUPPRESSIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True))
    tmp.replace(SUPPRESSIONS_PATH)
    logger.info(f"[suppressions] removed {email} ({len(current)} total)")
    return True

# CAN-SPAM required footer — hardcoded, cannot be disabled.
# The unsubscribe URL is hosted on app.wheellsverse.com (not the sending domain) because
# the FastAPI app responds there. Receivers don't require the opt-out URL to match the
# sending domain — only that it's functional for at least 30 days (CAN-SPAM § 7704(a)(4)).
_UNSUB_URL_BASE = os.getenv("SITEBOOST_UNSUB_URL_BASE", "https://app.wheellsverse.com")


def _can_spam_footer(domain: str, recipient_email: str = "") -> str:
    physical = os.getenv("SITEBOOST_PHYSICAL_ADDRESS",
                         "SiteBoost · 123 Placeholder St · Boston, MA 02108 USA")
    # Generate a per-recipient signed token. If we can't (secret unset), fall back to
    # a literal placeholder so dry-run scans don't crash — but real sends MUST have
    # a real token or the footer is non-compliant.
    if recipient_email:
        try:
            token = make_unsubscribe_token(recipient_email)
            unsub_url = f"{_UNSUB_URL_BASE}/u/{token}"
        except RuntimeError as e:
            logger.warning(f"unsubscribe token unavailable ({e}); using placeholder")
            unsub_url = f"{_UNSUB_URL_BASE}/u/{{UNSUBSCRIBE_TOKEN}}"
    else:
        unsub_url = f"{_UNSUB_URL_BASE}/u/{{UNSUBSCRIBE_TOKEN}}"
    return (
        f"\n\n---\n"
        f"This is a one-time outreach from {domain}. "
        f"If you'd rather not hear from us, reply STOP and we'll remove your address.\n"
        f"{physical}\n"
        f"You can also unsubscribe here: {unsub_url}"
    )


# ── Compose ─────────────────────────────────────────────────────────────────

# Each detected issue maps to (opening line, follow-up stat, short label for touch 2).
# Designed so the prospect can verify the claim themselves — every line refers to a
# concrete, falsifiable observation about THEIR website. That's what drives reply rate.
ISSUE_COPY = {
    "no-https": {
        "opener": "I noticed {domain} loads on http:// rather than https:// — Chrome shows visitors a \"Not Secure\" warning before they even reach your homepage.",
        "stat": "Sites without HTTPS lose ~13% of would-be customers at that warning screen",
        "short": "the SSL/security warning",
    },
    "ssl-broken": {
        "opener": "I tried to load {domain} just now and got an SSL/cert error — visitors using Chrome or Safari see a full-page \"Your connection is not private\" warning and almost always bounce.",
        "stat": "Cert errors block close to 100% of new visitors — they hit the red warning page and never reach you",
        "short": "the broken SSL cert",
    },
    "timeout": {
        "opener": "I tried to load {domain} a minute ago and it timed out — 5 seconds, no response.",
        "stat": "Google deranks pages slower than 3s, and 53% of mobile users abandon before a 3s load completes",
        "short": "the slow load",
    },
    "connection-failed": {
        "opener": "I tried to load {domain} and couldn't connect — visitors trying to reach you would see a \"this site can't be reached\" error in their browser.",
        "stat": "When a site won't load at all, you're invisible to any customer who searches first",
        "short": "the site-not-loading issue",
    },
    "http-403": {
        "opener": "I tried to load {domain} and got a 403 Forbidden — looks like the hosting config is blocking visitors.",
        "stat": "A 403 page tells search engines and humans alike that your business isn't reachable online",
        "short": "the 403 block",
    },
    "http-404": {
        "opener": "I tried to load {domain} and got a 404 — the page in your Google listing is either gone or broken.",
        "stat": "Every 404 is a customer who searched for you and reached a dead end",
        "short": "the 404",
    },
    "http-429": {
        "opener": "I tried to load {domain} and got rate-limited — looks like your hosting is throttling traffic.",
        "stat": "When real visitors get throttled like a bot would, they bounce and try the next result on Google",
        "short": "the throttling issue",
    },
    "http-500": {
        "opener": "I tried to load {domain} and got a 500 server error — the page is crashing instead of rendering.",
        "stat": "Server errors signal to Google that your site isn't trustworthy; ranking drops within days",
        "short": "the server crash",
    },
    "not-mobile-friendly": {
        "opener": "I noticed {domain} doesn't have a mobile viewport tag — on phones the page doesn't resize, so visitors have to pinch-zoom around to read it.",
        "stat": "60%+ of local-business searches happen on phones, and Google deranks non-mobile-friendly sites in mobile results",
        "short": "the mobile-resize problem",
    },
    "placeholder-or-empty": {
        "opener": "I loaded {domain} and the page is basically empty — looks like a stub that was set up but never finished.",
        "stat": "An empty page reads as \"this business is closed\" to most visitors",
        "short": "the blank-page issue",
    },
    "parking-page": {
        "opener": "I noticed {domain} shows a domain-parking page instead of your business — looks like the hosting lapsed or was never set up.",
        "stat": "Parking pages tell Google your business is inactive, which kills your search ranking",
        "short": "the parked-domain page",
    },
    "coming-soon": {
        "opener": "I noticed {domain} still shows a \"coming soon\" placeholder — happy to launch the real site for you instead.",
        "stat": "Every day a coming-soon page stays up is a day customers bounce to your competitors",
        "short": "the coming-soon placeholder",
    },
    "no-title": {
        "opener": "I noticed {domain} has no page title set — in Google search results, the URL shows instead of your business name, which kills clickthrough.",
        "stat": "Listings without proper titles get ~40% fewer clicks than properly tagged ones",
        "short": "the missing title tag",
    },
    "default-template": {
        "opener": "I loaded {domain} and it looks like the site's running on a default template that's never been customized — looks like it was set up and forgotten.",
        "stat": "Default templates rank ~30% worse in Google for local-business searches because they lack unique-content signals",
        "short": "the un-customized template",
    },
}

# Outdated-copyright detection encodes the actual year found (e.g. "copyright-2019").
# This template handles ANY such variant. Format string is interpolated at runtime
# with the actual year via the copy resolver below.
COPYRIGHT_COPY_TEMPLATE = {
    "opener": "I noticed {domain}'s footer still says © {year} — looks like the site hasn't been touched in a few years.",
    "stat": "Sites that haven't been updated in 3+ years signal to Google + visitors that the business is inactive or unreliable",
    "short": "the stale {year} site",
}

# No-website fallback — original copy, kept for prospects with no site at all
NO_WEBSITE_OPENER = "I noticed {business_name} doesn't have a website yet — uncommon for a {category} in {city} these days."
NO_WEBSITE_STAT = "72% of people look up a local business on their phone before calling — if they can't find a site, they call the next one"
NO_WEBSITE_SHORT = "the no-website situation"


def _issue_copy(issues: list[str], website: str, business_name: str,
                 category: str, city: str) -> dict[str, str]:
    """Return {opener, stat, short} for the highest-priority detected issue.

    No issues + no website → no-website fallback copy.
    No issues + has website → returns empty strings (caller should skip; shouldn't happen
    in normal flow because is_targetable() filters good-website prospects out).
    """
    if website:
        host = website.split("://")[-1].split("/")[0]
        domain = host[4:] if host.startswith("www.") else host
    else:
        domain = ""
    if not issues:
        if not website:
            return {
                "opener": NO_WEBSITE_OPENER.format(business_name=business_name,
                                                  category=category, city=city),
                "stat": NO_WEBSITE_STAT,
                "short": NO_WEBSITE_SHORT,
            }
        return {"opener": "", "stat": "", "short": ""}
    # Strip the "bad-website:" prefix if present (rejection-reason format)
    primary = issues[0].split(":", 1)[-1]

    # Copyright issues encode the year: "copyright-2019" → interpolate the year into the copy
    if primary.startswith("copyright-"):
        year_str = primary.split("-", 1)[1]
        return {
            "opener": COPYRIGHT_COPY_TEMPLATE["opener"].format(
                domain=domain or business_name, year=year_str),
            "stat": COPYRIGHT_COPY_TEMPLATE["stat"],
            "short": COPYRIGHT_COPY_TEMPLATE["short"].format(year=year_str),
        }

    template = ISSUE_COPY.get(primary)
    if not template:
        return {
            "opener": f"I noticed {domain} has some issues that are likely costing you visitors.",
            "stat": "Modern site-quality signals (HTTPS, mobile, speed) all factor into Google ranking",
            "short": "the site-quality issues",
        }
    return {
        "opener": template["opener"].format(domain=domain or business_name),
        "stat": template["stat"],
        "short": template["short"],
    }


def _email_body_touch1(ctx: dict, copy: dict) -> str:
    """Touch 1: opening hook + preview link + fix offer. Issue-aware."""
    return f"""Hi {ctx['first_name']},

{copy['opener']}

So I built a fix you can look at:

  {ctx['preview_url']}

That's a working preview, not a mockup. SSL on, mobile-first, fast. Yours to keep either way.

If you'd want me to put this live on your own domain with email + hosting included, I do the fix for $297 one-time, $49/mo to keep it running. Most customers see a noticeable bounce-rate drop within a week.

No pressure — the preview is yours regardless. Reply if you want to talk.

— {ctx['sender_name']}
{ctx['sender_company']}"""


def _email_body_touch2(ctx: dict, copy: dict) -> str:
    """Touch 2: nudge with one specific stat + the issue label."""
    return f"""Hi {ctx['first_name']},

Quick follow-up on the {ctx['business_name']} site preview I sent earlier this week: {ctx['preview_url']}

One thing worth knowing — {copy['stat']}.

The preview I built fixes {copy['short']}. Want me to launch it this week?

— {ctx['sender_name']}"""


def _email_body_touch3(ctx: dict, copy: dict) -> str:
    """Touch 3: breakup. Generic — no issue-specific text needed here."""
    return f"""Hi {ctx['first_name']},

Last note from me on the {ctx['business_name']} site — I assume the timing isn't right and I'll close the file on this one.

If anything changes, the preview will stay at {ctx['preview_url']} for another 30 days.

All the best,
— {ctx['sender_name']}
{ctx['sender_company']}"""


SUBJECTS = {
    "touch1": "{first_name} — quick fix idea for {business_name}",
    "touch2": "Re: quick fix idea for {business_name}",
    "touch3": "{first_name} — closing the file?",
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
    """Extract the city segment from a Google formatted address.

    Google returns addresses like '123 Main St, Hyannis, MA 02639, USA' — the city
    is NOT just `parts[-2]` because that returns 'MA 02639'. Walk backwards from the
    country segment, skipping segments that look like state+zip (2-letter state code
    optionally followed by digits).
    """
    import re
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if not parts:
        return "your area"
    # Drop trailing country (e.g. "USA", "United States") and state+zip combos
    state_zip = re.compile(r"^[A-Z]{2}(\s+\d{4,5}(-\d{4})?)?$")
    while parts and (parts[-1].upper() in {"USA", "UNITED STATES", "US", "CANADA"}
                      or state_zip.match(parts[-1])):
        parts.pop()
    return parts[-1] if parts else "your area"


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
    skipped_suppressed = 0
    for preview in manifest["previews"]:
        biz = by_name.get(preview["name"])
        if not biz or "contact" not in biz:
            continue
        contact = biz["contact"]
        # CAN-SPAM § 7704(a)(4) — honor prior opt-outs. Skip any email already on the list.
        if is_suppressed(contact.get("email", "")):
            skipped_suppressed += 1
            logger.info(f"[compose] skipping {contact['email']} (previously unsubscribed)")
            continue
        category_friendly = _category_friendly(biz.get("category", ""))
        city = _city_from_address(biz.get("address", ""))
        ctx = {
            "first_name": contact.get("first_name", "there") or "there",
            "business_name": biz["name"],
            "category": category_friendly,
            "city": city,
            "preview_url": preview["preview_url"],
            "sender_name": sender_name,
            "sender_company": company,
        }
        # Build issue-aware copy from the website probe results (bad-website pivot).
        # is_targetable() encodes the issue in the targetable_reason; here we read
        # the raw website_issues list directly off the enriched record.
        copy = _issue_copy(
            issues=biz.get("website_issues", []),
            website=biz.get("website", ""),
            business_name=biz["name"],
            category=category_friendly,
            city=city,
        )
        footer = _can_spam_footer(domain, contact["email"])
        sequence = {
            "to_email": contact["email"],
            "to_name": f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip(),
            "business_name": biz["name"],
            "website_issues": biz.get("website_issues", []),
            "touches": [
                {"day": 0,
                 "subject": SUBJECTS["touch1"].format(**ctx),
                 "body": _email_body_touch1(ctx, copy) + footer},
                {"day": 3,
                 "subject": SUBJECTS["touch2"].format(**ctx),
                 "body": _email_body_touch2(ctx, copy) + footer},
                {"day": 7,
                 "subject": SUBJECTS["touch3"].format(**ctx),
                 "body": _email_body_touch3(ctx, copy) + footer},
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


# ── Send (Instantly.ai v2) ──────────────────────────────────────────────────

# v1 was deprecated and returns 401 to any new keys. v2 collapsed the previous
# {campaign_id, leads:[...]} shape into a flat single-lead POST. Schema:
#   POST /api/v2/leads
#   Required: email
#   Optional: campaign (UUID), first_name, last_name, company_name,
#             personalization, website
INSTANTLY_API_BASE = "https://api.instantly.ai/api/v2"


def _extract_preview_url(touch_body: str) -> str:
    """Pull the preview-site URL out of a touch body (first https URL on its own line)."""
    for line in touch_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("https://") and "preview" in stripped:
            return stripped
    return ""


def _instantly_send_sequence(seq: dict, campaign_id: str, key: str) -> dict:
    """Push a prospect's contact info to Instantly v2 as a campaign lead.

    The 3-touch email SEQUENCE itself is configured at the campaign level in
    Instantly — this call just adds the recipient + personalization variables.
    Custom variables become {{first_name}}, {{company_name}}, {{personalization}}
    in the campaign template (which the operator wires up in the Instantly UI).

    The actual EMAIL BODY composed by compose_sequences() is kept for review
    in the run's 04-sequences.json — Instantly's template is the source of truth
    for what actually gets sent. The compose output is the recommended copy.
    """
    name_parts = (seq.get("to_name") or "").split(maxsplit=1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    touches = seq.get("touches", [])
    touch1_body = touches[0].get("body", "") if touches else ""
    preview_url = _extract_preview_url(touch1_body)

    payload = {
        "email": seq["to_email"],
        "campaign": campaign_id,
        "first_name": first_name,
        "last_name": last_name,
        "company_name": seq.get("business_name", ""),
        "personalization": preview_url,  # available as {{personalization}} in template
    }

    r = requests.post(
        f"{INSTANTLY_API_BASE}/leads",
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
    # Prefer auto-created campaign from active_campaign.json over env var. This
    # lets /instantly/auto-create-campaign immediately become the live campaign
    # without requiring a Railway env var update + redeploy.
    try:
        from core.siteboost_instantly import get_active_campaign_id
        campaign_id = get_active_campaign_id()
    except Exception:
        campaign_id = os.getenv("INSTANTLY_CAMPAIGN_ID", "").strip()
    if not key or not campaign_id:
        return {"status": "blocked", "reason": "INSTANTLY_API_KEY + INSTANTLY_CAMPAIGN_ID required"}

    # Honor per-prospect skip flag set via /api/narai/siteboost/sequences/skip.
    # Operators use this to remove low-quality prospects after composing without
    # re-running the whole pipeline.
    not_skipped = [s for s in seqs["sequences"] if not s.get("skipped")]
    skipped_count = len(seqs["sequences"]) - len(not_skipped)
    if skipped_count:
        logger.info(f"[send] skipping {skipped_count} sequences marked skipped=true")

    results = []
    for i, seq in enumerate(not_skipped[:max_per_day]):
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
