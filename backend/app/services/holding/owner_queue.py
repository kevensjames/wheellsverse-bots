"""Owner-queue reconciliation (§1-3) — feeds the EXISTING proposals_store, never a second queue.

Turns the reconciled plan's OWNER-required work into prepared OwnerActions (the irreducible human
action, with everything KAI could do already done — §2), upserts them into proposals_store deduped by
a stable source_key (§1), and auto-resolves owner items whose underlying blocker disappeared (§3).
Pure logic (prepare + reconcile) is DB-free and testable; apply_owner_queue is the thin DB bridge.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from app.services.holding.plan import Assignee, AutonomyClass
from app.services.holding.autonomous_work import OWNER_QUEUED

# §5 ranking ladder (lower = surfaced first).
_PRIORITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}

# §F2 — terminal owner-decision states the cycle writer must NEVER transition into OR out of. Kept here
# (DB-free) so the security-critical decision is testable without a database.
_TERMINAL_STATES = frozenset({"approved", "rejected", "executed", "superseded"})


def owner_upsert_disposition(existing_status: str | None) -> str:
    """PURE writer-only decision (§F2): given the newest row's status for a source_key (None = no row),
    return 'insert' | 'update' | 'skip_terminal'. NEVER a status change — absent → create PROPOSED;
    still-open PROPOSED → update safe fields; any terminal → hands off (never reopen an owner decision)."""
    if existing_status is None:
        return "insert"
    if existing_status == "proposed":
        return "update"
    return "skip_terminal"


@dataclass
class OwnerAction:
    company_id: str
    source_key: str                      # stable dedup key (§1: one item per requirement)
    priority: int
    title: str
    reason: str
    kai_completed: str                   # what KAI already did before queuing (§2)
    exact_owner_action: str              # the irreducible human step (§2 — never generic)
    surface: str = "UNAVAILABLE"
    estimated_time: str = "UNAVAILABLE"
    deadline: str = "UNAVAILABLE"
    risk_if_delayed: str = "UNAVAILABLE"
    next_after_owner: str = "UNAVAILABLE"
    evidence: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


# task_types / goals that are too generic to ever queue (§2 — no "review startup"/"work on marketing")
_GENERIC = {"review startup", "work on marketing", "fix deployment", "improve marketing"}


def _severity_name(priority: int) -> str:
    for name, rank in _PRIORITY_ORDER.items():
        if rank == priority:
            return name
    return "MEDIUM"


def prepare_owner_actions(reconciled_tasks: list, work_results: list, *, now: str = "") -> list[OwnerAction]:
    """Build prepared OwnerActions from OWNER-assigned reconciled tasks + OWNER_QUEUED work results.
    Deduped by source_key. Rejects generic titles (§2). ``reconciled_tasks`` are ReconciledTask;
    ``work_results`` are WorkResult. A task is owner-bound if assigned OWNER / autonomy≥A3, or its
    work outcome was OWNER_QUEUED."""
    owner_outcomes = {r.task_id for r in (work_results or []) if r.outcome == OWNER_QUEUED}
    out: dict[str, OwnerAction] = {}
    for rt in reconciled_tasks or []:
        t = getattr(rt, "task", rt)
        is_owner = (t.assigned_to == Assignee.OWNER.value
                    or AutonomyClass(t.autonomy) >= AutonomyClass.A3_EXTERNAL_HIGH_IMPACT
                    or t.task_id in owner_outcomes)
        if not is_owner:
            continue
        if (t.goal or "").strip().lower() in _GENERIC:
            continue                                       # §2: never queue vague work
        key = t.source_key or t.task_id
        if key in out:
            continue                                       # §1: one queue item per requirement
        # §2 preparation: surface what KAI already established from the task's evidence.
        ev = list(t.evidence or [])
        kai_done = ("Detected + surfaced this and completed all permitted read-only investigation; "
                    f"attached {len(ev)} evidence item(s)." if ev
                    else "Detected + surfaced this; no autonomous preparation was permitted.")
        out[key] = OwnerAction(
            company_id=t.company_id, source_key=key, priority=int(t.priority),
            title=t.goal, reason=t.reason, kai_completed=kai_done,
            exact_owner_action=t.expected_outcome or t.goal,
            next_after_owner="KAI resumes the plan for this company once you act.",
            evidence=ev)
    return list(out.values())


def to_proposals(actions: list[OwnerAction]) -> list[dict]:
    """Map OwnerActions to proposals_store.sync_open input (the existing owner queue schema)."""
    return [{"source_key": a.source_key, "severity": _severity_name(a.priority), "entity": a.company_id,
             "title": a.title,
             "action_class": "OWNER_REQUIRED", "proposed_action": a.exact_owner_action,
             "plan": a.next_after_owner, "risk": a.risk_if_delayed, "reversible": False,
             "impact": a.reason, "effort": a.estimated_time,
             # §2 preparation fields travel in the action JSON so the UI/brief can show them:
             "kai_completed": a.kai_completed, "surface": a.surface, "deadline": a.deadline,
             "evidence": a.evidence} for a in actions]


def reconcile_owner_queue(prior_open: list, actions: list[OwnerAction]) -> dict:
    """Pure reconciliation (§1/§3): given the currently-open proposals + the freshly-prepared owner
    actions, decide which to upsert and which stale open items to auto-resolve. Returns
    {upsert:[proposal dicts], resolve_absent:[source_keys still active]}. An existing unresolved
    requirement is UPDATEd (via sync_open dedup), never duplicated."""
    active_keys = [a.source_key for a in actions]
    prior_keys = {p.get("source_key") for p in (prior_open or []) if isinstance(p, dict)}
    return {
        "upsert": to_proposals(actions),
        "active_source_keys": active_keys,
        "would_resolve": sorted(k for k in prior_keys if k and k not in set(active_keys)),
    }


def apply_owner_queue(actions: list[OwnerAction]) -> dict:
    """DB bridge: upsert prepared actions into proposals_store (deduped) + auto-resolve vanished ones.
    Fails soft. Returns counts. NOTE: this couples the WRITE (visibility) with resolve_absent (auto-close)
    — it is intentionally NOT wired into the live cycle. The live cycle uses persist_owner_actions
    (writer-only) so KAI never auto-closes an owner decision. Kept for the closed-loop test."""
    from app.services.holding import proposals_store as ps
    inserted = ps.sync_open(to_proposals(actions))
    resolved = ps.resolve_absent([a.source_key for a in actions])
    return {"inserted": inserted, "resolved_stale": resolved, "active": len(actions)}


def persist_owner_actions(actions: list, *, writer=None, now: str | None = None) -> dict:
    """§F2 writer-ONLY owner-queue persistence: upsert prepared owner actions into the EXISTING
    proposals_store (create-if-absent, update-safe-fields-if-open, skip-if-terminal). Does NOT resolve,
    close, approve, reject, or supersede anything — visibility only; the human keeps the decision. The
    writer is injectable (tests pass a fake); default is proposals_store.upsert_owner_open. Returns the
    writer's result dict ({ok, inserted, updated, skipped_terminal})."""
    if writer is None:
        from app.services.holding import proposals_store as ps
        writer = ps.upsert_owner_open
    items = to_proposals(actions or [])
    if now is not None:
        for it in items:
            it["last_observed_at"] = now          # safe descriptive field: when KAI last saw the blocker
    return writer(items)


if __name__ == "__main__":
    from app.services.holding.test_owner_queue import run
    run()
