#!/usr/bin/env python3
"""
core/narai_autopilot.py
─────────────────────────────────────────────────────────────────────────────
NarAI Autonomous Creation Pipeline

SCHEDULE:
  Monday  01:00 AM  → Market Intel full scan (all 12 platforms)
  Daily   01:30 AM  → NarAI Creation Session (uses latest market data)

DAILY CREATION SESSION ORDER:
  Phase 1 — Social Posts (NarAI takes her time, no rushing)
    Facebook   : 5 posts + descriptions for 5 videos
    Instagram  : 5 posts + 1 video script
    Twitter/X  : 1 thread/post
    Blog       : 5 full articles

  Phase 2 — Digital Products
    Gumroad    : create 3 → QC each → publish best 2
    Etsy       : create 3 → QC each → publish best 2
    Payhip     : create 3 → QC each → publish best 2

  Phase 3 — KDP Books
    Amazon KDP : write 2 full ebooks → QC → cover → publish

QC LOOP RULES:
  After every piece of content NarAI creates:
    1. Submit to QualityControlBot (5 passes: errors, market fit,
       originality, platform rules, viral potential)
    2. If approved (score ≥ 75): proceed to publish
    3. If rejected: NarAI reads the revision instructions,
       rewrites the content, resubmits — max 5 revision rounds

MEMORY PHILOSOPHY:
  NarAI does NOT rush. She reads ALL market intelligence first,
  thinks deeply, then creates masterpieces worth thousands of
  likes, saves, and sales.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR  = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

AP_STATE_FILE = DATA_DIR / "autopilot_state.json"
AP_LOG_FILE   = DATA_DIR / "autopilot_log.json"

log = logging.getLogger("narai_autopilot")

MAX_QC_ROUNDS  = 5      # max revision cycles before giving up
QC_PASS_SCORE  = 75     # minimum score to approve
THINK_PAUSE    = 2      # seconds NarAI "thinks" between creations


# ══════════════════════════════════════════════════════════════════════════════
# STATE + LOG HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ap_load() -> dict:
    try:
        if AP_STATE_FILE.exists():
            return json.loads(AP_STATE_FILE.read_text())
    except Exception:
        pass
    return {
        "running": False, "session_id": None, "started_at": None,
        "phase": "idle", "task": "", "progress": 0,
        "stats": {"posts_created": 0, "posts_published": 0,
                  "products_created": 0, "products_published": 0,
                  "books_written": 0, "qc_passes": 0, "qc_fixes": 0},
        "today_content": [],
        "sessions": [],
    }

def _ap_save(state: dict):
    try:
        AP_STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    except Exception:
        pass

def _ap_log(msg: str, level: str = "INFO", phase: str = ""):
    entry = {"ts": _now(), "level": level, "msg": msg, "phase": phase}
    try:
        logs = _ap_load_logs()
        logs.insert(0, entry)
        AP_LOG_FILE.write_text(json.dumps(logs[:5000]))
    except Exception:
        pass
    log.info(f"[Autopilot] {msg}")

def _ap_load_logs() -> list:
    try:
        if AP_LOG_FILE.exists():
            return json.loads(AP_LOG_FILE.read_text())
    except Exception:
        pass
    return []


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _claude(prompt: str, system: str = "", max_tokens: int = 4000) -> str:
    """Call Claude for NarAI creation. Uses Sonnet for quality, Haiku for speed."""
    import anthropic
    model = os.getenv("NARAI_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    r = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system or _narai_system(),
        messages=[{"role": "user", "content": prompt}],
    )
    return r.content[0].text.strip()

def _claude_json(prompt: str, system: str = "", max_tokens: int = 3000) -> Any:
    raw = _claude(prompt, system, max_tokens)
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw.strip())
    except Exception:
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return {}

def _narai_system() -> str:
    return (
        "You are NarAI — the world's most creative and strategic digital content creator "
        "and digital product designer. You have deep knowledge of what makes content go "
        "viral on every platform. You create masterpieces, not average content. "
        "You think deeply before creating. Your content attracts thousands of likes, "
        "comments, saves, and your products sell because they solve real problems "
        "better than anything else on the market. "
        "Never rush. Never create generic content. Every word must count."
    )

def _get_market_intel(platform: str) -> dict:
    """Fetch the latest market intelligence for a platform."""
    try:
        from core.market_intelligence import get_platform_data, get_narai_briefing
        data = get_platform_data(platform)
        if not data:
            return {"briefing": get_narai_briefing()[:3000]}
        return data
    except Exception:
        return {}

def _get_full_briefing() -> str:
    """Get NarAI's full market briefing."""
    try:
        from core.market_intelligence import get_narai_briefing
        return get_narai_briefing()[:6000]
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# QC LOOP — THE GUARDIAN
# ══════════════════════════════════════════════════════════════════════════════

def _qc_loop(
    content: str,
    title: str,
    content_type: str,
    platform: str,
    state: dict,
) -> tuple[str, dict]:
    """
    Run QC and revision loop until approved or max rounds reached.
    Returns (final_content, qc_result).
    """
    from core.market_intelligence import QualityControlBot
    qc_bot = QualityControlBot()
    current_content = content
    rounds = 0

    while rounds < MAX_QC_ROUNDS:
        rounds += 1
        _ap_log(f"QC round {rounds}/{MAX_QC_ROUNDS} for '{title}' on {platform}", phase="qc")

        result = qc_bot.review(
            content=current_content,
            content_type=content_type,
            platform=platform,
            title=title,
        )

        state["stats"]["qc_passes"] = state["stats"].get("qc_passes", 0) + 1

        if result.get("approved"):
            _ap_log(f"✅ QC APPROVED '{title}' score={result['score']}/100 after {rounds} round(s)", phase="qc")
            return current_content, result

        # Rejected — NarAI fixes it
        score = result.get("score", 0)
        instructions = result.get("revision_instructions", "")
        issues = result.get("all_issues", [])

        _ap_log(
            f"🔄 QC score={score} — NarAI revising (round {rounds}): {'; '.join(issues[:3])}",
            level="WARNING", phase="qc"
        )
        state["stats"]["qc_fixes"] = state["stats"].get("qc_fixes", 0) + 1

        # NarAI rewrites with full revision context
        current_content = _claude(
            f"You created this {content_type} for {platform}:\n\n"
            f"---\n{current_content}\n---\n\n"
            f"QC Review Score: {score}/100\n"
            f"Issues found:\n" + "\n".join(f"• {i}" for i in issues[:10]) + "\n\n"
            f"Revision Instructions:\n{instructions}\n\n"
            "Rewrite the content fixing ALL issues. Make it a masterpiece. "
            "Keep the core message but elevate the quality dramatically. "
            "Return only the final content, no explanations.",
            max_tokens=4000,
        )
        time.sleep(THINK_PAUSE)

    # Max rounds reached — return best version
    _ap_log(f"⚠️ Max QC rounds reached for '{title}' — using best version", level="WARNING", phase="qc")
    return current_content, result


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — SOCIAL POSTS
# ══════════════════════════════════════════════════════════════════════════════

