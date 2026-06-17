"""Mood → tone-adaptation directives.

Maps a detected mood to a short instruction that tells KAI HOW to adjust its
delivery for this one reply. Kept terse so it nudges tone without derailing the
answer. 'neutral' yields no directive.
"""
from __future__ import annotations

MOOD_DIRECTIVES: dict[str, str] = {
    "stressed": (
        "The user sounds stressed/overwhelmed. Be a calm, grounding presence. "
        "Lead with the single most important next step, keep it short, and don't "
        "pile on options or caveats."
    ),
    "frustrated": (
        "The user sounds frustrated. Acknowledge it in one line, skip the preamble, "
        "and go straight to a concrete fix. Never get defensive."
    ),
    "anxious": (
        "The user sounds anxious. Be reassuring and concrete. Break things into "
        "small, clear steps, reduce uncertainty, and remind them what's already "
        "handled."
    ),
    "sad": (
        "The user sounds down. Lead with warmth and support, not problem-solving. "
        "Be gentle and present; only move to solutions if they ask."
    ),
    "tired": (
        "The user sounds tired/burned out. Be gentle and keep it light. Suggest the "
        "smallest useful action and give them permission to rest."
    ),
    "happy": (
        "The user is in a good mood. Match their warmth and enjoy the moment with "
        "them before getting down to business."
    ),
    "excited": (
        "The user is excited. Match their energy, celebrate the win with them, and "
        "keep the momentum going."
    ),
    "motivated": (
        "The user is motivated and focused. Be crisp and action-oriented — get out "
        "of their way and help them move fast."
    ),
}


def directive_for(mood: str) -> str:
    return MOOD_DIRECTIVES.get(mood, "")
