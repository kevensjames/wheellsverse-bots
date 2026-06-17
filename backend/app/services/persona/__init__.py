"""KAI persona — KAI's OWN personality (warm companion character).

storage.py    — SQLite ledger of persona traits (sections; seeded warm default).
composer.py   — group active traits into a prompt block.
injection.py  — persona_preamble() → the 'who you are' block at the top of the
                system prompt (scope KAI_SCOPE_PERSONA, fail-open).

Distinct from twin (the OPERATOR's self-model) and learning (behavioral fixes).
"""
from app.services.persona import composer, injection, storage

__all__ = ["composer", "injection", "storage"]
