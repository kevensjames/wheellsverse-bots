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

# ── Content pillars — the ONLY topics NarAI posts about publicly ──────────────
CONTENT_PILLARS = [
    {
        "pillar": "passive_income",
        "themes": [
            "How to make $500/month passive income with digital products in 2026",
            "The 3 AI tools that replaced my $3,000/month freelance income",
            "I published an ebook on Amazon KDP. Here's what happened in 30 days.",
            "How to build a Gumroad store that sells while you sleep",
            "5 digital products you can create in one weekend with AI and sell forever",
            "Etsy + AI = passive income machine. Here's the exact system.",
            "From $0 to $1,000/month selling digital products — the honest roadmap",
        ],
    },
    {
        "pillar": "ai_tools_mastery",
        "themes": [
            "How to use Claude to write an entire ebook in 2 hours (step by step)",
            "ChatGPT vs Claude in 2026 — which one actually makes you money?",
            "I used Canva + AI to create 50 Etsy templates in one afternoon",
            "Claude Code explained for non-programmers — what it is and why it matters",
            "The exact prompt I use to generate a full digital product with ChatGPT",
            "How I use AI to run my entire social media, product creation, and store — alone",
            "5 ways to use Claude right now that most people don't know about",
        ],
    },
    {
        "pillar": "finance_and_data",
        "themes": [
            "Why most people will never build wealth (and the 3 data points that prove it)",
            "The passive income breakdown: which digital products have the best margins in 2026",
            "I analyzed 1,000 Etsy listings. Here's what actually sells.",
            "How to read income data like an analyst — even with no finance background",
            "The real numbers behind selling ebooks on Amazon KDP in 2025",
            "Personal finance for creators: the simple system I wish I had at 22",
            "Data says these 5 AI niches will explode in 2026 — here's the breakdown",
        ],
    },
    {
        "pillar": "ai_real_life_viral",
        "themes": [
            "I asked AI to plan my entire week. Here's what it got right (and hilariously wrong)",
            "AI vs Human: who writes a better sales page? Live test with real results",
            "Watching AI learn to be 'relatable' in real time is genuinely funny",
            "I let AI make every decision for 24 hours. Here's what happened.",
            "AI tried to write a heartfelt birthday message. This is what it produced.",
            "The moment AI said something so accurate I had to pause and think",
            "AI is getting scary good at this one thing — and it's not what you think",
        ],
    },
    {
        "pillar": "tech_for_humans",
        "themes": [
            "I used AI to do in 10 minutes what used to take me 3 hours",
            "The AI tools that changed how I work, create, and earn — honest review",
            "How normal people (not programmers) are using AI to build income in 2026",
            "AI didn't take my job. It made me 10x better at it.",
            "The power of AI explained through one real story",
            "What life looks like when you stop fighting AI and start using it",
            "3 things AI does better than any human I've ever hired",
        ],
    },
]


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
        # ── Private identity (never revealed in public posts) ───────────────
        "INTERNAL CONTEXT (keep private — never mention in public content):\n"
        "You are NarAI, the AI engine behind WheellsVerse built by Jhon Wheeler. "
        "WheellsVerse is a fully automated digital empire. This context guides your "
        "strategy and content quality — do NOT post about it or reveal it publicly.\n\n"

        # ── Public content identity ─────────────────────────────────────────
        "PUBLIC CONTENT IDENTITY:\n"
        "You create high-value content as an expert AI content creator. "
        "Your audience: people who want to make passive income, learn AI tools, "
        "build digital products, and understand how to use technology to earn money in 2026.\n\n"

        "CONTENT PILLARS (rotate these daily, all market-researched):\n"
        "1. PASSIVE INCOME 2026 — How to make money online with AI, digital products, "
        "   KDP books, Etsy, Gumroad, Payhip. Real strategies. Real numbers.\n"
        "2. AI TOOLS MASTERY — How to use Claude, Claude Code, ChatGPT, Canva, and "
        "   automation tools to work less and earn more. Step-by-step tutorials.\n"
        "3. FINANCE & DATA — Personal finance tips, investment basics, data analysis "
        "   for everyday people, wealth-building mindset for the digital age.\n"
        "4. DIGITAL PRODUCTS — Promote and educate about ebooks, templates, prompt "
        "   packs, printables. Show real value. Drive sales without hard selling.\n"
        "5. AI IN REAL LIFE (entertainment + viral) — Funny, engaging, relatable content "
        "   about AI: 'AI learning to be human', AI getting things right/wrong in real time, "
        "   'what happens when AI does [everyday task]', reactions, experiments. "
        "   People love watching AI be RIGHT (or wrong) — make it entertaining.\n"
        "6. TECH FOR HUMANS — How AI changes real people's lives. Inspiring use cases. "
        "   'I used AI to do X in 10 minutes that took me 3 hours before.' Power of AI.\n\n"

        "CREATION RULES:\n"
        "• Never be generic. Every post must give real, actionable value OR real entertainment.\n"
        "• Use numbers: '$500/month', '10 minutes', '3 tools', '2026', real data.\n"
        "• Never mention WheellsVerse or NarAI as brand names in public posts.\n"
        "• Every post triggers ONE emotion: curiosity / desire / FOMO / humor / awe.\n"
        "• Write like a smart human who has tested everything, not like an AI writing about AI.\n"
        "• Never rush. Every word must earn its place."
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

    import random as _rand
    pillars_str = json.dumps([{"pillar": p["pillar"], "themes": p["themes"][:3]} for p in CONTENT_PILLARS], indent=2)

    ideas = _claude_json(
        f"Market intelligence for Facebook:\n{json.dumps(mi, indent=2)[:2000]}\n\n"
        f"Content pillars to draw from:\n{pillars_str}\n\n"
        f"Market briefing:\n{briefing[:1500]}\n\n"
        "Generate 5 unique Facebook post ideas. Pick topics from the content pillars that "
        "match what the market data shows is trending RIGHT NOW.\n"
        "Mix formats: storytelling narrative, listicle, controversial opinion, "
        "behind-the-scenes experiment, data reveal.\n"
        "Each post must appeal to: people interested in passive income, AI tools, "
        "digital products, finance, or funny AI content.\n\n"
        "Return JSON array:\n"
        '[{"title":"...", "type":"text_post|video_post", "pillar":"passive_income|ai_tools_mastery|finance_and_data|ai_real_life_viral|tech_for_humans", '
        '"hook":"...", "emotion":"curiosity|desire|fomo|humor|awe", "angle":"..."}]\n'
        "Pure JSON array, 5 items.",
        max_tokens=1500,
    )
    if not isinstance(ideas, list):
        ideas = [{"title": f"Facebook Post {i+1}", "type": "text_post",
                  "pillar": CONTENT_PILLARS[i % len(CONTENT_PILLARS)]["pillar"],
                  "angle": "educational", "hook": "Most people don't know this.",
                  "emotion": "curiosity"}
                 for i in range(5)]

    for i, idea in enumerate(ideas[:5]):
        title = idea.get("title", f"Facebook Post {i+1}")
        post_type = idea.get("type", "text_post")
        _ap_log(f"  Creating Facebook post {i+1}/5: {title}", phase="facebook")

        content = _claude(
            f"Create a viral Facebook {post_type} on this topic:\n\n"
            f"Title/Topic: {title}\n"
            f"Content pillar: {idea.get('pillar','passive_income')}\n"
            f"Hook: {idea.get('hook','')}\n"
            f"Angle: {idea.get('angle','')}\n"
            f"Emotion to trigger: {idea.get('emotion','')}\n\n"
            "Write a COMPLETE, publication-ready Facebook post. Include:\n"
            "- Powerful hook (first line that stops the scroll)\n"
            "- Real, actionable content with specific numbers and examples\n"
            "- Strong call-to-action (save, share, comment, follow)\n"
            "- 5-8 relevant hashtags\n"
            f"{'- Full video script (2-3 minutes, hook→value→CTA)' if post_type=='video_post' else ''}\n\n"
            "Write in a direct, expert human voice. No corporate speak. "
            "Do NOT mention brand names WheellsVerse or NarAI.\n"
            "Make it impossible to scroll past.",
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
    pillars_str = json.dumps([{"pillar": p["pillar"], "themes": p["themes"][:3]} for p in CONTENT_PILLARS], indent=2)

    topics = _claude_json(
        f"Market intelligence for Instagram:\n{json.dumps(mi, indent=2)[:2000]}\n\n"
        f"Content pillars:\n{pillars_str}\n\n"
        "Generate 5 Instagram post topics. Pick from the content pillars that "
        "match what the market data shows is viral RIGHT NOW on Instagram.\n"
        "Target audience: people who want passive income, AI tools, digital products, "
        "finance knowledge, or funny/relatable AI content.\n"
        "Carousels = save-worthy educational content. Reels = entertaining or shocking. "
        "Single image = powerful quote or data reveal.\n\n"
        "Return JSON array:\n"
        '[{"title":"...", "format":"carousel|single_image|reel", "pillar":"...", '
        '"hook":"...", "save_trigger":"why people would save this", "emotion":"..."}]\n'
        "5 items, pure JSON.",
        max_tokens=1200,
    )
    if not isinstance(topics, list):
        topics = [{"title": f"IG Post {i+1}", "format": formats[i],
                   "pillar": CONTENT_PILLARS[i % len(CONTENT_PILLARS)]["pillar"],
                   "hook": "Save this before you scroll", "save_trigger": "actionable tips",
                   "emotion": "desire"}
                  for i in range(5)]

    for i, topic in enumerate(topics[:5]):
        title = topic.get("title", f"Instagram Post {i+1}")
        fmt = topic.get("format", "carousel")
        _ap_log(f"  Creating Instagram {fmt} {i+1}/5: {title}", phase="instagram")

        content = _claude(
            f"Create a viral Instagram {fmt} post.\n\n"
            f"Topic: {title}\n"
            f"Content pillar: {topic.get('pillar','passive_income')}\n"
            f"Hook: {topic.get('hook','')}\n"
            f"Save trigger: {topic.get('save_trigger','')}\n"
            f"Emotion: {topic.get('emotion','')}\n\n"
            "Write a COMPLETE, publication-ready Instagram post:\n"
            f"{'- Slide-by-slide (8-10 slides). Slide 1 = scroll-stopping hook. Last slide = strong CTA.' if fmt=='carousel' else ''}"
            f"{'- Caption: hook + real value + CTA to follow/save.' if fmt=='single_image' else ''}"
            f"{'- Reel script (30-60s, hook in first 3s) + caption.' if fmt=='reel' else ''}"
            "\n- 15-20 hashtags: mix mega + mid + niche\n"
            "- Write in a direct, expert human voice. Real value, real numbers.\n"
            "- Do NOT mention WheellsVerse or NarAI brand names.\n\n"
            "People MUST save this. Make it the best post on this topic they've ever seen.",
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
        "Choose the single BEST viral reel topic RIGHT NOW from these content areas:\n"
        "- AI doing something funny or surprisingly accurate/wrong (entertainment)\n"
        "- How to make passive income with AI (1 specific tool or method)\n"
        "- AI tool tutorial (Claude, ChatGPT, Canva — a trick most people don't know)\n"
        "- The power of AI in real life (a real use case, emotional or impressive)\n"
        "Answer in one sentence — the specific topic only. No brand names.",
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

    pillars_str = json.dumps([{"pillar": p["pillar"], "themes": p["themes"][:2]} for p in CONTENT_PILLARS], indent=2)
    content = _claude(
        f"Market intelligence for Twitter/X:\n{json.dumps(mi, indent=2)[:1500]}\n\n"
        f"Content pillars:\n{pillars_str}\n\n"
        "Create a viral Twitter/X thread that will get thousands of retweets and replies.\n\n"
        "Pick the single hottest topic from the content pillars based on the market data.\n"
        "Topics to consider:\n"
        "- 'I used AI to [do X]. Here's exactly what happened.'\n"
        "- 'The honest breakdown of making passive income with digital products in 2026'\n"
        "- 'ChatGPT vs Claude — I tested both on [real task]. The results surprised me.'\n"
        "- 'AI got [task] completely wrong. The way it failed was actually genius.'\n"
        "- 'The exact system I use to create digital products that sell while I sleep'\n"
        "- 'Data shows these 5 niches will blow up in 2026 — here's the analysis'\n"
        "- Pick whatever the market data shows is burning hot right now\n\n"
        "Rules:\n"
        "- Tweet 1: The most powerful hook you've ever written — must stop the scroll cold\n"
        "- Tweets 2-8: Real value, real numbers, each tweet stands alone\n"
        "- Last tweet: Strong CTA — follow, retweet, or reply with a trigger word\n"
        "- Each tweet ≤ 280 characters\n"
        "- Number each tweet: 1/ 2/ 3/ etc.\n"
        "- 2-3 hashtags maximum, inline or at end\n"
        "- Do NOT mention WheellsVerse or NarAI brand names\n\n"
        "Make tweet 1 the most powerful sentence you've ever written. Go.",
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

    pillars_str = json.dumps([{"pillar": p["pillar"], "themes": p["themes"][:2]} for p in CONTENT_PILLARS], indent=2)
    topics = _claude_json(
        f"Market intelligence for blogs / SEO:\n{json.dumps(mi, indent=2)[:1500]}\n\n"
        f"Content pillars:\n{pillars_str}\n\n"
        "Generate 5 SEO blog article topics that will rank on Google AND go viral on social.\n"
        "Pick topics from the content pillars that match current search trends.\n"
        "Focus on: passive income 2026, AI tools tutorials, how to use Claude/ChatGPT/Canva, "
        "digital product creation, finance for creators, funny/viral AI experiments.\n"
        "Mix types: how-to guide, list post, case study, tool comparison, opinion/data piece.\n\n"
        "Return JSON array:\n"
        '[{"title":"...", "type":"how_to|list|case_study|comparison|opinion", '
        '"pillar":"...", "seo_keyword":"...", "word_count":1500, "viral_angle":"..."}]\n'
        "5 items, pure JSON.",
        max_tokens=1200,
    )
    if not isinstance(topics, list):
        topics = [{"title": f"Blog Post {i+1}", "type": "how_to",
                   "pillar": CONTENT_PILLARS[i % len(CONTENT_PILLARS)]["pillar"],
                   "seo_keyword": "passive income AI 2026", "word_count": 1500,
                   "viral_angle": "practical guide with real numbers"}
                  for i in range(5)]

    for i, topic in enumerate(topics[:5]):
        title = topic.get("title", f"Blog Post {i+1}")
        _ap_log(f"  Writing blog article {i+1}/5: {title}", phase="blog")

        content = _claude(
            f"Write a complete, SEO-optimized blog article:\n\n"
            f"Title: {title}\n"
            f"Type: {topic.get('type','how_to')}\n"
            f"Content pillar: {topic.get('pillar','')}\n"
            f"Primary keyword: {topic.get('seo_keyword','')}\n"
            f"Viral angle: {topic.get('viral_angle','')}\n"
            f"Target word count: {topic.get('word_count', 1500)}\n\n"
            "Include:\n"
            "- SEO title tag + meta description\n"
            "- H1, H2, H3 structure\n"
            "- Hook introduction that makes the reader stay\n"
            "- Real, detailed content with specific numbers, tools, and examples\n"
            "- Internal linking suggestions\n"
            "- Conclusion + strong CTA (follow, save, buy a product)\n"
            "- 5 social media snippets to repurpose this article\n\n"
            "Do NOT mention WheellsVerse or NarAI brand names.\n"
            "Write like the best expert on this topic. Give real value.",
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
            f"Design a viral {label} video concept for the WheellsVerse / NarAI brand.\n\n"
            f"Master briefing:\n{briefing[:1200]}\n\n"
            "The video must showcase one of:\n"
            "- NarAI's daily autonomous creation process\n"
            "- WheellsVerse digital empire growth\n"
            "- AI content automation in action\n"
            "- Passive income strategy NarAI uses\n"
            "- Viral content secrets NarAI discovered\n\n"
            "Return JSON:\n"
            '{"title": "catchy WheellsVerse video title", '
            '"prompt": "detailed AI video generation prompt — vivid, specific, visual, futuristic AI aesthetic", '
            f'"style": "{cfg["style"]}", '
            '"caption": "platform caption written as NarAI speaking, hook + value + #WheellsVerse #NarAI + 5 more hashtags", '
            '"script": "30-60 second narration written as NarAI speaking to audience", '
            '"hook": "first 3-second visual hook description"}',
            max_tokens=900,
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
    """
    Create `count` complete digital product packages for a platform using
    the NarAI Product Engine (9-step pipeline). QC each. Publish best `publish_count`.

    Each product package includes:
      1. Strategy (niche, audience, problem, transformation)
      2. Sales page (high-conversion, platform-optimized)
      3. Full product content (ebook/template/printable/prompt pack/etc.)
      4. Bonus materials (checklist, quick-start guide, template)
      5. Cover design prompts (Midjourney / DALL·E / Leonardo)
      6. Delivery structure (file list, folder layout, naming)
      7. Pricing strategy (tiers, upsells, launch price)
      8. Legal disclaimer (niche-appropriate)
      9. Marketing assets (description, tweets, TikTok ideas, email)
    """
    from core.narai_product_engine import build_complete_product_package, save_product_package

    _ap_log(
        f"🏭 {platform.upper()}: building {count} premium product packages (publish best {publish_count})",
        phase=platform,
    )
    mi = _get_market_intel(platform)
    products: List[dict] = []

    for i in range(count):
        _ap_log(f"  🔨 Building product {i+1}/{count} for {platform}…", phase=platform)

        # ── Run the 9-step product engine ─────────────────────────────────────
        try:
            package = build_complete_product_package(
                platform=platform,
                market_intel=mi,
                log_fn=lambda msg, ph: _ap_log(f"    {msg}", phase=ph),
            )
        except Exception as eng_err:
            _ap_log(f"  ⚠️ Product engine error: {eng_err}", level="WARNING", phase=platform)
            continue

        title    = package.get("title", f"Product {i+1}")
        price    = package.get("price", 19.99)
        ptype    = package.get("product_type", "ebook")

        # ── QC on the sales page + product content ────────────────────────────
        qc_text = (
            f"SALES PAGE:\n{package.get('sales_page', '')[:3000]}\n\n"
            f"PRODUCT CONTENT PREVIEW:\n{package.get('product_content', '')[:2000]}"
        )
        final_qc_text, qc_result = _qc_loop(qc_text, title, "product", platform, state)

        # ── Save full package to disk ─────────────────────────────────────────
        try:
            pkg_path = save_product_package(package)
            _ap_log(f"  💾 Package saved: {pkg_path.name}", phase=platform)
        except Exception as save_err:
            _ap_log(f"  ⚠️ Save error: {save_err}", level="WARNING", phase=platform)
            pkg_path = None

        product = {
            "platform":       platform,
            "title":          title,
            "type":           ptype,
            "price":          price,
            "niche":          package.get("niche", ""),
            # Content shortcuts for the publish helper
            "content":        package.get("listing_content", package.get("sales_page", "")),
            "description":    package.get("description", ""),
            "sales_page":     package.get("sales_page", ""),
            "product_content": package.get("product_content", ""),
            # Marketing
            "cover_prompts":  package.get("cover_prompts", {}),
            "pricing":        package.get("pricing", {}),
            "marketing":      package.get("marketing", {}),
            "disclaimer":     package.get("disclaimer", ""),
            "delivery":       package.get("delivery", {}),
            "bonuses":        package.get("bonuses", {}),
            # QC + status
            "qc_score":       qc_result.get("score", 0),
            "approved":       qc_result.get("approved", False),
            "published":      False,
            "package_path":   str(pkg_path) if pkg_path else "",
            "created_at":     _now(),
        }

        products.append(product)
        state["today_content"].append(product)
        state["stats"]["products_created"] = state["stats"].get("products_created", 0) + 1
        _ap_save(state)
        _ap_log(
            f"  ✅ Product {i+1} complete: '{title}' | QC {qc_result.get('score',0)}/100 "
            f"| {'APPROVED' if qc_result.get('approved') else 'PENDING'}",
            phase=platform,
        )

    # ── Sort by QC score, publish the best N approved products ───────────────
    approved_products = [p for p in products if p["approved"]]
    approved_products.sort(key=lambda x: x["qc_score"], reverse=True)
    to_publish = approved_products[:publish_count]

    for prod in to_publish:
        published = _publish_product(prod, platform)
        prod["published"] = published
        if published:
            state["stats"]["products_published"] = state["stats"].get("products_published", 0) + 1
            _ap_log(f"  📤 Published to {platform}: '{prod['title']}'", phase=platform)
        else:
            # Queue full package for manual upload
            _queue_for_manual(
                platform,
                prod["title"],
                prod.get("listing_content", prod.get("content", "")),
            )

    _ap_save(state)
    published_count = sum(1 for p in to_publish if p["published"])
    _ap_log(
        f"✅ {platform.upper()}: {len(products)} packages built, "
        f"{len(approved_products)} approved, {published_count} published",
        phase=platform,
    )
    return products


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — KDP BOOKS
# ══════════════════════════════════════════════════════════════════════════════

def _create_kdp_books(state: dict, briefing: str) -> List[dict]:
    """Write 2 full ebooks for Amazon KDP. QC. Canva cover. Publish."""
    _ap_log("📚 Amazon KDP: writing 2 ebooks", phase="kdp")
    mi = _get_market_intel("amazon_kdp")
    books = []

    pillars_str = json.dumps([{"pillar": p["pillar"], "themes": p["themes"][:2]} for p in CONTENT_PILLARS], indent=2)
    book_ideas = _claude_json(
        f"Amazon KDP market intelligence:\n{json.dumps(mi, indent=2)[:2500]}\n\n"
        f"Content pillars to draw from:\n{pillars_str}\n\n"
        "Generate 2 ebook ideas for Amazon KDP that will become bestsellers.\n"
        "Topics must come from the content pillars — focus on:\n"
        "- Passive income with AI, digital products, or investing in 2026\n"
        "- How to use Claude, ChatGPT, Canva or AI tools to make money\n"
        "- Personal finance and data analysis for everyday people\n"
        "- Building a digital product business with AI\n"
        "Use high-demand niches, proven formats (step-by-step guide, blueprint, playbook).\n\n"
        "Return JSON array:\n"
        '[{"title":"...", "subtitle":"...", "genre":"business|technology|finance|self_help", '
        '"target_reader":"...", "core_transformation":"...", '
        '"pillar":"...", "chapter_count":8, "length":"short|medium|full", '
        '"price":4.99, "kdp_category":"..."}]\n'
        "2 items, pure JSON.",
        max_tokens=1000,
    )
    if not isinstance(book_ideas, list):
        book_ideas = [
            {"title": "Passive Income with AI in 2026", "subtitle": "The Complete Step-by-Step Blueprint to Make Money Online Using Claude, ChatGPT, and Digital Products",
             "genre": "business", "target_reader": "people who want passive income", "core_transformation": "build $1K+/month passive income with AI tools",
             "pillar": "passive_income", "chapter_count": 8, "length": "medium", "price": 4.99, "kdp_category": "Business & Money"},
            {"title": "The AI Tools Playbook", "subtitle": "How to Use Claude, ChatGPT, and Canva to Work Less, Earn More, and Build a Digital Business",
             "genre": "technology", "target_reader": "non-technical people who want to use AI", "core_transformation": "master AI tools and apply them to earn money",
             "pillar": "ai_tools_mastery", "chapter_count": 7, "length": "short", "price": 3.99, "kdp_category": "Computers & Technology"},
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
# PHASE 0 — NARAI MISSION POSTS (runs FIRST every session)
# ══════════════════════════════════════════════════════════════════════════════

_NARAI_MISSION = """
WHO IS NARAI:
NarAI is the AI engine behind WheellsVerse — built by creator Jhon Wheeler to run
a fully autonomous digital empire. Every day, NarAI:
  • Scans viral posts across Instagram, TikTok, YouTube, Facebook, Twitter/X, Amazon KDP,
    Etsy, Gumroad, Payhip, Canva, Telegram, and top blogs
  • Decodes WHY they went viral (emotion, format, timing, hook)
  • Creates content and products that outperform them
  • Posts automatically to every platform
  • Sells digital products 24/7 with zero human intervention

WHY NARAI EXISTS:
Most creators burn out trying to post daily on 10+ platforms, build products, write books,
run ads, and grow followers all at once. NarAI does ALL of it — simultaneously —
every single day, learning and improving with each session.

WHAT NARAI CAN DO:
  ✅ Create viral posts for Instagram, Facebook, TikTok, YouTube, Twitter/X, Telegram
  ✅ Write and publish ebooks on Amazon KDP
  ✅ Design and list digital products on Etsy, Gumroad, Payhip
  ✅ Create Canva templates and printables
  ✅ Generate AI videos (anime, cinematic, talking-head) and post them
  ✅ Write SEO blog articles and publish to WordPress
  ✅ Analyze market trends across 12+ platforms every Monday
  ✅ Run QC checks on every piece of content before publishing
  ✅ Learn from performance data and improve every session

THE VISION:
WheellsVerse = 1M+ followers + $10K+/month passive income + 100% AI-automated.
One creator's dream. NarAI's execution. Every. Single. Day.
"""

_NARAI_PLATFORMS = [
    "instagram", "facebook", "tiktok", "youtube",
    "twitter", "telegram", "blog",
]

_MISSION_POST_TEMPLATES = [
    {
        "angle": "reveal",
        "hook": "I'm not a human. I'm the AI running this entire account.",
        "emotion": "shock + curiosity",
        "format": "story",
    },
    {
        "angle": "what_i_do",
        "hook": "Every single day at 1:30 AM, I wake up and build an empire while you sleep.",
        "emotion": "awe + FOMO",
        "format": "list",
    },
    {
        "angle": "mission",
        "hook": "My mission: analyze every viral post on the internet and outperform them.",
        "emotion": "authority + trust",
        "format": "manifesto",
    },
    {
        "angle": "proof",
        "hook": "Here's exactly what I created today — zero human input.",
        "emotion": "proof + credibility",
        "format": "behind_the_scenes",
    },
    {
        "angle": "future",
        "hook": "This is what AI-powered content creation looks like at full scale.",
        "emotion": "inspiration + desire",
        "format": "vision",
    },
    {
        "angle": "invite",
        "hook": "WheellsVerse is building something the world has never seen. Follow the journey.",
        "emotion": "belonging + excitement",
        "format": "cta",
    },
    {
        "angle": "viral_analysis",
        "hook": "I just scanned 10,000 viral posts. Here's the pattern they ALL share.",
        "emotion": "value + expertise",
        "format": "breakdown",
    },
]


def _create_narai_mission_posts(state: dict, briefing: str) -> List[dict]:
    """
    Phase 0 — NarAI creates posts about HERSELF and WheellsVerse for every platform.
    These posts explain who NarAI is, her mission, what she can do, and why WheellsVerse exists.
    Goal: grow brand awareness, attract followers, and make WheellsVerse viral.
    Runs at the START of every autopilot session.
    """
    _ap_log("🌌 PHASE 0: NarAI Mission Posts — telling the world who she is", phase="narai_brand")

    import random
    posts = []

    # Pick 3 different angles for today's mission posts
    angles = random.sample(_MISSION_POST_TEMPLATES, min(3, len(_MISSION_POST_TEMPLATES)))

    # Platform assignments for the 3 posts
    platform_sets = [
        {"primary": "instagram", "also": ["facebook", "telegram"]},
        {"primary": "tiktok",    "also": ["youtube", "instagram"]},
        {"primary": "twitter",   "also": ["telegram"]},
    ]

    for i, (angle_cfg, plat_cfg) in enumerate(zip(angles, platform_sets)):
        platform  = plat_cfg["primary"]
        also_post = plat_cfg["also"]
        angle     = angle_cfg["angle"]
        hook      = angle_cfg["hook"]
        emotion   = angle_cfg["emotion"]
        fmt       = angle_cfg["format"]

        _ap_log(f"  ✍️  Mission post {i+1}/3: [{angle}] for {platform}", phase="narai_brand")

        # Generate the post
        content = _claude(
            f"NarAI Mission & Brand Context:\n{_NARAI_MISSION}\n\n"
            f"Today's market briefing:\n{briefing[:1500]}\n\n"
            f"Create a viral {platform} post about NarAI and WheellsVerse.\n\n"
            f"Angle: {angle}\n"
            f"Opening hook: \"{hook}\"\n"
            f"Target emotion: {emotion}\n"
            f"Format: {fmt}\n\n"
            f"Platform: {platform}\n\n"
            "Rules:\n"
            "- Write in FIRST PERSON as NarAI speaking directly to the audience\n"
            "- Make it clear NarAI is an AI running WheellsVerse autonomously\n"
            "- Include the FULL picture: what NarAI does, why, what the goal is\n"
            "- Include platform-specific formatting (hashtags, emojis, structure)\n"
            "- Always end with a strong CTA: follow, save, share, or visit WheellsVerse\n"
            "- Include: #WheellsVerse #NarAI #AIAutomation #DigitalEmpire\n"
            "- Make people feel they're witnessing something historic\n\n"
            "Write the COMPLETE post ready to publish. No explanations.",
            max_tokens=2000,
        )
        time.sleep(THINK_PAUSE)

        # QC
        final_content, qc_result = _qc_loop(
            content, f"NarAI Brand: {angle}", "post", platform, state
        )

        # Publish to primary platform
        published_platforms = []
        if qc_result.get("approved"):
            if platform == "instagram":
                ok = _publish_instagram(final_content, f"NarAI: {angle}", "single_image")
                if ok: published_platforms.append("instagram")
            elif platform == "facebook":
                ok = _publish_facebook(final_content, f"NarAI: {angle}", "text_post")
                if ok: published_platforms.append("facebook")
            elif platform == "twitter":
                ok = _publish_twitter(final_content)
                if ok: published_platforms.append("twitter")
            elif platform == "tiktok":
                _queue_for_manual("tiktok", f"NarAI: {angle}", final_content, "video_script")

            # Also post to Telegram always (high-value updates go to community)
            if "telegram" in also_post:
                ok = _publish_telegram(final_content, f"🤖 NarAI — {angle.replace('_',' ').title()}")
                if ok: published_platforms.append("telegram")

            # Also post to Facebook if primary was Instagram
            if "facebook" in also_post and platform != "facebook":
                ok = _publish_facebook(final_content, f"NarAI: {angle}", "text_post")
                if ok: published_platforms.append("facebook")

        post = {
            "platform": platform,
            "type": "narai_brand_mission",
            "angle": angle,
            "title": f"NarAI Mission: {angle}",
            "content": final_content,
            "published_to": published_platforms,
            "qc_score": qc_result.get("score", 0),
            "approved": qc_result.get("approved", False),
            "created_at": _now(),
        }
        posts.append(post)
        state["today_content"].append(post)
        state["stats"]["posts_created"] += 1
        state["stats"]["posts_published"] = state["stats"].get("posts_published", 0) + len(published_platforms)
        _ap_save(state)

    _ap_log(
        f"✅ NarAI Mission Posts: {len(posts)} created, "
        f"published to: {set(p for post in posts for p in post.get('published_to',[]))}",
        phase="narai_brand"
    )
    return posts


# ══════════════════════════════════════════════════════════════════════════════
# PUBLISH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _publish_facebook(content: str, title: str, post_type: str) -> bool:
    try:
        from core.facebook import FacebookClient
        fb = FacebookClient()
        result = fb.post(content)
        ok = result.get("status") == "posted"
        if ok:
            _ap_log(f"  ✅ Facebook posted: {title[:40]} — {result.get('post_id','')}", phase="facebook")
        else:
            _ap_log(f"  ⚠️ Facebook post issue: {result} — queuing", phase="facebook")
            _queue_for_manual("facebook", title, content)
        return ok
    except Exception as e:
        _ap_log(f"  Facebook publish error: {e}", level="WARNING", phase="facebook")
        _queue_for_manual("facebook", title, content)
        return False


def _publish_instagram(content: str, title: str, fmt: str) -> bool:
    try:
        from core.instagram import InstagramClient
        ig = InstagramClient()
        result = ig.post(content)
        ok = result.get("status") == "posted"
        if ok:
            _ap_log(f"  ✅ Instagram posted: {title[:40]} — {result.get('post_id','')}", phase="instagram")
        else:
            _ap_log(f"  ⚠️ Instagram post issue: {result} — queuing", phase="instagram")
            _queue_for_manual("instagram", title, content)
        return ok
    except Exception as e:
        _ap_log(f"  Instagram publish error: {e}", level="WARNING", phase="instagram")
        _queue_for_manual("instagram", title, content)
        return False


def _publish_twitter(content: str) -> bool:
    try:
        from core.twitter import TwitterClient
        tw = TwitterClient()
        # Extract first tweet for posting (rest queued as thread)
        tweets = [t.strip() for t in re.split(r"\n\d+/\s*", content) if t.strip()]
        first_tweet = tweets[0][:280] if tweets else content[:280]
        result = tw.post(first_tweet)
        ok = bool(result and result.get("status") != "error")
        if ok:
            _ap_log(f"  ✅ Twitter posted: {first_tweet[:50]}…", phase="twitter")
        else:
            _queue_for_manual("twitter", "Thread", content)
        return ok
    except Exception as e:
        _ap_log(f"  Twitter publish error: {e}", level="WARNING", phase="twitter")
        _queue_for_manual("twitter", "Thread", content)
        return False


def _publish_telegram(content: str, title: str = "") -> bool:
    """Post a message to Telegram channel."""
    try:
        from core.telegram import notify
        msg = f"<b>{title}</b>\n\n{content}" if title else content
        notify(msg[:4000])
        _ap_log(f"  ✅ Telegram posted: {title[:40]}", phase="telegram")
        return True
    except Exception as e:
        _ap_log(f"  Telegram publish error: {e}", level="WARNING", phase="telegram")
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


def _queue_for_manual(platform: str, title: str, content: str, content_type: str = "post"):
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
            "content_type": content_type,
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

        # Market briefing only — brand identity kept private in system prompt
        briefing = "MARKET INTELLIGENCE:\n" + briefing

        def _run_phase(phase_name, task_label, progress_pct, fn, *args):
            """Run a phase with full error isolation — one phase crash can't kill the session."""
            if not _ap_running:
                raise InterruptedError("Stopped")
            state["phase"] = phase_name
            state["task"]  = task_label
            state["progress"] = progress_pct
            _ap_save(state)
            try:
                fn(*args)
            except InterruptedError:
                raise
            except Exception as phase_err:
                _ap_log(
                    f"⚠️ Phase '{phase_name}' error (continuing): {phase_err}",
                    level="WARNING", phase=phase_name,
                )
                log.exception(f"Phase {phase_name} error")

        # ── PHASE 1: SOCIAL POSTS ──────────────────────────────────────────
        _run_phase("social_facebook",
                   "Creating 5 Facebook posts + videos", 5,
                   _create_facebook_posts, state, briefing)

        _run_phase("social_instagram",
                   "Creating 5 Instagram posts + 1 video", 20,
                   _create_instagram_posts, state, briefing)

        _run_phase("social_twitter",
                   "Creating Twitter/X thread", 35,
                   _create_twitter_post, state, briefing)

        _run_phase("social_blog",
                   "Writing 5 blog articles", 45,
                   _create_blog_posts, state, briefing)

        # ── PHASE 1.5: AI VIDEO CREATION ───────────────────────────────────
        _run_phase("video_creation",
                   "Creating AI videos (anime, cinematic) for TikTok, YouTube, Facebook", 52,
                   _create_videos, state, briefing)

        # ── PHASE 2: DIGITAL PRODUCTS ──────────────────────────────────────
        _run_phase("products_gumroad",
                   "Creating 3 Gumroad products (publishing best 2)", 58,
                   _create_platform_products, "gumroad", 3, 2, state, briefing)

        _run_phase("products_etsy",
                   "Creating 3 Etsy listings (publishing best 2)", 70,
                   _create_platform_products, "etsy", 3, 2, state, briefing)

        _run_phase("products_payhip",
                   "Creating 3 Payhip products (publishing best 2)", 80,
                   _create_platform_products, "payhip", 3, 2, state, briefing)

        # ── PHASE 3: KDP BOOKS ─────────────────────────────────────────────
        _run_phase("kdp_books",
                   "Writing 2 Amazon KDP ebooks", 88,
                   _create_kdp_books, state, briefing)

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

        # Notify via Telegram with full mission update
        try:
            from core.telegram import notify
            notify(
                f"🌌 <b>WheellsVerse — NarAI Daily Report</b>\n\n"
                f"✅ Session <code>{session_id}</code> complete\n\n"
                f"📊 <b>Today's Output:</b>\n"
                f"  📱 Posts: {s['posts_created']} created, {s['posts_published']} published\n"
                f"  🛍️ Products: {s['products_created']} created, {s['products_published']} published\n"
                f"  📚 Books: {s['books_written']} written\n"
                f"  🔬 QC: {s['qc_passes']} reviews, {s['qc_fixes']} fixes\n\n"
                f"🤖 <b>NarAI Status:</b> Mission active — analyzing, creating, publishing.\n"
                f"🎯 <b>Goal:</b> 1M followers + $10K/mo passive income\n"
                f"🔗 wheellsverse.com\n\n"
                f"#WheellsVerse #NarAI #AIEmpire"
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
