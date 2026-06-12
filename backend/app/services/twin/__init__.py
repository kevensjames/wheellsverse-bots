"""KAI digital twin (v1: operator self-model + inject + draft-in-voice).

A stable, always-on, structured model of the OPERATOR (KAI's principal) —
distinct from episodic memory (per-message retrieval) and learning lessons
(behavioral fixes). Composed from operator-authored entries + KAI suggestions
(from KG facts), injected into the system prompt so KAI always knows who it
serves, and usable to DRAFT content in the operator's voice (drafts only,
never sent). Gated by KAI_SCOPE_TWIN.

  storage   — profile entries + draft history (SQLite sidecar)
  composer  — compose_profile (pure) + suggest_entries (KG facts → proposed)
  draft     — draft_as_operator (generate in the operator's voice)
  injection — active profile → system-prompt preamble (always-on, scope-gated)
"""
from app.services.twin.storage import (  # noqa: F401
    ENTRY_STATUSES,
    SECTIONS,
    TWIN_DB_PATH,
    Draft,
    Entry,
    add_draft,
    add_entry,
    get_entry,
    list_drafts,
    list_entries,
    set_entry_status,
    stats,
)
from app.services.twin.composer import compose_profile, suggest_entries  # noqa: F401
from app.services.twin.draft import draft_as_operator  # noqa: F401
from app.services.twin.injection import twin_preamble  # noqa: F401

__all__ = [
    "ENTRY_STATUSES",
    "SECTIONS",
    "TWIN_DB_PATH",
    "Draft",
    "Entry",
    "add_draft",
    "add_entry",
    "compose_profile",
    "draft_as_operator",
    "get_entry",
    "list_drafts",
    "list_entries",
    "set_entry_status",
    "stats",
    "suggest_entries",
    "twin_preamble",
]
