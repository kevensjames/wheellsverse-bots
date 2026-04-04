#!/usr/bin/env python3
"""
core/shorts_pipeline.py
─────────────────────────────────────────────────────────────────────────────
YouTube Shorts / TikTok / Reels Auto-Pipeline

Fully automated end-to-end:
  1. Pick topic  — from Feedback Loop (best performer) or topic list
  2. Write script — GPT-4o, 50-60 seconds, hook + value + CTA
  3. Generate voice — ElevenLabs (NarAI's voice) → mp3
  4. Create avatar video — HeyGen (NarAI's face lip-synced to voice) → mp4
  5. Download video locally
  6. Publish simultaneously to:
       • YouTube Shorts
       • TikTok
       • Instagram Reels
       • Facebook Reels
  7. Register in FeedbackLoop for performance tracking
  8. Alert via Telegram

Runs as a standalone pipeline, from the Decision Engine, or via API.

.env keys needed:
  HEYGEN_API_KEY, HEYGEN_AVATAR_ID, HEYGEN_VOICE_ID (optional)
  ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID (optional)
  YOUTUBE_CLIENT_SECRET_FILE  (for YouTube upload)
  TIKTOK_ACCESS_TOKEN         (for TikTok)
  INSTAGRAM_PAGE_TOKEN + INSTAGRAM_ACCOUNT_ID
  FACEBOOK_PAGE_TOKEN + FACEBOOK_PAGE_ID
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger    = logging.getLogger("shorts_pipeline")
BRAND     = os.getenv("BRAND_NAME",  "WheellsVerse")
CTA_URL   = os.getenv("CTA_URL",     "https://grateful-flexibility-production.up.railway.app/landing")
RESULTS_DIR = ROOT / "outputs" / "shorts_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Topic pool (fallback when FeedbackLoop has no data yet) ─────────────────

EXTENDED_PLATFORMS = ["youtube", "tiktok", "instagram", "facebook",
                       "linkedin", "threads", "pinterest"]

DEFAULT_TOPICS = [
    # Crypto
    ("Bitcoin is about to change — here's what you need to know right now",    "crypto"),
    ("3 crypto mistakes beginners make that wipe out their portfolio",          "crypto"),
    ("How to earn passive income from crypto without trading",                  "crypto"),
    ("Coinbase vs Binance — which one should you actually use in 2025?",       "crypto"),
    # Investing
    ("I started investing with $100 — here's exactly what happened",           "investing"),
    ("The dividend investing strategy that pays you every single month",        "investing"),
    ("Why 99% of beginners lose money in the stock market (and how not to)",   "investing"),
    ("Fractional shares explained — invest in Apple for $1",                   "investing"),
    # AI Tools
    ("The 3 AI tools that pay for themselves in the first week",               "ai_tools"),
    ("How I use AI to write 30 blog posts in one day",                        "ai_tools"),
    ("AI tools that actually make money — not just save time",                 "ai_tools"),
    ("Stop using ChatGPT wrong — this is how to make real money with AI",     "ai_tools"),
    # Passive Income
    ("5 passive income streams I built with under $500",                       "passive_income"),
    ("The affiliate marketing blueprint nobody shows beginners",               "passive_income"),
    ("How I made my first $1,000 online without selling anything",             "passive_income"),
    ("Side hustles that work in 2025 — ranked by actual earning potential",    "passive_income"),
]

HASHTAGS = {
    "crypto":         "#crypto #bitcoin #ethereum #investing #passiveincome",
    "investing":      "#investing #stockmarket #passiveincome #money #wealth",
    "ai_tools":       "#ai #aitools #chatgpt #automation #makemoneyonline",
    "passive_income": "#passiveincome #sidehustle #makemoney #financialfreedom",
    "general":        "#AI #crypto #investing #passiveincome #WheellsVerse",
}


# ─── Main Pipeline ────────────────────────────────────────────────────────────

class ShortsPipeline:
    """
    Orchestrates the full topic → script → voice → video → publish cycle.
    """

    def __init__(self):
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.model      = os.getenv("OPENAI_MODEL", "gpt-4o")

    def run(
        self,
        topic: str = None,
        niche: str = None,
        publish_to: List[str] = None,
        format: str = "shorts",          # "shorts" (9:16) or "landscape" (16:9)
        skip_video: bool = False,        # True = script+audio only (no HeyGen)
        dry_run: bool = False,           # True = don't actually publish
    ) -> Dict:
        """
        Full pipeline. Returns result dict with status per platform.
        """
        start = datetime.now()
        logger.info(f"[ShortsPipeline] Starting — topic={topic!r}")

        # ── Step 1: Pick topic ────────────────────────────────────────────────
        if not topic:
            topic, niche = self._pick_best_topic(niche)
        niche = niche or "general"

        logger.info(f"[ShortsPipeline] Topic: [{niche}] {topic}")

        # ── Step 2: Generate script ───────────────────────────────────────────
        script = self._write_script(topic, niche)
        if not script:
            return {"status": "error", "error": "Script generation failed"}

        logger.info(f"[ShortsPipeline] Script ready ({len(script)} chars)")

        # ── Step 3: Generate ElevenLabs voice audio ───────────────────────────
        audio_path = self._generate_audio(script, topic)
        logger.info(f"[ShortsPipeline] Audio: {audio_path}")

        # ── Step 4: Generate HeyGen avatar video ──────────────────────────────
        video_path = None
        video_url  = None

        if not skip_video:
            video_result = self._generate_video(script, topic, format)
            if video_result.get("status") == "completed":
                video_path = video_result.get("download_path")
                video_url  = video_result.get("video_url")
                logger.info(f"[ShortsPipeline] Video ready: {video_path}")
            else:
                logger.warning(f"[ShortsPipeline] Video failed: {video_result.get('error')}")

        # ── Step 5: Build caption ─────────────────────────────────────────────
        caption = self._build_caption(topic, niche, script)

        # ── Step 6: Publish ───────────────────────────────────────────────────
        platforms   = publish_to or ["youtube", "tiktok", "instagram", "facebook"]
        pub_results = {}

        if not dry_run and (video_path or video_url):
            pub_results = self._publish(
                video_path=video_path,
                video_url=video_url,
                title=topic,
                caption=caption,
                niche=niche,
                platforms=platforms,
                format=format,
            )
        elif dry_run:
            pub_results = {p: "dry_run" for p in platforms}
        else:
            pub_results = {p: "skipped: no video" for p in platforms}

        # ── Step 7: Register in FeedbackLoop ─────────────────────────────────
        post_id = f"short_{int(time.time())}"
        try:
            from core.feedback_loop import FeedbackLoop
            for platform, result in pub_results.items():
                pid = f"{post_id}_{platform}"
                if "error" not in str(result).lower() and result not in ("skipped", "dry_run"):
                    FeedbackLoop.get().register_post(
                        pid, topic, niche, "shorts_pipeline", platform, "short_video"
                    )
        except Exception as e:
            logger.warning(f"[ShortsPipeline] FeedbackLoop register failed: {e}")

        # ── Step 8: Save result ───────────────────────────────────────────────
        elapsed = (datetime.now() - start).seconds
        result  = {
            "status":       "completed",
            "topic":        topic,
            "niche":        niche,
            "format":       format,
            "script_chars": len(script),
            "audio_path":   str(audio_path) if audio_path else None,
            "video_path":   str(video_path) if video_path else None,
            "video_url":    video_url,
            "published":    pub_results,
            "elapsed_s":    elapsed,
            "timestamp":    start.isoformat(),
        }

        ts       = start.strftime("%Y%m%d_%H%M%S")
        safe     = "".join(c if c.isalnum() else "_" for c in topic[:40])
        out_file = RESULTS_DIR / f"short_{safe}_{ts}.json"
        out_file.write_text(json.dumps(result, indent=2, default=str))

        # ── Step 9: Telegram alert ────────────────────────────────────────────
        self._send_alert(topic, pub_results, elapsed)

        logger.info(f"[ShortsPipeline] Done in {elapsed}s — {pub_results}")
        return result

    # ── Step implementations ──────────────────────────────────────────────────

    def _pick_best_topic(self, niche: str = None) -> tuple:
        """Use FeedbackLoop best topics, fall back to DEFAULT_TOPICS."""
        try:
            from core.feedback_loop import FeedbackLoop
            best = FeedbackLoop.get().get_best_topics(niche=niche, platform="youtube", limit=3)
            if best:
                t = best[0]["topic"]
                logger.info(f"[ShortsPipeline] Using FeedbackLoop best topic: {t}")
                return t, niche or "general"
        except Exception:
            pass

        # Fallback random pick from defaults, optionally filtered by niche
        pool = [(t, n) for t, n in DEFAULT_TOPICS if not niche or n == niche]
        if not pool:
            pool = DEFAULT_TOPICS
        return random.choice(pool)

    def _write_script(self, topic: str, niche: str) -> Optional[str]:
        """Generate a 55-60 second video script with GPT-4o."""
        try:
            import openai
            client  = openai.OpenAI(api_key=self.openai_key)
            hashtags = HASHTAGS.get(niche, HASHTAGS["general"])

            prompt = f"""Write a 55-60 second YouTube Shorts / TikTok script on: "{topic}"

