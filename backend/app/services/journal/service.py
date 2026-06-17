"""Journal service — turn raw thoughts into a summarized, mood-tagged entry that
also feeds long-term memory.

Pipeline: detect mood (free lexicon) → summarize (LLM, fail-soft to a truncation)
→ store in the journal → best-effort write the summary to long-term memory so the
entry deepens what KAI knows. Every step is fail-soft so journaling never errors.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.services.journal import storage

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = (
    "You are summarizing the user's personal journal entry. In 1-2 warm, plain "
    "sentences, capture what actually matters — feelings, what happened, any goal "
    "or worry. Write in third person about the user. No preamble."
)


def _summarize(raw_text: str, router, user_id, prefer_local: bool) -> str:
    if router is None or user_id is None:
        return raw_text[:200]
    try:
        res = router.complete(
            user_id=user_id,
            messages=[{"role": "user", "content": raw_text}],
            system=_SUMMARY_SYSTEM,
            max_tokens=160,
            prefer_local=prefer_local,
        )
        text = (getattr(res, "content", "") or "").strip()
        return text or raw_text[:200]
    except Exception as e:  # fail-soft — a down brain must not lose the journal
        logger.warning("journal: summarize failed (%s); storing truncation", e)
        return raw_text[:200]


def create_journal_entry(raw_text: str, *, session=None, user_id: uuid.UUID | None = None,
                         router=None, prefer_local: bool = True,
                         store_to_memory: bool = True) -> dict[str, Any]:
    from app.services.eq.detection import detect_mood

    mood, _conf = detect_mood(raw_text)
    summary = _summarize(raw_text, router, user_id, prefer_local)
    entry = storage.add(raw_text, summary, mood)

    memory_saved = False
    if store_to_memory and session is not None and user_id is not None:
        try:
            from app.services.memory.store import add_memory
            add_memory(
                session, user_id=user_id,
                content=f"Journal ({mood}): {summary}",
                memory_type="note",
                metadata={"source": "journal", "mood": mood, "journal_id": entry.id},
            )
            session.commit()
            memory_saved = True
        except Exception as e:  # best-effort
            logger.warning("journal: memory write skipped (%s)", e)
    return {"entry": entry.as_dict(), "memory_saved": memory_saved}
