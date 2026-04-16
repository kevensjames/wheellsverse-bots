#!/usr/bin/env python3
"""
core/db.py
─────────────────────────────────────────────────────────────────────────────
Centralized SQLite data layer for WheellsVerse.

Uses sqlite-utils for schema-free table creation — tables are automatically
created on first insert. All structured data (affiliates, keywords, AEO
scores, content calendar, etc.) is stored here.

Usage:
    from core.db import get_db
    db = get_db()
    db["affiliates"].insert({"name": "...", "email": "..."})
    rows = list(db["affiliates"].rows_where("status = ?", ["lead"]))
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import threading
from pathlib import Path

import sqlite_utils

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "wheellsverse.db"

logger = logging.getLogger("db")

_db = None
_lock = threading.Lock()


def get_db() -> sqlite_utils.Database:
    """Return the singleton Database instance (thread-safe)."""
    global _db
    if _db is None:
        with _lock:
            if _db is None:
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                _db = sqlite_utils.Database(str(DB_PATH))
                # Enable WAL mode for better concurrent access
                _db.execute("PRAGMA journal_mode=WAL")
                logger.info(f"SQLite database opened: {DB_PATH}")
    return _db


def ensure_tables() -> None:
    """
    Pre-create core tables with explicit schemas.
    Called lazily on first use — sqlite-utils also auto-creates on insert,
    but this ensures indexes and column types are correct.
    """
    db = get_db()

    if "affiliates" not in db.table_names():
        db["affiliates"].create({
            "id": int,
            "name": str,
            "email": str,
            "platform": str,
            "url": str,
            "niche": str,
            "estimated_reach": int,
            "status": str,          # lead | contacted | negotiating | active | declined
            "competitor": str,
            "email_valid": bool,
            "email_confidence": float,
            "first_contact": str,
            "last_contact": str,
            "notes": str,
            "created_at": str,
        }, pk="id")
        db["affiliates"].create_index(["status"])
        db["affiliates"].create_index(["competitor"])

    if "keywords" not in db.table_names():
        db["keywords"].create({
            "id": int,
            "keyword": str,
            "volume": int,
            "difficulty": float,
            "position": int,
            "category": str,
            "tracked_since": str,
            "last_checked": str,
        }, pk="id")
        db["keywords"].create_index(["keyword"], unique=True, if_not_exists=True)

    if "keyword_history" not in db.table_names():
        db["keyword_history"].create({
            "id": int,
            "keyword_id": int,
            "position": int,
            "date": str,
            "search_engine": str,
        }, pk="id", foreign_keys=[("keyword_id", "keywords")])

    if "articles" not in db.table_names():
        db["articles"].create({
            "id": int,
            "keyword_id": int,
            "title": str,
            "slug": str,
            "status": str,         # draft | published | scheduled
            "word_count": int,
            "file_path": str,
            "url": str,
            "published_at": str,
            "created_at": str,
        }, pk="id")

    if "backlinks" not in db.table_names():
        db["backlinks"].create({
            "id": int,
            "source_url": str,
            "target_url": str,
            "anchor_text": str,
            "domain": str,
            "discovered_at": str,
            "status": str,
        }, pk="id")

    if "aeo_scores" not in db.table_names():
        db["aeo_scores"].create({
            "id": int,
            "domain": str,
            "url": str,
            "score": int,
            "faq_score": int,
            "schema_score": int,
            "qa_score": int,
            "format_score": int,
            "meta_score": int,
            "heading_score": int,
            "length_score": int,
            "scanned_at": str,
        }, pk="id")
        db["aeo_scores"].create_index(["domain"])

    if "content_calendar" not in db.table_names():
        db["content_calendar"].create({
            "id": int,
            "keyword": str,
            "title": str,
            "scheduled_date": str,
            "status": str,          # planned | writing | review | published | overdue
            "assigned_bot": str,
            "created_at": str,
        }, pk="id")

    if "prompt_results" not in db.table_names():
        db["prompt_results"].create({
            "id": int,
            "brand": str,
            "prompt_text": str,
            "engine": str,          # openai | anthropic
            "ai_response": str,
            "brand_mentioned": bool,
            "mention_type": str,    # mentioned | partial | not_mentioned
            "topic_category": str,
            "tested_at": str,
        }, pk="id")
        db["prompt_results"].create_index(["brand"])

    if "call_log" not in db.table_names():
        db["call_log"].create({
            "id": int,
            "channel": str,         # voice | sms | chat | email
            "direction": str,       # inbound | outbound
            "from_id": str,
            "summary": str,
            "transcript": str,
            "ai_reply": str,
            "duration_seconds": int,
            "created_at": str,
        }, pk="id")

    logger.info("Database tables verified")
