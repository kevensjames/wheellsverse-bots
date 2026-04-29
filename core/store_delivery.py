"""Store delivery — fires after a successful Stripe checkout to deliver the product.

Flow:
    Stripe checkout.session.completed → webhook → deliver(store_key, email)
    → lookup deliverable URL (env-driven) → send email via SMTP → record to JSON.

Design choices:
    - Deliverable URLs live in env vars (DELIVERY_URL_<KEY>) so you can update
      them on Railway without redeploying code.
    - If a URL isn't configured yet, buyer still gets a "preparing your order"
      holding email so they know the purchase registered.
    - All failures are caught by the caller via try/except — this module
      never crashes the webhook.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).parent.parent
DELIVERIES_FILE = ROOT / "data" / "store_deliveries.json"
logger = logging.getLogger("store_delivery")

# Default token lifetime for download links (365 days).
DEFAULT_TOKEN_TTL_SECONDS = 365 * 24 * 3600


def _secret() -> str:
    """Secret used to sign download tokens. Falls back to JWT secret if no dedicated one."""
    return (
        os.getenv("STORE_DOWNLOAD_SECRET")
        or os.getenv("NARAI_JWT_SECRET")
        or os.getenv("STRIPE_WEBHOOK_SECRET")
        or "change-me-store-download"
    )


def sign_download_token(store_key: str, buyer_email: str = "") -> str:
    """Create a signed, expiring token that unlocks /api/store/download/{store_key}."""
    from itsdangerous import URLSafeTimedSerializer
    serializer = URLSafeTimedSerializer(_secret(), salt="wheellsverse-store")
    payload = {"k": store_key, "e": buyer_email}
    return serializer.dumps(payload)


def verify_download_token(token: str, max_age: int = DEFAULT_TOKEN_TTL_SECONDS) -> Optional[dict]:
    """Return the decoded payload if valid, else None. Never raises."""
    from itsdangerous import URLSafeTimedSerializer, BadData, SignatureExpired
    serializer = URLSafeTimedSerializer(_secret(), salt="wheellsverse-store")
    try:
        return serializer.loads(token, max_age=max_age)
    except (BadData, SignatureExpired):
        return None


def _site_url() -> str:
    return (os.getenv("PUBLIC_APP_URL") or os.getenv("CTA_URL")
            or "https://app.wheellsverse.com").rstrip("/")


def _build_download_url(store_key: str, buyer_email: str = "") -> str:
    token = sign_download_token(store_key, buyer_email)
    return f"{_site_url()}/api/store/download/{store_key}?t={token}"


# Per-product delivery config. Keep names/prices/subjects in sync with core/store_setup.py.
# url_env is the env var name that holds the download/access URL for that product.
DELIVERABLES: Dict[str, Dict[str, str]] = {
    "bundle": {
        "subject": "Your AI Income Kit Bundle is ready",
        "url_env": "DELIVERY_URL_BUNDLE",
        "body": "Your complete bundle: {url}\n\nIncludes Prompt Bible, AI Income Course, Social Templates, Crypto Toolkit, Automation Guide, and the Resource Vault bonus.",
    },
    "prompt_bible": {
        "subject": "Your Prompt Bible — 10,000 Prompts",
        "url_env": "DELIVERY_URL_PROMPT_BIBLE",
        "body": "Here's your Prompt Bible: {url}\n\n10,000 copy-paste prompts across 20 categories.",
    },
    "ai_course": {
        "subject": "Your AI Income Blueprint — Access",
        "url_env": "DELIVERY_URL_AI_COURSE",
        "body": "Your course access: {url}\n\n5 modules + workbook. Start with Module 1: Your First $500 With AI.",
    },
    "social_templates": {
        "subject": "Your Social Media Template Pack",
        "url_env": "DELIVERY_URL_SOCIAL_TEMPLATES",
        "body": "365 ready-to-post templates: {url}\n\nFacebook + Instagram, covering AI/income/crypto niches.",
    },
    "crypto_toolkit": {
        "subject": "Your Crypto Starter Toolkit",
        "url_env": "DELIVERY_URL_CRYPTO_TOOLKIT",
        "body": "Your crypto toolkit: {url}\n\nExchange comparison, investing guide, DeFi yields, portfolio tracker.",
    },
    "automation_guide": {
        "subject": "Your AI Automation Guide",
        "url_env": "DELIVERY_URL_AUTOMATION_GUIDE",
        "body": "Your automation playbook: {url}\n\n10 workflows that save 20+ hours/week.",
    },
    "bot_pack": {
        "subject": "Your WheellsVerse Bot Pack Access",
        "url_env": "DELIVERY_URL_BOT_PACK",
        "body": "Your bot dashboard access: {url}\n\n6-month access to 110+ AI bots.",
    },
    "crypto_newsletter": {
        "subject": "Welcome to the Crypto Newsletter",
        "url_env": "DELIVERY_URL_CRYPTO_NEWSLETTER",
        "body": "You're subscribed. First issue arrives Monday. Archive: {url}",
    },
    "inner_circle": {
        "subject": "Welcome to the WhatsApp Inner Circle",
        "url_env": "DELIVERY_URL_INNER_CIRCLE",
        "body": "Your WhatsApp invite link: {url}\n\nI'll send the first daily tip tomorrow.",
    },
    "nexora_beta": {
        "subject": "NEXORA Beta — Your access is ready",
        "url_env": "DELIVERY_URL_NEXORA_BETA",
        "body": "Your NEXORA beta access: {url}",
    },
}


# Map of store_key → (repo-relative file path, mime type) for self-hosted deliverables.
# If the file exists at runtime, deliver() will auto-generate a signed download URL.
LOCAL_DELIVERABLES: Dict[str, tuple] = {
    "prompt_bible": ("data/store/prompt_bible/prompt_bible.pdf", "application/pdf"),
    "social_templates": ("data/store/social_templates/social_templates.csv", "text/csv"),
}


def has_local_deliverable(store_key: str) -> bool:
    """Return True if we can serve this product's file from the repo."""
    rel = LOCAL_DELIVERABLES.get(store_key, (None, None))[0]
    return bool(rel) and (ROOT / rel).exists()


