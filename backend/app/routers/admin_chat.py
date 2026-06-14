"""Operator-only chat endpoint. Full power, no tier gates.

Distinct from /kai/chat (the public, paid product) in three ways:

1. Auth: X-Admin-Token header (same as the rest of /admin/*), not a
   Supabase JWT. The operator doesn't sign up — they own the box.

2. Tier: routes through a synthetic 'operator' profile that's
   force-set to tier='ultra' on every call. Bypasses every paid-gate
   check in the codebase without having to thread an "operator=True"
   flag through tier checks.

3. Tools: the full default tool registry — including Composio (200+
   SaaS), MCP (whatever's in mcp_config.json), web_fetch, memory,
   trading_signal — with no preset filtering. The operator wants
   everything.

Spend tracking still runs (so the cost line on the dashboard reflects
your operator chats), but the daily/monthly caps in SpendTracker are
*soft* — the router falls back to Ollama when over cap rather than
refusing. That's fine for an operator; you'd notice the model swap.

Configuration:
  KAI_OPERATOR_USER_ID env var (UUID) — defaults to a fixed sentinel.
  Set this to your real Supabase user.id if you want your operator
  chats to share memory with your normal-user chats. Otherwise the
  default keeps operator memory cleanly separated.
"""
from __future__ import annotations

import logging
import os
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.models.profile import Profile
from app.services.nai_brain import Brain
from app.services.router import build_default_router
from app.services.tools import build_default_registry

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)

class OperatorNotConfigured(Exception):
    """Operator chat can't proceed without a real Supabase user mapped to
    the operator. We raise instead of inventing one because profiles.id
    has a FK to auth.users — a synthetic UUID would 500 on insert."""


def _operator_uuid_from_env() -> _uuid.UUID | None:
    raw = os.environ.get("KAI_OPERATOR_USER_ID", "").strip()
    if not raw:
        return None
    try:
        return _uuid.UUID(raw)
    except ValueError:
        logger.warning("KAI_OPERATOR_USER_ID=%r is not a valid UUID — ignoring", raw)
        return None


def _resolve_operator_profile(session: Session) -> Profile:
    """Find the profile the operator chat should run AS.

    Resolution order:
      1. KAI_OPERATOR_USER_ID env var — load that exact profile.
      2. Any existing tier='ultra' profile (heuristic: the operator most
         likely promoted their own account to ultra at launch).
      3. None — raise OperatorNotConfigured with a clear remediation.

    Tier is pinned to 'ultra' on every call so a stray DB edit can't
    silently downgrade and start tripping paid-gates.
    """
    op_id = _operator_uuid_from_env()
    if op_id is not None:
        prof = session.get(Profile, op_id)
        if prof is None:
            raise OperatorNotConfigured(
                f"KAI_OPERATOR_USER_ID={op_id} but no profile with that id exists. "
                f"Use your real Supabase user.id — sign in at /kai-ui/login.html "
                f"to find it, or copy from Supabase dashboard → Auth → Users."
            )
    else:
        # Heuristic fallback — first ultra-tier profile, oldest first
        # (most likely the operator's own seed account).
        prof = (
            session.query(Profile)
            .filter(Profile.tier == "ultra")
            .order_by(Profile.created_at.asc())
            .first()
        )
        if prof is None:
            raise OperatorNotConfigured(
                "No operator profile resolved. Either set "
                "KAI_OPERATOR_USER_ID=<your-supabase-user-id> in .env "
                "and restart the daemon, or promote your existing profile to "
                "tier='ultra' in the DB."
            )

    if (prof.tier or "").lower() != "ultra":
        logger.info(
            "operator profile %s was tier=%s — restoring to ultra",
            prof.id, prof.tier,
        )
        prof.tier = "ultra"
        session.commit()
    return prof


