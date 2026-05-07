"""Content generator — unified brief → prompt → router → formatted output.

Handles: blog posts, newsletters, social posts (twitter/linkedin/threads),
email drips, video scripts, podcast outlines. Each kind has a format template.
Uses NarAI v2 router so it automatically falls back across Claude/GPT/Ollama.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Optional

from infra.brain.interface import BrainClient

_brain = BrainClient(user_id="owner", mode="narai")


# ── Format templates ──────────────────────────────────────────────────────────
# Each defines: target model tier, target length, system-prompt suffix.

FORMATS: dict[str, dict[str, Any]] = {
    "blog": {
        "tier": "deep",
        "target_words": 1200,
        "prompt": (
            "Write a full-length blog post. Include: catchy title (H1), "
            "hook-first intro, 3-5 H2 sections with subheaders, concrete examples, "
            "actionable takeaways, meta description (<=155 chars), and 5 SEO keywords. "
            "Use markdown."
        ),
    },
    "newsletter": {
        "tier": "deep",
        "target_words": 600,
        "prompt": (
            "Write an email newsletter issue. Include: subject line (<=50 chars, "
            "high open rate), preview text, 1 big idea, 2-3 bullet insights, "
            "1 CTA. Tone: conversational, direct, personal. Plain text / markdown."
        ),
    },
    "twitter": {
        "tier": "fast",
        "target_words": 60,
        "prompt": (
            "Write a 5-tweet thread. Rules: first tweet is the HOOK, tweets 2-4 "
            "deliver value with numbers/examples, tweet 5 is the CTA. "
            "Each tweet <=280 chars. Number them 1/5, 2/5, etc."
        ),
    },
    "linkedin": {
        "tier": "fast",
        "target_words": 180,
        "prompt": (
            "Write a LinkedIn post. Hook in line 1, 3-5 short paragraphs with line "
            "breaks, 1 actionable takeaway, 1 engagement question at the end. "
            "No hashtags in the body — list 3 hashtags at the bottom."
        ),
    },
    "email_drip": {
        "tier": "fast",
        "target_words": 220,
        "prompt": (
            "Write a single email in a multi-part drip sequence. Include: "
            "subject line, personal greeting, 1 story or example, 1 takeaway, "
            "1 CTA. Keep under 200 words. Warm, human tone."
        ),
    },
    "video_script": {
        "tier": "deep",
        "target_words": 500,
        "prompt": (
            "Write a short-form video script (30-60 seconds). Include: "
            "HOOK (first 3 seconds), 3 beats, visual cue notes in brackets "
            "(e.g. [cut to product shot]), CTA. Output as timestamped rows."
        ),
    },
    "podcast_outline": {
        "tier": "deep",
        "target_words": 400,
        "prompt": (
            "Write a podcast episode outline. Include: episode title, "
            "tagline, guest intro, 5 timestamped discussion points with "
            "sub-questions each, show notes links placeholder, CTA."
        ),
    },
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ContentBrief:
    """Input to the generator."""
    kind: str                          # one of FORMATS keys
    topic: str
    audience: str = "entrepreneurs"    # who's it for
    tone: str = "direct, confident"    # voice
    goals: list[str] = field(default_factory=list)  # e.g. ["drive signups"]
    keywords: list[str] = field(default_factory=list)
    notes: str = ""                    # extra constraints
    use_memory: bool = True            # inject NarAI memory context
    use_rag: bool = True               # inject RAG context


@dataclass
class ContentResult:
    kind: str
    topic: str
    content: str
    model: str
    tier: str
    tokens: int
    word_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(brief: ContentBrief, fmt: dict[str, Any]) -> str:
    parts: list[str] = [fmt["prompt"]]
    parts.append(f"Topic: {brief.topic}")
    parts.append(f"Audience: {brief.audience}")
    parts.append(f"Tone: {brief.tone}")
    if brief.goals:
        parts.append("Goals:\n- " + "\n- ".join(brief.goals))
    if brief.keywords:
        parts.append("Keywords to weave in naturally: " + ", ".join(brief.keywords))
    if brief.notes:
        parts.append(f"Additional constraints: {brief.notes}")
    parts.append(f"Target length: ~{fmt['target_words']} words.")
    return "\n\n".join(parts)


def _build_system(brief: ContentBrief) -> str:
    mem_ctx = _brain.memory.recall_context(brief.topic) if brief.use_memory else ""
    rag_ctx = _brain.rag.query_context(brief.topic) if brief.use_rag else ""
    base = (
        "You are NarAI, a high-signal content generator for J.K. Blaze (WheellsVerse). "
        "Write like a senior copywriter — concrete, punchy, no filler. "
        "Avoid generic AI disclaimers."
    )
    return _brain.skills.build_system_prompt(
        base=base,
        skill="writer",
        memory_context=mem_ctx,
        rag_context=rag_ctx,
    )


# ── Public API ────────────────────────────────────────────────────────────────

async def generate(brief: ContentBrief) -> ContentResult:
    fmt = FORMATS.get(brief.kind)
    if fmt is None:
        raise ValueError(f"Unknown content kind '{brief.kind}'. "
                         f"Choose: {', '.join(FORMATS.keys())}")

    prompt = _build_prompt(brief, fmt)
    system = _build_system(brief)

    result = await _brain.router.call(prompt, tier=fmt["tier"], system=system)
    text = result.get("content", "")

    # Persist a memory record so future generations can reference past outputs
    if brief.use_memory:
        try:
            await _brain.memory.aremember(
                key=f"content:{brief.kind}:{brief.topic[:40]}",
                content=text[:600],
                tags=["content", brief.kind],
                source="content_generator",
            )
        except Exception:
            pass  # don't fail generation if memory write fails

    return ContentResult(
        kind=brief.kind,
        topic=brief.topic,
        content=text,
        model=result.get("model", ""),
        tier=fmt["tier"],
        tokens=result.get("tokens", 0),
        word_count=len(text.split()),
    )


def list_formats() -> list[dict[str, Any]]:
    return [
        {"kind": k, "tier": v["tier"], "target_words": v["target_words"]}
        for k, v in FORMATS.items()
    ]
