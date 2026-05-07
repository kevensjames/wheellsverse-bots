#!/usr/bin/env python3
"""
core/memory_engine.py
─────────────────────────────────────────────────────────────────────────────
Long-term memory: extracts durable user facts from conversations
and injects them into every future chat as context.

Facts are stored in the user_facts table (created by chat_db.init_db).
Uses claude-haiku-4-5-20251001 for extraction (cheap + fast).
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, List

from core.chat_db import _get_conn, _lock

logger = logging.getLogger("memory_engine")

_MODEL = "claude-haiku-4-5-20251001"

_EXTRACT_SYSTEM = (
    "You are a memory extraction assistant. Your job is to identify durable, reusable facts "
    "about the user from a conversation message. Only extract facts that are PERSISTENT — "
    "not temporary emotions, not questions, not task results. "
    "Examples of good facts: 'User builds automation bots', 'User prefers Python', "
    "'User is building WheellsVerse platform'. "
    "Return ONLY a JSON array (no other text): "
    '[{"fact": "...", "category": "preference|identity|goal|context|skill", "confidence": 0.0-1.0}] '
    "or [] if no durable facts found."
)


def extract_facts(conv_id: str, assistant_msg: str) -> List[Dict]:
    """
    Extract durable user facts from an assistant message.
    Runs as a background task — failures are silent.
    Returns list of extracted facts (also saves them to DB).
    """
    if not assistant_msg or len(assistant_msg) < 20:
        return []

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return []

    try:
        from core.claude_logged import create as claude_create
        resp = claude_create(
            model=_MODEL,
            max_tokens=512,
            system=_EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": f"Message: {assistant_msg[:1500]}"}],
            api_key=api_key,
            bot_name="memory_engine",
        )
        raw = resp.content[0].text.strip() if resp.content else "[]"

        # Parse JSON
        try:
            facts_list = json.loads(raw)
            if not isinstance(facts_list, list):
                return []
        except json.JSONDecodeError:
            return []

        # Save to DB
        conn = _get_conn()
        now = datetime.utcnow().isoformat()
        saved = []
        for f in facts_list[:5]:  # Cap at 5 facts per message
            if not isinstance(f, dict) or not f.get("fact"):
                continue
            fact_text = str(f.get("fact", "")).strip()
            category = str(f.get("category", "context"))
            confidence = float(f.get("confidence", 0.8))

            if not fact_text or confidence < 0.5:
                continue

            fact_id = str(uuid.uuid4())
            with _lock:
                conn.execute(
                    "INSERT INTO user_facts(id,fact,category,source_conv_id,confidence,created_at,last_seen) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (fact_id, fact_text, category, conv_id, confidence, now, now)
                )
                conn.commit()
            saved.append({"id": fact_id, "fact": fact_text, "category": category, "confidence": confidence})

        if saved:
            logger.debug(f"[memory] Extracted {len(saved)} facts from conv {conv_id}")
        return saved

    except Exception as e:
        logger.debug(f"[memory] extract_facts failed: {e}")
        return []


def recall_facts(query: str = "", limit: int = 10) -> List[Dict]:
    """
    Recall relevant user facts (keyword search + recency sort).
    """
    conn = _get_conn()
    if query:
        ql = query.lower().split()
        with _lock:
            rows = conn.execute(
                "SELECT id,fact,category,confidence,created_at FROM user_facts ORDER BY last_seen DESC LIMIT 200"
            ).fetchall()
        scored = []
        for row in rows:
            fact_lower = row[1].lower()
            score = sum(1 for w in ql if w in fact_lower)
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        rows = [r for _, r in scored[:limit]]
    else:
        with _lock:
            rows = conn.execute(
                "SELECT id,fact,category,confidence,created_at FROM user_facts ORDER BY last_seen DESC LIMIT ?",
                (limit,)
            ).fetchall()

    return [
        {"id": r[0], "fact": r[1], "category": r[2], "confidence": r[3], "created_at": r[4]}
        for r in rows
    ]


def format_memory_context(limit: int = 10) -> str:
    """
    Return a short context string of user facts for injection into system prompt.
    """
    facts = recall_facts(limit=limit)
    if not facts:
        return ""
    lines = ["[User Memory]\n"]
    for f in facts:
        lines.append(f"- {f['fact']}  ({f['category']})")
    lines.append("")
    return "\n".join(lines)


def forget_fact(fact_id: str) -> bool:
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM user_facts WHERE id=?", (fact_id,))
        conn.commit()
    return True


def list_facts() -> List[Dict]:
    return recall_facts(limit=200)


def clear_all_facts() -> int:
    conn = _get_conn()
    with _lock:
        count = conn.execute("SELECT COUNT(*) FROM user_facts").fetchone()[0]
        conn.execute("DELETE FROM user_facts")
        conn.commit()
    return count
