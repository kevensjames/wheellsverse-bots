"""Background memory extractor — KAI v1 build #3 (continual learning).

Mines DURABLE facts/preferences from a conversation and stores them in the
user's long-term memory automatically, deduping against what's already there.
This SIMULATES continual learning: KAI accumulates knowledge about the user over
time without the model having to explicitly call the memory tool each turn.

Honest ceiling: this grows a retrieval store — it is NOT online weight learning.
The model's weights stay frozen; KAI simply remembers more (and forgets dupes).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid

from app.services.memory.retrieval import search_memories
from app.services.memory.store import add_memory

logger = logging.getLogger(__name__)

_VALID_TYPES = {"fact", "event", "preference", "note"}


def _dedupe_threshold() -> float:
    try:
        return float(os.environ.get("KAI_MEMORY_DEDUPE_SIMILARITY", "0.90"))
    except ValueError:
        return 0.90


_EXTRACT_SYSTEM = """You extract DURABLE facts worth remembering about a user from a conversation.
Return ONLY a JSON array: [{"content": "...", "type": "fact|preference|event"}].
Rules:
- Include ONLY lasting facts, stable preferences, or important events — useful weeks later.
- EXCLUDE passing chitchat, one-off task details, questions, and anything ephemeral.
- Each content is a short third-person statement ("Lives in Taunton, MA", "Prefers concise replies").
- If nothing is worth remembering, return []."""


def _parse_facts(text: str) -> list[dict]:
    """Parse the model's JSON array, tolerating code fences / surrounding prose."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("\n") + 1:] if "\n" in s else s
    start, end = s.find("["), s.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        arr = json.loads(s[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [x for x in arr if isinstance(x, dict) and x.get("content")]


def _extract_facts(conversation_text: str, *, user_id: uuid.UUID, router, prefer_local: bool) -> list[dict]:
    try:
        result = router.complete(
            user_id=user_id,
            messages=[{"role": "user", "content": conversation_text[:8000]}],
            system=_EXTRACT_SYSTEM,
            max_tokens=400,
            prefer_local=prefer_local,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("memory extractor: LLM extract failed: %s", e)
        return []
    return _parse_facts(getattr(result, "content", "") or "")


def extract_and_store(*, user_id: uuid.UUID, messages: list[dict], router, prefer_local: bool = True, session=None) -> dict:
    """Extract durable facts from `messages` and store the NEW ones (skip near-
    duplicates by cosine similarity). Creates its own DB session if none is
    passed, so it can run in a background thread without sharing the request
    session. Fully fail-soft. Returns a summary dict."""
    from app.database import SessionLocal

    own = session is None
    s = session or SessionLocal()
    convo = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages if m.get("content")
    )
    stored = skipped = 0
    try:
        facts = _extract_facts(convo, user_id=user_id, router=router, prefer_local=prefer_local)
        threshold = _dedupe_threshold()
        for f in facts:
            content = (f.get("content") or "").strip()
            if not content:
                continue
            mtype = f.get("type") if f.get("type") in _VALID_TYPES else "fact"
            try:
                hits = search_memories(s, user_id=user_id, query=content, k=1, bump_last_used=False)
            except Exception:  # noqa: BLE001
                hits = []
            if hits and hits[0].similarity >= threshold:
                skipped += 1
                continue
            try:
                add_memory(s, user_id=user_id, content=content, memory_type=mtype,
                           metadata={"source": "auto_extract"})
                stored += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("memory extractor: store failed: %s", e)
        if own:
            s.commit()
        return {"extracted": len(facts), "stored": stored, "skipped_dupe": skipped}
    except Exception as e:  # noqa: BLE001
        logger.warning("memory extractor failed: %s", e)
        if own:
            s.rollback()
        return {"extracted": 0, "stored": stored, "skipped_dupe": skipped, "error": str(e)}
    finally:
        if own:
            s.close()


def spawn_extraction(*, user_id: uuid.UUID, user_message: str, assistant_reply: str, router, prefer_local: bool = True) -> None:
    """Fire-and-forget background extraction for one chat turn — never blocks the
    reply, never raises into the request. Opt-in (see brain.py)."""
    messages = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_reply},
    ]

    def _run() -> None:
        try:
            extract_and_store(user_id=user_id, messages=messages, router=router, prefer_local=prefer_local)
        except Exception as e:  # noqa: BLE001  (defensive — the thread must never crash the process)
            logger.warning("memory extraction thread failed: %s", e)

    threading.Thread(target=_run, name="kai-memory-extract", daemon=True).start()