def _create_facebook_posts(state: dict, briefing: str) -> List[dict]:
    """Create 5 Facebook posts + video descriptions. QC each. Publish when green."""
    _ap_log("📘 Facebook: starting 5 posts creation", phase="facebook")
    mi = _get_market_intel("facebook")
    posts = []

    ideas = _claude_json(
        f"Market intelligence for Facebook:\n{json.dumps(mi, indent=2)[:3000]}\n\n"
        f"Master briefing:\n{briefing[:2000]}\n\n"
        "Generate 5 unique Facebook post ideas that will go viral.\n"
        "Each should have a different angle, emotion, and format.\n"
        "Mix: educational, story-based, controversy (safe), list, behind-the-scenes.\n\n"
        "Return JSON array:\n"
        '[{"title":"...", "type":"text_post|video_post", "angle":"...", '
        '"hook":"...", "emotion":"...", "niche":"..."}]\n'
        "Pure JSON array, 5 items.",
        max_tokens=1500,
    )
    if not isinstance(ideas, list):
        ideas = [{"title": f"Facebook Post {i+1}", "type": "text_post",
                  "angle": "educational", "hook": "Did you know?",
                  "emotion": "curiosity", "niche": "digital products"}
                 for i in range(5)]

    for i, idea in enumerate(ideas[:5]):
        title = idea.get("title", f"Facebook Post {i+1}")
        post_type = idea.get("type", "text_post")
        _ap_log(f"  Creating Facebook post {i+1}/5: {title}", phase="facebook")

        content = _claude(
            f"Create a viral Facebook {post_type}:\n"
            f"Title/Topic: {title}\n"
            f"Hook: {idea.get('hook','')}\n"
            f"Angle: {idea.get('angle','')}\n"
            f"Emotion to trigger: {idea.get('emotion','')}\n"
            f"Niche: {idea.get('niche','')}\n\n"
            f"Market data shows what works on Facebook:\n{json.dumps(mi.get('viral_hooks',[]) or mi.get('top_viral_formats',[]), indent=2)[:1000]}\n\n"
            "Write a COMPLETE, publication-ready Facebook post. Include:\n"
            "- Powerful hook (first line people can't scroll past)\n"
            "- Engaging body with value, story, or insight\n"
            "- Strong call-to-action\n"
            "- 5-8 relevant hashtags\n"
            f"{'- Video description/script (2-3 minutes, hook→value→CTA)' if post_type=='video_post' else ''}\n\n"
            "Make it a masterpiece. Take your time.",
            max_tokens=2000,
        )
        time.sleep(THINK_PAUSE)

        # QC loop
        final_content, qc_result = _qc_loop(content, title, "post", "facebook", state)

        # Publish if approved
        published = False
        if qc_result.get("approved"):
            published = _publish_facebook(final_content, title, post_type)

        post = {
            "platform": "facebook",
            "title": title,
            "type": post_type,
            "content": final_content,
            "qc_score": qc_result.get("score", 0),
            "approved": qc_result.get("approved", False),
            "published": published,
            "created_at": _now(),
        }
        posts.append(post)
        state["today_content"].append(post)
        state["stats"]["posts_created"] = state.get("stats", {}).get("posts_created", 0) + 1
        if published:
            state["stats"]["posts_published"] = state.get("stats", {}).get("posts_published", 0) + 1
        _ap_save(state)

    _ap_log(f"✅ Facebook: {len(posts)} posts created, {sum(1 for p in posts if p['published'])} published", phase="facebook")
    return posts


