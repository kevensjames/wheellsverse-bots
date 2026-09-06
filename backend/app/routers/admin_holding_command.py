"""§90 Holding Command API + §91 governed streaming — ONE typed, owner-only command entrypoint.

Mirrors the fabric pattern (admin_capabilities.InvokeBody + POST /command): the server
AUTHENTICATES the owner (require_kai_ultra), builds the authoritative owner Principal ITSELF
— never from the body: role/authority/scope JSON fields are not modeled and are ignored (§4/§6)
— and routes a TYPED command through the deterministic §8 resolver to the EXISTING CapabilityBrain
(capability path) or SystemKnowledgeIndex (holding read path). The command string is NEVER exec'd
as a shell/eval; it is classified to a coarse intent and dispatched (command_router.resolve).

Consequential/mutating intents fail CLOSED to REQUIRE_APPROVAL (HTTP 202) — no execution (§24).
Capability EXECUTION additionally requires KAI_CAPABILITY_EXECUTION_ENABLED (brake #1): with it off,
a capability intent returns the Brain's PLAN only (PREPARE_ONLY), never a live invocation.

Dormant unless KAI_HOLDING_COMMAND_ENABLED — main.py includes this router only when the flag is on,
so a disabled deployment has ZERO new surface (route absent when flag off).

§91 streaming reuses the hardened SSE mechanism from admin_chat (_sse_async: real cancellation;
cookie/session auth, no tokens in URLs) and emits the §91 event taxonomy. It NEVER streams hidden
chain-of-thought, secrets, credentials, internal prompts, or unsanitized capability output —
evidence is redacted (holding.task_resolver.redact) and command/context text is injection-scanned
(capability.results). Consequential events carry correlation_id/mission_id/environment/timestamp/
provenance.
"""
from __future__ import annotations

import asyncio
import logging
import uuid as _uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.routers.admin_chat import require_kai_ultra, _sse_async, _check_rate  # reuse gate + hardened SSE
from app.services.capability.seed import seed_registry, seed_graph
from app.services.capability.risk import Principal
from app.services.capability.brain import CapabilityBrain
from app.services.capability.command import plan_and_execute, default_v1_operation
from app.services.capability.execution import CapabilityExecutionService, Status
from app.services.capability.results import scan_fields
from app.services.holding.task_resolver import redact                         # §29 evidence redaction
from app.services.holding.knowledge_index import SystemKnowledgeIndex
from app.services.holding.command_router import resolve, CommandContext, Intent, Dispatch
from app.services.holding.approval_dialog import authorize as approve_action, reject as reject_action, ConfirmationStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/holding", tags=["holding-command"],
                   dependencies=[Depends(require_kai_ultra)])   # OWNER-ONLY, all routes (§6)

# ── §91 event taxonomy (names are load-bearing — the presence layer switches on `type`) ───────────
EV_PRESENCE = "KAI_PRESENCE"
EV_TRANSCRIPT_FINAL = "TRANSCRIPT_FINAL"
EV_COMMAND_ACCEPTED = "COMMAND_ACCEPTED"
EV_CONTEXT_RESOLVED = "CONTEXT_RESOLVED"
EV_MISSION_LINKED = "MISSION_LINKED"
EV_CAPABILITY_SELECTED = "CAPABILITY_SELECTED"
EV_WORKER_UPDATE = "WORKER_UPDATE"
EV_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
EV_ACTION_RESULT = "ACTION_RESULT"
EV_ACTION_COMPLETE = "ACTION_COMPLETE"
EV_SYSTEM_DEGRADED = "SYSTEM_DEGRADED"

# ── one process-wide execution plane (the SAME service the fabric HTTP route + Brain flow use, §29) ─
_registry = seed_registry()
_graph = seed_graph()
_brain = CapabilityBrain(_registry, _graph)


