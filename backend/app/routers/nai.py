"""Chat API endpoints. Mounted under both /kai (canonical) and /nai (legacy
during the brand-transition window). The router itself defines no prefix —
main.py wires it in twice with different prefixes.

Two chat modes:
- POST /kai/chat — full tool loop available, JSON in/out  (legacy: /nai/chat)
- GET  /kai/chat/stream — SSE token streaming, no tools (EventSource limit)
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.stream_auth import get_user_for_stream
from app.models.conversation import Conversation, Message
from app.dependencies.supabase_jwt import UserPrincipal as User  # Path X alias
from app.schemas.nai import (
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationOut,
    MessageOut,
)
from app.services.nai_brain import Brain
from app.services.router import build_default_router
from app.services.router.router import SpendCapExceeded
from app.services.tools import build_default_registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def _build_brain(session: Session) -> Brain:
    return Brain(
        session=session,
        router=build_default_router(session),
        registry=build_default_registry(),
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ChatResponse:
    rt = build_default_router(session)
    registry = build_default_registry()
    persona_prompt = ""
    preset_id_used: str | None = None
    auto_routed = False
    # Opt-in super-router: pick + apply the best domain expert for this message.
    if request.auto_route:
        from app.services.agent_router import classify_domain
        routed = classify_domain(router=rt, user_id=current_user.id, question=request.message)
        if routed.get("preset_id"):
            from app.services.presets import filter_registry, get_preset
            preset = get_preset(routed["preset_id"])
            if preset is not None:
                persona_prompt = preset.system_prompt
                registry = filter_registry(registry, preset)
                preset_id_used = preset.id
                auto_routed = True
    brain = Brain(session=session, router=rt, registry=registry)
    try:
        conv, msg, cost = brain.chat(
            user_id=current_user.id,
            conversation_id=request.conversation_id,
            user_message=request.message,
            use_tools=request.use_tools,
            prefer_local=request.prefer_local,
            max_tokens=request.max_tokens,
            persona_prompt=persona_prompt,
        )
    except SpendCapExceeded as e:
        # 402 Payment Required — the user hit their spend cap and there's no free
        # local model to absorb it. A clear, non-crashing signal.
        raise HTTPException(status_code=402, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ChatResponse(
        conversation_id=conv.id,
        message=MessageOut.model_validate(msg),
        total_cost_usd=cost,
        preset_id=preset_id_used,
        auto_routed=auto_routed,
    )


def _sse_format(events: Iterator[dict]) -> Iterator[bytes]:
    """Serialize brain events to SSE. Fail-SOFT: if the event generator raises
    (spend cap, or a provider error before/after first token), emit a clean
    error event and close the stream instead of dropping the connection with a
    raw traceback. (Full mid-stream provider FAILOVER — retrying a fallback
    model — is a separate, larger change; this stops the crash.)"""
    try:
        for event in events:
            line = f"data: {json.dumps(event)}\n\n"
            yield line.encode("utf-8")
    except SpendCapExceeded as e:
        err = {"type": "error", "code": "spend_cap", "message": str(e)}
        yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
    except Exception as e:  # noqa: BLE001 — never let a stream die with a raw 500
        logger.warning("chat stream errored: %s", e)
        err = {"type": "error", "message": "The assistant hit an error. Please try again."}
        yield f"data: {json.dumps(err)}\n\n".encode("utf-8")


@router.get("/chat/stream")
def chat_stream(
    message: str = Query(..., min_length=1, max_length=10_000),
    conversation_id: uuid.UUID | None = Query(None),
    prefer_local: bool = Query(False),
    max_tokens: int = Query(1024, ge=64, le=4096),
    current_user: User = Depends(get_user_for_stream),
    session: Session = Depends(get_db),
):
    """SSE streaming endpoint. Tools are disabled in streaming mode."""
    brain = _build_brain(session)
    events = brain.stream(
        user_id=current_user.id,
        conversation_id=conversation_id,
        user_message=message,
        prefer_local=prefer_local,
        max_tokens=max_tokens,
    )
    return StreamingResponse(_sse_format(events), media_type="text/event-stream")


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[ConversationOut]:
    brain = _build_brain(session)
    convs = brain.list_conversations(current_user.id, limit=limit)
    return [
        ConversationOut(
            id=c.id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
            message_count=c.message_count,
        )
        for c in convs
    ]


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
def get_conversation(
    conv_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ConversationDetail:
    brain = _build_brain(session)
    conv = brain.get_conversation(current_user.id, conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[MessageOut.model_validate(m) for m in conv.messages],
    )


@router.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(
    conv_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    conv = (
        session.query(Conversation)
        .filter(
            Conversation.id == conv_id,
            Conversation.user_id == current_user.id,
        )
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    session.delete(conv)
    session.commit()
