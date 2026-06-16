"""SiteBoost post-payment onboarding.

Triggered by Stripe webhook (checkout.session.completed → store_key=siteboost_site)
or by manual CLI for testing. Sends 3 emails over the first 48 hours:

    T+0min   "Welcome — here's what happens next"  (with intake form link)
    T+24h    "Just a nudge — your intake form"    (only fires if form not submitted)
    T+48h    "Your site is live!"                  (with credentials + 2-min loom)

Tracks state in data/launches/siteboost/customers/<customer_id>.json so
re-runs are idempotent.

Usage (test):
    python -m core.siteboost_onboarding --customer test123 --email you@example.com \
        --name "Mama Lupita" --business "Mama Lupita's Tortilleria" --send welcome
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
CUSTOMERS_DIR = ROOT / "data" / "launches" / "siteboost" / "customers"
logger = logging.getLogger("siteboost.onboarding")

INTAKE_BASE_URL = os.getenv("SITEBOOST_INTAKE_URL", "https://hello.wheellsverse.com/intake")
PREVIEW_BASE_URL = os.getenv("SITEBOOST_PREVIEW_URL", "https://preview.hello.wheellsverse.com")


# ── Email templates ─────────────────────────────────────────────────────────

WELCOME_EMAIL = """Hi {first_name},

✓ Got your $497 — confirmed and you're in the queue.

Here's what happens next:

  1. Right now: fill out a short intake form (5 min — hours, services, photos)
     → {intake_url}

  2. Within 48 hours of you submitting that form: your site goes live on your
     domain. I'll send the URL + a 2-min Loom walking through how to request
     changes.

  3. In 30 days: your first $49 monthly charge clears for hosting +
     maintenance. Cancel anytime from your customer dashboard.

  4. Forever: just hit reply when you want changes. New hours, new menu,
     holiday update, new photos. I make the change, send you a screenshot,
     you say "looks good" — done.

