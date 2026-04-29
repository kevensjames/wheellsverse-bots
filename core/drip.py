#!/usr/bin/env python3
"""
core/drip.py
─────────────────────────────────────────────────────────────────────────────
Email drip sequence engine — welcome series via ConvertKit.

When a lead is captured:
  1. Subscriber is added to ConvertKit
  2. Tagged "welcome_drip"
  3. Enrolled in a 5-email sequence (one per day)

Each email has a different affiliate focus:
  Day 1 — Welcome + free stock (Robinhood)
  Day 2 — Crypto starter guide (Coinbase)
  Day 3 — AI tools that save money (Jasper)
  Day 4 — Passive income resources (Amazon books)
  Day 5 — Build your online business (Bluehost)

If a ConvertKit Sequence ID is set (CONVERTKIT_DRIP_SEQUENCE_ID), the
subscriber is enrolled directly. Otherwise, the sequence emails are
broadcast as individual time-delayed emails via the broadcasts API.

Usage:
  from core.drip import enroll_in_drip
  enroll_in_drip(email="user@example.com", first_name="Alice", source="blog")
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("drip")

# ── Drip email content ────────────────────────────────────────────────────────


def _site_url() -> str:
    from urllib.parse import urlparse
    raw = os.getenv("CTA_URL", "https://wheellsverse-bots.pages.dev")
    p = urlparse(raw)
    return f"{p.scheme}://{p.netloc}"


DRIP_SEQUENCE = [
    {
        "day": 1,
        "subject": "Welcome to WheellsVerse 👋 Here's your free stock",
        "body": lambda: f"""
<h2>Welcome to WheellsVerse!</h2>
<p>Hey, I'm J.K. Blaze — and I built WheellsVerse to share the exact AI tools
and income strategies that are working right now.</p>

<p>Over the next few days I'll send you the best of what I've found. Starting today:</p>

<h3>🎁 Get a FREE stock (worth up to $200)</h3>
<p>Robinhood is giving away free stocks just for signing up.
Zero-commission investing, instant account setup.</p>
<p><a href="{_site_url()}/go/webull" style="background:#00d4ff;color:#000;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;">Claim Your Free Stock →</a></p>

<p>Talk soon,<br/><strong>J.K. Blaze</strong><br/>WheellsVerse</p>
<hr/>
<p style="font-size:12px;color:#888;">
You're receiving this because you signed up at <a href="{_site_url()}">{_site_url()}</a>.
</p>
""",
    },
    {
        "day": 2,
        "subject": "The beginner's crypto guide (+ $10 free Bitcoin)",
        "body": lambda: f"""
<h2>Crypto doesn't have to be complicated</h2>
<p>Most people lose money in crypto because they skip the basics.
Here's the short version:</p>
<ul>
  <li>Start with Bitcoin and Ethereum only</li>
  <li>Never invest more than you can afford to lose</li>
  <li>Use dollar-cost averaging (buy a fixed amount weekly)</li>
  <li>Keep coins on a reputable exchange, not random wallets</li>
</ul>

<h3>₿ Get $10 in free Bitcoin</h3>
<p>Coinbase is the easiest on-ramp for beginners — regulated, insured, and simple.</p>
<p><a href="{_site_url()}/go/coinbase" style="background:#0052ff;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;">Claim $10 Bitcoin on Coinbase →</a></p>

<p>See you tomorrow,<br/><strong>J.K. Blaze</strong></p>
""",
    },
    {
        "day": 3,
        "subject": "10 AI tools replacing $500/month in software costs",
        "body": lambda: f"""
<h2>Cut your tool stack costs in half</h2>
<p>I ran the numbers on my own business. Here are the AI tools saving me the most money:</p>
<ol>
  <li><strong>Jasper AI</strong> — replaces a $2k/mo copywriter for blog + ad copy</li>
  <li><strong>Make.com</strong> — replaces $300/mo in Zapier fees</li>
  <li><strong>Canva AI</strong> — replaces a $500/mo graphic designer</li>
  <li><strong>ChatGPT</strong> — replaces a $1k/mo research assistant</li>
  <li><strong>Claude</strong> — long-form writing, analysis, code reviews</li>
</ol>

<h3>✍️ Start with Jasper (free trial)</h3>
<p><a href="{_site_url()}/go/jasper" style="background:#7c3aed;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;">Try Jasper Free →</a></p>

<p>More tomorrow,<br/><strong>J.K. Blaze</strong></p>
""",
    },
    {
        "day": 4,
        "subject": "7 passive income streams that actually work in 2025",
        "body": lambda: f"""