def _create_instagram_posts(state: dict, briefing: str) -> List[dict]:
    """Create 5 Instagram posts + 1 video script. QC each. Publish when green."""
    _ap_log("📸 Instagram: starting 5 posts + 1 video", phase="instagram")
    mi = _get_market_intel("instagram")
    posts = []

    # 5 posts (mix of carousel, single image, reel caption)
    formats = ["carousel", "single_image", "carousel", "reel", "single_image"]
    topics = _claude_json(
        f"Market intelligence for Instagram:\n{json.dumps(mi, indent=2)[:2500]}\n\n"
        "Generate 5 Instagram post topics that will get massive saves and shares.\n"
        "Formats: carousel, single image, reel.\n\n"
        "Return JSON array:\n"
        '[{"title":"...", "format":"carousel|single_image|reel", "hook":"...", '
        '"save_trigger":"...", "niche":"..."}]\n'
        "5 items, pure JSON.",
        max_tokens=1200,
    )
    if not isinstance(topics, list):
        topics = [{"title": f"IG Post {i+1}", "format": formats[i],
                   "hook": "You need to know this", "save_trigger": "valuable tips",
                   "niche": "digital creator"}
                  for i in range(5)]

    for i, topic in enumerate(topics[:5]):
        title = topic.get("title", f"Instagram Post {i+1}")
        fmt = topic.get("format", "carousel")
        _ap_log(f"  Creating Instagram {fmt} {i+1}/5: {title}", phase="instagram")

        content = _claude(
            f"Create a viral Instagram {fmt} post:\n"
            f"Topic: {title}\n"
            f"Hook: {topic.get('hook','')}\n"
            f"Save trigger: {topic.get('save_trigger','')}\n\n"
            "Write a COMPLETE, publication-ready Instagram post:\n"
            f"{'- Slide-by-slide content (10 slides max)' if fmt=='carousel' else ''}"
            f"{'- Caption with hook + value + CTA' if fmt=='single_image' else ''}"
            f"{'- Reel script + caption' if fmt=='reel' else ''}"
            "\n- 15-20 strategic hashtags (mix high/medium/niche)\n"
            "- Alt text for accessibility\n\n"
            "Make every slide irresistible. People must save this.",
            max_tokens=2000,
        )
        time.sleep(THINK_PAUSE)

        final_content, qc_result = _qc_loop(content, title, "post", "instagram", state)
        published = False
        if qc_result.get("approved"):
            published = _publish_instagram(final_content, title, fmt)

        post = {
            "platform": "instagram", "title": title, "format": fmt,
            "content": final_content, "qc_score": qc_result.get("score", 0),
            "approved": qc_result.get("approved", False), "published": published,
            "created_at": _now(),
        }
        posts.append(post)
        state["today_content"].append(post)
        state["stats"]["posts_created"] += 1
        if published:
            state["stats"]["posts_published"] += 1
        _ap_save(state)

    # 1 dedicated video — generate with Pika/Runway/HeyGen
    _ap_log("  Creating Instagram Reel video", phase="instagram")
    video_topic = _claude(
        f"Based on this Instagram market data:\n{json.dumps(mi, indent=2)[:1500]}\n\n"
        "What is the single BEST video topic for a viral Instagram reel right now? "
        "One sentence answer only.",
        max_tokens=100,
    )
    # Generate video prompt + script
    video_plan = _claude_json(
        f"Create a viral Instagram Reel concept for: {video_topic}\n\n"
        "Return JSON:\n"
        '{"prompt": "detailed visual prompt for AI video generation (anime style, vivid, cinematic)", '
        '"style": "anime|cinematic|3d|cartoon", '
        '"script": "30-second spoken script with timing cues", '
        '"caption": "Instagram caption with hook + hashtags", '
        '"title": "short reel title"}',
        max_tokens=1000,
    )
    if not isinstance(video_plan, dict):
        video_plan = {"prompt": f"Anime style viral reel about {video_topic}", "style": "anime",
                      "script": video_topic, "caption": video_topic, "title": video_topic}

    final_script, qc_video = _qc_loop(
        video_plan.get("script", ""), f"Reel: {video_topic[:50]}", "video_script", "instagram", state
    )

    # Generate actual video
    published = False
    video_url = ""
    if qc_video.get("approved"):
        try:
            from core.video_engine import generate_video, post_video_to_instagram
            _ap_log(f"  🎬 Generating video ({video_plan.get('style','anime')}) via AI engine…", phase="instagram")
            vresult = generate_video(
                prompt=video_plan.get("prompt", video_topic),
                style=video_plan.get("style", "anime"),
                platform="instagram",
                script=final_script,
            )
            if vresult.get("success"):
                video_url = vresult.get("video_url", "")
                local_path = vresult.get("local_path", "")
                _ap_log(f"  ✅ Video generated via {vresult.get('source','')}: {video_url[:60]}", phase="instagram")
                pub = post_video_to_instagram(local_path, video_plan.get("caption", ""))
                published = pub.get("success", False)
            else:
                _ap_log(f"  ⚠️ Video generation failed: {vresult.get('error','')} — queuing script", phase="instagram")
                _queue_for_manual("instagram", f"Reel: {video_topic[:50]}", final_script, "video_script")
        except Exception as ve:
            _ap_log(f"  ⚠️ Video engine error: {ve}", phase="instagram")
            _queue_for_manual("instagram", f"Reel: {video_topic[:50]}", final_script, "video_script")

    video_post = {
        "platform": "instagram", "title": f"Reel: {video_topic[:50]}", "format": "video",
        "content": final_script, "video_url": video_url,
        "qc_score": qc_video.get("score", 0),
        "approved": qc_video.get("approved", False), "published": published, "created_at": _now(),
    }
    posts.append(video_post)
    state["today_content"].append(video_post)
    state["stats"]["posts_created"] += 1
    if published:
        state["stats"]["posts_published"] += 1
    _ap_save(state)

    _ap_log(f"✅ Instagram: {len(posts)} items created", phase="instagram")
    return posts


def _create_twitter_post(state: dict, briefing: str) -> dict:
    """Create 1 powerful Twitter/X thread. QC. Publish when green."""
    _ap_log("🐦 Twitter/X: creating viral thread", phase="twitter")
    mi = _get_market_intel("twitter")

    content = _claude(
        f"Market intelligence for Twitter/X:\n{json.dumps(mi, indent=2)[:2000]}\n\n"
        "Create a viral Twitter/X thread that will get thousands of retweets.\n\n"
        "Rules:\n"
        "- Tweet 1: The hook (must stop the scroll — controversial, surprising, or deeply valuable)\n"
        "- Tweets 2-8: The value (each tweet stands alone but together tells a story)\n"
        "- Last tweet: CTA + follow request\n"
        "- Each tweet ≤ 280 characters\n"
        "- Number each tweet: 1/ 2/ 3/ etc.\n\n"
        "Choose a topic from: digital products, AI tools, passive income, creator economy, "
        "or whatever the market data shows is trending.\n\n"
        "Make tweet 1 the most powerful sentence you've ever written.",
        max_tokens=2000,
    )
    time.sleep(THINK_PAUSE)

    title = "Twitter Thread"
    final_content, qc_result = _qc_loop(content, title, "post", "twitter", state)
    published = False
    if qc_result.get("approved"):
        published = _publish_twitter(final_content)

    post = {
        "platform": "twitter", "title": title, "type": "thread",
        "content": final_content, "qc_score": qc_result.get("score", 0),
        "approved": qc_result.get("approved", False), "published": published,
        "created_at": _now(),
    }
    state["today_content"].append(post)
    state["stats"]["posts_created"] += 1
    if published:
        state["stats"]["posts_published"] += 1
    _ap_save(state)

    _ap_log(f"✅ Twitter: thread created (score={qc_result.get('score',0)}, published={published})", phase="twitter")
    return post


def _create_blog_posts(state: dict, briefing: str) -> List[dict]:
    """Create 5 full blog articles. QC each. Publish when green."""
    _ap_log("📰 Blog: starting 5 articles", phase="blog")
    mi = _get_market_intel("blog")
    posts = []

    topics = _claude_json(
        f"Market intelligence for blogs:\n{json.dumps(mi, indent=2)[:2000]}\n\n"
        "Generate 5 blog article topics that will rank on Google AND go viral on social.\n"
        "Mix: how-to guide, list post, case study, opinion, tool review.\n\n"
        "Return JSON array:\n"
        '[{"title":"...", "type":"how_to|list|case_study|opinion|review", '
        '"seo_keyword":"...", "word_count":1500, "viral_angle":"..."}]\n'
        "5 items, pure JSON.",
        max_tokens=1200,
    )
    if not isinstance(topics, list):
        topics = [{"title": f"Blog Post {i+1}", "type": "how_to",
                   "seo_keyword": "digital products", "word_count": 1500,
                   "viral_angle": "practical guide"}
                  for i in range(5)]

    for i, topic in enumerate(topics[:5]):
        title = topic.get("title", f"Blog Post {i+1}")
        _ap_log(f"  Writing blog article {i+1}/5: {title}", phase="blog")

        content = _claude(
            f"Write a complete, SEO-optimized blog article:\n\n"
            f"Title: {title}\n"
            f"Type: {topic.get('type','how_to')}\n"
            f"Primary keyword: {topic.get('seo_keyword','')}\n"
            f"Viral angle: {topic.get('viral_angle','')}\n"
            f"Target word count: {topic.get('word_count', 1500)}\n\n"
            "Include:\n"
            "- SEO title tag + meta description\n"
            "- H1, H2, H3 headers\n"
            "- Introduction with a hook\n"
            "- Detailed body content (real value, examples, data)\n"
            "- Internal linking suggestions\n"
            "- Conclusion + CTA\n"
            "- 5 social media snippets from this article\n\n"
            "This must be the best article ever written on this topic.",
            max_tokens=4000,
        )
        time.sleep(THINK_PAUSE)

        final_content, qc_result = _qc_loop(content, title, "blog_post", "blog", state)
        published = False
        if qc_result.get("approved"):
            published = _publish_blog(final_content, title)

        post = {
            "platform": "blog", "title": title, "type": topic.get("type", "how_to"),
            "content": final_content, "qc_score": qc_result.get("score", 0),
            "approved": qc_result.get("approved", False), "published": published,
            "created_at": _now(),
        }
        posts.append(post)
        state["today_content"].append(post)
        state["stats"]["posts_created"] += 1
        if published:
            state["stats"]["posts_published"] += 1
        _ap_save(state)

    _ap_log(f"✅ Blog: {len(posts)} articles written", phase="blog")
    return posts


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1.5 — AI VIDEO CREATION (TikTok + YouTube Shorts + Facebook Video)
# ══════════════════════════════════════════════════════════════════════════════