def _audit_sink(rec: dict) -> None:
    """Best-effort audit → App B AuditLog (fail-open). Only policy metadata, never secrets (§20)."""
    try:
        from app.database import SessionLocal
        from app.models.admin import AuditLog
        s = SessionLocal()
        try:
            safe = {k: rec.get(k) for k in ("capability", "operation", "status", "decision",
                                            "action_class", "role", "mission_id", "correlation_id",
                                            "intent", "dispatch", "event")}
            s.add(AuditLog(action=rec.get("event", "holding.command.event"), actor_type="owner",
                           event_metadata=safe))
            s.commit()
        finally:
            s.close()
    except Exception:
        pass


_service = CapabilityExecutionService(_registry, audit=_audit_sink)

_HTTP = {Status.OK: 200, Status.APPROVAL_REQUIRED: 202, Status.DENIED: 403,
         Status.OPERATION_NOT_ENABLED: 403, Status.CAPABILITY_UNKNOWN: 404, Status.OPERATION_UNKNOWN: 404,
         Status.CAPABILITY_UNAVAILABLE: 503, Status.INPUT_REJECTED: 400, Status.RATE_LIMITED: 429,
         Status.TIMEOUT: 504, Status.FAILED: 502}


def _owner() -> Principal:
    """Only an owner reaches here (require_kai_ultra). Build the principal from THAT fact, never from
    the request body — a forged role/authority in JSON can never grant anything (§4/§6)."""
    return Principal(id="kai-owner", role="owner", scopes=set())


def _env() -> str:
    try:
        from app.config import settings
        return str(getattr(settings, "APP_ENV", "") or "production")
    except Exception:
        return "production"


def _exec_enabled() -> bool:
    try:
        from app.config import settings
        return bool(getattr(settings, "KAI_CAPABILITY_EXECUTION_ENABLED", False))
    except Exception:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HoldingCommandBody(BaseModel):
    """§90 envelope. The client submits ONLY these descriptive fields. Authoritative fields
    (role/authority/scopes/approved/environment) are NOT modeled and are ignored — the server derives
    principal/environment itself (extra='ignore' drops anything else)."""
    model_config = {"extra": "ignore"}
    command: str = ""
    context: dict = Field(default_factory=dict)
    selected_company: str = ""
    selected_mission: str = ""
    interaction_mode: str = "text"           # text | voice | palette — descriptive only, never authority
    client_capabilities: list = Field(default_factory=list)


def _context(body: HoldingCommandBody) -> CommandContext:
    conv = ""
    if isinstance(body.context, dict):
        conv = str(body.context.get("conversation_id", ""))
    return CommandContext(conversation_id=conv, selected_company=body.selected_company,
                          selected_mission=body.selected_mission)


def _knowledge() -> SystemKnowledgeIndex:
    return SystemKnowledgeIndex(today=_now()[:10])


def _brain_readonly_step(plan):
    """Return (needs_approval, first_selected_id). A step whose policy is REQUIRE_APPROVAL means the
    Brain routed a non-read capability — surface it as approval, never auto-run."""
    needs = any(s.needs_approval for s in plan.steps)
    sel = next((s.cap_id for s in plan.steps if not s.is_dependency), None)
    return needs, sel