def local_deliverable_path(store_key: str) -> Optional[Path]:
    rel = LOCAL_DELIVERABLES.get(store_key, (None, None))[0]
    return ROOT / rel if rel else None


def local_deliverable_mime(store_key: str) -> str:
    return LOCAL_DELIVERABLES.get(store_key, (None, "application/octet-stream"))[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_deliveries() -> list:
    if DELIVERIES_FILE.exists():
        try:
            return json.loads(DELIVERIES_FILE.read_text())
        except Exception:
            return []
    return []


def _record(entry: dict) -> None:
    entries = _load_deliveries()
    entries.insert(0, entry)
    entries = entries[:500]  # keep last 500
    DELIVERIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    DELIVERIES_FILE.write_text(json.dumps(entries, indent=2))


def _send_email(to_email: str, subject: str, body: str) -> dict:
    host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    port = int(os.getenv("EMAIL_PORT", "587"))
    user = os.getenv("EMAIL_USER", "")
    pwd = os.getenv("EMAIL_PASSWORD", "")
    from_name = os.getenv("EMAIL_FROM_NAME", "WheellsVerse")
    if not (user and pwd):
        return {"sent": False, "reason": "EMAIL_USER/EMAIL_PASSWORD not set"}
    msg = MIMEMultipart()
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, pwd)
            server.send_message(msg)
        return {"sent": True}
    except Exception as e:
        logger.warning(f"SMTP send failed for {to_email}: {e}")
        return {"sent": False, "reason": str(e)}


