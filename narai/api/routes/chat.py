"""Chat route — accepts a prompt, returns NarAI's response with tier + memory + RAG."""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from narai.api.auth import require_auth
from narai.core import memory, rag, router, skills, tiers
from narai.core.db import ChatLog, SessionLocal

rt = APIRouter(prefix="/chat", tags=["chat"])


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


@rt.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, _: str = Depends(require_auth)) -> ChatResponse:
    tier = req.tier or tiers.classify(req.message)
    mem_ctx = await memory.arecall(req.message, n=4)
    rag_ctx = await rag.aquery(req.message, n=3)

    system = skills.build_system_prompt(
        base="You are NarAI, J.K. Blaze's personal AI assistant. Be direct, sharp, and useful.",
        skill=req.skill,
        memory_context=memory.recall_context(req.message) if mem_ctx else None,
        rag_context=rag.query_context(req.message) if rag_ctx else None,
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
    system = skills.build_system_prompt(
        base="You are NarAI, J.K. Blaze's personal AI assistant. Be direct, sharp, and useful.",
        skill=req.skill,
        memory_context=memory.recall_context(req.message),
        rag_context=rag.query_context(req.message),
    )

    async def generate():
        async for chunk in router.stream(req.message, tier=tier, system=system):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
