"""KAI CurrentAttentionModel (§17) — KAI's bounded, OBSERVABLE operational focus.

This is NOT hidden chain-of-thought and NOT an LLM "thinking" loop (§79). It is a normalized,
event-driven READ over already-authoritative live state — the same substrate the rest of the Holding
OS uses:

  • self_model.what_am_i_doing()              → operational posture (a real summary string)
  • digital_twin.portfolio_view().needs_attention → which companies are flagged (real, health-derived)
  • plan.py PlanTask(s)                       → what KAI is actually planned to work on (assignee/status/priority)
  • owner_queue / proposals_store             → what is awaiting an OWNER decision

Every field is REAL/DERIVED (traced to one of those sources) or honestly UNAVAILABLE — never invented.
Crucially, when there is nothing to focus on, the model reports an HONEST IDLE state; it never
fabricates a mission just to look busy (§0#16-19, §64 never fake presence). Emitted strings are
DETERMINISTIC TEMPLATES filled ONLY with real source values/counts (task goals/reasons, proposal
titles, company ids, worker/job ids, counts) — no invented facts, no reasoning tokens.

Sources are injectable (like self_model.py / digital_twin.py) so this is a plain ``python3`` self-test
with no DB. Each default source is wrapped fail-open: a subsystem that errors → empty, never a crash.
"""
from __future__ import annotations

from typing import Any, Callable

UNAVAILABLE = "UNAVAILABLE"

# Bounded observation cap (§79 — attention is a fixed-size read, never an unbounded scan).
_MAX_SECONDARY = 5

# Non-terminal plan statuses KAI can still be focused on (mirrors plan.TaskStatus values).
_ACTIVE_STATUSES = {"PROPOSED", "ACTIVE"}

_SEV_NAMES = ("CRITICAL", "HIGH", "MEDIUM", "INFO")           # priority int 0..3 → name
_SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}
_HORIZON_RANK = {"TODAY": 0, "7_DAY": 1, "30_DAY": 2, "90_DAY": 3}

# Source tokens (what each field traces to) — used in the `sources` map so "sourced" is mechanical.
SRC_PLAN = "holding.plan:PlanTask"
SRC_PLAN_BLOCKED = "holding.plan:PlanTask(status=BLOCKED)"
SRC_PORTFOLIO = "digital_twin.portfolio_view.needs_attention"
SRC_PROPOSALS = "holding.proposals_store"
SRC_WORKERS = "holding.status.list_workers"
SRC_POSTURE = "self_model.what_am_i_doing"


def _sev_name(priority: int) -> str:
    return _SEV_NAMES[priority] if 0 <= priority < len(_SEV_NAMES) else "MEDIUM"


def _field(t: Any, key: str, default: Any = None) -> Any:
    """Read a PlanTask field whether it's a dataclass instance or a plain dict."""
    if isinstance(t, dict):
        return t.get(key, default)
    return getattr(t, key, default)


def _norm_task(t: Any) -> dict:
    p = _field(t, "priority", 2)
    a = _field(t, "autonomy", 0)
    return {
        "task_id": _field(t, "task_id"),
        "company_id": _field(t, "company_id") or UNAVAILABLE,
        "goal": _field(t, "goal") or UNAVAILABLE,
        "reason": _field(t, "reason") or "",
        "status": (_field(t, "status") or "PROPOSED"),
        "assigned_to": (_field(t, "assigned_to") or "KAI"),
        "autonomy": int(a) if a is not None else 0,
        "priority": int(p) if p is not None else 2,
        "horizon": (_field(t, "horizon") or "TODAY"),
        "source_key": _field(t, "source_key"),
    }


# ── default live sources (fail-open, lazy imports so this file self-tests with no DB) ─────────────
def _plan_tasks() -> list:
    """No standalone 'current plan tasks' store exists — plans live transiently inside a cycle run.
    Default is an honest empty list; the cycle (or any caller holding live tasks) INJECTS them via
    ``sources={"plan_tasks": ...}``. Empty here is honest, not a fabricated 'no work' claim."""
    return []