Brand: {BRAND} — Daily AI, crypto, and passive income signals.

Script structure (strict):
1. HOOK (0-5s): Bold statement or shocking fact. No fluff. Must stop the scroll.
2. VALUE (5-50s): 3 punchy points. Specific numbers. Real examples. Fast pace.
3. CTA (50-60s): "Follow {BRAND} for daily signals — link in bio."

Rules:
- Conversational, fast-paced, never corporate
- Include 1 affiliate recommendation naturally (Coinbase, Robinhood, or Jasper AI)
- End with: "Find the link in bio."
- Output ONLY the spoken script. No stage directions, no timestamps."""

            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        f"You are NarAI, the AI brain of {BRAND}. "
                        "You create viral short-form video scripts that sound natural when spoken aloud."
                    )},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.80,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[ShortsPipeline] Script generation failed: {e}")
            return None

    def _generate_audio(self, script: str, title: str) -> Optional[Path]:
        """Generate voice via ElevenLabs (or OpenAI TTS fallback)."""
        try:
            from core import elevenlabs as el
            safe     = "".join(c if c.isalnum() else "_" for c in title[:30])
            filename = f"short_{safe}_{int(time.time())}.mp3"
            return el.speak(script, filename=filename)
        except Exception as e:
            logger.warning(f"[ShortsPipeline] Audio generation failed: {e}")
            return None

    def _generate_video(self, script: str, title: str, format: str) -> Dict:
        """Generate avatar video via HeyGen."""
        try:
            from core import heygen
            if not heygen.is_configured():
                logger.info("[ShortsPipeline] HeyGen not configured — skipping video")
                return {"status": "skipped", "error": "HEYGEN_API_KEY not set"}
            return heygen.create_video_and_wait(script, title=title, format=format)
        except Exception as e:
            logger.error(f"[ShortsPipeline] HeyGen video failed: {e}")
            return {"status": "error", "error": str(e)}

    def _build_caption(self, topic: str, niche: str, script: str) -> str:
        """Build a platform caption from the topic and script excerpt."""
        hashtags = HASHTAGS.get(niche, HASHTAGS["general"])
        return (
            f"{topic}\n\n"
            f"{script[:120].strip()}...\n\n"
            f"Follow {BRAND} for daily AI + crypto + income signals!\n"
            f"🔗 {CTA_URL}\n\n"
            f"{hashtags} #{BRAND.replace(' ','')}"
        )

    def _publish(self, video_path: Optional[Path], video_url: str,
                 title: str, caption: str, niche: str,
                 platforms: List[str], format: str) -> Dict:
        """Publish to all requested platforms in parallel."""
        import threading
        results = {}
        lock    = threading.Lock()

        def _pub(platform: str):
            r = self._publish_one(
                platform, video_path, video_url, title, caption, format
            )
            with lock:
                results[platform] = r

        threads = [threading.Thread(target=_pub, args=(p,)) for p in platforms]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

        return results

    def _publish_one(self, platform: str, video_path: Optional[Path],
                     video_url: str, title: str, caption: str,
                     format: str) -> str:
        """Publish to a single platform. Returns status string."""
        try:
            if platform == "youtube":
                return self._pub_youtube(video_path, title, caption)
            elif platform == "tiktok":
                return self._pub_tiktok(video_path or video_url, title, caption)
            elif platform == "instagram":
                return self._pub_instagram(video_path or video_url, caption)
            elif platform == "facebook":
                return self._pub_facebook(video_path or video_url, caption)
            elif platform == "linkedin":
                return self._pub_linkedin(title, caption, script if 'script' in dir() else caption)
            elif platform == "threads":
                return self._pub_threads(caption)
            elif platform == "pinterest":
                return self._pub_pinterest(title, caption, niche if 'niche' in dir() else "general")
            else:
                return f"unknown platform: {platform}"
        except Exception as e:
            logger.error(f"[ShortsPipeline] Publish {platform} error: {e}")
            return f"error: {e}"

    def _pub_youtube(self, video_path: Optional[Path], title: str,
                     description: str) -> str:
        try:
            from core.youtube import get_youtube
            yt = get_youtube()
            if not yt.is_connected():
                return "skipped: YouTube OAuth not connected"
            result = yt.upload_video(
                video_path=str(video_path) if video_path else None,
                title=title[:100],
                description=description[:5000],
                tags=["AI","crypto","investing","passiveincome","WheellsVerse","Shorts"],
                category_id="22",   # People & Blogs
            )
            pid = result.get("id") or result.get("video_id") or "uploaded"
            return f"published:{pid}"
        except Exception as e:
            return f"error: {e}"

    def _pub_tiktok(self, video_source, title: str, caption: str) -> str:
        try:
            from core.tiktok import get_tiktok
            tk = get_tiktok()
            video_url = str(video_source) if isinstance(video_source, Path) else video_source
            result = tk.post_video(
                video_url=video_url,
                caption=caption[:2200],
                title=title[:150],
            )
            return result.get("status") or result.get("publish_id") or "published"
        except Exception as e:
            return f"error: {e}"

    def _pub_instagram(self, video_source, caption: str) -> str:
        try:
            from core.instagram import get_instagram
            ig = get_instagram()
            if not ig.is_configured():
                return "skipped: Instagram not configured"
            video_url = str(video_source) if isinstance(video_source, Path) else video_source
            result = ig.post(caption[:2200], video_url=video_url)
            return result.get("post_id") or result.get("status") or "published"
        except Exception as e:
            return f"error: {e}"

    def _pub_facebook(self, video_source, caption: str) -> str:
        try:
            from core.facebook import get_facebook
            fb = get_facebook()
            if not fb.is_configured():
                return "skipped: Facebook not configured"
            video_url = str(video_source) if isinstance(video_source, Path) else video_source
            result = fb.post(caption[:63206], video_url=video_url)
            return result.get("post_id") or result.get("status") or "published"
        except Exception as e:
            return f"error: {e}"

    def _pub_linkedin(self, title: str, caption: str, script: str = "") -> str:
        try:
            from core.linkedin import get_linkedin
            li = get_linkedin()
            if not li.is_configured():
                return "skipped: LinkedIn not configured — visit /api/linkedin/auth"
            from core.linkedin import generate_post
            text   = generate_post(title, niche="general")
            result = li.post(text or caption[:1300])
            return result.get("post_id") or result.get("status") or "published"
        except Exception as e:
            return f"error: {e}"

    def _pub_threads(self, caption: str) -> str:
        try:
            from core.threads import get_threads
            th = get_threads()
            if not th.is_configured():
                return "skipped: Threads not configured — set THREADS_ACCESS_TOKEN or INSTAGRAM_PAGE_TOKEN"
            from core.threads import generate_post as th_gen
            # Threads has 500 char limit — use a fresh short post
            text   = th_gen(caption[:200], niche="general") or caption[:480]
            result = th.post(text)
            return result.get("post_id") or result.get("status") or "published"
        except Exception as e:
            return f"error: {e}"

    def _pub_pinterest(self, title: str, caption: str, niche: str = "general") -> str:
        try:
            from core.pinterest import get_pinterest
            pt = get_pinterest()
            if not pt.is_configured():
                return "skipped: Pinterest not configured — visit /api/pinterest/auth"
            result = pt.pin(title, niche=niche)
            return result.get("pin_id") or result.get("status") or "published"
        except Exception as e:
            return f"error: {e}"

    def _send_alert(self, topic: str, pub_results: Dict, elapsed: int):
        try:
            token   = os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = os.getenv("TELEGRAM_CHAT_ID")
            if not (token and chat_id):
                return

            platforms_ok = [p for p, r in pub_results.items()
                            if "error" not in str(r) and "skipped" not in str(r)]
            msg = (
                f"🎬 NEW SHORT PUBLISHED!\n\n"
                f"📝 {topic}\n"
                f"📱 Platforms: {', '.join(platforms_ok) if platforms_ok else 'none'}\n"
                f"⏱️ Rendered in {elapsed}s\n"
                f"🕐 {datetime.now().strftime('%H:%M')}"
            )
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": msg},
                timeout=8,
            )
        except Exception:
            pass


# ─── Convenience function ─────────────────────────────────────────────────────

_pipeline: Optional[ShortsPipeline] = None

def get_shorts_pipeline() -> ShortsPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ShortsPipeline()
    return _pipeline


def run_short(topic: str = None, niche: str = None,
              publish_to: List[str] = None, **kwargs) -> Dict:
    """One-line convenience to run the full pipeline."""
    return get_shorts_pipeline().run(topic=topic, niche=niche,
                                     publish_to=publish_to, **kwargs)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="YouTube Shorts / TikTok / Reels Pipeline")
    parser.add_argument("--topic",      type=str, default=None)
    parser.add_argument("--niche",      type=str, default=None,
                        choices=["crypto","investing","ai_tools","passive_income"])
    parser.add_argument("--platforms",  type=str, default="youtube,tiktok,instagram,facebook")
    parser.add_argument("--format",     type=str, default="shorts",
                        choices=["shorts","landscape"])
    parser.add_argument("--skip-video", action="store_true",
                        help="Generate script+audio only, skip HeyGen")
    parser.add_argument("--dry-run",    action="store_true",
                        help="Full pipeline but don't actually publish")
    args = parser.parse_args()

    result = run_short(
        topic=args.topic,
        niche=args.niche,
        publish_to=args.platforms.split(","),
        format=args.format,
        skip_video=args.skip_video,
        dry_run=args.dry_run,
    )
    print(f"\n✅ Status: {result['status']}")
    print(f"   Topic:  {result['topic']}")
    print(f"   Audio:  {result['audio_path']}")
    print(f"   Video:  {result['video_path']}")
    print(f"   Published: {result['published']}")
