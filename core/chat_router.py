#!/usr/bin/env python3
"""
core/chat_router.py
─────────────────────────────────────────────────────────────────────────────
FastAPI router for persistent conversation memory.
Prefix: /api/memory
─────────────────────────────────────────────────────────────────────────────
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.chat_db import (
    add_message,
    create_conversation,
    delete_conversation,
    delete_message,
    export_conversation,
    get_conversation,
    get_db_stats,
    get_settings,
    list_conversations,
    search_conversations,
    set_message_feedback,
    update_conversation,
    update_settings,
)

logger = logging.getLogger("chat_router")
router = APIRouter(prefix="/api/memory", tags=["memory"])


# ─── Request models ───────────────────────────────────────────────────────────

class CreateConvRequest(BaseModel):
    title: Optional[str] = "New Chat"
    system_prompt: Optional[str] = None
    model: Optional[str] = None


class UpdateConvRequest(BaseModel):
    title: Optional[str] = None
    system_prompt: Optional[str] = None
    pinned: Optional[bool] = None
    model: Optional[str] = None


class AddMessageRequest(BaseModel):
    role: str
    content: str
    tokens_used: Optional[int] = 0


class FeedbackRequest(BaseModel):
    message_id: str
    feedback: int  # 1=thumbs up, -1=thumbs down, 0=neutral


class SettingsUpdateRequest(BaseModel):
    updates: dict


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/conversations")
def mem_create_conv(req: CreateConvRequest):
    cid = create_conversation(req.title or "New Chat", req.system_prompt, req.model)
    conv = get_conversation(cid)
    return {"ok": True, "conversation": conv}


@router.get("/conversations")
def mem_list_convs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
):
    convs = list_conversations(limit=limit, offset=offset, search=search)
    return {"conversations": convs, "total": len(convs)}


@router.get("/conversations/{conversation_id}")
def mem_get_conv(conversation_id: str):
    conv = get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.patch("/conversations/{conversation_id}")
def mem_update_conv(conversation_id: str, req: UpdateConvRequest):
    conv = get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    update_conversation(
        conversation_id,
        title=req.title,
        system_prompt=req.system_prompt,
        pinned=req.pinned,
        model=req.model,
    )
    return {"ok": True, "conversation": get_conversation(conversation_id)}


@router.delete("/conversations/{conversation_id}")
def mem_delete_conv(conversation_id: str):
    conv = get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    delete_conversation(conversation_id)
    return {"ok": True}


@router.get("/conversations/{conversation_id}/export")
def mem_export_conv(
    conversation_id: str,
    format: str = Query(default="json", pattern="^(json|markdown)$"),
):
    content = export_conversation(conversation_id, format)
    if not content:
        raise HTTPException(status_code=404, detail="Conversation not found")
    media = "application/json" if format == "json" else "text/markdown"
    from fastapi.responses import Response
    return Response(content=content, media_type=media)


@router.post("/conversations/{conversation_id}/messages")
def mem_add_message(conversation_id: str, req: AddMessageRequest):
    conv = get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    has_code = "```" in req.content or "def " in req.content or "import " in req.content
    mid = add_message(
        conversation_id, req.role, req.content,
        tokens_used=req.tokens_used or 0,
        has_code=has_code,
    )
    return {"ok": True, "message_id": mid}


@router.delete("/messages/{message_id}")
def mem_delete_msg(message_id: str):
    delete_message(message_id)
    return {"ok": True}


@router.post("/messages/feedback")
def mem_feedback(req: FeedbackRequest):
    set_message_feedback(req.message_id, req.feedback)
    return {"ok": True}


@router.get("/search")
def mem_search(q: str = Query(..., min_length=1)):
    convs = search_conversations(q, limit=20)
    return {"query": q, "results": convs}


@router.get("/settings")
def mem_get_settings():
    return get_settings()


@router.patch("/settings")
def mem_update_settings(req: SettingsUpdateRequest):
    update_settings(req.updates)
    return {"ok": True, "settings": get_settings()}


@router.get("/stats")
def mem_stats():
    return get_db_stats()
