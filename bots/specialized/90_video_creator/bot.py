#!/usr/bin/env python3
"""
Bot #90 — AI Video Creator (HeyGen)
Category: Specialized
Purpose: Generate AI avatar videos from scripts using HeyGen API,
         then auto-publish to YouTube, TikTok, and Instagram Reels.

Credentials needed in .env:
  HEYGEN_API_KEY         — from app.heygen.com → API
  HEYGEN_AVATAR_ID       — avatar ID to use (from HeyGen dashboard)
  HEYGEN_VOICE_ID        — voice ID to use (from HeyGen dashboard)
"""

import os
import sys
import time
import requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


HEYGEN_API = "https://api.heygen.com"


class VideoCreatorBot(BaseBot):

    def __init__(self):
        super().__init__("90_video_creator", "specialized")
        self.api_key = os.getenv("HEYGEN_API_KEY", "")
        self.avatar_id = os.getenv("HEYGEN_AVATAR_ID", "")
        self.voice_id = os.getenv("HEYGEN_VOICE_ID", "")

    def _headers(self):
        return {"X-Api-Key": self.api_key, "Content-Type": "application/json"}

    # ── HeyGen API ─────────────────────────────────────────────────────────────

    def generate_video(self, script: str, title: str = "") -> dict:
        """Submit a video generation job to HeyGen. Returns video_id."""
        if not self.api_key:
            return {"error": "HEYGEN_API_KEY not set in .env"}

        # Trim script to HeyGen limit (~1500 chars per segment)
        script_trimmed = script[:1500]

        payload = {
            "video_inputs": [
                {
                    "character": {
                        "type": "avatar",
                        "avatar_id": self.avatar_id or "default",
                        "avatar_style": "normal",
                    },
                    "voice": {
                        "type": "text",
                        "input_text": script_trimmed,
                        "voice_id": self.voice_id or "default",
                    },
                    "background": {
                        "type": "color",
                        "value": "#080b11",
                    },
                }
            ],
            "dimension": {"width": 1280, "height": 720},
            "caption": False,
        }

        resp = requests.post(
            f"{HEYGEN_API}/v2/video/generate",
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        data = resp.json()
        if resp.status_code != 200 or (data.get("error") is not None):
            err = data.get("error") or {}
            msg = err.get("message", str(data)) if isinstance(err, dict) else str(err)
            return {"error": msg}

        video_id = data.get("data", {}).get("video_id", "")
        self.logger.info("HeyGen video submitted: %s", video_id)
        return {"video_id": video_id}

    def poll_video(self, video_id: str, max_wait: int = 300) -> dict:
        """Poll until video is ready. Returns download URL."""
        start = time.time()
        while time.time() - start < max_wait:
            resp = requests.get(
                f"{HEYGEN_API}/v1/video_status.get?video_id={video_id}",
                headers=self._headers(),
                timeout=15,
            )
            data = resp.json().get("data", {})
            status = data.get("status", "")
            self.logger.info("HeyGen status: %s", status)

            if status == "completed":
                return {
                    "status": "completed",
                    "video_url": data.get("video_url", ""),
                    "thumbnail": data.get("thumbnail_url", ""),
                }
            if status == "failed":
                return {"status": "failed", "error": data.get("error", "unknown")}

            time.sleep(15)

        return {"status": "timeout", "error": f"Video not ready after {max_wait}s"}

    def list_avatars(self) -> list:
        """Return available avatars in your HeyGen account."""
        resp = requests.get(
            f"{HEYGEN_API}/v2/avatars",
            headers=self._headers(),
            timeout=15,
        )
        return resp.json().get("data", {}).get("avatars", [])

    def list_voices(self) -> list:
        """Return available voices in your HeyGen account."""
        resp = requests.get(
            f"{HEYGEN_API}/v2/voices",
            headers=self._headers(),
            timeout=15,
        )
        return resp.json().get("data", {}).get("voices", [])

    # ── Bot Run ────────────────────────────────────────────────────────────────

    def run(self, topic: str = None, script: str = None,
            publish_to: str = None, **kwargs):

        cfg = self.config
        topic = topic or cfg.get("topic", "AI tools for passive income")
        publish_to = publish_to or cfg.get("publish_to", "youtube,instagram,facebook")

        # Step 1: Generate script with GPT if not provided
        if not script:
            self.logger.info("Generating video script for: %s", topic)
            script = self.ai(
                f"""Write a 60-second engaging video script about: {topic}

Brand: WheellsVerse — AI-powered daily signals for stocks, crypto & passive income.

Format:
- Hook (first 5 seconds — grab attention)
- Main value (45 seconds — 3 key points)
- CTA (last 10 seconds — follow for daily tips)

Style: Energetic, conversational, no filler. Maximum information density.
Output ONLY the spoken script, no stage directions.""",
                max_tokens=600,
            )
            self.logger.info("Script generated (%d chars)", len(script))

        # Step 2: Submit to HeyGen
        if not self.api_key:
            # Save script only (no HeyGen key)
            self.logger.warning("HEYGEN_API_KEY not set — saving script only")
            ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self.save_output(
                f"# Video Script: {topic}\n\n{script}",
                f"video_script_{ts}.md", ext="md"
            )
            return {"status": "script_only", "file": str(path),
                    "note": "Add HEYGEN_API_KEY to .env to generate video"}

        self.logger.info("Submitting to HeyGen...")
        submit = self.generate_video(script, title=topic)
        if "error" in submit:
            return {"status": "error", "error": submit["error"], "script": script}

        video_id = submit["video_id"]

        # Step 3: Poll for completion
        self.logger.info("Waiting for video to render (video_id=%s)...", video_id)
        result = self.poll_video(video_id, max_wait=300)

        if result["status"] != "completed":
            return {"status": result["status"], "video_id": video_id,
                    "error": result.get("error", ""), "script": script}

        video_url = result["video_url"]
        thumbnail = result.get("thumbnail", "")
        self.logger.info("Video ready: %s", video_url)

        # Step 4: Publish
        publish_results = {}
        platforms = [p.strip() for p in publish_to.split(",")]

        caption_base = (
            f"{topic}\n\n"
            "💡 Follow WheellsVerse for daily AI + crypto + passive income tips!\n\n"
            "#AI #PassiveIncome #Crypto #Investing #WheellsVerse"
        )

        if "instagram" in platforms:
            try:
                from core.instagram import get_instagram
                ig = get_instagram()
                if ig.is_configured():
                    ig_caption = caption_base + " #Reels"
                    result = ig.post(ig_caption, video_url=video_url)
                    publish_results["instagram"] = result.get("post_id") or result.get("status")
                    self.logger.info("Instagram result: %s", result)
                else:
                    publish_results["instagram"] = "skipped: add INSTAGRAM_PAGE_TOKEN+INSTAGRAM_ACCOUNT_ID or INSTAGRAM_USERNAME+INSTAGRAM_PASSWORD to .env"
                    self.logger.warning("Instagram skipped: no credentials configured")
            except Exception as e:
                self.logger.error("Instagram exception: %s", e)
                publish_results["instagram"] = f"error: {e}"

        if "facebook" in platforms:
            try:
                from core.facebook import get_facebook
                fb = get_facebook()
                if fb.is_configured():
                    result = fb.post(caption_base, video_url=video_url)
                    publish_results["facebook"] = result.get("post_id") or result.get("status")
                    self.logger.info("Facebook result: %s", result)
                else:
                    publish_results["facebook"] = "skipped: add FACEBOOK_PAGE_TOKEN+FACEBOOK_PAGE_ID or FACEBOOK_EMAIL+FACEBOOK_PASSWORD to .env"
                    self.logger.warning("Facebook skipped: no credentials configured")
            except Exception as e:
                self.logger.error("Facebook exception: %s", e)
                publish_results["facebook"] = f"error: {e}"

        if "youtube" in platforms:
            try:
                from core.youtube import get_youtube
                yt = get_youtube()
                if yt.is_connected():
                    yt_result = yt.upload_video(
                        video_url=video_url,
                        title=topic,
                        description=(
                            f"{script[:500]}\n\n"
                            "Subscribe for daily AI + crypto + passive income tips!\n"
                            "https://grateful-flexibility-production.up.railway.app/landing/"
                        ),
                        tags=["AI", "PassiveIncome", "Crypto", "Investing", "WheellsVerse"],
                    )
                    self.logger.info("YouTube upload result: %s", yt_result)
                    publish_results["youtube"] = yt_result
                else:
                    publish_results["youtube"] = "skipped: YouTube not connected"
                    self.logger.warning("YouTube upload skipped: not connected")
            except Exception as e:
                self.logger.error("YouTube upload exception: %s", e)
                publish_results["youtube"] = f"error: {e}"

        # Notify Telegram
        try:
            from core.telegram import notify
            platforms_done = ", ".join(k for k, v in publish_results.items() if "error" not in str(v))
            notify(
                f"🎬 <b>Video Created!</b>\n"
                f"📌 {topic[:80]}\n"
                f"📱 Published to: {platforms_done or 'none'}\n"
                f"🔗 <a href='{video_url}'>Download video</a>"
            )
        except Exception:
            pass

        # Save output
        ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() else "_" for c in topic[:30])
        path = self.save_output(
            f"# Video: {topic}\n\n**Script:**\n{script}\n\n"
            f"**Video URL:** {video_url}\n\n"
            f"**Published:** {publish_results}",
            f"video_{safe}_{ts}.md", ext="md"
        )

        return {
            "status": "completed",
            "video_id": video_id,
            "video_url": video_url,
            "thumbnail": thumbnail,
            "publish_results": publish_results,
            "file": str(path),
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI Video Creator (HeyGen)")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--publish", type=str, default="youtube,instagram")
    parser.add_argument("--avatars", action="store_true", help="List available avatars")
    parser.add_argument("--voices", action="store_true", help="List available voices")
    args = parser.parse_args()

    bot = VideoCreatorBot()

    if args.avatars:
        avatars = bot.list_avatars()
        for a in avatars:
            print(f"{a.get('avatar_id')} — {a.get('avatar_name')}")
    elif args.voices:
        voices = bot.list_voices()
        for v in voices[:20]:
            print(f"{v.get('voice_id')} — {v.get('name')} ({v.get('language')})")
    else:
        result = bot.execute(topic=args.topic, publish_to=args.publish)
        print(f"\n✅ Video: {result.get('video_url', result.get('file'))}")