def deliver(store_key: str, buyer_email: str, buyer_name: str = "",
            event_id: str = "", amount_usd: float = 0.0) -> dict:
    """Deliver the product for a completed Stripe checkout.

    Returns a dict with `status`: one of
      - `sent`          delivery email went out with real URL
      - `queued`        holding email sent (URL env var not configured yet)
      - `email_failed`  we tried but SMTP returned an error
      - `unknown_key`   store_key not in DELIVERABLES — nothing sent
      - `no_email`      buyer email missing — nothing sent
    """
    ts = _now()
    if not buyer_email:
        _record({"ts": ts, "store_key": store_key, "status": "no_email", "event_id": event_id, "amount": amount_usd})
        return {"status": "no_email"}

    config = DELIVERABLES.get(store_key)
    if not config:
        logger.warning(f"Unknown store_key: {store_key}")
        _record({"ts": ts, "store_key": store_key, "email": buyer_email, "status": "unknown_key", "event_id": event_id, "amount": amount_usd})
        return {"status": "unknown_key"}

    # Priority: self-hosted file (if the store has a local deliverable) → env-var URL → holding email
    url = ""
    if has_local_deliverable(store_key):
        url = _build_download_url(store_key, buyer_email)
    else:
        url = os.getenv(config["url_env"], "").strip()

    name = buyer_name.strip() or "there"

    if url:
        subject = config["subject"]
        body = (
            f"Hi {name},\n\n"
            f"{config['body'].format(url=url)}\n\n"
            f"30-day money-back guarantee. Reply to this email if you need anything.\n\n"
            f"— J.K. Blaze\nWheellsVerse"
        )
        status_tag = "sent"
    else:
        subject = config["subject"] + " — preparing your delivery"
        body = (
            f"Hi {name},\n\n"
            f"Thanks for your purchase — your order is being prepared and will arrive "
            f"in your inbox shortly.\n\n"
            f"If you don't see it within 24 hours, reply to this email.\n\n"
            f"— J.K. Blaze\nWheellsVerse"
        )
        status_tag = "queued"

    result = _send_email(buyer_email, subject, body)
    final_status = status_tag if result["sent"] else "email_failed"
    _record({
        "ts": ts,
        "store_key": store_key,
        "email": buyer_email,
        "name": buyer_name,
        "status": final_status,
        "email_result": result,
        "event_id": event_id,
        "amount": amount_usd,
    })
    return {"status": final_status, **result}


# ═════════════════════════════════════════════════════════════════════════
# SHOPIFY ORDER DELIVERY — fires from /api/shopify/webhook on `orders/paid`
# ═════════════════════════════════════════════════════════════════════════

# Mapping: title-keyword → list of PDF filenames in data/store/digital/
SHOPIFY_DIGITAL_MAP = [
    # Bundle FIRST — its keywords are more specific
    {"keywords": ["wheellsverse library", "4-book bundle", "library — 4-book"],
     "files": ["the_cartographer_of_dying_cities.pdf",
               "the_last_star_counter.pdf",
               "seven_suspects_one_alibi.pdf",
               "the_memory_thief_volume_2.pdf"],
     "label": "WheellsVerse 4-Book Bundle",
     "subject": "Your WheellsVerse Library — 4 books inside"},
    {"keywords": ["cartographer of dying cities"],
     "files": ["the_cartographer_of_dying_cities.pdf"],
     "label": "The Cartographer of Dying Cities",
     "subject": "Your download: The Cartographer of Dying Cities"},
    {"keywords": ["last star counter"],
     "files": ["the_last_star_counter.pdf"],
     "label": "The Last Star Counter",
     "subject": "Your download: The Last Star Counter"},
    {"keywords": ["seven suspects", "detective morrison"],
     "files": ["seven_suspects_one_alibi.pdf"],
     "label": "Seven Suspects, One Alibi",
     "subject": "Your download: Seven Suspects, One Alibi"},
    {"keywords": ["memory thief: volume 2", "memory thief: complete"],
     "files": ["the_memory_thief_volume_2.pdf"],
     "label": "The Memory Thief: Volume 2",
     "subject": "Your download: The Memory Thief Volume 2"},
    {"keywords": ["memory thief: a detective sara chen", "detective sara chen"],
     "files": ["the_memory_thief_v1.pdf"],
     "label": "The Memory Thief — Detective Sara Chen",
     "subject": "Your download: The Memory Thief"},
    {"keywords": ["bloodline awakening vol 1", "bloodline awakening vol1"],
     "files": ["bloodline_awakening_vol1.pdf"],
     "label": "Bloodline Awakening Vol 1",
     "subject": "Your download: Bloodline Awakening Vol 1"},
    {"keywords": ["top 5 ai tools", "ai tools that pay you back"],
     "files": ["top_5_ai_tools_2026.pdf"],
     "label": "Top 5 AI Tools 2026",
     "subject": "Your download: Top 5 AI Tools 2026"},
]

