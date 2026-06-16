"""OpenAI-compatible /v1/chat/completions endpoint.

Drop-in for clients using the official `openai` SDK: set
``OPENAI_BASE_URL=https://kai.wheellsverse.com/v1`` and
``OPENAI_API_KEY=kai_xxx``. Calls land here.

Why mimic OpenAI's shape and not invent our own:
    Adoption friction is the only thing that matters for an API. A dev
    paying $19/mo for KAI Pro can flip one env var and immediately use
    KAI inside Continue.dev / Cursor / their own scripts. No SDK rewrite.

Scope of v1
-----------
    Supports:        model, messages, temperature, max_tokens, stream
    Returns:         OpenAI ChatCompletion / ChatCompletionChunk shape
    Auth:            Authorization: Bearer kai_xxx (Pro/Max/Ultra only)

NOT in v1 (intentional):
    - tools/function-calling — needs the full Brain loop, separate work
    - n>1 sampling
    - logprobs / top_logprobs
    - response_format = json_schema
    - usage breakdown (we report 0/0/0 for now)
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.api_key_auth import require_api_key_user
from app.dependencies.supabase_jwt import UserPrincipal
from app.services.router import build_default_router

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["openai-compat"])


# ── Request / Response shapes (OpenAI subset) ─────────────────────────────


class Message(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant|tool)$")
    content: str


class ChatCompletionsRequest(BaseModel):
    model: str = "gpt-4o-mini"
    messages: List[Message]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8000)
    stream: bool = False


class Choice(BaseModel):
    index: int = 0
    message: Message
    finish_reason: str = "stop"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage


# ── Endpoint ──────────────────────────────────────────────────────────────


@router.post("/chat/completions")
def chat_completions(
    body: ChatCompletionsRequest,
    user: UserPrincipal = Depends(require_api_key_user),
    db: Session = Depends(get_db),
):
    """OpenAI-compatible chat completions.

    Routes through the same Router that powers /kai/chat (so the chosen
    model and adapters honor the operator's STRIPE_PRICE_PRO-tier budget
    cap), but skips the conversation persistence + tool loop — clients
    using the OpenAI API typically manage their own message history.
    """
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages required")

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created_ts = int(time.time())

    # Translate OpenAI message list → Router shape. System message is split
    # out separately (Router accepts it as a top-level `system=` arg).
    sys_parts = [m.content for m in body.messages if m.role == "system"]
    convo = [
        {"role": m.role, "content": m.content}
        for m in body.messages if m.role in ("user", "assistant")
    ]
    if not convo:
        raise HTTPException(status_code=400, detail="at least one user message required")

    router_obj = build_default_router(db)

    try:
        result = router_obj.complete(
            user_id=user.id,
            messages=convo,
            max_tokens=body.max_tokens or 1024,
            temperature=body.temperature,
            system="\n\n".join(sys_parts) if sys_parts else None,
        )
    except Exception as e:
        logger.exception("v1 chat completion failed")
        raise HTTPException(status_code=502, detail=f"upstream model error: {e}")

    text = result.content
    in_tokens = int(result.input_tokens)
    out_tokens = int(result.output_tokens)
    finish = result.finish_reason or "stop"

    if body.stream:
        # Stream the response in OpenAI's chunk format. Even for a non-true-stream
        # backend, we can emit role chunk → content chunk → [DONE].
        def gen() -> Iterator[bytes]:
            base = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": body.model,
            }
            # Role chunk first (OpenAI convention)
            chunk = {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
            yield f"data: {json.dumps(chunk)}\n\n".encode()
            # Content chunk — for non-streaming backends, send the whole text at once
            chunk = {**base, "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
            yield f"data: {json.dumps(chunk)}\n\n".encode()
            # Final stop chunk
            chunk = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}
            yield f"data: {json.dumps(chunk)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream")

    return ChatCompletionResponse(
        id=completion_id,
        created=created_ts,
        model=body.model,
        choices=[
            Choice(
                index=0,
                message=Message(role="assistant", content=text),
                finish_reason=finish,
            )
        ],
        usage=Usage(
            prompt_tokens=in_tokens,
            completion_tokens=out_tokens,
            total_tokens=in_tokens + out_tokens,
        ),
    )


@router.get("/models")
def list_models(user: UserPrincipal = Depends(require_api_key_user)):
    """OpenAI-compatible /v1/models. Lists models that KAI's router supports."""
    now = int(time.time())
    items = [
        {"id": m, "object": "model", "created": now, "owned_by": "kai"}
        for m in ("gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "claude-3-5-haiku")
    ]
    return {"object": "list", "data": items}