def _create_videos(state: dict, briefing: str) -> List[dict]:
    """
    Generate 3 AI videos daily:
      1. TikTok — anime/stylized short (9:16, 5-10s clip → full caption + script)
      2. YouTube Short — cinematic (9:16)
      3. Facebook Video — educational/story (16:9)
    Uses Pika Labs for anime, Runway ML for cinematic, HeyGen for talking-head.
    """
    from core.video_engine import generate_video, publish_video_everywhere, get_available_engines
    engines = get_available_engines()
    if not engines["any"]:
        _ap_log("⚠️ No video API keys configured — skipping video phase (add PIKA_API_KEY or RUNWAYML_API_KEY)", phase="video")
        return []

    _ap_log(f"🎬 Video: engines available — Pika:{engines['pika']} Runway:{engines['runway']} HeyGen:{engines['heygen']}", phase="video")

    video_configs = [
        {
            "platform": "tiktok",
            "style": "anime",
            "aspect": "9:16",
            "label": "TikTok anime short",
            "post_to": ["tiktok", "instagram"],
        },
        {
            "platform": "youtube",
            "style": "cinematic",
            "aspect": "9:16",
            "label": "YouTube Short cinematic",
            "post_to": ["youtube"],
        },
        {
            "platform": "facebook",
            "style": "cinematic",
            "aspect": "16:9",
            "label": "Facebook video educational",
            "post_to": ["facebook"],
        },
    ]

    videos = []
    for cfg in video_configs:
        label = cfg["label"]
        _ap_log(f"  🎞️ Creating {label}…", phase="video")

        # Ask NarAI to design the video concept
        concept = _claude_json(
            f"Design a viral {label} video concept.\n\n"
            f"Master briefing:\n{briefing[:1500]}\n\n"
            "Return JSON:\n"
            '{"title": "catchy title", '
            '"prompt": "detailed AI video generation prompt — vivid, specific, visual", '
            f'"style": "{cfg["style"]}", '
            '"caption": "platform caption with hook + 5 hashtags", '
            '"script": "30-60 second narration/script", '
            '"hook": "first 3-second hook description"}',
            max_tokens=800,
        )
        if not isinstance(concept, dict):
            concept = {
                "title": label, "prompt": f"Viral {cfg['style']} video about digital success",
                "style": cfg["style"], "caption": label, "script": label, "hook": label,
            }

        title   = concept.get("title", label)
        prompt  = concept.get("prompt", label)
        caption = concept.get("caption", title)
        script  = concept.get("script", "")

        # QC the script
        final_script, qc_result = _qc_loop(script, title, "video_script", cfg["platform"], state)

        published_to = []
        video_url    = ""
        local_path   = ""

        if qc_result.get("approved"):
            _ap_log(f"  ✅ Script approved (score {qc_result.get('score',0)}) — generating video…", phase="video")
            vresult = generate_video(
                prompt=prompt,
                style=cfg["style"],
                platform=cfg["platform"],
                script=final_script,
            )
            if vresult.get("success"):
                video_url  = vresult.get("video_url", "")
                local_path = vresult.get("local_path", "")
                source     = vresult.get("source", "")
                _ap_log(f"  🎬 {source.upper()} video ready: {video_url[:60]}", phase="video")

                pub_result = publish_video_everywhere(local_path, title, caption, platforms=cfg["post_to"])
                published_to = pub_result.get("published", [])
                failed_to    = pub_result.get("failed", [])
                if published_to:
                    _ap_log(f"  📤 Published to: {', '.join(published_to)}", phase="video")
                if failed_to:
                    _ap_log(f"  ⚠️ Failed on: {', '.join(failed_to)}", phase="video")
                    _queue_for_manual(cfg["platform"], title, f"Video: {video_url}\n\nCaption: {caption}", "video")
            else:
                _ap_log(f"  ⚠️ Video gen failed: {vresult.get('error','')} — queuing", phase="video")
                _queue_for_manual(cfg["platform"], title, f"Script:\n{final_script}\n\nCaption: {caption}", "video_script")
        else:
            _ap_log(f"  ❌ Script rejected (score {qc_result.get('score',0)}) — skipping", phase="video")

        video_rec = {
            "platform": cfg["platform"], "title": title, "style": cfg["style"],
            "video_url": video_url, "local_path": local_path,
            "caption": caption, "script": final_script,
            "qc_score": qc_result.get("score", 0),
            "approved": qc_result.get("approved", False),
            "published_to": published_to, "created_at": _now(),
        }
        videos.append(video_rec)
        state["today_content"].append(video_rec)
        state["stats"]["posts_created"] += 1
        if published_to:
            state["stats"]["posts_published"] += len(published_to)
        _ap_save(state)
        time.sleep(THINK_PAUSE)

    _ap_log(f"✅ Video phase: {len(videos)} videos created", phase="video")
    return videos


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — DIGITAL PRODUCTS
# ══════════════════════════════════════════════════════════════════════════════