class AdminChatRequest(BaseModel):
    message: str
    conversation_id: _uuid.UUID | None = None
    # Tools on by default — the whole point of admin chat is full power.
    use_tools: bool = True
    # prefer_local routes through Ollama. Off by default; flip on for
    # privacy-sensitive prompts (e.g. dumping production data into chat).
    prefer_local: bool = False
    max_tokens: int = 2048
    # Optional expert-agent preset id (swe / marketing / finance / research /
    # legal_research). When set, prepends a persona system prompt + filters
    # the tool registry to the preset's whitelist. None = bare KAI.
    preset_id: str | None = None
    # Super-router: when no preset is explicitly selected, classify the message
    # and auto-apply the best-fitting expert agent. Opt-in (default off) so the
    # bare-KAI default is unchanged. Ignored if preset_id is set.
    auto_route: bool = False
    # Self-correction: opt-in critic + reviser pass on KAI's draft reply
    # BEFORE the response is returned. Adds ~1-2 LLM calls per turn (~$0.001
    # extra on the cheap critic + reviser path). Off by default to keep
    # the cost predictable.
    self_correct: bool = False
    # Max critique-revise iterations when self_correct=True. Default 1
    # (one critique + at most one revision). Hard-capped at 3.
    self_correct_max_iterations: int = 1
    # Verification-confidence: opt-in. After the reply, check it against the
    # user's indexed documents (grounding.verify_statement) and return a REAL
    # grounded verdict + confidence (vs the agent's self-rated tag). One extra
    # LLM call; off by default.
    verify: bool = False


# Appended to a GROUNDED expert agent's persona (one that can search the
# knowledge base) so each answer self-rates how well its cited sources support
# it. The dashboard parses the trailing tag into a colored confidence badge and
# strips it from the shown text.
_CONFIDENCE_INSTRUCTION = (
    "\n\nAt the very end of your reply, on its own line, output exactly one tag "
    "[confidence: high|medium|low] reflecting how well your CITED SOURCES support "
    "the answer — 'high' only when directly backed by citations, 'low' when you "
    "could not ground it."
)


