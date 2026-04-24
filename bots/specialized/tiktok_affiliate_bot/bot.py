#!/usr/bin/env python3
"""
bots/specialized/tiktok_affiliate_bot/bot.py
─────────────────────────────────────────────
Generates TikTok captions + video scripts for affiliate content
and posts them to TikTok via the Content Posting API.

When TIKTOK_ACCESS_TOKEN is not set:  saves content as markdown only.
When connected:                        posts as a video (from URL) or drafts.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

AMAZON_TAG = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")
COINBASE_URL = os.getenv("AFFILIATE_COINBASE_URL", "https://app.wheellsverse.com/go/coinbase")
ROBINHOOD_URL = os.getenv("AFFILIATE_ROBINHOOD_URL", "https://app.wheellsverse.com/go/robinhood")

# TikTok topics that drive affiliate clicks
TRENDING_TOPICS = [
    "Top 5 passive income apps paying real money in 2025",
    "How to earn crypto rewards without trading",
    "Free stock investing apps for beginners",
    "AI side hustles you can start today with $0",
    "Best cashback and reward tools that actually pay",
    "How to make money while you sleep using automation",
    "Stock market for beginners — no experience needed",
    "Crypto staking explained in 60 seconds",
]


class TiktokAffiliateBotBot(BaseBot):
    """Generates & posts TikTok affiliate content using the TikTok API."""

    def __init__(self):
        super().__init__("tiktok_affiliate_bot", "specialized")

    def run(self, topic: str = None, video_url: str = None,
            privacy: str = "SELF_ONLY", **kwargs):

        # Rotate topics automatically
        import random
        if not topic:
            topic = random.choice(TRENDING_TOPICS)

        self.logger.info(f"Running {self.name}: {topic}")

        # ── 1. Generate caption + script ──────────────────────────────────────
        system_str = (
            "You are a viral TikTok content creator for WheellsVerse. "
            "You write short, punchy, hook-driven scripts and captions that drive "
            "affiliate clicks. Style: confident, casual, 'money mindset' energy. "
            "Always open with a strong hook that stops the scroll."
        )

        prompt = f"""Create TikTok content for this topic: "{topic}"

Return a JSON object with:
{{
  "caption": "TikTok caption under 150 chars with 4-6 trending hashtags",
  "script": "60-second video script (hook + 3 tips + CTA), ~150 words",
  "hook": "First 3 seconds hook line — must stop the scroll",
  "hashtags": ["list", "of", "8", "hashtags"],
  "cta": "Call-to-action with affiliate link context"
}}

Affiliate links to naturally weave in:
- Amazon: https://www.amazon.com/s?k=investing+tools&tag={AMAZON_TAG}
- Coinbase (crypto sign-up, $10 bonus): {COINBASE_URL}
- Robinhood (free stock investing): {ROBINHOOD_URL}

Topic niche: {topic}
Goal: maximum affiliate clicks + follows"""

        import json as _json
        raw = self.ai(prompt, system=system_str, max_tokens=800)

        # Parse GPT response
        try:
            # Strip markdown fences if present
            raw_clean = raw.strip()
            if raw_clean.startswith("```"):
                raw_clean = raw_clean.split("\n", 1)[1].rsplit("```", 1)[0]
            content = _json.loads(raw_clean)
        except Exception:
            content = {
                "caption": raw[:150],
                "script": raw,
                "hook": raw[:80],
                "hashtags": ["#passiveincome", "#investing", "#money", "#tiktok"],
                "cta": f"Sign up for free: {ROBINHOOD_URL}",
            }

        caption = content.get("caption", "")
        script = content.get("script", "")
        hook = content.get("hook", "")
        hashtags = " ".join(content.get("hashtags", []))
        cta = content.get("cta", "")

        # Full caption for TikTok post
        full_caption = f"{caption}\n\n{hashtags}"

        # ── 2. Save as markdown ───────────────────────────────────────────────
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")

        output = f"""# TikTok Content — {topic}
*Generated: {_dt.now().strftime('%Y-%m-%d %H:%M')}*

## Hook (first 3 seconds)
{hook}

## 60-Second Script
{script}

## Caption (post-ready)
{full_caption}

## CTA
{cta}

---
*Affiliate links: Amazon `{AMAZON_TAG}` | Coinbase | Robinhood*
"""
        path = self.save_output(output, f"{self.name}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")

        result = {
            "file": str(path),
            "topic": topic,
            "bot": self.name,
            "caption": full_caption,
            "script": script,
            "posted": False,
            "publish_id": None,
        }

        # ── 3. Post to TikTok if connected ────────────────────────────────────
        tiktok_token = os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()
        if tiktok_token and video_url:
            try:
                from core.tiktok import get_tiktok
                tt = get_tiktok()
                post_result = tt.post_video_from_url(
                    video_url=video_url,
                    caption=full_caption,
                    privacy=privacy,
                )
                result["posted"] = True
                result["publish_id"] = post_result.get("publish_id")
                self.logger.info(f"Posted to TikTok — publish_id: {result['publish_id']}")
            except Exception as e:
                self.logger.warning(f"TikTok post failed (content saved locally): {e}")
        elif tiktok_token:
            self.logger.info(
                "TikTok is connected — pass video_url= to post a video. "
                "Content saved locally."
            )
        else:
            self.logger.info(
                "TikTok not connected yet — visit /api/tiktok/auth to authorize. "
                "Content saved locally."
            )

        return result


if __name__ == "__main__":
    bot = TiktokAffiliateBotBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
    if result.get("posted"):
        print(f"Posted to TikTok — publish_id: {result['publish_id']}")
