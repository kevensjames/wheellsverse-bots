"""Voice/text journal — record thoughts → summarize + mood → store + remember.

storage.py  — journal entries (raw/summary/mood).
service.py  — create_journal_entry(): mood + LLM summary (fail-soft) + memory write.

Scope KAI_SCOPE_JOURNAL (audited at the router).
"""
from app.services.journal import service, storage

__all__ = ["service", "storage"]
