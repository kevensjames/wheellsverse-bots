#!/usr/bin/env python3
"""
core/prompt_router.py
─────────────────────────────────────────────────────────────────────────────
Prompt Library CRUD.

GET    /api/prompts           — list (filter ?category=&search=&sort=)
POST   /api/prompts           — create
GET    /api/prompts/{id}      — get single
PATCH  /api/prompts/{id}      — update
DELETE /api/prompts/{id}      — delete
POST   /api/prompts/{id}/use  — increment use_count, return body
─────────────────────────────────────────────────────────────────────────────
"""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.chat_db import _get_conn, _lock

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class PromptCreate(BaseModel):
    title: str
    body: str
    category: str = "general"
    tags: str = ""
    is_public: bool = False


class PromptUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None
    is_public: Optional[bool] = None


def _row_to_dict(row) -> dict:
    keys = ["id", "title", "body", "category", "tags", "use_count", "created_at", "updated_at", "is_public"]
    return dict(zip(keys, row))


@router.get("")
def list_prompts(
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "use_count",
    limit: int = 100,
    offset: int = 0,
):
    conn = _get_conn()
    query = "SELECT id,title,body,category,tags,use_count,created_at,updated_at,is_public FROM prompts WHERE 1=1"
    params: list = []
    if category:
        query += " AND category=?"
        params.append(category)
    if search:
        query += " AND (title LIKE ? OR body LIKE ? OR tags LIKE ?)"
        s = f"%{search}%"
        params += [s, s, s]
    sort_col = "use_count" if sort == "use_count" else "updated_at"
    query += f" ORDER BY {sort_col} DESC LIMIT ? OFFSET ?"
    params += [limit, offset]

    with _lock:
        rows = conn.execute(query, params).fetchall()
    prompts = [_row_to_dict(r) for r in rows]

    # Get categories list
    with _lock:
        cats = [r[0] for r in conn.execute("SELECT DISTINCT category FROM prompts ORDER BY category").fetchall()]

    return {"prompts": prompts, "categories": cats, "total": len(prompts)}


@router.post("")
def create_prompt(p: PromptCreate):
    if not p.title.strip() or not p.body.strip():
        raise HTTPException(status_code=400, detail="title and body are required")
    pid = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    conn = _get_conn()
    with _lock:
        conn.execute(
            "INSERT INTO prompts(id,title,body,category,tags,created_at,updated_at,is_public) VALUES(?,?,?,?,?,?,?,?)",
            (pid, p.title.strip(), p.body.strip(), p.category, p.tags, now, now, int(p.is_public))
        )
        conn.commit()
    return {"id": pid, "created": True}


@router.get("/{pid}")
def get_prompt(pid: str):
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT id,title,body,category,tags,use_count,created_at,updated_at,is_public FROM prompts WHERE id=?",
            (pid,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return _row_to_dict(row)


@router.patch("/{pid}")
def update_prompt(pid: str, p: PromptUpdate):
    conn = _get_conn()
    with _lock:
        existing = conn.execute("SELECT id FROM prompts WHERE id=?", (pid,)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Prompt not found")

    fields = []
    vals = []
    if p.title is not None:
        fields.append("title=?")
        vals.append(p.title.strip())
    if p.body is not None:
        fields.append("body=?")
        vals.append(p.body.strip())
    if p.category is not None:
        fields.append("category=?")
        vals.append(p.category)
    if p.tags is not None:
        fields.append("tags=?")
        vals.append(p.tags)
    if p.is_public is not None:
        fields.append("is_public=?")
        vals.append(int(p.is_public))

    if not fields:
        return {"updated": False}

    fields.append("updated_at=?")
    vals.append(datetime.utcnow().isoformat())
    vals.append(pid)

    with _lock:
        conn.execute(f"UPDATE prompts SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    return {"updated": True}


@router.delete("/{pid}")
def delete_prompt(pid: str):
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM prompts WHERE id=?", (pid,))
        conn.commit()
    return {"deleted": True}


@router.post("/{pid}/use")
def use_prompt(pid: str):
    conn = _get_conn()
    with _lock:
        conn.execute("UPDATE prompts SET use_count=use_count+1 WHERE id=?", (pid,))
        conn.commit()
        row = conn.execute(
            "SELECT id,title,body,category,tags,use_count,created_at,updated_at,is_public FROM prompts WHERE id=?",
            (pid,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return _row_to_dict(row)
