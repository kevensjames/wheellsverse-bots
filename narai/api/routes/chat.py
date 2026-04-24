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
from narai.core.overwhelm import detect_async, modifier_for
from narai.core.mode_router import (
    route_async, parse_override, modifier_for as mode_modifier_for,
)

rt = APIRouter(prefix="/chat", tags=["chat"])

logger = logging.getLogger("narai.chat")

# Single-user app — everything keyed to "owner" to match the JWT `sub` claim.
_DEFAULT_USER_ID = "owner"

# Step 2 Memory Engine — lazy singleton so import doesn't touch disk.
_memory_store: MemoryStore | None = None

# Hold references to fire-and-forget tasks so asyncio's garbage collector
# doesn't reap them before the extraction LLM call completes. Python 3.11
# docs explicitly warn about this footgun.
_BACKGROUND_TASKS: set = set()


def _get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
        logger.info(f"MemoryStore ready at {_memory_store.data_dir}")
    return _memory_store


async def _extract_and_remember(user_message: str, user_id: str) -> None:
    """Non-blocking fact extraction. Memory writes must never break the chat."""
    try:
        async def _llm(system: str, user: str) -> str:
            resp = await router.call(user, tier="fast", system=system)
            return resp.get("content", "")

        new_facts = await extract_facts_async(user_message, _llm)
        logger.info(
            f"fact extraction for {user_id!r}: "
            f"msg={user_message[:60]!r} extracted={len(new_facts)}"
        )
        if not new_facts:
            return
        store = _get_memory_store()
        for f in new_facts:
            stored = store.remember_fact(
                user_id=user_id,
                content=f.get("content", ""),
                category=f.get("category", "other"),
                source="extracted",
            )
            logger.info(
                f"fact stored: user={user_id} cat={stored.category} "
                f"content={stored.content[:80]!r}"
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


async def _detect_overwhelm(user_message: str):
    """Step 3: two-pass overwhelm detection. Fast-pass runs regex; ambiguous
    cases invoke a cheap LLM classifier via the NarAI router. Never raises —
    memory/identity must keep working if this fails.
    """
    async def _classifier(system: str, user: str) -> str:
        resp = await router.call(user, tier="fast", system=system)
        return resp.get("content", "")

    try:
        state = await detect_async(user_message, async_llm_call=_classifier)
        logger.info(
            f"overwhelm: level={state.level} score={state.score:.2f} "
            f"signals={len(state.signals)}"
        )
        return state
    except Exception as e:
        logger.warning(f"overwhelm detection failed (non-fatal): {e}")
        from narai.core.overwhelm import OverwhelmState
        return OverwhelmState("none", 0.0, "detection error", [])


# Step 4: per-user mode lock (admin NarAI is single-user, keyed to "owner").
# Dict is module-level intentionally — resets on process restart, which is
# acceptable for a voice/behavior lock. User can always say "stay in X" again.
_MODE_LOCKS: dict[str, str] = {}


def _apply_override(user_message: str, user_id: str) -> None:
    """Mutate the per-user mode lock if the message contains a recognized
    override command (stay in operator/companion, release the mode)."""
    cmd = parse_override(user_message)
    if cmd == "release":
        if _MODE_LOCKS.pop(user_id, None):
            logger.info(f"mode lock released for {user_id}")
    elif cmd in ("operator", "companion"):
        _MODE_LOCKS[user_id] = cmd
        logger.info(f"mode lock set for {user_id}: {cmd}")


async def _route_mode(user_message: str, user_id: str, overwhelm_level: str):
    """Step 4: pick operator vs companion for this turn. Fast-pass regex first,
    deep LLM classifier only for the ambiguous band. Respects lock + overwhelm.
    """
    async def _classifier(system: str, user: str) -> str:
        resp = await router.call(user, tier="fast", system=system)
        return resp.get("content", "")

    try:
        decision = await route_async(
            user_message,
            overwhelm_level=overwhelm_level,
            manual_override=_MODE_LOCKS.get(user_id),
            async_llm_call=_classifier,
        )
        logger.info(
            f"mode: {decision.mode} forced={decision.forced} "
            f"score={decision.score:.2f} reason={decision.reason!r}"
        )
        return decision
    except Exception as e:
        logger.warning(f"mode routing failed (non-fatal): {e}")
        from narai.core.mode_router import ModeDecision
        return ModeDecision("operator", 0.0, f"routing error: {e}", False)


async def run_pipeline_async(
    user_id: str,
    user_message: str,
    skill: str | None = None,
    tier: str | None = None,
    history: list[dict] | None = None,
) -> dict:
    """Shared Step 1-4 pipeline runner. Used by the /chat REST route and the
    /voice/ws WebSocket route. Returns a dict with reply, mode, overwhelm
    level, model, and tier so both entry points can use the same plumbing.

    Does NOT persist to ChatLog (that's REST-specific); the voice route has
    its own episode tagging pattern. Memory-store episode logging + fact
    extraction still fire so conversation continuity works across channels.
    """
    resolved_tier = tier or tiers.classify(user_message)
    _apply_override(user_message, user_id)
    mem_hits = await memory.arecall(user_message, n=4)
    rag_hits = await rag.aquery(user_message, n=3)
    overwhelm_state = await _detect_overwhelm(user_message)
    mode_decision = await _route_mode(
        user_message, user_id, overwhelm_state.level,
    )

    system = skills.build_system_prompt(
        base=build_identity_prompt(
            user_context=_build_user_context(user_message),
            overwhelm_modifier=modifier_for(overwhelm_state) or None,
            mode_modifier=mode_modifier_for(mode_decision) or None,
        ),
        skill=skill,
        memory_context=memory.format_recall(mem_hits) or None,
        rag_context=rag.format_query(rag_hits) or None,
    )

    result = await router.call(
        user_message,
        tier=resolved_tier,
        system=system,
        history=history,
    )

    # Episode tag — mirrors /chat POST path so timelines stay coherent
    # regardless of which surface (REST or voice WS) the turn came from.
    try:
        _get_memory_store().log_episode(
            user_id,
            f"[mode={mode_decision.mode} overwhelm={overwhelm_state.level}] "
            f"User: {user_message}\nNarAI: {result['content']}",
        )
    except Exception as e:
        logger.warning(f"episode log failed (non-fatal): {e}")

    task = asyncio.create_task(_extract_and_remember(user_message, user_id))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    return {
        "reply": result["content"],
        "model": result["model"],
        "tier": resolved_tier,
        "tokens": result["tokens"],
        "mode": mode_decision.mode,
        "overwhelm": overwhelm_state.level,
        "skill": skill,
    }


@rt.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, _: str = Depends(require_auth)) -> ChatResponse:
    tier = req.tier or tiers.classify(req.message)
    _apply_override(req.message, _DEFAULT_USER_ID)
    mem_hits = await memory.arecall(req.message, n=4)
    rag_hits = await rag.aquery(req.message, n=3)
    overwhelm_state = await _detect_overwhelm(req.message)
    mode_decision = await _route_mode(
        req.message, _DEFAULT_USER_ID, overwhelm_state.level,
    )

    system = skills.build_system_prompt(
        base=build_identity_prompt(
            user_context=_build_user_context(req.message),
            overwhelm_modifier=modifier_for(overwhelm_state) or None,
            mode_modifier=mode_modifier_for(mode_decision) or None,
        ),
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

    # Step 2 + 3 + 4: log the turn with mode + overwhelm tags so Step 7 can
    # mine for patterns (e.g. "user slides into companion mode on Sundays",
    # "Nexora topic triggers overwhelm 60% of the time").
    try:
        _get_memory_store().log_episode(
            _DEFAULT_USER_ID,
            f"[mode={mode_decision.mode} overwhelm={overwhelm_state.level}] "
            f"User: {req.message}\nNarAI: {result['content']}",
        )
    except Exception as e:
        logger.warning(f"episode log failed (non-fatal): {e}")

    task = asyncio.create_task(
        _extract_and_remember(req.message, _DEFAULT_USER_ID)
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

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
    _apply_override(req.message, _DEFAULT_USER_ID)
    mem_hits = await memory.arecall(req.message, n=4)
    rag_hits = await rag.aquery(req.message, n=3)
    overwhelm_state = await _detect_overwhelm(req.message)
    mode_decision = await _route_mode(
        req.message, _DEFAULT_USER_ID, overwhelm_state.level,
    )
    system = skills.build_system_prompt(
        base=build_identity_prompt(
            user_context=_build_user_context(req.message),
            overwhelm_modifier=modifier_for(overwhelm_state) or None,
            mode_modifier=mode_modifier_for(mode_decision) or None,
        ),
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
    task = asyncio.create_task(
        _extract_and_remember(req.message, _DEFAULT_USER_ID)
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Memory debug (Step 2 verification) ──────────────────────────────────────
# Lets you inspect what NarAI currently remembers about you, without having
# to guess from chat replies. Auth-gated via the same JWT as /chat.

@rt.get("/memory/debug")
async def memory_debug(_: str = Depends(require_auth)) -> dict:
    store = _get_memory_store()
    facts = store.recall_facts(_DEFAULT_USER_ID)
    episode_count = store.episodes.count()
    grouped: dict[str, list[dict]] = {}
    for f in facts:
        grouped.setdefault(f.category, []).append({
            "content": f.content,
            "source": f.source,
            "created_at": f.created_at,
        })
    return {
        "user_id": _DEFAULT_USER_ID,
        "fact_count": len(facts),
        "episode_count": episode_count,
        "facts_by_category": grouped,
    }
