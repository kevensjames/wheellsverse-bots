"""Mood detection — fast, free, dependency-free lexicon classifier.

Runs on every operator message with ZERO extra LLM cost/latency (a model call
per turn would double cost and slow replies). It scores the message against
weighted signal lexicons and returns the dominant mood + a confidence. Good
enough to steer TONE; it never gates capability, so a miss just means a neutral
tone. (A future opt-in LLM classifier could refine this.)

Moods: stressed, frustrated, anxious, sad, tired, happy, excited, motivated,
neutral.
"""
from __future__ import annotations

import re

# Signal phrases per mood. Multi-word phrases are matched as substrings; single
# tokens match on word boundaries. Tuned for how an operator actually types.
_LEXICON: dict[str, tuple[str, ...]] = {
    "stressed": (
        "stressed", "overwhelmed", "too much", "so much to do", "no time",
        "swamped", "drowning", "under pressure", "can't keep up", "buried",
        "spread thin", "deadline",
    ),
    "frustrated": (
        "frustrated", "annoying", "annoyed", "ugh", "wtf", "why won't", "still broken",
        "not working", "doesn't work", "again?!", "stupid", "hate this", "fed up",
        "come on", "seriously", "broken again",
    ),
    "anxious": (
        "anxious", "worried", "nervous", "scared", "afraid", "what if", "unsure",
        "uncertain", "stressing about", "freaking out", "panic", "on edge",
    ),
    "sad": (
        "sad", "depressed", "down", "unhappy", "lonely", "hopeless", "miserable",
        "crying", "heartbroken", "lost", "empty", "give up", "giving up",
    ),
    "tired": (
        "tired", "exhausted", "burned out", "burnt out", "burnout", "drained",
        "no energy", "worn out", "sleepy", "can't focus", "need a break", "fatigued",
    ),
    "happy": (
        "happy", "glad", "grateful", "love it", "feeling good", "great day",
        "content", "relieved", "thankful", "good mood", "yay",
    ),
    "excited": (
        "excited", "amazing", "awesome", "incredible", "can't wait", "let's go",
        "pumped", "stoked", "thrilled", "🔥", "🚀", "wow", "this is huge",
    ),
    "motivated": (
        "motivated", "focused", "let's do this", "ready to", "locked in", "grind",
        "ship it", "let's build", "on it", "determined", "crush it", "dialed in",
    ),
}

# Negative moods slightly outweigh positive on ties — a struggling user needs the
# tone shift more than an upbeat one.
_WEIGHT = {"stressed": 1.2, "frustrated": 1.2, "anxious": 1.2, "sad": 1.3,
           "tired": 1.1, "happy": 1.0, "excited": 1.0, "motivated": 1.0}


def detect_mood(text: str) -> tuple[str, float]:
    """Return (mood, confidence in 0..1). 'neutral' with 0.0 when no signal."""
    if not text or not text.strip():
        return "neutral", 0.0
    low = text.lower()
    scores: dict[str, float] = {}
    for mood, phrases in _LEXICON.items():
        hits = 0
        for p in phrases:
            if " " in p or not p.isalpha():
                if p in low:
                    hits += 1
            elif re.search(rf"\b{re.escape(p)}\b", low):
                hits += 1
        if hits:
            scores[mood] = hits * _WEIGHT.get(mood, 1.0)
    if not scores:
        return "neutral", 0.0
    # Intensity bump: shouting / emphatic punctuation strengthens the read.
    intensity = 1.0
    if "!!" in text or "?!" in text:
        intensity += 0.25
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) >= 8 and sum(ch.isupper() for ch in letters) / len(letters) > 0.6:
        intensity += 0.25
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    raw = scores[best] * intensity
    confidence = max(0.0, min(raw / 3.0, 1.0))  # ~3 weighted hits → full confidence
    return best, round(confidence, 2)
