#!/usr/bin/env python3
"""
Revenue Stream #6 — YouTube Faceless Channel
Purpose: Generates complete YouTube video scripts, titles, descriptions, and
         thumbnails for a faceless AI income channel. Target: 1,000 subs → monetize.
         Topics: AI tools, passive income, crypto, automation.
         Bot creates 1 video script daily + SEO optimized metadata.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are an elite YouTube content strategist and scriptwriter for faceless
channels. You've helped 20+ channels hit 100,000 subscribers in under 6 months.
You know exactly what YouTube's algorithm rewards: strong retention, clear value
delivery, and irresistible thumbnails. Your scripts are structured for maximum
watch time — hooks that prevent skipping, chapters that deliver constant value,
and calls to action that convert viewers to subscribers and buyers. You specialize
in AI, passive income, crypto, and tech education channels."""

VIDEO_TOPICS = [
    ("Top 10 AI Tools That Actually Make Money in 2026", "AI tools, income, automation"),
    ("I Made $500 With AI In 30 Days — Here's Exactly How", "passive income, AI, case study"),
    ("ChatGPT Side Hustles: 7 Ways to Earn $100/Day", "ChatGPT, side hustle, income"),
    ("The TRUTH About Passive Income With Crypto (Nobody Says This)", "crypto, passive income, truth"),
    ("Best AI Tools for Content Creators in 2026 (Tested & Ranked)", "AI tools, content creation"),
    ("How to Make Money While You Sleep With AI Automation", "automation, passive income"),
    ("Coinbase vs Binance vs Robinhood: Which is Actually Best?", "crypto, comparison, beginners"),
    ("5 DeFi Platforms Paying 10%+ APY Right Now", "DeFi, yield, passive income"),
    ("I Replaced My Content Team With AI — Here's What Happened", "AI, content, business"),
    ("The AI Prompt That Made Me $1,000 (Copy This Exactly)", "ChatGPT, prompts, income"),
    ("How to Start a Faceless YouTube Channel With AI in 2026", "YouTube, AI, passive income"),
    ("Best Passive Income Ideas That Actually Work in 2026", "passive income, real, tested"),
    ("How I Built a 6-Figure AI Business With No Coding Skills", "AI business, no code"),
    ("The Crypto Investing Strategy I Wish I Knew 5 Years Ago", "crypto, investing, strategy"),
    ("10 AI Tools That Replace Expensive Software (Save $500/Month)", "AI tools, save money"),
]


class YouTubeChannelBot(BaseBot):

    def __init__(self):
        super().__init__("06_youtube_channel", "revenue")
        import os
        self.channel_name = "WheellsVerse"
        self.coinbase_url = os.getenv("AFFILIATE_COINBASE_URL", "https://coinbase.com/join/wheellsverse")
        self.gumroad_url = os.getenv("GUMROAD_PROMPT_BIBLE_URL", "https://gum.co/wheellsverse-prompts")

    def run(self, action: str = "script", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "script")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "script": self._video_script,
            "metadata": self._video_metadata,
            "thumbnail": self._thumbnail_brief,
            "batch": self._script_batch,
            "channel_plan": self._channel_plan,
            "shorts": self._shorts_script,
        }
        fn = actions.get(action, self._video_script)
        return fn(ts, **kwargs)

    def _video_script(self, ts: str, **kwargs) -> dict:
        topic_idx = kwargs.get("topic_idx", datetime.now().day % len(VIDEO_TOPICS))
        title, keywords = VIDEO_TOPICS[topic_idx]

        prompt = f"""Write a complete YouTube video script for: {title}

Channel: {self.channel_name} | Niche: {keywords}
Target length: 8-12 minutes (faceless channel, voiceover)

Script format:

[HOOK — 0:00 to 0:45]
Do NOT start with "Hey guys" or channel intro.
Open with the most shocking/surprising/valuable thing from the video.
One of these hooks: Shocking stat | Bold claim | Surprising result | Controversial take
On screen: [HOOK TEXT IN CAPS]

[INTRO — 0:45 to 1:30]
- Briefly tease what they'll learn (3 bullets)
- "Stay to the end because I'm sharing [specific valuable thing]"
- Quick subscriber CTA
[ON SCREEN: Chapter preview graphic]

[MAIN CONTENT — 1:30 to 9:00]
Structure as 5-7 main points. For each point:
[POINT TITLE — shown on screen]
Voiceover: [2-3 paragraphs, conversational]
[B-ROLL SUGGESTION: what to show]
[ON SCREEN TEXT: key stat or quote]

[AFFILIATE MENTION — natural, around 5-minute mark]
Natural integration: mention Coinbase or prompt bible link in context
"I personally use [tool] and link is in the description"

[OUTRO — last 60 seconds]
- Summary of 3 key takeaways
- Clear subscribe CTA with reason
- Tease next video
- "Check description for all links and free resources"

Total estimated speaking words: 1,400-1,800
Style: knowledgeable friend, confident but not arrogant"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "youtube_scripts"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_title = title[:40].lower().replace(" ", "_").replace("'", "")
        (out_dir / f"script_{safe_title}.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"yt_script_{ts}.md", ext="md")
        return {"file": str(path), "action": "script", "title": title}

    def _video_metadata(self, ts: str, **kwargs) -> dict:
        topic_idx = kwargs.get("topic_idx", datetime.now().day % len(VIDEO_TOPICS))
        title, keywords = VIDEO_TOPICS[topic_idx]

        prompt = f"""Generate complete YouTube SEO metadata for video: {title}