DIGITAL_DIR = ROOT / "data" / "store" / "digital"


def _find_shopify_match(title: str) -> Optional[dict]:
    t = (title or "").lower()
    for entry in SHOPIFY_DIGITAL_MAP:
        for kw in entry["keywords"]:
            if kw in t:
                return entry
    return None


def _send_email_with_attachments(to_email: str, subject: str, body: str,
                                  attachments: list[Path]) -> dict:
    """SMTP send with PDF attachments. Returns {sent, reason?}."""
    from email.message import EmailMessage
    host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    port = int(os.getenv("EMAIL_PORT", "587"))
    user = os.getenv("EMAIL_USER", "")
    pwd = os.getenv("EMAIL_PASSWORD", "")
    from_name = os.getenv("EMAIL_FROM_NAME", "WheellsVerse")
    if not (user and pwd):
        return {"sent": False, "reason": "EMAIL_USER/PASSWORD not set"}

    msg = EmailMessage()
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    for p in attachments:
        if not p.exists():
            logger.warning(f"[shopify_delivery] missing file: {p}")
            continue
        with open(p, "rb") as f:
            data = f.read()
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=p.name)

    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        return {"sent": True}
    except Exception as e:
        logger.warning(f"[shopify_delivery] SMTP failed: {e}")
        return {"sent": False, "reason": f"{type(e).__name__}: {e}"}


def deliver_shopify_order(order: dict) -> dict:
    """Receives a Shopify order JSON; emails any digital line items as PDF attachments."""
    order_id = order.get("id")
    customer = order.get("customer") or {}
    email = (order.get("email") or customer.get("email") or "").strip()
    first_name = (customer.get("first_name") or "").strip()

    if not email:
        return {"status": "no_email", "order_id": order_id}

    line_items = order.get("line_items") or []
    delivered = []
    skipped = []

    for li in line_items:
        title = li.get("title") or ""
        entry = _find_shopify_match(title)
        if not entry:
            skipped.append({"title": title, "reason": "not a digital product / no map entry"})
            continue

        attachments = [DIGITAL_DIR / f for f in entry["files"]]
        missing = [p.name for p in attachments if not p.exists()]
        if missing:
            skipped.append({"title": title, "reason": f"missing files: {missing}"})
            continue

        body = (
            f"Hey {first_name or 'operator'},\n\n"
            f"Thanks for buying {entry['label']}.\n\n"
            f"Your file{'s' if len(attachments) > 1 else ''} {'are' if len(attachments) > 1 else 'is'} attached. "
            f"Save {'them' if len(attachments) > 1 else 'it'} somewhere safe.\n\n"
            f"If anything comes through corrupted or missing, hit reply.\n\n"
            f"— J.K.W. · WheellsVerse\n"
            f"  https://shop.wheellsverse.com"
        )

        result = _send_email_with_attachments(email, entry["subject"], body, attachments)
        record = {
            "ts": _now(),
            "order_id": order_id,
            "email": email,
            "title": title,
            "label": entry["label"],
            "files": [p.name for p in attachments],
            "status": "sent" if result.get("sent") else "email_failed",
            "email_result": result,
        }
        _record(record)
        if result.get("sent"):
            delivered.append(record)
        else:
            skipped.append({"title": title, "reason": f"smtp: {result.get('reason')}"})

    return {
        "status": "ok" if delivered else "no_digital_items",
        "delivered": delivered,
        "skipped": skipped,
        "order_id": order_id,
        "email": email,
    }


def extract_store_key(session_data: dict) -> Optional[str]:
    """Pull the store_key out of a Stripe checkout.session.completed payload.
    Checks both the session metadata and, if expanded, line-item product metadata."""
    meta = session_data.get("metadata") or {}
    if meta.get("store_key"):
        return meta["store_key"]
    # If metadata wasn't set on the session, the PaymentLink metadata we set
    # in store_setup.py lives on the PaymentLink, not the Session. We can
    # read it back via payment_link_id if needed, but that requires a Stripe
    # API call. For now we rely on the session having the metadata propagated
    # or the caller passing it directly.
    return None