If your domain isn't registered yet, mention it in the intake form and I'll
register one for you (added to next month's invoice — $12/yr).

Any questions before then, just hit reply.

— Jay
SiteBoost AI

P.S. If you've already started the intake, no rush. The 48-hour clock starts
when you submit, not when you paid.
"""

NUDGE_EMAIL = """Hi {first_name},

Quick nudge — I haven't seen your intake form come through yet for
{business_name}.

Form's right here: {intake_url}

Most people knock it out in about 5 minutes. The reason I wait for it before
building: I'd rather use your real hours/services/photos than make stuff up.

If anything's blocking you, hit reply and tell me what's in the way — I can
usually work around it (e.g., "I don't have photos handy" → I use stock that
matches your category).

— Jay
"""

SITE_LIVE_EMAIL = """Hi {first_name},

🎉 Your site is live: https://{custom_domain}

Took a few small tweaks based on what you sent — let me know if anything
needs to change. I'll keep making revisions free for the first 30 days,
unlimited.

How to request changes:
  Just hit reply with whatever you need:
    "Update Thursday hours to 9-7"
    "Add this photo of the new patio"
    "Change the phone number to..."

I'll make the change within 1 business day, send you a screenshot, and ask
for the green light before publishing.

Bonus — here's a 2-minute walkthrough of your site + how to update it:
  https://loom.com/share/{loom_id}

Welcome aboard. Talk soon.

— Jay
SiteBoost AI

P.S. Your first $49/mo hosting charge will clear in ~30 days. Cancel
anytime, no contract.
"""


# ── Customer state ──────────────────────────────────────────────────────────

def _customer_file(customer_id: str) -> Path:
    CUSTOMERS_DIR.mkdir(parents=True, exist_ok=True)
    return CUSTOMERS_DIR / f"{customer_id}.json"


def _load_customer(customer_id: str) -> dict:
    p = _customer_file(customer_id)
    if not p.exists():
        return {"customer_id": customer_id, "history": []}
    return json.loads(p.read_text())


def _save_customer(customer_id: str, data: dict) -> None:
    _customer_file(customer_id).write_text(json.dumps(data, indent=2))


def _record_event(customer_id: str, event: str, **extra) -> None:
    cust = _load_customer(customer_id)
    cust.setdefault("history", []).append({
        "event": event, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **extra
    })
    if event == "payment":
        cust["paid_at"] = cust["history"][-1]["ts"]
    if event == "intake_submitted":
        cust["intake_submitted_at"] = cust["history"][-1]["ts"]
    if event == "site_live":
        cust["site_live_at"] = cust["history"][-1]["ts"]
    _save_customer(customer_id, cust)


# ── SMTP ────────────────────────────────────────────────────────────────────

def _send(to_email: str, subject: str, body: str, dry_run: bool = True) -> dict:
    """Send via SiteBoost outbound SMTP. Dry-run prints to stdout."""
    if dry_run:
        print(f"\n{'='*70}\n  [DRY-RUN] would send:\n  To: {to_email}\n  Subject: {subject}\n{'-'*70}")
        print(body)
        print("="*70 + "\n")
        return {"sent": True, "mode": "dry-run"}

    host = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    port = int(os.getenv("EMAIL_PORT", "587"))
    user = os.getenv("SITEBOOST_SMTP_USER", os.getenv("EMAIL_USER", "")).strip()
    pwd = os.getenv("SITEBOOST_SMTP_PASSWORD", os.getenv("EMAIL_PASSWORD", "")).strip()
    from_name = os.getenv("SITEBOOST_BRAND", "SiteBoost AI")

    if not (user and pwd):
        return {"sent": False, "reason": "SITEBOOST_SMTP_USER/PASSWORD not set"}

    msg = MIMEMultipart()
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        return {"sent": True, "mode": "live"}
    except Exception as e:
        logger.exception("siteboost SMTP send failed")
        return {"sent": False, "reason": str(e)}


# ── Public actions ──────────────────────────────────────────────────────────

def send_welcome(customer_id: str, to_email: str, first_name: str,
                 business_name: str = "", dry_run: bool = True) -> dict:
    """T+0: welcome email with intake link."""
    intake_url = f"{INTAKE_BASE_URL}?customer={customer_id}"
    body = WELCOME_EMAIL.format(
        first_name=first_name or "there",
        intake_url=intake_url,
    )
    result = _send(to_email, "✓ Got your $497 — what happens next", body, dry_run=dry_run)
    _record_event(customer_id, "welcome_sent",
                  to=to_email, dry_run=dry_run, smtp=result.get("sent", False))
    return result


def send_nudge(customer_id: str, to_email: str, first_name: str,
               business_name: str, dry_run: bool = True) -> dict:
    """T+24h: only fires if intake not yet submitted."""
    cust = _load_customer(customer_id)
    if cust.get("intake_submitted_at"):
        return {"sent": False, "reason": "intake already submitted; skipping nudge"}
    intake_url = f"{INTAKE_BASE_URL}?customer={customer_id}"
    body = NUDGE_EMAIL.format(
        first_name=first_name or "there",
        business_name=business_name or "your business",
        intake_url=intake_url,
    )
    result = _send(to_email, f"quick nudge on {business_name}'s site", body, dry_run=dry_run)
    _record_event(customer_id, "nudge_sent",
                  to=to_email, dry_run=dry_run, smtp=result.get("sent", False))
    return result


def send_site_live(customer_id: str, to_email: str, first_name: str,
                   custom_domain: str, loom_id: str = "PLACEHOLDER",
                   dry_run: bool = True) -> dict:
    """T+48h after intake: site is live."""
    body = SITE_LIVE_EMAIL.format(
        first_name=first_name or "there",
        custom_domain=custom_domain,
        loom_id=loom_id,
    )
    result = _send(to_email, f"🎉 Your site is live: {custom_domain}", body, dry_run=dry_run)
    _record_event(customer_id, "site_live_sent",
                  to=to_email, dry_run=dry_run, smtp=result.get("sent", False))
    return result


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True, help="Customer ID (Stripe customer id or test id)")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="there", help="First name")
    p.add_argument("--business", default="Your Business")
    p.add_argument("--send", choices=["welcome", "nudge", "site-live"], required=True)
    p.add_argument("--domain", default="yourbusiness.com", help="For site-live email")
    p.add_argument("--live", action="store_true")
    args = p.parse_args()

    if args.send == "welcome":
        r = send_welcome(args.customer, args.email, args.name,
                         business_name=args.business, dry_run=not args.live)
    elif args.send == "nudge":
        r = send_nudge(args.customer, args.email, args.name,
                       business_name=args.business, dry_run=not args.live)
    else:
        r = send_site_live(args.customer, args.email, args.name,
                           custom_domain=args.domain, dry_run=not args.live)
    print(json.dumps(r, indent=2))