@router.post("/command")
def holding_command(body: HoldingCommandBody):
    """§90 typed governed command. Server derives the owner principal; the command STRING is classified
    (never exec'd). Consequential → 202 REQUIRE_APPROVAL. Read → knowledge index. Capability → Brain
    (executes read-only only when brake #1 is on, else PREPARE_ONLY)."""
    corr = _uuid.uuid4().hex
    env = _env()
    res = resolve(body.command, _context(body), environment=env)
    base = {"correlation_id": corr, "environment": env, "timestamp": _now(),
            "intent": res.intent, "reference": res.reference, "injection_flags": res.injection_flags,
            "rationale": res.rationale}
    _audit_sink({"event": "holding.command.received", "intent": res.intent, "dispatch": res.dispatch,
                 "decision": res.decision, "action_class": res.action_class, "correlation_id": corr,
                 "mission_id": body.selected_mission})

    # §24 consequential → owner approval, HTTP 202, no execution
    if res.intent == Intent.CONSEQUENTIAL.value:
        return JSONResponse(status_code=202, content={**base, "status": "REQUIRE_APPROVAL",
                            "action_class": res.action_class, "approval": res.approval,
                            "mission_id": body.selected_mission, "provenance": "REAL"})

    # read/query → the read-only SystemKnowledgeIndex (cited evidence, honest UNKNOWN)
    if res.dispatch == Dispatch.KNOWLEDGE.value:
        ans = _knowledge().ask(body.command)
        return JSONResponse(status_code=200, content={**base, "status": ans.get("status"),
                            "answer": ans.get("answer"), "results": ans.get("results"),
                            "evidence_refs": ans.get("evidence_refs", []),
                            "freshness": ans.get("freshness"), "provenance": "REAL"})

    # capability-shaped → the Brain (read-only V1 only). Execution gated by brake #1.
    if res.dispatch == Dispatch.BRAIN.value:
        plan = _brain.plan(body.command, _owner())
        needs, sel = _brain_readonly_step(plan)
        payload = {**base, "selected": plan.selected_ids(), "plan_summary": plan.summary,
                   "rejected": plan.rejected}
        if needs:
            return JSONResponse(status_code=202, content={**payload, "status": "REQUIRE_APPROVAL",
                                "note": "Brain selected a capability needing approval — not auto-run."})
        if not _exec_enabled():
            return JSONResponse(status_code=200, content={**payload, "status": "PREPARE_ONLY",
                                "note": "capability execution disabled (KAI_CAPABILITY_EXECUTION_ENABLED off)."})
        out = plan_and_execute(_brain, _service, body.command, _owner(), {}, mission_id=body.selected_mission)
        er = out.get("result")
        if er is None:
            return JSONResponse(status_code=200, content={**payload, "status": "NO_EXECUTABLE_CAPABILITY",
                                "note": out.get("note")})
        d = er.to_dict()
        d["evidence"] = redact(d.get("evidence"))     # §29 defense-in-depth: never emit unredacted evidence
        return JSONResponse(status_code=_HTTP.get(er.status, 200),
                            content={**payload, "status": er.status, "selected_capability": out.get("selected"),
                                     "operation": out.get("operation"), "result": d, "provenance": er.provenance})

    # unknown → honest refusal, no execution
    return JSONResponse(status_code=200, content={**base, "status": "UNKNOWN",
                        "answer": "I can't route that to an authorized holding intent (read / capability / "
                                  "consequential). Nothing ran.", "provenance": "REAL"})


@router.get("/voice/capabilities")
def holding_voice_capabilities():
    """§6/§7 honest voice capability truth for the presence layer (Phase 7b). Read-only; nothing listens.
    Reports the REAL KAI_VOICE_ENABLED flag, the PUSH_TO_TALK default, wake-word UNAVAILABLE (no on-device
    engine; cloud continuous audio is forbidden), BROWSER_LIMITED transcription, and that the voice channel
    can NEVER authorize (§75). The frontend renders DISABLED-WITH-REASON from this — never a fake-working mic."""
    from app.services.holding.voice_session import VoiceSessionManager
    caps = VoiceSessionManager(environment=_env()).capabilities()
    caps.update({"approval_by_voice": "REFUSED", "audio_persisted": False,
                 "contract": "FINAL transcript TEXT → POST /admin/holding/command[/stream] (interaction_mode=voice)",
                 "timestamp": _now(), "provenance": "REAL"})
    return JSONResponse(status_code=200, content=caps, headers={"Cache-Control": "no-store"})


