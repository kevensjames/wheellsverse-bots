"""
Rewrites text replies for voice output.
Mode-aware: companion = even shorter, operator = structured but stripped of markdown.
"""
from __future__ import annotations

import re
from typing import Literal

VoiceMode = Literal["operator", "companion"]


# Hard limits per mode (in sentences)
MAX_SENTENCES = {
    "operator": 6,
    "companion": 3,
}

# Max characters before we force truncation
MAX_CHARS = {
    "operator": 600,
    "companion": 280,
}


def strip_markdown(text: str) -> str:
    """Remove markdown artifacts that sound wrong when spoken."""
    # Code blocks → "Code block available in chat."
    text = re.sub(r"```[\s\S]*?```", "[code block shown in chat]", text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Bold / italic
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    # Headers
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    # Bullets → natural speech
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    # Numbered lists stay readable but lose the period after number
    text = re.sub(r"^\s*(\d+)\.\s+", r"\1. ", text, flags=re.MULTILINE)
    # Links [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Collapse whitespace
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    # Simple splitter — good enough for voice
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [p.strip() for p in parts if p.strip()]


def truncate_for_voice(text: str, mode: VoiceMode) -> str:
    sentences = split_sentences(text)
    max_s = MAX_SENTENCES[mode]
    if len(sentences) > max_s:
        sentences = sentences[:max_s]
    out = " ".join(sentences)
    if len(out) > MAX_CHARS[mode]:
        out = out[: MAX_CHARS[mode]].rsplit(" ", 1)[0] + "..."
    return out


def to_ssml(text: str, mode: VoiceMode) -> str:
    """Wrap text in SSML with mode-appropriate pacing."""
    # Companion = softer, slightly slower. Operator = normal.
    rate = "95%" if mode == "companion" else "100%"
    pitch = "-2%" if mode == "companion" else "0%"

    # Add small pauses after clauses for natural breathing
    paced = re.sub(r"([,;])\s+", r'\1<break time="150ms"/> ', text)
    paced = re.sub(r"([.!?])\s+", r'\1<break time="300ms"/> ', paced)

    return (
        f'<speak><prosody rate="{rate}" pitch="{pitch}">'
        f'{paced}'
        f'</prosody></speak>'
    )


def format_for_voice(
    text: str,
    mode: VoiceMode = "operator",
    use_ssml: bool = True,
) -> tuple[str, str]:
    """
    Return (spoken_text, text_for_chat_display).
    Chat gets the full original. Voice gets the stripped + truncated version.
    """
    stripped = strip_markdown(text)
    truncated = truncate_for_voice(stripped, mode)
    spoken = to_ssml(truncated, mode) if use_ssml else truncated
    return spoken, text  # chat shows original
