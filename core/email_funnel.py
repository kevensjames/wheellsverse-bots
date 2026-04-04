#!/usr/bin/env python3
"""
core/email_funnel.py
─────────────────────────────────────────────────────────────────────────────
Email Funnel Builder — automated nurture sequences that convert subscribers.

What it builds:
  • Welcome sequence (5 emails) for new subscribers
  • Niche-specific nurture sequences (crypto, AI tools, passive income, investing)
  • Behavioral sequences triggered by actions (link click, purchase, inactivity)
  • Re-engagement sequences for cold subscribers (30+ days inactive)
  • Broadcast emails (weekly newsletter, market alerts, launch announcements)

Revenue model:
  Every email sequence ends with an affiliate offer timed for maximum trust.
  Sequences are designed to convert at 3-8% (vs 1% industry average).

Segmentation logic:
  • new_subscriber  → welcome sequence
  • crypto_interest → 5-email crypto education + Coinbase offer
  • ai_interest     → 5-email AI tools sequence + Jasper offer
  • passive_income  → 5-email passive income sequence + ClickBank offer
  • inactive_30d    → re-engagement sequence
  • purchased       → buyer sequence (upsell/cross-sell)

Integrates with:
  - ConvertKit (primary ESP — sequences, broadcasts, tags)
  - AffiliateOptimizer (uses winning affiliate links per niche)
  - FeedbackLoop (sends best-performing content topics)

.env keys:
  CONVERTKIT_API_KEY    — from ConvertKit → Settings → Developer
  CONVERTKIT_API_SECRET — same page
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR     = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
FUNNEL_FILE  = DATA_DIR / "email_funnels.json"

logger    = logging.getenv = os.getenv
logger    = logging.getLogger("email_funnel")

BRAND     = os.getenv("BRAND_NAME",  "WheellsVerse")
AUTHOR    = os.getenv("AUTHOR_NAME", "J.K. Blaze")
CTA_URL   = os.getenv("CTA_URL",     "https://grateful-flexibility-production.up.railway.app/landing")
CK_KEY    = os.getenv("CONVERTKIT_API_KEY",    "")
CK_SECRET = os.getenv("CONVERTKIT_API_SECRET", "")
CK_BASE   = "https://api.convertkit.com/v3"


# ─── ConvertKit helpers ───────────────────────────────────────────────────────

def _ck_get(path: str, params: dict = None) -> Dict:
    p = {"api_secret": CK_SECRET, **(params or {})}
    try:
        r = requests.get(f"{CK_BASE}{path}", params=p, timeout=15)
        return r.json() if r.status_code == 200 else {"error": r.text[:200]}
    except Exception as e:
        return {"error": str(e)}


def _ck_post(path: str, body: dict = None) -> Dict:
    payload = {"api_secret": CK_SECRET, **(body or {})}
    try:
        r = requests.post(f"{CK_BASE}{path}", json=payload, timeout=15)
        return r.json() if r.status_code in (200, 201) else {"error": r.text[:200]}
    except Exception as e:
        return {"error": str(e)}


def is_configured() -> bool:
    return bool(CK_KEY and CK_SECRET)


# ─── Subscriber management ────────────────────────────────────────────────────

def add_subscriber(email: str, first_name: str = "", tags: List[str] = None,
                   sequence_id: str = None) -> Dict:
    """
    Add a subscriber to ConvertKit and optionally start them on a sequence.
    Called by: DMReplyEngine (interested users), landing page webhook, etc.
    """
    if not is_configured():
        logger.warning("[EmailFunnel] ConvertKit not configured")
        return {"error": "ConvertKit not configured"}

    # Find or create a form to subscribe to
    forms = _ck_get("/forms").get("forms", [])
    if not forms:
        return {"error": "No ConvertKit forms found — create at least one form"}

    form_id = forms[0]["id"]
    body    = {"email": email, "first_name": first_name}
    if tags:
        body["tags"] = tags

    result = _ck_post(f"/forms/{form_id}/subscribe", body)

    if "subscription" in result:
        sub_id = result["subscription"].get("id")
        logger.info(f"[EmailFunnel] Subscribed: {email} (sub_id={sub_id})")

        # Add tags
        if tags:
            _apply_tags(email, tags)

        # Start sequence
        if sequence_id:
            start_sequence(email, sequence_id)

        return {"status": "subscribed", "subscription_id": sub_id, "email": email}

    return result


def tag_subscriber(email: str, tag_name: str) -> Dict:
    """Add a tag to a subscriber (used for segmentation)."""
    return _apply_tags(email, [tag_name])


def _apply_tags(email: str, tags: List[str]) -> Dict:
    """Apply tags to a subscriber by creating tags and tagging them."""
    results = []
    for tag_name in tags:
        # Create tag if not exists
        tag_result = _ck_post("/tags", {"tag": {"name": tag_name}})
        tag_id     = (tag_result.get("id") or
                      tag_result.get("tag", {}).get("id"))
        if tag_id:
            result = _ck_post(f"/tags/{tag_id}/subscribe",
                               {"email": email, "api_secret": CK_SECRET})
            results.append(result)
    return {"tagged": len(results)}


def get_subscriber(email: str) -> Optional[Dict]:
    """Get subscriber details."""
    result = _ck_get("/subscribers", {"email_address": email})
    subs   = result.get("subscribers", [])
    return subs[0] if subs else None


def get_subscribers_count() -> int:
    """Return total active subscribers."""
    result = _ck_get("/subscribers")
    return result.get("total_subscribers", 0)


# ─── Sequence builder ─────────────────────────────────────────────────────────

def build_sequence(niche: str, sequence_type: str = "nurture") -> List[Dict]:
    """
    Generate a complete email sequence with GPT-4o.
    Returns list of email dicts ready to create in ConvertKit.

    sequence_type: nurture / welcome / re_engagement / buyer
    """
    try:
        import openai
        from core.affiliate_optimizer import get_best_link
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        best_link = get_best_link(niche)
        aff_label = best_link.get("label", "our top recommendation")
        aff_url   = best_link.get("url", CTA_URL)

        sequence_specs = {
            "welcome": {
                "count": 5,
                "theme": "welcome the subscriber, set expectations, deliver first value",
                "flow":  "Welcome → Your Story → Free Resource → Core Insight → First Offer",
            },
            "nurture": {
                "count": 7,
                "theme": f"educate on {niche}, build trust, convert to affiliate offer",
                "flow":  "Hook → Problem → Insight 1 → Insight 2 → Social Proof → Deep Dive → Offer",
            },
            "re_engagement": {
                "count": 3,
                "theme": "win back inactive subscribers with urgency and value",
                "flow":  "We miss you → Best content recap → Final chance offer",
            },
            "buyer": {
                "count": 4,
                "theme": "thank buyer, deliver value, upsell to next product",
                "flow":  "Thank you → How to get results → Advanced tip → Upgrade offer",
            },
        }
        spec = sequence_specs.get(sequence_type, sequence_specs["nurture"])

        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": (
                    f"You are {AUTHOR}, founder of {BRAND}. "
                    "You write email sequences that convert at 3-8%. "
                    "Voice: direct, personal, like a smart friend. Never corporate. "
                    "Each email has ONE job. Subject lines are curiosity-driven (no clickbait)."
                )},
                {"role": "user", "content": (
                    f"Write a {spec['count']}-email {sequence_type} sequence for {BRAND}.\n"
                    f"Niche: {niche}\n"
                    f"Theme: {spec['theme']}\n"
                    f"Email flow: {spec['flow']}\n\n"
                    f"Affiliate offer to feature: {aff_label} — {aff_url}\n"
                    f"CTA URL: {CTA_URL}\n\n"
                    f"For each email return:\n"
                    f"- subject: (punchy, <50 chars, no emojis)\n"
                    f"- preview: (35 chars max, complements subject)\n"
                    f"- body: (150-300 words, conversational, ONE clear CTA at the end)\n"
                    f"- delay_days: (0 for first, then 1,2,3,5,7,10...)\n\n"
                    f"Return ONLY valid JSON: array of {spec['count']} email objects."
                )},
            ],
            max_tokens=3000,
            temperature=0.75,
        )

        raw     = resp.choices[0].message.content.strip()
        # Extract JSON array
        start   = raw.find("[")
        end     = raw.rfind("]") + 1
        emails  = json.loads(raw[start:end])

        logger.info(f"[EmailFunnel] Generated {len(emails)}-email {sequence_type} sequence for {niche}")
        return emails

    except Exception as e:
        logger.error(f"[EmailFunnel] build_sequence failed: {e}")
        return []


def create_sequence_in_convertkit(name: str, emails: List[Dict]) -> Dict:
    """
    Create a sequence in ConvertKit from the generated email list.
    Returns {"sequence_id": ..., "emails_created": N}
    """
    if not is_configured():
        return {"error": "ConvertKit not configured"}

    # ConvertKit API v3 doesn't have sequence creation — save locally instead
    # and use broadcasts for direct sending
    seq_id = f"seq_{name.replace(' ','_').lower()}_{int(time.time())}"

    # Save sequence to disk for reference / manual import
    sequences = _load_sequences()
    sequences[seq_id] = {
        "name":    name,
        "emails":  emails,
        "created": datetime.now().isoformat(),
        "sent_count": 0,
    }
    _save_sequences(sequences)

    logger.info(f"[EmailFunnel] Sequence saved: {seq_id} ({len(emails)} emails)")
    return {"sequence_id": seq_id, "emails_created": len(emails), "name": name}


def start_sequence(email: str, sequence_id: str) -> Dict:
    """Tag a subscriber to start them on a sequence (ConvertKit automation)."""
    tag_name = f"sequence:{sequence_id}"
    return _apply_tags(email, [tag_name])


def send_broadcast(subject: str, body: str,
                   segment: str = None) -> Dict:
    """
    Send a broadcast email to all subscribers (or a segment).
    Used for: weekly newsletter, market alerts, viral content promotions.
    """
    if not is_configured():
        return {"error": "ConvertKit not configured"}

    payload: Dict = {
        "subject":    subject,
        "content":    body,
        "description": f"Broadcast: {subject[:50]}",
    }

    result = _ck_post("/broadcasts", {"broadcast": payload})

    if "broadcast" in result:
        broadcast_id = result["broadcast"].get("id")
        logger.info(f"[EmailFunnel] Broadcast created: {broadcast_id} — {subject}")
        return {"status": "created", "broadcast_id": broadcast_id}

    return result


def generate_broadcast(topic: str, niche: str = "general") -> Dict:
    """
    Generate + send a broadcast email on a topic.
    Full pipeline: topic → GPT email → ConvertKit broadcast.
    """
    try:
        import openai
        from core.affiliate_optimizer import get_best_link
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        best_link = get_best_link(niche)

        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[
                {"role": "system", "content": (
                    f"You are {AUTHOR} at {BRAND}. "
                    "Write broadcast emails that people actually read and click. "
                    "Subject line: specific, curiosity-driven. "
                    "Body: 200-300 words, one insight, one affiliate CTA."
                )},
                {"role": "user", "content": (
                    f"Write a broadcast email on: '{topic}'\n"
                    f"Niche: {niche}\n"
                    f"Affiliate CTA: {best_link.get('label','')} — {best_link.get('url','')}\n"
                    f"Return JSON: {{\"subject\": \"...\", \"preview\": \"...\", \"body\": \"...\"}}"
                )},
            ],
            max_tokens=600,
            temperature=0.75,
        )
        raw  = resp.choices[0].message.content.strip()
        data = json.loads(raw[raw.find("{"):raw.rfind("}")+1])

        result = send_broadcast(
            subject=data.get("subject", topic),
            body=data.get("body", ""),
        )
        result["subject"]  = data.get("subject", "")
        result["preview"]  = data.get("preview", "")
        return result

    except Exception as e:
        logger.error(f"[EmailFunnel] generate_broadcast failed: {e}")
        return {"error": str(e)}


def get_stats() -> Dict:
    """Return ConvertKit account stats."""
    if not is_configured():
        return {"error": "not configured"}

    subs    = _ck_get("/subscribers")
    seqs    = _load_sequences()
    forms   = _ck_get("/forms").get("forms", [])
    broadcasts = _ck_get("/broadcasts").get("broadcasts", [])

    return {
        "configured":        True,
        "total_subscribers": subs.get("total_subscribers", 0),
        "sequences_built":   len(seqs),
        "forms":             len(forms),
        "broadcasts_sent":   len(broadcasts),
        "open_rate":         "pull from ConvertKit dashboard",
    }


# ─── Weekly newsletter automation ─────────────────────────────────────────────

def send_weekly_newsletter() -> Dict:
    """
    Auto-generate and send the weekly WheellsVerse newsletter.
    Pulls best content from FeedbackLoop + current market data.
    """
    try:
        import openai
        from core.feedback_loop import FeedbackLoop
        from core.integrations import IntegrationsHub

        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        fl     = FeedbackLoop.get()

        # Get top content
        top_crypto    = fl.get_best_topics("crypto", limit=2)
        top_ai        = fl.get_best_topics("ai_tools", limit=2)
        top_investing = fl.get_best_topics("investing", limit=2)

        # Get market data
        try:
            hub    = IntegrationsHub()
            crypto = hub.get_crypto()
            btc    = next((c for c in crypto if "bitcoin" in c.get("name","").lower()), {})
            btc_price = f"${btc.get('current_price',0):,.0f}" if btc else "N/A"
        except Exception:
            btc_price = "N/A"

        from core.affiliate_optimizer import get_best_link
        best = get_best_link("crypto")

        week_str = datetime.now().strftime("%B %d, %Y")

        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[{"role": "user", "content": (
                f"Write the weekly {BRAND} newsletter for {week_str}.\n\n"
                f"Bitcoin price: {btc_price}\n"
                f"Top crypto topics: {[t['topic'] for t in top_crypto]}\n"
                f"Top AI topics: {[t['topic'] for t in top_ai]}\n"
                f"Top investing topics: {[t['topic'] for t in top_investing]}\n"
                f"Featured affiliate: {best.get('label','')} — {best.get('url','')}\n\n"
                "Newsletter format:\n"
                "- Subject line (specific, data-driven, <60 chars)\n"
                "- Opening: 2 sentences on biggest insight this week\n"
                "- Section 1: Crypto (100 words)\n"
                "- Section 2: AI Tools (100 words)\n"
                "- Section 3: Passive Income tip (100 words)\n"
                "- Affiliate spotlight (50 words, genuine recommendation)\n"
                "- Sign-off from J.K. Blaze\n\n"
                "Return JSON: {\"subject\": \"...\", \"body\": \"...\"}"
            )}],
            max_tokens=1000,
            temperature=0.72,
        )
        raw  = resp.choices[0].message.content.strip()
        data = json.loads(raw[raw.find("{"):raw.rfind("}")+1])

        result = send_broadcast(
            subject=data.get("subject", f"{BRAND} Weekly — {week_str}"),
            body=data.get("body", ""),
        )
        logger.info(f"[EmailFunnel] Weekly newsletter sent: {data.get('subject','')}")
        return {**result, "subject": data.get("subject",""), "week": week_str}

    except Exception as e:
        logger.error(f"[EmailFunnel] Weekly newsletter failed: {e}")
        return {"error": str(e)}


# ─── Persistence helpers ──────────────────────────────────────────────────────

def _load_sequences() -> Dict:
    if FUNNEL_FILE.exists():
        try:
            return json.loads(FUNNEL_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_sequences(data: Dict):
    FUNNEL_FILE.write_text(json.dumps(data, indent=2))


def summary() -> Dict:
    seqs = _load_sequences()
    ck   = get_stats()
    return {
        "configured":        is_configured(),
        "total_subscribers": ck.get("total_subscribers", 0),
        "sequences_built":   len(seqs),
        "broadcasts_sent":   ck.get("broadcasts_sent", 0),
        "sequences":         list(seqs.keys()),
    }