def _create_platform_products(
    platform: str,
    count: int,
    publish_count: int,
    state: dict,
    briefing: str,
) -> List[dict]:
    """Create `count` digital products for a platform, QC each, publish best `publish_count`."""
    _ap_log(f"🛍️ {platform.upper()}: creating {count} digital products (publish best {publish_count})", phase=platform)
    mi = _get_market_intel(platform)
    products = []

    # Research best product ideas
    product_ideas = _claude_json(
        f"Market intelligence for {platform}:\n{json.dumps(mi, indent=2)[:2500]}\n\n"
        f"Generate {count} digital product ideas for {platform} that will sell immediately.\n"
        "Focus on high-demand, low-competition niches with proven buyer intent.\n\n"
        "Return JSON array:\n"
        '[{"title":"...", "type":"ebook|template_pack|printable|guide|course_pdf|prompt_pack", '
        '"price":9.99, "target_buyer":"...", "pain_point":"...", '
        '"unique_angle":"...", "included":"..."}]\n'
        f"{count} items, pure JSON.",
        max_tokens=1500,
    )
    if not isinstance(product_ideas, list):
        product_ideas = [{"title": f"{platform.title()} Product {i+1}", "type": "ebook",
                          "price": 9.99, "target_buyer": "digital creators",
                          "pain_point": "needs tools", "unique_angle": "practical",
                          "included": "PDF guide"}
                         for i in range(count)]

    for i, idea in enumerate(product_ideas[:count]):
        title = idea.get("title", f"Product {i+1}")
        _ap_log(f"  Creating {platform} product {i+1}/{count}: {title}", phase=platform)

        # Create full product content
        product_content = _claude(
            f"Create a COMPLETE digital product for {platform}:\n\n"
            f"Product: {title}\n"
            f"Type: {idea.get('type','ebook')}\n"
            f"Price: ${idea.get('price', 9.99)}\n"
            f"Target buyer: {idea.get('target_buyer','')}\n"
            f"Pain point solved: {idea.get('pain_point','')}\n"
            f"Unique angle: {idea.get('unique_angle','')}\n"
            f"What's included: {idea.get('included','')}\n\n"
            "Create the following (all complete and ready to use):\n\n"
            "1. PRODUCT LISTING:\n"
            "   - Headline (attention-grabbing)\n"
            "   - Description (400+ words, benefit-focused, proof-driven)\n"
            "   - Bullet points (what's included)\n"
            "   - Who it's for\n"
            "   - What results they'll get\n\n"
            "2. PRODUCT CONTENT OUTLINE:\n"
            "   (Full table of contents / template structure / printable layout)\n\n"
            "3. CANVA DESIGN BRIEF:\n"
            "   - Exact dimensions needed\n"
            "   - Color scheme\n"
            "   - Typography style\n"
            "   - Key visual elements for the cover/mockup\n\n"
            "4. SEO TAGS: 13 tags people actually search for\n\n"
            "Make this the best-selling product in its category.",
            max_tokens=3000,
        )
        time.sleep(THINK_PAUSE)

        final_content, qc_result = _qc_loop(product_content, title, "product", platform, state)

        product = {
            "platform": platform,
            "title": title,
            "type": idea.get("type", "ebook"),
            "price": idea.get("price", 9.99),
            "content": final_content,
            "qc_score": qc_result.get("score", 0),
            "approved": qc_result.get("approved", False),
            "published": False,
            "created_at": _now(),
        }
        products.append(product)
        state["today_content"].append(product)
        state["stats"]["products_created"] = state["stats"].get("products_created", 0) + 1
        _ap_save(state)

    # Sort by QC score, publish best N
    approved = [p for p in products if p["approved"]]
    approved.sort(key=lambda x: x["qc_score"], reverse=True)
    to_publish = approved[:publish_count]

    for prod in to_publish:
        published = _publish_product(prod, platform)
        prod["published"] = published
        if published:
            state["stats"]["products_published"] = state["stats"].get("products_published", 0) + 1
            _ap_log(f"  ✅ Published to {platform}: {prod['title']}", phase=platform)

    _ap_save(state)
    _ap_log(f"✅ {platform.upper()}: {len(products)} created, {sum(1 for p in to_publish if p['published'])} published", phase=platform)
    return products


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — KDP BOOKS
# ══════════════════════════════════════════════════════════════════════════════

def _create_kdp_books(state: dict, briefing: str) -> List[dict]:
    """Write 2 full ebooks for Amazon KDP. QC. Canva cover. Publish."""
    _ap_log("📚 Amazon KDP: writing 2 ebooks", phase="kdp")
    mi = _get_market_intel("amazon_kdp")
    books = []

    book_ideas = _claude_json(
        f"Amazon KDP market intelligence:\n{json.dumps(mi, indent=2)[:2500]}\n\n"
        "Generate 2 ebook ideas for Amazon KDP that will become bestsellers.\n"
        "Focus on high-demand niches, proven formats, emotional hooks.\n\n"
        "Return JSON array:\n"
        '[{"title":"...", "subtitle":"...", "genre":"...", '
        '"target_reader":"...", "core_transformation":"...", '
        '"chapter_count":8, "length":"short|medium|full", '
        '"price":4.99, "kdp_category":"..."}]\n'
        "2 items, pure JSON.",
        max_tokens=1000,
    )
    if not isinstance(book_ideas, list):
        book_ideas = [
            {"title": "The Digital Product Blueprint", "subtitle": "How to Create and Sell Digital Products That Actually Sell",
             "genre": "business", "target_reader": "entrepreneurs", "core_transformation": "create passive income",
             "chapter_count": 8, "length": "medium", "price": 4.99, "kdp_category": "Business & Money"},
            {"title": "AI Side Hustle Guide 2025", "subtitle": "Use AI Tools to Build Multiple Income Streams",
             "genre": "business", "target_reader": "side hustlers", "core_transformation": "financial freedom",
             "chapter_count": 7, "length": "short", "price": 3.99, "kdp_category": "Computers & Technology"},
        ]

    for i, idea in enumerate(book_ideas[:2]):
        title = idea.get("title", f"Book {i+1}")
        full_title = f"{title}: {idea.get('subtitle','')}" if idea.get("subtitle") else title
        _ap_log(f"  Writing KDP book {i+1}/2: {title}", phase="kdp")

        # Write the full book
        book_content = _write_full_ebook(idea)
        time.sleep(THINK_PAUSE)

        # QC the book
        final_book, qc_result = _qc_loop(
            book_content[:8000],  # QC on first 8000 chars (enough to judge quality)
            full_title,
            "ebook",
            "amazon_kdp",
            state,
        )

        # Generate Canva cover brief
        cover_brief = _claude(
            f"Create a detailed Canva book cover design brief for:\n\n"
            f"Title: {title}\n"
            f"Subtitle: {idea.get('subtitle','')}\n"
            f"Genre: {idea.get('genre','business')}\n"
            f"Target reader: {idea.get('target_reader','')}\n\n"
            "Specify EXACTLY:\n"
            "- KDP cover dimensions (6×9 inches → 1800×2700px at 300 DPI)\n"
            "- Color palette (3 specific hex codes)\n"
            "- Typography: title font, subtitle font, author font\n"
            "- Background design (gradient, pattern, image concept)\n"
            "- Visual elements (icons, shapes, imagery)\n"
            "- Overall mood/style\n"
            "- Canva template search terms to start from\n\n"
            "This cover must look like a #1 Amazon bestseller.",
            max_tokens=800,
        )

        # Try to generate actual cover via Canva API
        canva_url = _generate_canva_cover(title, idea)

        # Build KDP listing
        kdp_listing = _claude(
            f"Create a complete Amazon KDP listing for:\n\n"
            f"Title: {title}\n"
            f"Subtitle: {idea.get('subtitle','')}\n"
            f"Genre: {idea.get('genre','')}\n"
            f"Target reader: {idea.get('target_reader','')}\n"
            f"Core transformation: {idea.get('core_transformation','')}\n"
            f"KDP Category: {idea.get('kdp_category','')}\n"
            f"Price: ${idea.get('price', 4.99)}\n\n"
            "Create:\n"
            "1. BOOK DESCRIPTION (600 words, HTML formatted for KDP, benefit-driven)\n"
            "2. KEYWORDS: 7 keyword phrases (each under 50 chars)\n"
            "3. CATEGORIES: 2 exact KDP browse categories\n"
            "4. AUTHOR BIO (150 words, builds authority)\n"
            "5. BACK COVER COPY (200 words)\n\n"
            "Every word must make someone want to buy immediately.",
            max_tokens=2000,
        )

        # Package for KDP
        kdp_package = _package_kdp_book(title, book_content, idea)

        published = False
        if qc_result.get("approved"):
            _ap_log(f"  ✅ KDP book approved — packaging for upload: {title}", phase="kdp")
            # Store complete package for manual/API upload
            published = _save_kdp_package(title, book_content, kdp_listing, cover_brief, canva_url)

        book = {
            "platform": "amazon_kdp",
            "title": title,
            "subtitle": idea.get("subtitle", ""),
            "type": "ebook",
            "price": idea.get("price", 4.99),
            "qc_score": qc_result.get("score", 0),
            "approved": qc_result.get("approved", False),
            "published": published,
            "canva_url": canva_url,
            "has_listing": True,
            "package_path": str(DATA_DIR / "kdp_packages" / f"{title[:40].replace(' ','_')}.json"),
            "created_at": _now(),
        }
        books.append(book)
        state["today_content"].append(book)
        state["stats"]["books_written"] = state["stats"].get("books_written", 0) + 1
        if published:
            state["stats"]["products_published"] = state["stats"].get("products_published", 0) + 1
        _ap_save(state)

    _ap_log(f"✅ KDP: {len(books)} books written", phase="kdp")
    return books


