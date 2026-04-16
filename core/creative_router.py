#!/usr/bin/env python3
"""
core/creative_router.py
─────────────────────────────────────────────────────────────────────────────
Creative Tools for J.K. Blaze content creation.

POST /api/creative/lyrics          — song lyrics
POST /api/creative/novel-chapter   — novel chapter
POST /api/creative/social-pack     — social media content pack
POST /api/creative/content-calendar — weekly content calendar
POST /api/creative/ad-copy         — A/B ad copy variants
─────────────────────────────────────────────────────────────────────────────
"""

import os
from typing import List
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/creative", tags=["creative"])


def _claude(system: str, prompt: str, max_tokens: int = 2048) -> str:
    """Call Claude for a creative generation task."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text if resp.content else ""


class LyricsRequest(BaseModel):
    theme: str
    genre: str = "pop"
    mood: str = "uplifting"
    length: str = "standard"   # short | standard | long


class NovelChapterRequest(BaseModel):
    genre: str = "thriller"
    character_names: str = ""
    plot_summary: str
    chapter_num: int = 1
    style: str = "modern"
    word_count: int = 800


class SocialPackRequest(BaseModel):
    topic: str
    platforms: List[str] = ["twitter", "instagram", "linkedin"]
    tone: str = "professional"
    include_hashtags: bool = True


class ContentCalendarRequest(BaseModel):
    niche: str
    weeks: int = 4
    platforms: List[str] = ["twitter", "instagram"]
    posts_per_week: int = 5


class AdCopyRequest(BaseModel):
    product: str
    audience: str
    platform: str = "facebook"
    goal: str = "conversions"
    variants: int = 5


@router.post("/lyrics")
def creative_lyrics(req: LyricsRequest):
    system = (
        "You are J.K. Blaze, a multi-genre songwriter and poet. "
        "You write emotionally powerful, commercially viable lyrics with strong hooks. "
        "Structure songs with clear verse/pre-chorus/chorus/bridge sections."
    )
    length_map = {"short": "2 verses + chorus", "standard": "3 verses + chorus + bridge", "long": "4 verses + chorus + bridge + outro"}
    length_desc = length_map.get(req.length, "3 verses + chorus + bridge")
    prompt = (
        f"Write a {req.genre} song about '{req.theme}' with a {req.mood} mood.\n"
        f"Structure: {length_desc}\n"
        f"Include [Verse 1], [Pre-Chorus] (optional), [Chorus], [Verse 2], [Bridge], etc. labels.\n"
        f"Make it catchy with a strong, memorable hook."
    )
    lyrics = _claude(system, prompt, max_tokens=1500)
    return {"lyrics": lyrics, "theme": req.theme, "genre": req.genre}


@router.post("/novel-chapter")
def creative_novel_chapter(req: NovelChapterRequest):
    system = (
        "You are J.K. Blaze, a bestselling author. "
        "You write compelling, cinematic prose with vivid characters and page-turning tension. "
        "Show don't tell. Use strong dialogue. Vary sentence length."
    )
    prompt = (
        f"Write Chapter {req.chapter_num} of a {req.genre} novel.\n"
        f"Plot context: {req.plot_summary}\n"
        f"Characters: {req.character_names or 'create appropriate characters'}\n"
        f"Style: {req.style}\n"
        f"Target length: ~{req.word_count} words\n\n"
        f"Begin the chapter directly without a title header."
    )
    chapter = _claude(system, prompt, max_tokens=3000)
    return {"chapter": chapter, "chapter_num": req.chapter_num, "genre": req.genre}


@router.post("/social-pack")
def creative_social_pack(req: SocialPackRequest):
    system = (
        "You are a social media expert for WheellsVerse. "
        "You create platform-optimized content that drives engagement. "
        "You know the character limits, optimal formats, and best practices for each platform."
    )
    platform_list = ", ".join(req.platforms)
    hashtag_instruction = "Include relevant hashtags." if req.include_hashtags else "No hashtags."
    prompt = (
        f"Create a social media content pack about: '{req.topic}'\n"
        f"Tone: {req.tone}\n"
        f"Create content for: {platform_list}\n"
        f"{hashtag_instruction}\n\n"
        f"For each platform, provide:\n"
        f"- Twitter/X: 1 main tweet + 4 thread tweets (if applicable)\n"
        f"- Instagram: Caption + CTA\n"
        f"- LinkedIn: Full professional post\n"
        f"- Other platforms: appropriate format\n\n"
        f"Format with clear **Platform: Name** headers."
    )
    content = _claude(system, prompt, max_tokens=2000)
    return {"content": content, "topic": req.topic, "platforms": req.platforms}


@router.post("/content-calendar")
def creative_content_calendar(req: ContentCalendarRequest):
    system = (
        "You are a content strategist for WheellsVerse. "
        "You create strategic content calendars that build audience, drive traffic, and generate revenue."
    )
    platform_list = ", ".join(req.platforms)
    prompt = (
        f"Create a {req.weeks}-week content calendar for niche: '{req.niche}'\n"
        f"Platforms: {platform_list}\n"
        f"Posts per week: {req.posts_per_week}\n\n"
        f"Return as a structured JSON array with this format:\n"
        f'[{{"week": 1, "day": "Monday", "platform": "Twitter", "topic": "...", "type": "educational|promotional|engagement", "hook": "..."}}]\n\n'
        f"Make topics varied, strategic, and relevant to the niche."
    )
    calendar_text = _claude(system, prompt, max_tokens=3000)
    # Try to parse as JSON, fall back to text
    import json
    try:
        # Extract JSON from the response
        import re
        json_match = re.search(r'\[.*\]', calendar_text, re.DOTALL)
        calendar_data = json.loads(json_match.group()) if json_match else None
    except Exception:
        calendar_data = None
    return {"calendar": calendar_data or calendar_text, "niche": req.niche, "weeks": req.weeks}


@router.post("/ad-copy")
def creative_ad_copy(req: AdCopyRequest):
    system = (
        "You are a direct response copywriter for WheellsVerse. "
        "You write high-converting ad copy using proven frameworks (AIDA, PAS, benefit-led). "
        "You A/B test angles: emotional, logical, urgency, social proof, fear of missing out."
    )
    prompt = (
        f"Write {req.variants} {req.platform} ad copy variants for:\n"
        f"Product: {req.product}\n"
        f"Target Audience: {req.audience}\n"
        f"Goal: {req.goal}\n\n"
        f"For each variant:\n"
        f"- Primary text (under 125 chars for social)\n"
        f"- Headline (under 40 chars)\n"
        f"- CTA button text\n"
        f"- Angle/approach used (e.g., 'emotional', 'urgency', 'social proof')\n\n"
        f"Number each variant clearly."
    )
    copies = _claude(system, prompt, max_tokens=2000)
    return {"ad_copies": copies, "product": req.product, "platform": req.platform}
