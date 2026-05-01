#!/usr/bin/env python3
"""
core/repurpose.py
─────────────────────────────────────────────────────────────────────────────
Auto-repurposing pipeline.

Takes one piece of content (markdown) and produces ready-to-publish
format for every channel — simultaneously.

Output formats:
  twitter_thread    — 6-8 tweet thread with hook + key points + CTA
  tiktok_caption    — punchy 150-char caption + hashtags
  email_subject     — 5 A/B subject line variants
  reddit_post       — self-post title + body formatted for Reddit
  instagram_caption — carousel-ready caption with line breaks + emojis
  linkedin_post     — professional tone, 1200-char limit

Usage:
  from core.repurpose import repurpose
  result = repurpose(content="...", title="...")
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("repurpose")

REPURPOSE_DIR = ROOT / "outputs" / "repurposed"

CTA_URL = os.getenv("CTA_URL", "https://grateful-flexibility-production.up.railway.app/landing")
BRAND = os.getenv("BRAND_NAME", "WheellsVerse")
AUTHOR = os.getenv("AUTHOR_NAME", "J.K. Blaze")


# ── GPT helper ────────────────────────────────────────────────────────────────

def _gpt(prompt: str, system: str = "", max_tokens: int = 800) -> str:
    from core.llm_client import safe_openai_call
    model = os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = safe_openai_call(
        messages=messages, model=model, max_tokens=max_tokens, temperature=0.7,
        bot_name="repurpose._gpt",
    )
    return resp.choices[0].message.content.strip()


def _personality_system(platform: str, topic: str = "") -> str:
    """Inject NarAI personality + goal directive into system prompt."""
    try:
        from core.personality import PersonalityEngine
        from core.goal_tracker import GoalTracker
        identity = PersonalityEngine.get().get_full_prompt(platform, topic)
        directive = GoalTracker.get().get_content_directive(platform, topic)
        return f"{identity}\n\nCONTENT DIRECTIVE: {directive}"
    except Exception:
        return f"You are NarAI, a sharp AI content creator for {BRAND}. Brand: {AUTHOR}."


def _extract_title(content: str, fallback: str = "") -> str:
    m = re.search(r"^#+\s+(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else fallback or "WheellsVerse Post"


def _first_paragraph(content: str) -> str:
    """Get first non-heading paragraph (first 500 chars)."""
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and len(line) > 40:
            return line[:500]
    return content[:500]


# ── Per-channel formatters ────────────────────────────────────────────────────

def _make_twitter_thread(title: str, content: str) -> str:
    from core.twitter import TwitterClient
    tweets = TwitterClient.format_thread_from_markdown(content, max_tweets=8)
    return "\n\n---\n".join(tweets)


def _make_tiktok_caption(title: str, content: str) -> str:
    tags = "#passiveincome #money #investing #sidehustle #crypto #makemoney #financialfreedom #ai #wealth"
    snippet = _first_paragraph(content)[:200]
    caption = _gpt(
        f"Write a punchy TikTok caption (max 150 chars, no hashtags) for this content:\n\nTitle: {title}\n\n{snippet}",
        system=_personality_system("tiktok", title),
        max_tokens=80,
    )
    return f"{caption[:150]}\n\n{tags}"


def _make_email_subjects(title: str, content: str) -> str:
    snippet = _first_paragraph(content)[:300]
    subjects = _gpt(
        f"Write 5 email subject line variants (A/B test ready) for this article. "
        f"Each on its own line, numbered. Mix curiosity, urgency, benefit, and social proof angles.\n\n"
        f"Title: {title}\n\nContent preview: {snippet}",
        system="You write high-converting email subject lines for a finance newsletter. Be specific with numbers.",
        max_tokens=200,
    )
    return subjects


def _make_reddit_post(title: str, content: str) -> str:
    snippet = _first_paragraph(content)[:400]
    body = _gpt(
        f"Write a Reddit self-post for r/passiveincome or r/personalfinance. "
        f"Start with a personal hook, share the key insight, ask a question at the end. "
        f"Keep it under 400 words. Do NOT be promotional or salesy — Reddit users hate that.\n\n"
        f"Based on: {title}\n\n{snippet}",
        system="You write authentic, helpful Reddit posts about personal finance and passive income. "
               "Write in first person, be genuine, share real insights.",
        max_tokens=500,
    )
    reddit_title = _gpt(
        f"Write a Reddit post title (max 100 chars) for: {title}. "
        f"Make it conversational and curiosity-driven.",
        max_tokens=50,
    )
    return f"TITLE: {reddit_title.strip()}\n\n{body}"


def _make_instagram_caption(title: str, content: str) -> str:
    snippet = _first_paragraph(content)[:300]
    caption = _gpt(
        f"Write an Instagram carousel caption (200-300 chars) for this finance content. "
        f"Use line breaks for readability. Start with a hook. End with a CTA like 'Save this post 📌'. "
        f"Add 5 relevant hashtags at the end.\n\nTitle: {title}\n\n{snippet}",
        system=_personality_system("instagram", title),
        max_tokens=250,
    )
    return caption


def _make_linkedin_post(title: str, content: str) -> str:
    snippet = _first_paragraph(content)[:400]
    post = _gpt(
        f"Write a LinkedIn post (600-900 chars) about this topic. "
        f"Start with a bold single-sentence hook. Use line breaks after every 1-2 sentences. "
        f"Share 3 key insights as a numbered list. End with a thought-provoking question.\n\n"
        f"Title: {title}\n\nContent: {snippet}",
        system=_personality_system("linkedin", title),
        max_tokens=400,
    )
    return post


def _make_threads_post(title: str, content: str) -> str:
    snippet = _first_paragraph(content)[:200]
    post = _gpt(
        f"Write a Threads post (max 500 chars) — conversational hot take or insight. "
        f"No hashtags. End with a question or strong opinion.\n\nTitle: {title}\n\n{snippet}",
        system=_personality_system("threads", title),
        max_tokens=120,
    )
    return post[:500]


def _make_facebook_post(title: str, content: str) -> str:
    snippet = _first_paragraph(content)[:400]
    post = _gpt(
        f"Write a Facebook post (150-300 words) — friendly, shareable, community angle. "
        f"Start with a question or relatable hook. End by asking followers their opinion. "
        f"Include CTA to link in bio or comments.\n\nTitle: {title}\n\n{snippet}",
        system=_personality_system("facebook", title),
        max_tokens=350,
    )
    return post


def _make_pinterest_pin(title: str, content: str) -> str:
    snippet = _first_paragraph(content)[:300]
    result = _gpt(
        f"Write a Pinterest pin. Return JSON with two fields: "
        f"'title' (max 100 chars, keyword-rich, benefit-driven) and "
        f"'description' (2-3 sentences, searchable, evergreen).\n\nTopic: {title}\n\n{snippet}",
        system=_personality_system("pinterest", title),
        max_tokens=150,
    )
    return result


def _make_youtube_script(title: str, content: str) -> str:
    snippet = content[:800]
    script = _gpt(
        f"Write a 55-60 second YouTube Shorts script (spoken word, ~150 words). "
        f"Structure: Hook (5s) → 3 Key Points (40s) → CTA (10s). "
        f"CTA: 'Follow for more AI and money content. Link in bio to get the free Blueprint.'\n\n"
        f"Topic: {title}\n\n{snippet}",
        system=_personality_system("youtube", title),
        max_tokens=300,
    )
    return script


# ── Main repurpose function ───────────────────────────────────────────────────

FORMATS = {
    "twitter_thread": _make_twitter_thread,
    "tiktok_caption": _make_tiktok_caption,
    "email_subjects": _make_email_subjects,
    "reddit_post": _make_reddit_post,
    "instagram_caption": _make_instagram_caption,
    "linkedin_post": _make_linkedin_post,
    "threads_post": _make_threads_post,
    "facebook_post": _make_facebook_post,
    "pinterest_pin": _make_pinterest_pin,
    "youtube_script": _make_youtube_script,
}


def repurpose(
    content: str,
    title: str = "",
    formats: Optional[List[str]] = None,
    save: bool = True,
) -> Dict[str, str]:
    """
    Repurpose markdown content into all platform formats simultaneously.

    Args:
        content: Markdown article text
        title:   Article title (extracted from content if not provided)
        formats: Subset of FORMATS keys, or None = all
        save:    Whether to save outputs to disk

    Returns:
        Dict mapping format name → formatted string
    """
    title = title or _extract_title(content)
    target_formats = formats or list(FORMATS.keys())

    results: Dict[str, str] = {}
    errors: Dict[str, str] = {}

    def _run_format(fmt_name: str) -> tuple:
        fn = FORMATS[fmt_name]
        try:
            output = fn(title, content)
            return fmt_name, output, None
        except Exception as e:
            logger.error(f"Repurpose failed [{fmt_name}]: {e}")
            return fmt_name, None, str(e)

    # Run all formats in parallel
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(_run_format, fmt): fmt for fmt in target_formats}
        for future in as_completed(futures):
            fmt_name, output, error = future.result()
            if output:
                results[fmt_name] = output
            if error:
                errors[fmt_name] = error

    if save and results:
        _save_repurposed(title, results)

    logger.info(f"Repurposed '{title}' into {len(results)} formats "
                f"({len(errors)} errors)")

    return {
        "title": title,
        "formats": results,
        "errors": errors,
    }


def _save_repurposed(title: str, results: Dict[str, str]):
    """Save all repurposed formats to outputs/repurposed/{slug}/"""
    import re as _re
    from datetime import datetime
    slug = _re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPURPOSE_DIR / f"{ts}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    for fmt_name, content in results.items():
        ext = "md" if fmt_name in ("twitter_thread", "reddit_post", "linkedin_post") else "txt"
        (out_dir / f"{fmt_name}.{ext}").write_text(content, encoding="utf-8")

    logger.info(f"Repurposed content saved: {out_dir}")
    return str(out_dir)


def repurpose_file(md_path: str, **kwargs) -> Dict:
    """Repurpose directly from a markdown file."""
    content = Path(md_path).read_text(encoding="utf-8")
    return repurpose(content=content, **kwargs)


def repurpose_topic(topic: str, niche: str = "general",
                    formats: Optional[List[str]] = None) -> Dict:
    """
    Generate and repurpose from just a topic string — no existing content needed.
    GPT writes the source article first, then repurposes it to all platforms.
    """
    from core.goal_tracker import GoalTracker
    directive = ""
    try:
        directive = GoalTracker.get().get_content_directive(topic=topic)
    except Exception:
        pass

    content = _gpt(
        f"Write a 400-600 word blog article about: {topic}\n"
        f"Niche: {niche}\n"
        f"Brand: {BRAND} | Author: {AUTHOR}\n"
        f"{'Content directive: ' + directive if directive else ''}\n\n"
        "Include: compelling headline (H1), 3 sections with H2s, "
        "actionable tips with numbers, and a closing CTA to "
        f"get the free AI Entrepreneur Blueprint at {CTA_URL}",
        system=_personality_system("linkedin", topic),
        max_tokens=800,
    )
    result = repurpose(content=content, title=topic, formats=formats)

    # Track in GoalTracker
    try:
        GoalTracker.get().increment("blog_posts", 1)
    except Exception:
        pass

    return result