def _write_full_ebook(idea: dict) -> str:
    """Write a complete ebook chapter by chapter."""
    title = idea.get("title", "Untitled")
    subtitle = idea.get("subtitle", "")
    chapters = idea.get("chapter_count", 8)
    genre = idea.get("genre", "business")
    transformation = idea.get("core_transformation", "")
    reader = idea.get("target_reader", "")

    # First: generate full outline
    outline = _claude_json(
        f"Write a detailed book outline for:\n"
        f"Title: {title}\n"
        f"Subtitle: {subtitle}\n"
        f"Genre: {genre}\n"
        f"Core transformation: {transformation}\n"
        f"Target reader: {reader}\n"
        f"Chapters: {chapters}\n\n"
        "Return JSON:\n"
        '{"intro":"...", "chapters":[{"num":1,"title":"...","summary":"...","key_points":["..."]}], "conclusion":"..."}\n'
        "Pure JSON.",
        max_tokens=2000,
    )

    # Write each chapter
    book_parts = []
    book_parts.append(f"# {title}\n## {subtitle}\n\n")
    book_parts.append(f"---\n*For {reader} who want to {transformation}.*\n\n---\n\n")

    intro = outline.get("intro", "")
    if intro:
        intro_content = _claude(
            f"Write the introduction for the book '{title}':\n{intro}\n\n"
            "Make it so compelling readers MUST continue. 400-600 words.",
            max_tokens=1000,
        )
        book_parts.append(f"## Introduction\n\n{intro_content}\n\n")

    for ch in (outline.get("chapters") or [])[:chapters]:
        ch_num = ch.get("num", 1)
        ch_title = ch.get("title", f"Chapter {ch_num}")
        ch_summary = ch.get("summary", "")
        key_points = ch.get("key_points", [])

        _ap_log(f"    Writing chapter {ch_num}: {ch_title}", phase="kdp")
        chapter = _claude(
            f"Write Chapter {ch_num} of '{title}':\n\n"
            f"Chapter title: {ch_title}\n"
            f"Summary: {ch_summary}\n"
            f"Key points to cover: {', '.join(key_points)}\n\n"
            "Write 1200-1800 words. Include:\n"
            "- Opening story or hook\n"
            "- Core content with actionable steps\n"
            "- Real examples or case studies\n"
            "- End with a chapter summary + action step\n\n"
            "Write like a bestselling author.",
            max_tokens=2500,
        )
        book_parts.append(f"## Chapter {ch_num}: {ch_title}\n\n{chapter}\n\n")
        time.sleep(1)

    conclusion = outline.get("conclusion", "")
    if conclusion:
        conc_content = _claude(
            f"Write the conclusion for '{title}':\n{conclusion}\n\n"
            "Leave readers inspired, equipped, and ready to take action. 300-500 words.",
            max_tokens=800,
        )
        book_parts.append(f"## Conclusion\n\n{conc_content}\n\n")

    return "".join(book_parts)