@router.get("/gesture/capabilities")
def holding_gesture_capabilities():
    """§8/§94 honest camera/gesture capability truth for the presence layer (Phase 8). Read-only; nothing
    opens a camera. Reports the REAL KAI_CAMERA_ENABLED flag (camera OFF | AVAILABLE_SESSION — a per-session
    owner enable is still required and never persisted), indicator REQUIRED, inference LOCAL_ONLY, the
    recognizer seam RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED (no certified local model in this repo), and that a
    gesture can NEVER authorize (§75). The frontend renders DISABLED-WITH-REASON from this."""
    from app.config import settings
    from app.services.holding.gesture_policy import GestureSessionPolicy
    caps = GestureSessionPolicy.capabilities(settings)
    caps.update({"timestamp": _now(), "provenance": "REAL"})
    return JSONResponse(status_code=200, content=caps, headers={"Cache-Control": "no-store"})


class ConfirmBody(BaseModel):
    """§24 approval-turn envelope. Descriptive only — the server derives the owner principal + channel;
    a forged role/authority is not modeled and is ignored (extra='ignore')."""
    model_config = {"extra": "ignore"}
    pending_action_id: str = ""
    reply: str = ""                          # the owner's natural confirming/declining words
    interaction_mode: str = "text"           # text | voice | gesture — voice/gesture carry NO authority (§75)


@router.post("/command/confirm")
def holding_command_confirm(body: ConfirmBody):
    """§24 durable approval turn. Interprets the owner's reply over the EXISTING approval model: only an
    explicit approve/reject verb BOUND to the pending action id acts; a casual "ok"/"do it" (or a
    voice/gesture confirmation, §75) fails CLOSED with no write. An approval resolves to a DURABLE
    proposals_store record, never a chat string. Execution stays separately gated (§24)."""
    corr = _uuid.uuid4().hex
    ch = "voice" if body.interaction_mode == "voice" else ("gesture" if body.interaction_mode == "gesture" else "text")
    owner = _owner().id
    out = approve_action(body.pending_action_id, principal=owner, utterance=body.reply, channel=ch)
    dec = out.get("decision", {})
    base = {"correlation_id": corr, "environment": _env(), "timestamp": _now(),
            "decision": dec, "provenance": "REAL"}
    _audit_sink({"event": "holding.command.confirm", "decision": dec.get("status"),
                 "correlation_id": corr, "mission_id": body.pending_action_id})
    if out["authorized"]:
        return JSONResponse(status_code=200, content={**base, "status": "APPROVED", "record": out["record"]})
    if dec.get("status") == ConfirmationStatus.REJECTED.value:
        rj = reject_action(body.pending_action_id, principal=owner, utterance=body.reply, channel=ch)
        if rj.get("rejected"):
            return JSONResponse(status_code=200, content={**base, "status": "REJECTED", "record": rj["record"]})
        # the durable rejection did NOT occur (already-decided / not open) — report truthfully, never fake success
        return JSONResponse(status_code=202, content={**base, "status": "REJECT_NOT_APPLIED",
                                                      "reason": rj.get("reason", "no durable rejection write")})
    # fail closed: no durable write; ask for an explicit, bound confirmation
    return JSONResponse(status_code=202, content={**base, "status": "REQUIRE_CONFIRMATION",
                                                  "reason": out["reason"]})


