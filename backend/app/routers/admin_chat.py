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


@router.post("/kai-chat")
def admin_chat(req: AdminChatRequest, session: Session = Depends(get_db)):
    try:
        prof = _resolve_operator_profile(session)
    except OperatorNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    brain = Brain(
        session=session,
        router=build_default_router(session),
        registry=build_default_registry(),
    )
    try:
        conv, msg, cost = brain.chat(
            user_id=prof.id,
            conversation_id=req.conversation_id,
            user_message=req.message,
            use_tools=req.use_tools,
            prefer_local=req.prefer_local,
            max_tokens=req.max_tokens,
        )
    except ValueError as e:
        # Brain raises ValueError for unknown conversation_id etc.
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("admin chat failed")
        raise HTTPException(status_code=502, detail=f"chat error: {e}")

    return {
        "conversation_id": str(conv.id),
        "message": {
            "role": msg.role,
            "content": msg.content,
            "adapter": getattr(msg, "adapter", None),
            "model": getattr(msg, "model", None),
        },
        "total_cost_usd": cost,
    }