Niche keywords: {keywords}

Generate:
1. OPTIMIZED TITLE (3 variations — A/B test) — include keyword in first 60 chars
2. DESCRIPTION (500 words):
   - First 125 chars: hook with keyword (visible before "show more")
   - Main description: what the video covers (3 paragraphs)
   - CHAPTERS section with timestamps (create logical timestamps)
   - LINKS section: Coinbase: {self.coinbase_url} | Prompts: {self.gumroad_url}
   - DISCLAIMER: "Not financial advice. For educational purposes only."
   - Subscribe reminder + social links placeholder
3. TAGS (30 YouTube tags, mix of broad + specific)
4. CARD/END SCREEN suggestions
5. PINNED COMMENT (80 words, high-engagement question + links)
6. COMMUNITY POST to announce the video (100 words)"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(result, f"yt_metadata_{ts}.md", ext="md")
        return {"file": str(path), "action": "metadata", "title": title}

    def _thumbnail_brief(self, ts: str, **kwargs) -> dict:
        topic_idx = kwargs.get("topic_idx", datetime.now().day % len(VIDEO_TOPICS))
        title, _ = VIDEO_TOPICS[topic_idx]

        prompt = f"""Create a YouTube thumbnail brief for: {title}

Design brief for DALL-E or Canva:
1. MAIN TEXT (max 5 words in CAPS, high contrast) — the clickable hook
2. BACKGROUND — specific description (dark gradient, specific colors)
3. VISUAL ELEMENT — what image/graphic to use (person, chart, phone, money, etc.)
4. COLOR PALETTE — specific hex codes (WheellsVerse brand: #00d4ff cyan, dark bg)
5. EMOTION — what the viewer should FEEL looking at it (FOMO, curiosity, excitement)
6. DALL-E PROMPT — ready-to-use prompt to generate the thumbnail image

Also provide:
- A/B test variant brief (different layout/text angle)
- Mobile preview note (will it look good at 240x135px?)
- CTR prediction: why this will get clicks"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=800)
        path = self.save_output(result, f"thumbnail_{ts}.md", ext="md")
        return {"file": str(path), "action": "thumbnail", "title": title}

    def _script_batch(self, ts: str, **kwargs) -> dict:
        """Generate scripts for first 10 videos."""
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "youtube_scripts"
        out_dir.mkdir(parents=True, exist_ok=True)
        results = []

        for i, (title, keywords) in enumerate(VIDEO_TOPICS[:10]):
            prompt = f"""Write a complete YouTube script for: {title}
Keywords: {keywords} | Channel: {self.channel_name}

