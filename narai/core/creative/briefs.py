"""Creative briefs — translate a concept into prompts/scripts usable by
downstream tools (Suno, Runway, MidJourney, Stability). No external calls here.
"""
from __future__ import annotations

from typing import Any

from narai.core import router, skills


async def music_brief(concept: str, vibe: str = "cinematic, melodic",
                      duration_sec: int = 60) -> dict[str, Any]:
    """Generate a music brief + Suno-style prompt."""
    prompt = (
        f"Design a {duration_sec}-second music piece. Concept: {concept}. "
        f"Vibe: {vibe}. Output:\n"
        "1. Genre + subgenre (1 line)\n"
        "2. BPM range and key\n"
        "3. Instruments (comma-separated list)\n"
        "4. 3-section structure with bar counts (e.g. Intro 8 bars · Verse 16 bars · Outro 8 bars)\n"
        "5. Mood tags (5 adjectives)\n"
        "6. A single-line Suno-style prompt ready to paste into a generator"
    )
    system = skills.build_system_prompt(
        base="You are NarAI as a music director. Concrete, specific, usable in a generator."
    )
    result = await router.call(prompt, tier="fast", system=system)
    return {"concept": concept, "brief": result.get("content", ""), "model": result.get("model", "")}


async def video_brief(concept: str, platform: str = "tiktok",
                      duration_sec: int = 30) -> dict[str, Any]:
    """Generate a short-form video brief with shot list + hook."""
    prompt = (
        f"Design a {duration_sec}-second video for {platform}. Concept: {concept}. "
        "Output:\n"
        "1. HOOK (first 3 seconds, specific)\n"
        "2. Shot list: 5-8 rows, each [timestamp] [action/visual] [audio]\n"
        "3. On-screen text (3-5 captions)\n"
        "4. CTA (1 line)\n"
        "5. Thumbnail prompt for an AI image gen"
    )
    system = skills.build_system_prompt(
        base="You are NarAI as a short-form video director. Tight pacing, hook-first."
    )
    result = await router.call(prompt, tier="fast", system=system)
    return {"concept": concept, "brief": result.get("content", ""), "platform": platform,
            "model": result.get("model", "")}


async def image_prompts(concept: str, n: int = 4, style: str = "cinematic") -> dict[str, Any]:
    """Generate n variant image prompts for a concept."""
    prompt = (
        f"Generate {n} variant image generation prompts for: {concept}. Style: {style}. "
        "Each prompt should be: (a) 20-40 words, (b) include composition/lighting/mood, "
        "(c) be different from the others. Number them 1..N."
    )
    result = await router.call(prompt, tier="fast")
    return {"concept": concept, "prompts": result.get("content", ""), "n": n, "style": style,
            "model": result.get("model", "")}