def _portfolio() -> dict:
    from app.services.holding.digital_twin import HoldingDigitalTwin
    return HoldingDigitalTwin().portfolio_view()


def _owner_requests() -> list:
    from app.services.holding import proposals_store as ps
    return ps.list_proposals(status="proposed")


def _workers() -> list:
    from app.services.holding import status as hstat
    return hstat.list_workers()


def _posture() -> str:
    from app.services.holding.self_model import OperationalSelfModel
    return OperationalSelfModel().what_am_i_doing()


_DEFAULT_SOURCES: dict[str, Callable[[], Any]] = {
    "plan_tasks": _plan_tasks, "portfolio": _portfolio, "owner_requests": _owner_requests,
    "workers": _workers, "posture": _posture,
}


class CurrentAttentionModel:
    """Assemble KAI's bounded operational focus from live state. One read, no loop (§79)."""

    def __init__(self, *, sources: dict[str, Callable[[], Any]] | None = None):
        self._src = {**_DEFAULT_SOURCES, **(sources or {})}

    def _get(self, name: str, default: Any) -> Any:
        fn = self._src.get(name)
        if fn is None:
            return default
        try:
            v = fn()
            return v if v is not None else default
        except Exception:      # noqa: BLE001 — a failing subsystem is honestly empty, never a guess
            return default

    def snapshot(self) -> dict:
        tasks = [_norm_task(t) for t in (self._get("plan_tasks", []) or [])]
        portfolio = self._get("portfolio", {}) or {}
        needs_attention = list(portfolio.get("needs_attention", []) if isinstance(portfolio, dict) else [])
        proposals = [p for p in (self._get("owner_requests", []) or []) if isinstance(p, dict)]
        workers = [w for w in (self._get("workers", []) or []) if isinstance(w, dict)]

        # active KAI-assigned work, most important first (severity, then nearest horizon)
        active = sorted(
            (t for t in tasks if t["assigned_to"] == "KAI" and t["status"] in _ACTIVE_STATUSES),
            key=lambda t: (t["priority"], _HORIZON_RANK.get(t["horizon"], 9)))
        primary = active[0] if active else None

        # any BLOCKED plan task is a concrete blocker (prefer one on the current company)
        blocked = [t for t in tasks if t["status"] == "BLOCKED"]

        # open owner decisions, most severe first (proposals arrive newest-first, kept stable within a sev)
        proposals = sorted(proposals, key=lambda p: _SEV_RANK.get((p.get("severity") or "MEDIUM"), 2))

        # worker jobs actually running right now (online AND holding a job id) — REAL from heartbeat table
        active_jobs = [{"worker_id": w.get("worker_id"), "job_id": w.get("current_job")}
                       for w in workers if w.get("online") and w.get("current_job") is not None]

        srcmap: dict[str, str] = {}

        # ── current_company ───────────────────────────────────────────────────────────────────
        if primary:
            current_company = primary["company_id"]
            srcmap["current_company"] = SRC_PLAN
        elif needs_attention:
            current_company = needs_attention[0]
            srcmap["current_company"] = SRC_PORTFOLIO
        else:
            current_company = UNAVAILABLE
            srcmap["current_company"] = UNAVAILABLE

        # ── current_blocker (BLOCKED plan task; prefer the current company) ─────────────────────
        blk = next((t for t in blocked if t["company_id"] == current_company), None) or (blocked[0] if blocked else None)
        if blk:
            current_blocker = f"{blk['goal']}: {blk['reason']}".strip(": ")
            srcmap["current_blocker"] = SRC_PLAN_BLOCKED
        else:
            current_blocker = UNAVAILABLE
            srcmap["current_blocker"] = UNAVAILABLE

        # ── current_owner_request (top open proposal) ───────────────────────────────────────────
        if proposals:
            top = proposals[0]
            current_owner_request = {
                "proposal_id": top.get("id"), "title": top.get("title") or UNAVAILABLE,
                "company": top.get("entity") or UNAVAILABLE, "severity": top.get("severity") or UNAVAILABLE,
                "source_key": top.get("source_key"),
            }
            srcmap["current_owner_request"] = SRC_PROPOSALS
        else:
            current_owner_request = UNAVAILABLE
            srcmap["current_owner_request"] = UNAVAILABLE

        # ── primary_mission + priority_reason ───────────────────────────────────────────────────
        if primary:
            primary_mission = primary["goal"]                        # passthrough of a real task goal
            priority_reason = f"{_sev_name(primary['priority'])} · {primary['reason']}".strip(" ·")
            srcmap["primary_mission"] = SRC_PLAN
            srcmap["priority_reason"] = SRC_PLAN
        else:
            # NO active mission — never fabricate one. Report honest UNAVAILABLE; the priority_reason,
            # if anything, explains why we're merely MONITORING (portfolio flag), else UNAVAILABLE.
            primary_mission = UNAVAILABLE
            srcmap["primary_mission"] = UNAVAILABLE
            if needs_attention:
                priority_reason = f"Portfolio health flagged {current_company} as needing attention"
                srcmap["priority_reason"] = SRC_PORTFOLIO
            else:
                priority_reason = UNAVAILABLE
                srcmap["priority_reason"] = UNAVAILABLE

        # ── secondary_observations (bounded) ────────────────────────────────────────────────────
        secondary: list[dict] = []
        for c in needs_attention:
            if c != current_company and len(secondary) < _MAX_SECONDARY:
                secondary.append({"observation": f"{c} needs attention", "source": SRC_PORTFOLIO})
        for t in active[1:]:
            if len(secondary) < _MAX_SECONDARY:
                secondary.append({"observation": t["goal"], "source": SRC_PLAN})
        # label from the sources that ACTUALLY contributed (not a blanket portfolio+plan token)
        present = {o["source"] for o in secondary}
        srcmap["secondary_observations"] = (
            "+".join(s for s in (SRC_PORTFOLIO, SRC_PLAN) if s in present) if secondary else UNAVAILABLE)

        # ── worker jobs + pending approvals (real from their tables; 0/[] is honest, still sourced) ─
        srcmap["active_worker_jobs"] = SRC_WORKERS
        pending_approval = len(proposals)
        srcmap["pending_approval"] = SRC_PROPOSALS

        # ── focus_state + honest summary (composed only from real values/counts) ────────────────
        if primary:
            focus_state = "ACTIVE"
            # a real active task with a blank goal degrades gracefully — never "Working on: UNAVAILABLE"
            summary = (f"Working on {current_company} (task goal unavailable)."
                       if primary_mission == UNAVAILABLE
                       else f"Working on: {primary_mission} — {current_company}.")
        elif needs_attention or proposals or active_jobs:
            focus_state = "MONITORING"
            bits = []
            if needs_attention:
                bits.append(f"monitoring {len(needs_attention)} company/ies needing attention")
            if proposals:
                bits.append(f"{len(proposals)} awaiting your approval")
            if active_jobs:
                bits.append(f"{len(active_jobs)} worker job(s) running")
            summary = "No active mission — " + ", ".join(bits) + "."
        else:
            focus_state = "IDLE"
            summary = "No active focus — nothing requires attention and no work is queued."

        return {
            "focus_state": focus_state,               # ACTIVE / MONITORING / IDLE (idle is honest)
            "primary_mission": primary_mission,
            "secondary_observations": secondary,
            "current_company": current_company,
            "current_blocker": current_blocker,
            "current_owner_request": current_owner_request,
            "active_worker_jobs": active_jobs,
            "pending_approval": pending_approval,
            "priority_reason": priority_reason,
            "operational_posture": self._get("posture", UNAVAILABLE) or UNAVAILABLE,  # §17 substrate, sourced
            "summary": summary,
            "sources": srcmap,                        # every §17 field → real source token or UNAVAILABLE
            "hidden_reasoning_exposed": False,        # invariant asserted by the tests (§17/§87)
        }


if __name__ == "__main__":
    from app.services.holding.test_attention_model import run
    run()
