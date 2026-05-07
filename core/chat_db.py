#!/usr/bin/env python3
"""
core/chat_db.py
─────────────────────────────────────────────────────────────────────────────
SQLite-backed persistent conversation memory for NarAI.
Tables: conversations, messages, files, settings
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("chat_db")

ROOT = Path(__file__).parent.parent
DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "data" / "narai_chat.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


# ─── Connection & Init ───────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def init_db():
    """Create all tables if they don't exist."""
    conn = _get_conn()
    with _lock:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id           TEXT PRIMARY KEY,
                title        TEXT NOT NULL DEFAULT 'New Chat',
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL,
                model        TEXT NOT NULL DEFAULT 'claude-sonnet-4-20250514',
                system_prompt TEXT,
                pinned       INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS messages (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                tokens_used     INTEGER DEFAULT 0,
                has_code        INTEGER DEFAULT 0,
                has_image       INTEGER DEFAULT 0,
                has_file        INTEGER DEFAULT 0,
                search_used     INTEGER DEFAULT 0,
                feedback        INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS files (
                id              TEXT PRIMARY KEY,
                message_id      TEXT REFERENCES messages(id) ON DELETE CASCADE,
                conversation_id TEXT NOT NULL,
                filename        TEXT NOT NULL,
                filepath        TEXT NOT NULL,
                filetype        TEXT NOT NULL,
                size            INTEGER DEFAULT 0,
                created_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
            CREATE INDEX IF NOT EXISTS idx_files_conv    ON files(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_conv_updated  ON conversations(updated_at DESC);

            CREATE TABLE IF NOT EXISTS prompts (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                body       TEXT NOT NULL,
                category   TEXT NOT NULL DEFAULT 'general',
                tags       TEXT NOT NULL DEFAULT '',
                use_count  INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                is_public  INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_prompts_cat ON prompts(category);

            CREATE TABLE IF NOT EXISTS user_facts (
                id             TEXT PRIMARY KEY,
                fact           TEXT NOT NULL,
                category       TEXT NOT NULL DEFAULT 'context',
                source_conv_id TEXT,
                confidence     REAL NOT NULL DEFAULT 0.8,
                created_at     TEXT NOT NULL,
                last_seen      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                body       TEXT NOT NULL DEFAULT '',
                type       TEXT NOT NULL DEFAULT 'info',
                read       INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                action_url TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_notif_read ON notifications(read);

            CREATE TABLE IF NOT EXISTS api_keys (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                key_hash      TEXT NOT NULL UNIQUE,
                plan          TEXT NOT NULL DEFAULT 'free',
                created_at    TEXT NOT NULL,
                last_used     TEXT,
                request_count INTEGER NOT NULL DEFAULT 0,
                rate_limit    INTEGER NOT NULL DEFAULT 100,
                active        INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                user_email         TEXT PRIMARY KEY,
                plan               TEXT NOT NULL DEFAULT 'free',
                stripe_customer_id TEXT,
                stripe_sub_id      TEXT,
                status             TEXT NOT NULL DEFAULT 'inactive',
                period_end         TEXT
            );

            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id             TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                bot_name       TEXT NOT NULL,
                category       TEXT NOT NULL DEFAULT '',
                schedule_type  TEXT NOT NULL DEFAULT 'interval',
                schedule_value TEXT NOT NULL DEFAULT '60',
                enabled        INTEGER NOT NULL DEFAULT 1,
                last_run       TEXT,
                next_run       TEXT,
                run_count      INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS bot_runs (
                id           TEXT PRIMARY KEY,
                bot_name     TEXT NOT NULL,
                category     TEXT NOT NULL DEFAULT '',
                start_time   TEXT NOT NULL,
                end_time     TEXT,
                exit_code    INTEGER,
                duration_sec REAL,
                triggered_by TEXT NOT NULL DEFAULT 'manual'
            );
            CREATE INDEX IF NOT EXISTS idx_bot_runs_name ON bot_runs(bot_name);

            CREATE TABLE IF NOT EXISTS api_events (
                id           TEXT PRIMARY KEY,
                endpoint     TEXT NOT NULL,
                method       TEXT NOT NULL DEFAULT 'GET',
                status_code  INTEGER NOT NULL DEFAULT 200,
                duration_ms  REAL NOT NULL DEFAULT 0,
                ts           TEXT NOT NULL,
                model_used   TEXT NOT NULL DEFAULT '',
                tokens_in    INTEGER NOT NULL DEFAULT 0,
                tokens_out   INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_api_events_ts ON api_events(ts);

            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id          TEXT PRIMARY KEY,
                endpoint    TEXT NOT NULL UNIQUE,
                keys_auth   TEXT NOT NULL,
                keys_p256dh TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_docs (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                content    TEXT NOT NULL,
                source     TEXT NOT NULL DEFAULT '',
                embedding  BLOB,
                created_at TEXT NOT NULL,
                tags       TEXT NOT NULL DEFAULT '',
                chunks     INTEGER NOT NULL DEFAULT 1
            );
        """)
        conn.commit()

        # Insert defaults
        defaults = {
            "default_model": "claude-sonnet-4-20250514",
            "temperature": "0.7",
            "max_tokens": "4096",
            "auto_speak": "false",
            "search_enabled": "false",
            "theme": "dark",
            "font_size": "medium",
            "system_prompt": (
                "You are NarAI, a powerful personal AI assistant built by Jhon (J.K. Blaze). "
                "You have access to WheellsVerse — a 142-bot automation system. "
                "You can write code, run bots, search the web, read files, and remember conversations. "
                "You are direct, precise, and never waste words. "
                "When you write code you always write complete working production code with no placeholders."
            ),
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v)
            )
        conn.commit()

        # Seed starter prompts
        import uuid as _uuid
        starter_prompts = [
            ("Marketing Email", "Write a compelling marketing email for {{product}} targeting {{audience}}. Include a strong subject line, 3 benefit bullets, and a CTA.", "marketing", "email,copywriting"),
            ("SEO Blog Post", "Write a 1200-word SEO-optimized blog post about {{topic}}. Include H2 subheadings, keyword density of 1-2%, and a meta description.", "seo", "blog,content"),
            ("Python Bot Template", "Create a Python bot that {{task}}. Extend the BaseBot class, add error handling, and include logging. Follow WheellsVerse conventions.", "coding", "python,bot"),
            ("Product Description", "Write 3 product description variants for {{product}}. Short (50 words), medium (100 words), long (200 words). Focus on benefits over features.", "ecommerce", "product,amazon"),
            ("Social Media Pack", "Create a social media content pack for {{topic}}: 1 Twitter thread (5 tweets), 1 Instagram caption with hashtags, 1 LinkedIn post.", "social", "twitter,instagram,linkedin"),
            ("Market Analysis", "Analyze the current market opportunity for {{niche}}. Cover: market size, top 3 competitors, key trends, entry strategy, revenue potential.", "analysis", "market,strategy"),
            ("Ad Copy Variants", "Write 5 Facebook/Instagram ad copy variants for {{product}}. Each under 125 characters. Mix emotional, logical, and urgency-based approaches.", "advertising", "ads,facebook"),
            ("Code Review", "Review the following code for: bugs, security issues, performance problems, and style improvements. Be specific with line numbers and fixes:\n\n{{code}}", "coding", "review,debugging"),
            ("Customer Support Reply", "Write a professional, empathetic customer support reply to this complaint: {{complaint}}. Acknowledge, apologize, explain, and offer resolution.", "customer_service", "support,email"),
            ("Business Plan Section", "Write the {{section}} section of a business plan for {{company}} in {{industry}}. Be concrete with numbers, timelines, and milestones.", "business", "strategy,planning"),
        ]
        now = datetime.now(timezone.utc).isoformat()
        for title, body, category, tags in starter_prompts:
            conn.execute(
                "INSERT OR IGNORE INTO prompts(id,title,body,category,tags,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (str(_uuid.uuid4()), title, body, category, tags, now, now)
            )
        conn.commit()


# ─── ID helpers ──────────────────────────────────────────────────────────────

def _uid() -> str:
    import uuid
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.utcnow().isoformat()


# ─── Conversations ────────────────────────────────────────────────────────────

def create_conversation(
    title: str = "New Chat",
    system_prompt: Optional[str] = None,
    model: Optional[str] = None,
) -> str:
    init_db()
    conn = _get_conn()
    cid = _uid()
    now = _now()
    m = model or get_setting("default_model") or "claude-sonnet-4-20250514"
    with _lock:
        conn.execute(
            "INSERT INTO conversations(id,title,created_at,updated_at,model,system_prompt,pinned) "
            "VALUES(?,?,?,?,?,?,0)",
            (cid, title, now, now, m, system_prompt),
        )
        conn.commit()
    return cid


def get_conversation(conversation_id: str) -> Optional[Dict]:
    init_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM conversations WHERE id=?", (conversation_id,)
    ).fetchone()
    if not row:
        return None
    conv = dict(row)
    msgs = conn.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",
        (conversation_id,),
    ).fetchall()
    conv["messages"] = [dict(m) for m in msgs]
    return conv


def list_conversations(
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    pinned_first: bool = True,
) -> List[Dict]:
    init_db()
    conn = _get_conn()
    if search:
        rows = conn.execute(
            "SELECT c.*, COUNT(m.id) as msg_count FROM conversations c "
            "LEFT JOIN messages m ON m.conversation_id=c.id "
            "WHERE c.title LIKE ? OR EXISTS("
            "  SELECT 1 FROM messages WHERE conversation_id=c.id AND content LIKE ?) "
            "GROUP BY c.id ORDER BY c.pinned DESC, c.updated_at DESC LIMIT ? OFFSET ?",
            (f"%{search}%", f"%{search}%", limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT c.*, COUNT(m.id) as msg_count FROM conversations c "
            "LEFT JOIN messages m ON m.conversation_id=c.id "
            "GROUP BY c.id ORDER BY c.pinned DESC, c.updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        # Get first user message preview
        first = conn.execute(
            "SELECT content FROM messages WHERE conversation_id=? AND role='user' "
            "ORDER BY created_at LIMIT 1",
            (d["id"],),
        ).fetchone()
        d["preview"] = (dict(first)["content"][:80] if first else "")
        result.append(d)
    return result


def update_conversation(
    conversation_id: str,
    title: Optional[str] = None,
    system_prompt: Optional[str] = None,
    pinned: Optional[bool] = None,
    model: Optional[str] = None,
):
    init_db()
    conn = _get_conn()
    sets, vals = [], []
    if title is not None:
        sets.append("title=?")
        vals.append(title)
    if system_prompt is not None:
        sets.append("system_prompt=?")
        vals.append(system_prompt)
    if pinned is not None:
        sets.append("pinned=?")
        vals.append(1 if pinned else 0)
    if model is not None:
        sets.append("model=?")
        vals.append(model)
    if not sets:
        return
    sets.append("updated_at=?")
    vals.append(_now())
    vals.append(conversation_id)
    with _lock:
        conn.execute(f"UPDATE conversations SET {','.join(sets)} WHERE id=?", vals)
        conn.commit()


def delete_conversation(conversation_id: str):
    init_db()
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        conn.commit()


def search_conversations(query: str, limit: int = 20) -> List[Dict]:
    return list_conversations(limit=limit, search=query)


def pin_conversation(conversation_id: str, pinned: bool):
    update_conversation(conversation_id, pinned=pinned)


# ─── Messages ─────────────────────────────────────────────────────────────────

def add_message(
    conversation_id: str,
    role: str,
    content: str,
    tokens_used: int = 0,
    has_code: bool = False,
    has_image: bool = False,
    has_file: bool = False,
    search_used: bool = False,
) -> str:
    init_db()
    conn = _get_conn()
    mid = _uid()
    now = _now()
    with _lock:
        conn.execute(
            "INSERT INTO messages(id,conversation_id,role,content,created_at,"
            "tokens_used,has_code,has_image,has_file,search_used) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (mid, conversation_id, role, content, now,
             tokens_used, int(has_code), int(has_image), int(has_file), int(search_used)),
        )
        conn.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id)
        )
        conn.commit()
    return mid


def get_messages(conversation_id: str, limit: int = 200) -> List[Dict]:
    init_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?",
        (conversation_id, limit),
    ).fetchall()
    return list(reversed([dict(r) for r in rows]))


def delete_message(message_id: str):
    init_db()
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM messages WHERE id=?", (message_id,))
        conn.commit()


def set_message_feedback(message_id: str, feedback: int):
    init_db()
    conn = _get_conn()
    with _lock:
        conn.execute("UPDATE messages SET feedback=? WHERE id=?", (feedback, message_id))
        conn.commit()


# ─── Files ────────────────────────────────────────────────────────────────────

def add_file(
    conversation_id: str,
    filename: str,
    filepath: str,
    filetype: str,
    size: int,
    message_id: Optional[str] = None,
) -> str:
    init_db()
    conn = _get_conn()
    fid = _uid()
    with _lock:
        conn.execute(
            "INSERT INTO files(id,message_id,conversation_id,filename,filepath,filetype,size,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (fid, message_id, conversation_id, filename, filepath, filetype, size, _now()),
        )
        conn.commit()
    return fid


def get_conversation_files(conversation_id: str) -> List[Dict]:
    init_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM files WHERE conversation_id=? ORDER BY created_at",
        (conversation_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Settings ─────────────────────────────────────────────────────────────────

def get_settings() -> Dict[str, str]:
    init_db()
    conn = _get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_setting(key: str, default: str = "") -> str:
    init_db()
    conn = _get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def update_setting(key: str, value: str):
    init_db()
    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, value)
        )
        conn.commit()


def update_settings(updates: Dict[str, str]):
    for k, v in updates.items():
        update_setting(k, str(v))


# ─── Auto-title ───────────────────────────────────────────────────────────────

def auto_title(conversation_id: str):
    """Generate a short smart title from the first user message using Claude."""
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT content FROM messages WHERE conversation_id=? AND role='user' "
            "ORDER BY created_at LIMIT 1",
            (conversation_id,),
        ).fetchone()
        if not row:
            return
        first_msg = dict(row)["content"][:300]

        from core.claude_logged import create as _claude_create
        resp = _claude_create(
            model="claude-haiku-4-5-20251001",
            max_tokens=30,
            system="Generate a short 3-6 word title for this conversation. Return ONLY the title, no quotes.",
            messages=[{"role": "user", "content": first_msg}],
            bot_name="chat_db_title",
        )
        title = resp.content[0].text.strip().strip('"').strip("'")[:60]
        if title:
            update_conversation(conversation_id, title=title)
            logger.info(f"[chat_db] Auto-titled '{conversation_id}' → '{title}'")
    except Exception as e:
        logger.debug(f"[chat_db] auto_title failed: {e}")


# ─── Export ───────────────────────────────────────────────────────────────────

def export_conversation(conversation_id: str, fmt: str = "json") -> str:
    conv = get_conversation(conversation_id)
    if not conv:
        return ""
    if fmt == "markdown":
        lines = [f"# {conv['title']}", f"*Created: {conv['created_at']}*", ""]
        for m in conv["messages"]:
            role_label = "**You**" if m["role"] == "user" else "**NarAI**"
            lines.append(f"{role_label}: {m['content']}")
            lines.append("")
        return "\n".join(lines)
    return json.dumps(conv, indent=2, ensure_ascii=False)


# ─── History for Claude API ───────────────────────────────────────────────────

def get_claude_history(conversation_id: str, max_messages: int = 40) -> List[Dict]:
    """Return messages formatted for Anthropic API messages array."""
    msgs = get_messages(conversation_id, limit=max_messages)
    result = []
    for m in msgs:
        role = m["role"]
        if role not in ("user", "assistant"):
            continue
        result.append({"role": role, "content": m["content"]})
    return result


# ─── Stats ────────────────────────────────────────────────────────────────────

def get_db_stats() -> Dict:
    init_db()
    conn = _get_conn()
    total_convs = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    total_msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    total_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    return {
        "conversations": total_convs,
        "messages": total_msgs,
        "files": total_files,
        "db_path": str(DB_PATH),
        "db_size_kb": round(DB_PATH.stat().st_size / 1024, 1) if DB_PATH.exists() else 0,
    }


# Auto-init on import
try:
    init_db()
except Exception as _e:
    logger.warning(f"chat_db init deferred: {_e}")