@router.post("/kai-chat")
def admin_chat(req: AdminChatRequest, session: Session = Depends(get_db)):
    try:
        prof = _resolve_operator_profile(session)
    except OperatorNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))

    # ─── preset handling ─────────────────────────────────────────────
    # If the operator selected an expert-agent preset, look it up + apply:
    #   - filter the tool registry to the preset's whitelist
    #   - prepend the preset's system_prompt to KAI's baseline
    # Unknown preset_id is a 400 (not silent fallback) so a typo in the UI
    # surfaces as an error instead of degrading to bare KAI.
    persona_prompt = ""
    registry = build_default_registry()
    rt = build_default_router(session)
    preset_id_used: str | None = None
    auto_routed = False

    # Super-router: no preset chosen + auto_route on → classify → pick the best
    # expert. classify_domain validates against the catalog (hallucinated/empty
    # → None), so effective_preset_id is always a real id or None.
    effective_preset_id = req.preset_id
    if effective_preset_id is None and req.auto_route:
        from app.services.agent_router import classify_domain
        routed = classify_domain(router=rt, user_id=prof.id, question=req.message)
        if routed.get("preset_id"):
            effective_preset_id = routed["preset_id"]
            auto_routed = True
            logger.info("admin_chat: auto-routed to %s (confidence=%s)",
                        effective_preset_id, routed.get("confidence"))

    if effective_preset_id:
        from app.services.presets import filter_registry, get_preset
        preset = get_preset(effective_preset_id)
        if preset is None:
            # Manual id typo → 400; an auto-routed id is pre-validated, so this
            # only fires for a bad explicit preset_id.
            if auto_routed:
                logger.warning("admin_chat: auto-routed id %r not found — ignoring", effective_preset_id)
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown preset_id={req.preset_id!r}; see GET /admin/presets",
                )
        else:
            persona_prompt = preset.system_prompt
            # Grounded agents (those wired to the knowledge base) self-rate
            # confidence so the dashboard can badge it.
            if "document_search" in (preset.tool_whitelist or []):
                persona_prompt += _CONFIDENCE_INSTRUCTION
            registry = filter_registry(registry, preset)
            preset_id_used = preset.id
            logger.info(
                "admin_chat: preset=%s applied%s (tools kept=%d, persona prompt %d chars)",
                preset.id, " [auto]" if auto_routed else "",
                len(registry._tools), len(persona_prompt),
            )

    brain = Brain(
        session=session,
        router=rt,
        registry=registry,
    )
    try:
        conv, msg, cost = brain.chat(
            user_id=prof.id,
            conversation_id=req.conversation_id,
            user_message=req.message,
            use_tools=req.use_tools,
            prefer_local=req.prefer_local,
            max_tokens=req.max_tokens,
            persona_prompt=persona_prompt,
        )
    except ValueError as e:
        # Brain raises ValueError for unknown conversation_id etc.
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("admin chat failed")
        raise HTTPException(status_code=502, detail=f"chat error: {e}")

    # ─── self-correction (opt-in) ────────────────────────────────────
    # Critic + reviser pass on the draft reply. Adds 1-2 LLM calls;
    # the critic uses the CHEAP adapter, the reviser reuses whatever
    # produced the draft. Fail-open everywhere — a broken critic must
    # never block a real reply.
    correction_meta: dict | None = None
    final_content = msg.content
    if req.self_correct:
        try:
            from app.services.self_correction import run_correction_loop
            router_obj = brain.router
            adapters = getattr(router_obj, "adapters", {}) or {}
            original_adapter = (
                adapters.get(getattr(msg, "adapter", None))
                or next(iter(adapters.values()), None)
            )
            corr = run_correction_loop(
                user_message=req.message,
                initial_draft=msg.content or "",
                router=router_obj,
                original_adapter=original_adapter,
                max_iterations=req.self_correct_max_iterations,
                prefer_local=req.prefer_local,
            )
            final_content = corr.final_text or msg.content
            cost = (cost or 0.0) + (corr.total_cost or 0.0)
            correction_meta = {
                "iterations": corr.iterations,
                "was_revised": corr.was_revised,
                "final_severity": (
                    corr.verdicts[-1].severity if corr.verdicts else "none"
                ),
                "critic_cost_usd": round(corr.total_cost, 6),
            }
            # If revised, persist the corrected text back to the saved message
            # so the conversation history reflects what the operator actually
            # saw, not the pre-revision draft.
            if corr.was_revised and msg.content != final_content:
                msg.content = final_content
                try:
                    session.commit()
                except Exception as e:
                    logger.warning("self_correction: persist revised text failed: %s", e)
                    session.rollback()
        except Exception as e:
            # Hard-fail-open: log + return the original draft.
            logger.warning("self_correction: loop crashed, returning draft: %s", e)

    # ─── verification-confidence (opt-in) ────────────────────────────
    # Check the final reply against the user's indexed docs for a REAL grounded
    # verdict + confidence. Fail-soft — never blocks the reply.
    verification = None
    if req.verify:
        try:
            from app.services import grounding
            v = grounding.verify_statement(
                db=session, router=rt, user_id=prof.id, statement=final_content,
            )
            verification = {
                "verdict": v.get("verdict"),
                "confidence": v.get("confidence"),
                "reason": v.get("reason", ""),
                "sources_checked": v.get("sources_checked", 0),
            }
        except Exception as e:
            logger.warning("admin_chat: verification failed: %s", e)

    return {
        "conversation_id": str(conv.id),
        "message": {
            "role": msg.role,
            "content": final_content,
            "adapter": getattr(msg, "adapter", None),
            "model": getattr(msg, "model", None),
        },
        "total_cost_usd": cost,
        # Real grounded verification (set only when verify=True). None otherwise.
        "verification": verification,
        # Surface the preset id back so the dashboard can show
        # "preset=swe" in the response meta line for confirmation.
        "preset_id": preset_id_used,
        # True when the super-router auto-selected the preset (vs operator picking).
        "auto_routed": auto_routed,
        # Set only when self_correct=True. None otherwise so existing
        # clients that don't look for it are unaffected.
        "self_correction": correction_meta,
    }