Condensed format (600 words) with full structure:
[HOOK 30s] [INTRO 45s] [5 MAIN POINTS 7min] [OUTRO 45s]
Include affiliate mentions for Coinbase and Prompt Bible naturally.
Add chapter markers."""

            result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
            safe = title[:30].lower().replace(" ", "_").replace("'", "").replace(",", "")
            fpath = out_dir / f"video_{i + 1:02d}_{safe}.md"
            fpath.write_text(f"# Video {i + 1}: {title}\n\n{result}", encoding="utf-8")
            results.append(str(fpath))
            self.logger.info("Generated script %d/10: %s", i + 1, title)

        path = self.save_output(
            f"# YouTube Scripts Batch — {len(results)} videos generated\n\n" +
            "\n".join(f"- {r}" for r in results),
            f"yt_batch_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🎬 YouTube Channel — 10 Scripts Generated!\n{chr(10).join(t[0] for t in VIDEO_TOPICS[:10])}")
        except Exception:
            pass

        return {"file": str(path), "action": "batch", "count": len(results)}

    def _channel_plan(self, ts: str, **kwargs) -> dict:
        topics_str = "\n".join(f"{i + 1}. {t[0]}" for i, t in enumerate(VIDEO_TOPICS))
        prompt = f"""Create a complete YouTube channel launch plan for {self.channel_name}.

First 30 videos planned:
{topics_str}
[...+ 15 more to plan]

Channel plan includes:
1. CHANNEL SETUP CHECKLIST — name, description, about, links, playlists
2. UPLOAD SCHEDULE — 3x/week is optimal for new channels (Mon, Wed, Fri)
3. FIRST 7 VIDEOS STRATEGY — sequence them for maximum sub retention
4. SEO STRATEGY — pillar topics, keyword clusters, search intent
5. MONETIZATION ROADMAP:
   - 0-1,000 subs: affiliate income (Coinbase + Prompt Bible links)
   - 1,000-10,000: YouTube Partner Program ($1-5 RPM)
   - 10,000+: Sponsorships ($500-$5,000/video)
6. CONTENT BATCHING — record 4 videos in 1 day workflow
7. THUMBNAIL TEMPLATE — consistent brand style
8. ANALYTICS TO TRACK — CTR, AVD, subscriber conversion rate

Revenue projection at 1,000 / 10,000 / 100,000 subscribers."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        path = self.save_output(result, f"channel_plan_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"📺 YouTube Channel Plan Complete\n🎯 Goal: 1,000 subs → monetize\n📁 {Path(str(path)).name}")
        except Exception:
            pass

        return {"file": str(path), "action": "channel_plan"}

    def _shorts_script(self, ts: str, **kwargs) -> dict:
        """Generate 5 YouTube Shorts scripts for faster growth."""
        shorts_topics = [
            "This AI tool saves me 20 hours/week",
            "How to make $100/day with ChatGPT (60 seconds)",
            "The easiest passive income with crypto in 2026",
            "I use this prompt every single day",
            "3 AI tools every creator needs right now",
        ]
        scripts = []
        for topic in shorts_topics:
            prompt = f"""Write a 60-second YouTube Shorts script: {topic}

Format:
[0:00] HOOK — One bold statement (max 8 words on screen)
[0:03-0:50] CONTENT — 3-4 quick tips/points, spoken fast, on-screen text for each
[0:50-0:60] CTA — "Follow for more AI income tips"

Voiceover words only. Fast pace. Each point = 1-2 sentences max.
Include [TEXT ON SCREEN:] cues for each point."""

            result = self.claude(prompt, system=SYSTEM, max_tokens=400)
            scripts.append(f"## SHORT: {topic}\n\n{result}")

        combined = "\n\n---\n\n".join(scripts)
        out_dir = Path(__file__).resolve().parents[3] / "outputs" / "products" / "youtube_scripts"
        (out_dir / "shorts_batch.md").write_text(combined, encoding="utf-8")
        path = self.save_output(combined, f"shorts_{ts}.md", ext="md")
        return {"file": str(path), "action": "shorts"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="YouTube Channel Bot")
    parser.add_argument("--action", default="script",
                        choices=["script", "metadata", "thumbnail", "batch", "channel_plan", "shorts"])
    parser.add_argument("--topic-idx", type=int, default=None)
    args = parser.parse_args()
    bot = YouTubeChannelBot()
    result = bot.execute(action=args.action, topic_idx=args.topic_idx)
    print(f"\n✅ YouTube Channel: {result['file']}")