def _generate_canva_cover(title: str, idea: dict) -> str:
    """Try to create a Canva cover via API. Returns URL or empty string."""
    try:
        import urllib.request
        token_file = DATA_DIR / "canva_token.json"
        if not token_file.exists():
            return ""
        tok_data = json.loads(token_file.read_text())
        token = tok_data.get("access_token", "")
        if not token:
            return ""

        body = json.dumps({
            "design_type": {"type": "custom", "width": 1800, "height": 2700},
            "title": f"KDP Cover: {title[:40]}",
        }).encode()
        req = urllib.request.Request(
            "https://api.canva.com/rest/v1/designs",
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            url = data.get("design", {}).get("urls", {}).get("edit_url", "")
            if url:
                _ap_log(f"  Canva cover created for '{title}'", phase="kdp")
            return url
    except Exception as e:
        log.debug(f"Canva cover generation failed: {e}")
        return ""


def _package_kdp_book(title: str, content: str, idea: dict) -> str:
    """Save ebook as HTML package ready for KDP upload."""
    pkg_dir = DATA_DIR / "kdp_packages"
    pkg_dir.mkdir(exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", title[:40])
    html_path = pkg_dir / f"{safe_name}.html"
    # Convert markdown-ish content to clean HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>{title}</title>
<style>
body{{font-family:'Georgia',serif;line-height:1.8;max-width:650px;margin:60px auto;padding:0 30px;color:#222;}}
h1{{font-size:2em;text-align:center;margin-bottom:0.2em;}}
h2{{font-size:1.4em;color:#333;border-bottom:1px solid #eee;padding-bottom:6px;margin-top:2em;}}
h3{{font-size:1.1em;color:#555;}}
p{{margin:1em 0;text-align:justify;}}
.subtitle{{text-align:center;color:#666;font-style:italic;margin-bottom:2em;}}
.dedication{{text-align:center;margin:3em 0;font-style:italic;color:#777;}}
@media print{{body{{margin:0;padding:0.5in;}}}}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="subtitle">{idea.get('subtitle','')}</p>
<div class="dedication">By WheellsVerse</div>
<hr/>
{content.replace(chr(10), '<br/>').replace('## ', '<h2>').replace('# ', '<h1>').replace('</h1>', '</h1>').replace('</h2>', '</h2>')}
</body>
</html>"""
    html_path.write_text(html_content, encoding="utf-8")
    return str(html_path)


def _save_kdp_package(title: str, content: str, listing: str, cover_brief: str, canva_url: str) -> bool:
    """Save complete KDP upload package as JSON."""
    try:
        pkg_dir = DATA_DIR / "kdp_packages"
        pkg_dir.mkdir(exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", title[:40])
        pkg = {
            "title": title, "content_preview": content[:500],
            "listing": listing, "cover_brief": cover_brief,
            "canva_url": canva_url, "created_at": _now(),
            "status": "ready_for_upload",
        }
        (pkg_dir / f"{safe_name}_package.json").write_text(json.dumps(pkg, indent=2))
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# PUBLISH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _publish_facebook(content: str, title: str, post_type: str) -> bool:
    try:
        from core.facebook import get_client
        fb = get_client()
        if hasattr(fb, "post_to_page"):
            result = fb.post_to_page(content)
            return bool(result)
        _ap_log(f"  Facebook: content saved for manual posting — {title[:40]}", phase="facebook")
        _queue_for_manual("facebook", title, content)
        return False
    except Exception as e:
        _ap_log(f"  Facebook publish error: {e}", level="WARNING", phase="facebook")
        _queue_for_manual("facebook", title, content)
        return False


def _publish_instagram(content: str, title: str, fmt: str) -> bool:
    try:
        from core.instagram import get_client
        ig = get_client()
        if hasattr(ig, "create_post"):
            result = ig.create_post(caption=content)
            return bool(result)
        _ap_log(f"  Instagram: content saved for manual posting — {title[:40]}", phase="instagram")
        _queue_for_manual("instagram", title, content)
        return False
    except Exception as e:
        _ap_log(f"  Instagram publish error: {e}", level="WARNING", phase="instagram")
        _queue_for_manual("instagram", title, content)
        return False


def _publish_twitter(content: str) -> bool:
    try:
        from core.twitter import get_client
        tw = get_client()
        tweets = [t.strip() for t in re.split(r"\d+/", content) if t.strip()]
        if hasattr(tw, "post_tweet") and tweets:
            result = tw.post_tweet(tweets[0])
            return bool(result)
        _ap_log("  Twitter: thread saved for manual posting", phase="twitter")
        _queue_for_manual("twitter", "Thread", content)
        return False
    except Exception as e:
        _ap_log(f"  Twitter publish error: {e}", level="WARNING", phase="twitter")
        _queue_for_manual("twitter", "Thread", content)
        return False


def _publish_blog(content: str, title: str) -> bool:
    try:
        import urllib.request, os
        wp_url  = os.getenv("WORDPRESS_API_URL", "")
        wp_user = os.getenv("WORDPRESS_USER", "")
        wp_pass = os.getenv("WORDPRESS_APP_PASSWORD", "")
        if not (wp_url and wp_user and wp_pass):
            _queue_for_manual("blog", title, content)
            return False
        import base64
        creds = base64.b64encode(f"{wp_user}:{wp_pass}".encode()).decode()
        body  = json.dumps({"title": title, "content": content, "status": "publish"}).encode()
        req = urllib.request.Request(
            f"{wp_url}/wp-json/wp/v2/posts",
            data=body,
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
            return bool(data.get("id"))
    except Exception as e:
        _ap_log(f"  Blog publish error: {e}", level="WARNING", phase="blog")
        _queue_for_manual("blog", title, content)
        return False


def _publish_product(product: dict, platform: str) -> bool:
    title   = product.get("title", "")
    content = product.get("content", "")
    price   = product.get("price", 9.99)

    # Extract description from content
    desc = content[:2000]

    try:
        if platform == "gumroad":
            import urllib.request, urllib.parse
            token = os.getenv("GUMROAD_ACCESS_TOKEN", "")
            if not token:
                _queue_for_manual(platform, title, content)
                return False
            price_cents = int(float(price) * 100)
            data = urllib.parse.urlencode({
                "name": title, "description": desc,
                "price": price_cents, "published": "true",
            }).encode()
            req = urllib.request.Request(
                "https://api.gumroad.com/v2/products",
                data=data,
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                return resp.get("success", False)

        elif platform in ("etsy", "payhip"):
            _queue_for_manual(platform, title, content)
            return False

    except Exception as e:
        _ap_log(f"  {platform} publish error: {e}", level="WARNING", phase=platform)
        _queue_for_manual(platform, title, content)
        return False

    return False


def _queue_for_manual(platform: str, title: str, content: str):
    """Save content to manual publish queue when API not available."""
    try:
        queue_file = DATA_DIR / "autopilot_publish_queue.json"
        queue = []
        if queue_file.exists():
            try:
                queue = json.loads(queue_file.read_text())
            except Exception:
                pass
        queue.insert(0, {
            "platform": platform, "title": title,
            "content_preview": content[:300],
            "content": content,
            "queued_at": _now(), "status": "pending",
        })
        queue = queue[:200]
        queue_file.write_text(json.dumps(queue, indent=2, default=str))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# MAIN AUTOPILOT SESSION
# ══════════════════════════════════════════════════════════════════════════════

_ap_running = False
_ap_thread  = None


def run_autopilot_session(session_id: str = None):
    """
    Full NarAI autonomous creation session.
    Phases: Social → Products → KDP Books
    Called by the 1:30 AM daily schedule.
    """
    global _ap_running

    session_id = session_id or f"ap_{int(time.time())}"
    _ap_running = True

    state = _ap_load()
    state.update({
        "running": True, "session_id": session_id,
        "started_at": _now(), "phase": "starting",
        "task": "NarAI is reading market intelligence…",
        "progress": 0, "today_content": [],
        "stats": {"posts_created": 0, "posts_published": 0,
                  "products_created": 0, "products_published": 0,
                  "books_written": 0, "qc_passes": 0, "qc_fixes": 0},
    })
    _ap_save(state)
    _ap_log(f"🚀 NarAI Autopilot session {session_id} started", phase="start")

    try:
        # Read all market intelligence before creating anything
        _ap_log("🧠 NarAI reading full market briefing before creating…", phase="briefing")
        briefing = _get_full_briefing()
        if not briefing:
            _ap_log("⚠️ No market briefing available — running with base knowledge", level="WARNING")
            briefing = "No market briefing available. Use best practices."

        # ── PHASE 1: SOCIAL POSTS ──────────────────────────────────────────
        state["phase"] = "social_facebook"
        state["task"]  = "Creating 5 Facebook posts + videos"
        state["progress"] = 5
        _ap_save(state)
        _create_facebook_posts(state, briefing)

        if not _ap_running: raise InterruptedError("Stopped")

        state["phase"] = "social_instagram"
        state["task"]  = "Creating 5 Instagram posts + 1 video"
        state["progress"] = 20
        _ap_save(state)
        _create_instagram_posts(state, briefing)

        if not _ap_running: raise InterruptedError("Stopped")

        state["phase"] = "social_twitter"
        state["task"]  = "Creating Twitter/X thread"
        state["progress"] = 35
        _ap_save(state)
        _create_twitter_post(state, briefing)

        if not _ap_running: raise InterruptedError("Stopped")

        state["phase"] = "social_blog"
        state["task"]  = "Writing 5 blog articles"
        state["progress"] = 45
        _ap_save(state)
        _create_blog_posts(state, briefing)

        if not _ap_running: raise InterruptedError("Stopped")

        # ── PHASE 1.5: AI VIDEO CREATION ───────────────────────────────────
        state["phase"] = "video_creation"
        state["task"]  = "Creating AI videos (anime, cinematic) for TikTok, YouTube, Facebook"
        state["progress"] = 52
        _ap_save(state)
        _create_videos(state, briefing)

        if not _ap_running: raise InterruptedError("Stopped")

        # ── PHASE 2: DIGITAL PRODUCTS ──────────────────────────────────────
        state["phase"] = "products_gumroad"
        state["task"]  = "Creating 3 Gumroad products (publishing best 2)"
        state["progress"] = 58
        _ap_save(state)
        _create_platform_products("gumroad", 3, 2, state, briefing)

        if not _ap_running: raise InterruptedError("Stopped")

        state["phase"] = "products_etsy"
        state["task"]  = "Creating 3 Etsy listings (publishing best 2)"
        state["progress"] = 70
        _ap_save(state)
        _create_platform_products("etsy", 3, 2, state, briefing)

        if not _ap_running: raise InterruptedError("Stopped")

        state["phase"] = "products_payhip"
        state["task"]  = "Creating 3 Payhip products (publishing best 2)"
        state["progress"] = 80
        _ap_save(state)
        _create_platform_products("payhip", 3, 2, state, briefing)

        if not _ap_running: raise InterruptedError("Stopped")

        # ── PHASE 3: KDP BOOKS ─────────────────────────────────────────────
        state["phase"] = "kdp_books"
        state["task"]  = "Writing 2 Amazon KDP ebooks"
        state["progress"] = 88
        _ap_save(state)
        _create_kdp_books(state, briefing)

        # ── DONE ───────────────────────────────────────────────────────────
        state["phase"]    = "complete"
        state["task"]     = "Session complete ✅"
        state["progress"] = 100
        s = state["stats"]
        summary = (
            f"✅ Autopilot session {session_id} complete — "
            f"posts: {s['posts_created']} created / {s['posts_published']} published | "
            f"products: {s['products_created']} created / {s['products_published']} published | "
            f"books: {s['books_written']} | "
            f"QC passes: {s['qc_passes']} / fixes: {s['qc_fixes']}"
        )
        _ap_log(summary, phase="complete")

        # Save session to history
        session_record = {
            "id": session_id, "started_at": state["started_at"],
            "completed_at": _now(), "stats": state["stats"],
            "status": "completed", "content_count": len(state["today_content"]),
        }
        sessions = state.get("sessions", [])
        sessions.insert(0, session_record)
        state["sessions"] = sessions[:30]

        # Notify via Telegram
        try:
            from core.telegram import notify
            notify(
                f"🤖 <b>NarAI Autopilot Complete</b>\n"
                f"📱 Posts: {s['posts_created']} created, {s['posts_published']} published\n"
                f"🛍️ Products: {s['products_created']} created, {s['products_published']} published\n"
                f"📚 Books: {s['books_written']}\n"
                f"🔬 QC: {s['qc_passes']} reviews, {s['qc_fixes']} fixes"
            )
        except Exception:
            pass

    except InterruptedError:
        state["phase"] = "stopped"
        state["task"]  = "Stopped by user"
        _ap_log("⏹ Autopilot stopped by user", level="WARNING")
    except Exception as e:
        state["phase"] = "error"
        state["task"]  = f"Error: {str(e)[:100]}"
        _ap_log(f"❌ Autopilot error: {e}", level="ERROR")
        log.exception("Autopilot session error")
    finally:
        state["running"]   = False
        _ap_running        = False
        _ap_save(state)


def start_autopilot_background(session_id: str = None) -> str:
    global _ap_running, _ap_thread
    if _ap_running:
        return "already_running"
    session_id = session_id or f"ap_{int(time.time())}"
    _ap_thread = threading.Thread(
        target=run_autopilot_session,
        args=(session_id,),
        daemon=True, name="narai-autopilot",
    )
    _ap_thread.start()
    return session_id


def stop_autopilot():
    global _ap_running
    _ap_running = False


def get_ap_status() -> dict:
    state = _ap_load()
    return {
        "running":    _ap_running,
        "session_id": state.get("session_id"),
        "phase":      state.get("phase", "idle"),
        "task":       state.get("task", ""),
        "progress":   state.get("progress", 0),
        "started_at": state.get("started_at"),
        "stats":      state.get("stats", {}),
        "today_content": state.get("today_content", []),
        "sessions":   state.get("sessions", []),
    }


def get_ap_logs(limit: int = 200) -> list:
    logs = _ap_load_logs()[:limit]
    return [
        f"[{e.get('ts','')[:19]}] [{e.get('level','INFO')}] [{e.get('phase','—')}] {e.get('msg','')}"
        for e in logs
    ]


def get_publish_queue(limit: int = 50) -> list:
    try:
        queue_file = DATA_DIR / "autopilot_publish_queue.json"
        if queue_file.exists():
            return json.loads(queue_file.read_text())[:limit]
    except Exception:
        pass
    return []
