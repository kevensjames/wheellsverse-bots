"""Emotional intelligence — read the operator's mood, adapt KAI's tone.

detection.py   — fast, free lexicon mood classifier (no LLM call per message).
adaptation.py  — mood → terse tone directive.
injection.py   — analyze(text) → (mood, confidence, preamble) for the system prompt.
storage.py     — mood-sample history (trend dashboard + future check-in/relationship).

Scope KAI_SCOPE_EQ; fail-open (a miss just means a neutral tone, never a failure).
"""
from app.services.eq import adaptation, detection, injection, storage

__all__ = ["adaptation", "detection", "injection", "storage"]