@router.post("/command/stream")
def holding_command_stream(request: Request, body: HoldingCommandBody):
    """§91 governed SSE for a command turn. Reuses the hardened _sse_async (real cancellation, cookie
    auth, no tokens in URLs). Emits the §91 taxonomy; NEVER streams CoT / secrets / raw capability
    output (evidence is redacted, command text injection-scanned). Consequential events carry
    correlation_id/mission_id/environment/timestamp/provenance."""
    retry_after = _check_rate(request)
    if retry_after is not None:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="rate_limited", headers={"Retry-After": str(retry_after)})
    corr = request.headers.get("x-correlation-id") or _uuid.uuid4().hex
    env = _env()
    mission_id = body.selected_mission

    def ev(kind: str, **fields) -> dict:
        return {"type": kind, "correlation_id": corr, "environment": env, "timestamp": _now(), **fields}

    def _events():
        try:
            yield ev(EV_PRESENCE, state="THINKING")
            # §54/§8 classify (never exec) + §76 injection scan (markers are inert data)
            res = resolve(body.command, _context(body), environment=env)
            if body.interaction_mode == "voice":
                yield ev(EV_TRANSCRIPT_FINAL, text=redact(body.command)[:400])
            yield ev(EV_COMMAND_ACCEPTED, command=redact(body.command)[:400],
                     injection_flags=res.injection_flags, intent=res.intent)
            yield ev(EV_CONTEXT_RESOLVED, reference=res.reference,
                     selected_company=body.selected_company, selected_mission=mission_id)
            if mission_id:
                yield ev(EV_MISSION_LINKED, mission_id=mission_id, provenance="REAL")

            if res.intent == Intent.CONSEQUENTIAL.value:
                yield ev(EV_APPROVAL_REQUIRED, mission_id=mission_id, provenance="REAL",
                         action_class=res.action_class, approval=res.approval)
                yield {"type": "done", "correlation_id": corr, "status": "REQUIRE_APPROVAL"}
                return

            if res.dispatch == Dispatch.KNOWLEDGE.value:
                ans = _knowledge().ask(body.command)
                yield ev(EV_ACTION_RESULT, provenance="REAL", status=ans.get("status"),
                         answer=ans.get("answer"), evidence_refs=ans.get("evidence_refs", []),
                         freshness=ans.get("freshness"))
                yield ev(EV_ACTION_COMPLETE, status=ans.get("status"))
                yield {"type": "done", "correlation_id": corr, "status": ans.get("status")}
                return

            if res.dispatch == Dispatch.BRAIN.value:
                plan = _brain.plan(body.command, _owner())
                needs, _sel = _brain_readonly_step(plan)
                yield ev(EV_CAPABILITY_SELECTED, selected=plan.selected_ids(),
                         rationale=plan.summary)          # observable rationale, not hidden CoT
                if needs:
                    yield ev(EV_APPROVAL_REQUIRED, mission_id=mission_id, provenance="REAL",
                             note="selected capability needs approval — not auto-run")
                    yield {"type": "done", "correlation_id": corr, "status": "REQUIRE_APPROVAL"}
                    return
                if not _exec_enabled():
                    yield ev(EV_ACTION_RESULT, provenance="REAL", status="PREPARE_ONLY",
                             note="capability execution disabled (brake #1 off)")
                    yield {"type": "done", "correlation_id": corr, "status": "PREPARE_ONLY"}
                    return
                out = plan_and_execute(_brain, _service, body.command, _owner(), {}, mission_id=mission_id)
                er = out.get("result")
                if er is None:
                    yield ev(EV_ACTION_RESULT, provenance="REAL", status="NO_EXECUTABLE_CAPABILITY",
                             note=out.get("note"))
                    yield {"type": "done", "correlation_id": corr, "status": "NO_EXECUTABLE_CAPABILITY"}
                    return
                yield ev(EV_ACTION_RESULT, provenance=er.provenance, status=er.status,
                         selected_capability=out.get("selected"), operation=out.get("operation"),
                         evidence=redact(er.evidence), injection_flags=er.injection_flags)  # §29 redacted
                yield ev(EV_ACTION_COMPLETE, status=er.status)
                yield {"type": "done", "correlation_id": corr, "status": er.status}
                return

            yield ev(EV_ACTION_RESULT, provenance="REAL", status="UNKNOWN",
                     answer="Not an authorized holding intent — nothing ran.")
            yield {"type": "done", "correlation_id": corr, "status": "UNKNOWN"}
        except (GeneratorExit, asyncio.CancelledError):
            raise
        except Exception:
            logger.exception("holding command stream failed (corr=%s)", corr)
            # after headers are sent we can't change the HTTP status — one safe event, never a traceback
            yield ev(EV_SYSTEM_DEGRADED, error="internal_error")

    return StreamingResponse(
        _sse_async(request, _events()), media_type="text/event-stream",
        headers={"X-Correlation-Id": corr, "Cache-Control": "no-cache",
                 "X-Accel-Buffering": "no", "Connection": "keep-alive"})