<h2>Passive income that doesn't require going viral</h2>
<p>Forget the hype. Here are the streams that are quietly working for people right now:</p>
<ol>
  <li>Dividend stocks (Robinhood makes this easy)</li>
  <li>Crypto staking (Coinbase pays up to 5% APY)</li>
  <li>Affiliate blogging (what I do with WheellsVerse)</li>
  <li>Selling digital products on Gumroad</li>
  <li>Print-on-demand (Printify + Etsy)</li>
  <li>Renting out assets (car, room, equipment)</li>
  <li>High-yield savings accounts</li>
</ol>

<h3>📚 The best books on building these streams</h3>
<p><a href="{_site_url()}/go/amazon" style="background:#ff9900;color:#000;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;">Browse Passive Income Books on Amazon →</a></p>

<p>One more email coming tomorrow,<br/><strong>J.K. Blaze</strong></p>
""",
    },
    {
        "day": 5,
        "subject": "How to start a profitable website in a weekend",
        "body": lambda: f"""
<h2>Your online business foundation</h2>
<p>Every income stream I run flows through a website. Here's the minimum you need:</p>
<ol>
  <li><strong>Domain name</strong> — $12/year on Namecheap</li>
  <li><strong>Hosting</strong> — Bluehost starts at $2.95/mo (I use this)</li>
  <li><strong>WordPress</strong> — free CMS, 10 min setup</li>
  <li><strong>ConvertKit</strong> — email list from day one (free up to 1,000 subs)</li>
  <li><strong>3 affiliate links</strong> — Robinhood + Coinbase + Amazon = $0 upfront</li>
</ol>

<h3>🚀 Get hosting for $2.95/mo</h3>
<p><a href="{_site_url()}/go/bluehost" style="background:#00a0e4;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:bold;">Start with Bluehost →</a></p>

<p>That's the core of it. Reply to this email anytime — I read every message.</p>
<p>To your success,<br/><strong>J.K. Blaze</strong><br/>WheellsVerse</p>
""",
    },
]


# ── Enrollment ────────────────────────────────────────────────────────────────

def enroll_in_drip(email: str, first_name: str = "", source: str = "") -> dict:
    """
    Enroll a new subscriber in the welcome drip sequence.

    1. Add subscriber to ConvertKit with "welcome_drip" tag
    2. If CONVERTKIT_DRIP_SEQUENCE_ID is set → enroll directly in that sequence
    3. Otherwise → create 5 broadcast drafts (user sends manually or via scheduler)

    Returns a dict with status info.
    """
    from core.convertkit import get_convertkit
    ck = get_convertkit()

    if not ck.is_connected():
        logger.warning("ConvertKit not connected — drip enrollment skipped")
        return {"status": "skipped", "reason": "ConvertKit not configured"}

    # 1. Add subscriber + tag
    result = ck.add_subscriber(
        email=email,
        first_name=first_name,
        tags=["welcome_drip", f"source_{source}" if source else "welcome_drip"],
        fields={"source": source} if source else {},
    )
    sub_id = result.get("subscriber", {}).get("id")
    logger.info(f"Drip enrollment: {email} (id={sub_id})")

    # 2. Try native sequence enrollment
    seq_id = os.getenv("CONVERTKIT_DRIP_SEQUENCE_ID", "").strip()
    if seq_id:
        try:
            ck.add_to_sequence(email=email, sequence_id=int(seq_id))
            logger.info(f"Enrolled {email} in CK sequence {seq_id}")
            return {"status": "enrolled_in_sequence", "sequence_id": seq_id, "subscriber_id": sub_id}
        except Exception as e:
            logger.warning(f"Sequence enrollment failed — falling back to broadcast drafts: {e}")

    # 3. Fallback: create broadcast drafts for each drip email
    drafts = []
    for step in DRIP_SEQUENCE:
        try:
            broadcast = ck.create_broadcast(
                subject=step["subject"],
                content=step["body"](),
                description=f"Drip Day {step['day']} — {step['subject'][:60]}",
            )
            draft_id = broadcast.get("broadcast", {}).get("id")
            drafts.append({"day": step["day"], "broadcast_id": draft_id, "subject": step["subject"]})
            logger.info(f"Drip draft created: Day {step['day']} — id={draft_id}")
        except Exception as e:
            logger.error(f"Failed to create drip draft day {step['day']}: {e}")

    return {
        "status": "drafts_created",
        "email": email,
        "subscriber_id": sub_id,
        "drafts": drafts,
        "note": "Set CONVERTKIT_DRIP_SEQUENCE_ID to auto-enroll future subscribers",
    }
