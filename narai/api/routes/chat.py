"""Chat route — accepts a prompt, returns NarAI's response with tier + memory + RAG."""
import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from narai.api.auth import require_auth
from narai.core import memory, rag, router, skills, tiers
from narai.core.db import ChatLog, SessionLocal
from narai.core.extractor import extract_facts_async
from narai.core.identity import build_system_prompt as build_identity_prompt
from narai.core.memory import MemoryStore

rt = APIRouter(prefix="/chat", tags=["chat"])

logger = logging.getLogger("narai.chat")

# Single-user app — everything keyed to "owner" to match the JWT `sub` claim.
_DEFAULT_USER_ID = "owner"

# Step 2 Memory Engine — lazy singleton so import doesn't touch disk.
_memory_store: MemoryStore | None = None


def _get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store


async def _extract_and_remember(user_message: str, user_id: str) -> None:
    """Non-blocking fact extraction. Memory writes must never break the chat."""
    try:
        async def _llm(system: str, user: str) -> str:
            resp = await router.call(user, tier="fast", system=system)
            return resp.get("content", "")

        new_facts = await extract_facts_async(user_message, _llm)
        if not new_facts:
            return
        store = _get_memory_store()
        for f in new_facts:
            store.remember_fact(
                user_id=user_id,
                content=f.get("content", ""),
                category=f.get("category", "other"),
                source="extracted",
            )
    except Exception as e:
        logger.warning(f"fact extraction failed (non-fatal): {e}")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    skill: str | None = None
    tier: str | None = None  # override auto-classification
    stream: bool = False
    history: list[dict] | None = None


class ChatResponse(BaseModel):
    reply: str
    model: str
    tier: str
    tokens: int
    skill: str | None


def _build_user_context(query: str) -> str | None:
    """Facts + recent episodes for the owner, formatted for the identity prompt."""
    try:
        store = _get_memory_store()
        ctx = store.get_context(_DEFAULT_USER_ID, query=query)
        return ctx or None
    except Exception as e:
        logger.warning(f"memory context failed (non-fatal): {e}")
        return None


@rt.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, _: str = Depends(require_auth)) -> ChatResponse:
    tier = req.tier or tiers.classify(req.message)
    mem_hits = await memory.arecall(req.message, n=4)
    rag_hits = await rag.aquery(req.message, n=3)

    system = skills.build_system_prompt(
        base=build_identity_prompt(user_context=_build_user_context(req.message)),
        skill=req.skill,
        memory_context=memory.format_recall(mem_hits) or None,
        rag_context=rag.format_query(rag_hits) or None,
    )

    result = await router.call(
        req.message,
        tier=tier,
        system=system,
        history=req.history,
    )

    async with SessionLocal() as session:
        session.add(ChatLog(
            message=req.message,
            response=result["content"],
            model_used=result["model"],
            tier=tier,
            tokens_used=result["tokens"],
            skill=req.skill,
        ))
        await session.commit()

    # Step 2: log the turn as an episode + fire-and-forget fact extraction.
    try:
        _get_memory_store().log_episode(
            _DEFAULT_USER_ID,
            f"User: {req.message}\nNarAI: {result['content']}",
        )
    except Exception as e:
        logger.warning(f"episode log failed (non-fatal): {e}")

    asyncio.create_task(_extract_and_remember(req.message, _DEFAULT_USER_ID))

    return ChatResponse(
        reply=result["content"],
        model=result["model"],
        tier=tier,
        tokens=result["tokens"],
        skill=req.skill,
    )


@rt.post("/stream")
async def chat_stream(req: ChatRequest, _: str = Depends(require_auth)) -> StreamingResponse:
    tier = req.tier or tiers.classify(req.message)
    mem_hits = await memory.arecall(req.message, n=4)
    rag_hits = await rag.aquery(req.message, n=3)
    system = skills.build_system_prompt(
        base=build_identity_prompt(user_context=_build_user_context(req.message)),
        skill=req.skill,
        memory_context=memory.format_recall(mem_hits) or None,
        rag_context=rag.format_query(rag_hits) or None,
    )

    async def generate():
        async for chunk in router.stream(req.message, tier=tier, system=system):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    # Stream route: fire-and-forget fact extraction; episode logged only on
    # non-stream path so we don't re-assemble chunks here.
    asyncio.create_task(_extract_and_remember(req.message, _DEFAULT_USER_ID))

    return StreamingResponse(generate(), media_type="text/event-stream")
