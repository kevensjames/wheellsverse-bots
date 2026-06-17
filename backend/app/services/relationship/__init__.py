"""Relationship engine — the KAI↔operator bond (continuity + shared milestones).

storage.py    — state (interactions/trust/first-met) + milestones; familiarity
                derived from interaction count.
injection.py  — relationship_preamble() → shared-history block in the system
                prompt (scope KAI_SCOPE_RELATIONSHIP, fail-open).
"""
from app.services.relationship import injection, storage

__all__ = ["injection", "storage"]
