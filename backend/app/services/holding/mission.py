"""§27 Mission system + §28 flood control — a THIN persisted HEADER that WRAPS the existing work records.

A Mission is NOT a second work store. It is a durable identity + linkage row (mission_id, company,
objective, origin, priority, risk, authority_level, root_signature, timestamps) that LINKS to the
already-certified records the rest of the holding OS produces:

  • PlanTask(s)        (plan.py)            — the plan/steps, matched live by source_key/root_signature
  • proposals          (proposals_store)    — approvals + owner decisions, matched by source_key
  • worker_jobs        (worker_jobs)        — the worker plane, joined by the EXISTING mission_id column
  • CycleRecord        (holding_cycle)      — cycle context/timing
  • WorkResult(s)      (autonomous_work)    — in-cycle execution outcomes (carry the §22 `verified` flag)

Everything a mission "has" — plan, steps, capabilities, workers, status, evidence, artifacts, approvals,
verified_outcome — is DERIVED LIVE from those linked records (mission_view / derive_status). The header
copies NONE of it. This is CONSOLIDATION, not a parallel table: no PlanTask/worker_jobs are duplicated,
no new work store or daemon is introduced (§79 — bounded, pure functions over already-collected state).

§26 truth: a mission is COMPLETE only with REAL verified evidence. A worker "done" with code-only
evidence (a diff/branch and no verification signal) is NEVER COMPLETE — it derives to READY_FOR_REVIEW,
and mark_completed() refuses to stamp it. Status is DERIVED from the linked records' real state, never a
stored guess.

§28 one-active-mission-per-root-problem: dedup by root_signature (holding_problems.root_signature). If an
ACTIVE mission already exists for a root, a second is SUPPRESSED (no owner-queue flooding).

Pure/injectable core (derive_status / dedup_decision / mission_view) so it is a plain python3 self-test
(mirrors test_registry.py); the DB header uses the self-creating-table, fail-soft pattern of
proposals_store / cycle_store on App B's Postgres.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, asdict, fields as _dc_fields
from enum import Enum

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal


class MissionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    BLOCKED = "BLOCKED"
    VERIFYING = "VERIFYING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# A mission is "active" (blocks a duplicate for the same root, §28) unless it reached a terminal state.
TERMINAL = frozenset({MissionStatus.COMPLETE.value, MissionStatus.FAILED.value, MissionStatus.CANCELLED.value})

_OWNER_REQUIRED_AUTONOMY = 3               # AutonomyClass.A3_EXTERNAL_HIGH_IMPACT and above are owner-gated
_TASK_TERMINAL = ("COMPLETE", "SUPERSEDED", "REMOVED")
# §29 'writes': the first autonomy class that MUTATES — A2_REVERSIBLE_INTERNAL_WRITE maps to
# ActionClass.REVERSIBLE_WRITE; A0/A1 map to READ_ONLY (plan.py::_TO_ACTION_CLASS). So an effect is a
# real "write" only when its autonomy is A2+; A0/A1 read-only work (and the dark posture, autonomy off →
# 0 executions) produce NO writes → 'NONE'. No second policy — this reads the SAME autonomy ladder.
_WRITE_AUTONOMY_MIN = 2
# §29 KAI-WORKING-NOW = active (non-terminal) missions that are not merely PROPOSED (no scope yet).
_WORKING_STATUSES = (frozenset(s.value for s in MissionStatus) - TERMINAL - {MissionStatus.PROPOSED.value})


@dataclass
class MissionHeader:
    """THIN identity + linkage ONLY. Carries NO plan/steps/status/evidence/workers/artifacts — those are
    DERIVED live from the linked records by mission_view()."""
    mission_id: str
    company: str
    objective: str
    root_signature: str
    origin: str = "PROBLEM"                 # PROBLEM | OWNER | OPPORTUNITY | PROACTIVE | ...
    created_by: str = "kai"
    priority: str = "MEDIUM"
    risk: str = "UNKNOWN"
    authority_level: str = "A0_OBSERVE"     # AutonomyClass name — the real gate stays capability risk policy
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""
    cancelled: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _d(x) -> dict:
    return x.as_dict() if hasattr(x, "as_dict") else dict(x)


# ── §26 evidence truth — an explicit POSITIVE verification signal is required, never absence-of-negative ──
def _outcome_is_verified(evidence) -> bool:
    """A verified outcome is a non-empty dict carrying an EXPLICIT proof-of-verification signal. A code-only
    'done' (a branch/diff/files_changed with no verification) has none of these → NOT verified (§26).
    Fail-closed: anything ambiguous is unverified."""
    if not isinstance(evidence, dict) or not evidence:
        return False
    if evidence.get("verified") is True:
        return True
    if evidence.get("execution") == "COMPLETED":
        return True
    if evidence.get("tests_passed") is True or evidence.get("verified_outcome"):
        return True
    return False


def _job_verified(job: dict) -> bool:
    """A worker job is a verified completion only if it SUCCEEDED and posted verified evidence. A succeeded
    job with no evidence, or with code-only evidence, is NOT a verified completion (§22/§26)."""
    return job.get("status") == "succeeded" and _outcome_is_verified(job.get("evidence"))


# ── §27 status DERIVATION — pure function of the linked records' REAL state (never a stored guess) ────────
def derive_status(*, plan_tasks=None, proposals=None, worker_jobs=None, work_results=None,
                  cancelled: bool = False) -> str:
    """Derive a mission's lifecycle status from its linked records. Deterministic precedence: in-flight and
    owner-pending signals win over terminal ones (a queued retry keeps a mission WAITING, not FAILED), and
    COMPLETE fires ONLY on real verified evidence with no work outstanding (§26). Pure/bounded (§79)."""
    jobs = [_d(j) for j in (worker_jobs or [])]
    props = [_d(p) for p in (proposals or [])]
    tasks = [_d(t) for t in (plan_tasks or [])]
    wrs = [_d(w) for w in (work_results or [])]

    def _autonomy(t) -> int:
        try:
            return int(t.get("autonomy", 0))
        except (TypeError, ValueError):
            return 0

    any_running = any(j.get("status") in ("running", "claimed") for j in jobs)
    any_queued = any(j.get("status") == "queued" for j in jobs)
    job_succeeded = [j for j in jobs if j.get("status") == "succeeded"]
    job_failed = [j for j in jobs if j.get("status") in ("failed", "expired")]

    await_approval = (
        any(p.get("status") == "proposed" for p in props)                    # owner decision pending
        or any(w.get("outcome") == "OWNER_QUEUED" for w in wrs)
        or any((t.get("assigned_to") == "OWNER" or _autonomy(t) >= _OWNER_REQUIRED_AUTONOMY)
               and t.get("status") not in _TASK_TERMINAL for t in tasks)
    )
    ready_review = (
        any(w.get("outcome") == "A2_READY_FOR_REVIEW" for w in wrs)
        # a succeeded job with evidence but NOT verified = code-only 'done' → owner review, NEVER complete
        or any(j.get("status") == "succeeded" and j.get("evidence") and not _job_verified(j) for j in jobs)
    )
    verifying = any(j.get("status") == "succeeded" and not j.get("evidence") for j in jobs)  # done-claim, no proof
    blocked = (
        any(w.get("outcome") in ("BLOCKED_CAPABILITY", "BLOCKED_WORKER", "NEEDS_CERTIFICATION", "BLOCKED_POLICY")
            for w in wrs)
        or any(t.get("status") == "BLOCKED" and t.get("assigned_to") != "OWNER" for t in tasks)
    )
    has_verified = (
        any(_job_verified(j) for j in job_succeeded)
        or any(w.get("outcome") == "EXECUTED" and w.get("verified") is True for w in wrs)
        or any(p.get("status") == "executed" and _outcome_is_verified((p.get("action") or {}).get("evidence") or p.get("evidence"))
               for p in props)
    )
    plan_all_complete = all(t.get("status") in _TASK_TERMINAL for t in tasks)   # True when there are no tasks
    has_scope = bool(jobs or props or tasks or wrs)

    if cancelled:
        return MissionStatus.CANCELLED.value
    if any_running:
        return MissionStatus.ACTIVE.value
    if await_approval:
        return MissionStatus.WAITING_FOR_APPROVAL.value
    if any_queued:
        return MissionStatus.WAITING.value
    if ready_review:
        return MissionStatus.READY_FOR_REVIEW.value
    if verifying:
        return MissionStatus.VERIFYING.value
    if blocked:
        return MissionStatus.BLOCKED.value
    if has_verified and plan_all_complete:
        return MissionStatus.COMPLETE.value                    # §26 — only with real verified evidence
    if job_failed and not job_succeeded and not has_verified:
        return MissionStatus.FAILED.value
    if has_scope:
        return MissionStatus.PLANNING.value
    return MissionStatus.PROPOSED.value


# ── §28 flood control — PURE dedup decision (mirrors owner_queue's pure-decision + DB-mechanics split) ────
def dedup_decision(root_signature: str, existing, status_resolver) -> tuple[str, str | None]:
    """PURE: 'suppress' (a still-ACTIVE mission already owns this root, §28) or 'insert'. ``existing`` is
    the list of candidate mission header dicts; ``status_resolver(mission)->status`` derives each one's
    live status (never a stored guess). A cancelled/completed header is terminal (does not block)."""
    for m in existing or []:
        if m.get("root_signature") != root_signature:
            continue
        if m.get("cancelled") or m.get("completed_at"):
            continue                                            # durable terminal act — never blocks a new mission
        if status_resolver(m) not in TERMINAL:
            return ("suppress", m.get("mission_id"))
    return ("insert", None)


# ── DERIVED VIEW — assembles the full mission from the linked records; copies nothing ────────────────────
def _linked_evidence(jobs: list, props: list, wrs: list) -> list:
    ev = []
    for j in jobs:
        if _job_verified(j):
            ev.append({"source": "worker_job", "job_id": j.get("id"), "correlation_id": j.get("correlation_id"),
                       "verified": True, "evidence": j.get("evidence")})
    for w in wrs:
        # §26: match has_verified EXACTLY (any EXECUTED+verified work_result contributes evidence). A
        # missing correlation_id must NOT drop the evidence — else a mission could derive COMPLETE while
        # evidence is [] (the old inconsistency). correlation_id is surfaced when present, never required.
        if w.get("outcome") == "EXECUTED" and w.get("verified") is True:
            ev.append({"source": "work_result", "correlation_id": w.get("correlation_id"), "verified": True})
    for p in props:
        if p.get("status") == "executed":
            pe = (p.get("action") or {}).get("evidence") or p.get("evidence")
            if _outcome_is_verified(pe):
                ev.append({"source": "proposal", "proposal_id": p.get("id"), "verified": True, "evidence": pe})
    return ev


def _writes_from_records(jobs: list, props: list, wrs: list) -> list:
    """§29 'writes' — the REAL, evidenced mutations this mission produced. A write is an effect whose
    autonomy is A2+ (REVERSIBLE_WRITE and up) that actually took hold: an EXECUTED+verified work result,
    an executed proposal, or a verified worker job on an A2+ task. Read-only work (A0/A1 probes/inspections)
    and the current dark posture (autonomy off → 0 executions) yield an empty list → the view renders
    'NONE'. Fail-closed toward NONE: an effect of unknown autonomy is NOT counted as a write (never
    fabricated). A2-prepared isolated changes are surfaced distinctly (owner reviews/merges — NOT live)."""
    out = []
    for w in wrs:
        try:
            au = int(w.get("autonomy") or 0)
        except (TypeError, ValueError):
            au = 0
        if w.get("outcome") == "EXECUTED" and w.get("verified") is True and au >= _WRITE_AUTONOMY_MIN:
            out.append({"kind": "EXECUTED", "capability": w.get("capability_id"),
                        "operation": w.get("operation"), "correlation_id": w.get("correlation_id")})
        elif w.get("outcome") == "A2_READY_FOR_REVIEW":
            out.append({"kind": "PREPARED_ISOLATED", "capability": w.get("capability_id"),
                        "note": "isolated branch; owner reviews/merges (not a live write)"})
    for p in props:
        if p.get("status") == "executed":
            out.append({"kind": "EXECUTED_PROPOSAL", "proposal_id": p.get("id"), "title": p.get("title")})
    for j in jobs:
        try:
            au = int((j.get("task") or {}).get("autonomy") or 0)
        except (TypeError, ValueError):
            au = 0
        if _job_verified(j) and au >= _WRITE_AUTONOMY_MIN:
            out.append({"kind": "EXECUTED", "worker": j.get("worker"), "job_id": j.get("id"),
                        "correlation_id": j.get("correlation_id")})
    return out


def mission_view(header, *, plan_tasks=None, proposals=None, worker_jobs=None, work_results=None,
                 cycle_record=None) -> dict:
    """The read-only mission the dashboard renders (§27/§29). status/plan/steps/capabilities/workers/
    evidence/verified_outcome are ALL derived from the linked records — the header contributes only
    identity + linkage. Pure/injectable."""
    h = _d(header)
    jobs = [_d(j) for j in (worker_jobs or [])]
    props = [_d(p) for p in (proposals or [])]
    tasks = [_d(t) for t in (plan_tasks or [])]
    wrs = [_d(w) for w in (work_results or [])]
    cyc = _d(cycle_record) if cycle_record else {}

    status = derive_status(plan_tasks=tasks, proposals=props, worker_jobs=jobs, work_results=wrs,
                           cancelled=bool(h.get("cancelled")))

    # plan/steps: prefer real PlanTasks; else derive step stubs from linked proposals (title/status).
    if tasks:
        steps = [{"task_id": t.get("task_id"), "goal": t.get("goal"), "status": t.get("status"),
                  "assigned_to": t.get("assigned_to"), "autonomy": t.get("autonomy")} for t in tasks]
    else:
        steps = [{"task_id": f"proposal:{p.get('id')}", "goal": p.get("title"), "status": p.get("status"),
                  "assigned_to": "OWNER", "autonomy": None} for p in props]
    done = sum(1 for s in steps if s.get("status") in _TASK_TERMINAL or s.get("status") == "executed")
    next_step = next((s.get("goal") for s in steps
                      if s.get("status") not in _TASK_TERMINAL and s.get("status") != "executed"), None)

    caps = sorted({c for c in
                   [w.get("capability_id") for w in wrs if w.get("capability_id")]
                   + [(j.get("task") or {}).get("capability") for j in jobs]
                   if c})
    started = min([j.get("claimed_at") or j.get("created_at") for j in jobs
                   if (j.get("claimed_at") or j.get("created_at"))], default=None)
    evidence = _linked_evidence(jobs, props, wrs)
    # §29 action = what KAI is doing NOW: a live running worker's capability, else the next step, else the
    # objective. writes = the real evidenced mutations (empty when read-only / dark → the panel shows NONE).
    running_caps = [(j.get("task") or {}).get("capability") for j in jobs
                    if j.get("status") in ("running", "claimed")]
    running_caps = [c for c in running_caps if c]
    action = running_caps[0] if running_caps else (next_step or h.get("objective"))
    writes = _writes_from_records(jobs, props, wrs)

    # §26 fail-closed invariant: COMPLETE is only truthful if the evidence is surfaceable. has_verified
    # and _linked_evidence now use identical criteria, so this holds by construction — but if evidence
    # can't be surfaced it must NOT read COMPLETE. Downgrade to READY_FOR_REVIEW rather than emit a
    # COMPLETE with no evidence + a None verified_outcome (never lie about completion).
    if status == MissionStatus.COMPLETE.value and not evidence:
        status = MissionStatus.READY_FOR_REVIEW.value

    return {
        "mission_id": h.get("mission_id"), "company": h.get("company"), "objective": h.get("objective"),
        "origin": h.get("origin"), "created_by": h.get("created_by"), "priority": h.get("priority"),
        "risk": h.get("risk"), "authority_level": h.get("authority_level"),
        "root_signature": h.get("root_signature"),
        "created_at": h.get("created_at"), "updated_at": h.get("updated_at"),
        "completed_at": h.get("completed_at"), "cancelled": bool(h.get("cancelled")),
        # ── DERIVED (nothing below is stored on the header) ──
        "status": status,
        "started_at": started,
        "progress": f"{done}/{len(steps)}" if steps else "0/0",
        "next_step": next_step,
        "action": action,                       # §29 — what KAI is doing now (live worker cap / next step)
        "writes": writes,                       # §29 — real evidenced mutations ([] = read-only → 'NONE')
        "plan": steps,
        "steps": steps,
        "capabilities": caps,
        "workers": [{"worker": j.get("worker"), "status": j.get("status"), "claimed_by": j.get("claimed_by"),
                     "attempt": j.get("attempt"), "job_id": j.get("id")} for j in jobs],
        "proposals": [{"id": p.get("id"), "title": p.get("title"), "status": p.get("status")} for p in props],
        "approvals": [{"id": p.get("id"), "status": p.get("status"), "decided_at": p.get("decided_at")}
                      for p in props if p.get("status") in ("approved", "rejected", "executed")],
        "evidence": evidence,
        "artifacts": [j.get("correlation_id") for j in jobs if j.get("correlation_id")],
        # §26 — a verified_outcome is present ONLY when the mission genuinely derived to COMPLETE
        "verified_outcome": (evidence[0] if (status == MissionStatus.COMPLETE.value and evidence) else None),
        "cycle": {"cycle_id": cyc.get("cycle_id"), "completed_at": cyc.get("completed_at")} if cyc else {},
        "linked": {"plan_tasks": len(tasks), "proposals": len(props), "worker_jobs": len(jobs),
                   "work_results": len(wrs)},
    }


# ── §29 KAI WORKING NOW — enriched per-active-mission rows (truthful, live, no fabricated progress) ──────
def working_now(mission_views) -> list:
    """§29 'KAI WORKING NOW' — one row per ACTIVE (non-terminal, non-PROPOSED) mission, carrying the real
    per-mission fields DERIVED from its linked records via mission_view(): mission/company/action/
    capability/worker/started_at/progress/next_step/status/writes. ``writes`` is 'NONE' when the mission
    is read-only (the current dark posture executes 0 → no writes); otherwise the real list of evidenced
    mutations. Nothing is invented — every field comes straight from mission_view()'s live derivation, so
    an empty/read-only mission shows an honest 0/N progress and NONE writes. Pure/injectable."""
    rows = []
    for mv in mission_views or []:
        m = _d(mv)
        if m.get("status") not in _WORKING_STATUSES:
            continue                                  # terminal/proposed missions are not "working now"
        workers = [w.get("worker") for w in (m.get("workers") or []) if w.get("worker")]
        caps = m.get("capabilities") or []
        writes = m.get("writes") or []
        rows.append({
            "mission_id": m.get("mission_id"), "company": m.get("company"),
            "objective": m.get("objective"), "status": m.get("status"),
            "action": m.get("action"),
            "capability": caps[0] if caps else None, "capabilities": caps,
            "worker": workers[0] if workers else None, "workers": workers,
            "started_at": m.get("started_at"), "progress": m.get("progress"),
            "next_step": m.get("next_step"),
            "writes": writes if writes else "NONE",   # §29 — NONE when read-only (never fabricated)
        })
    return rows


# ── durable header store (self-creating table, fail-soft — proposals_store / cycle_store pattern) ─────────
_DDL = """CREATE TABLE IF NOT EXISTS holding_missions (
    mission_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    company TEXT, objective TEXT, origin TEXT NOT NULL DEFAULT 'PROBLEM', created_by TEXT,
    priority TEXT, risk TEXT, authority_level TEXT NOT NULL DEFAULT 'A0_OBSERVE',
    root_signature TEXT NOT NULL DEFAULT '',
    cancelled BOOLEAN NOT NULL DEFAULT false
)"""
_IDX = "CREATE INDEX IF NOT EXISTS holding_missions_root ON holding_missions (root_signature)"
# §28 atomic backstop: at most ONE active (not cancelled, not completed) mission per root_signature.
# The pure dedup_decision is the primary gate; this partial unique index closes the concurrency race
# where two create_mission calls both pass dedup then both INSERT — the DB rejects the 2nd, and
# create_mission turns that conflict into a §28 suppression (never a crash).
_UNIQ = ("CREATE UNIQUE INDEX IF NOT EXISTS holding_missions_active_root ON holding_missions "
         "(root_signature) WHERE cancelled = false AND completed_at IS NULL")


def _ensure(db) -> None:
    db.execute(text(_DDL))
    for stmt in (_IDX, _UNIQ):
        try:
            db.execute(text(stmt))
        except Exception:
            pass


def _row_to_header(r) -> dict:
    return {"mission_id": r[0], "created_at": str(r[1]), "updated_at": str(r[2]),
            "completed_at": str(r[3]) if r[3] else "", "company": r[4], "objective": r[5],
            "origin": r[6], "created_by": r[7], "priority": r[8], "risk": r[9],
            "authority_level": r[10], "root_signature": r[11], "cancelled": bool(r[12])}


_SELECT = ("SELECT mission_id, created_at, updated_at, completed_at, company, objective, origin, "
           "created_by, priority, risk, authority_level, root_signature, cancelled FROM holding_missions")


def _rows_by_root(db, root_signature: str) -> list:
    rows = db.execute(text(_SELECT + " WHERE root_signature = :r ORDER BY created_at DESC"),
                      {"r": root_signature}).fetchall()
    return [_row_to_header(r) for r in rows]


def _linked_proposals(root_signature: str) -> list:
    if not root_signature:
        return []
    try:
        from app.services.holding.proposals_store import list_proposals
        return [p for p in list_proposals(limit=200) if p.get("source_key") == root_signature]
    except Exception:
        return []


def _default_status_resolver(m: dict) -> str:
    """Derive an existing mission's live status from its REAL linked records (worker_jobs by mission_id,
    proposals by source_key==root_signature). Plan tasks are not persisted, so activeness for dedup is
    derived from the durable worker-plane + owner-decision state. Fail-soft."""
    try:
        from app.services.holding import worker_jobs as wj
        jobs = wj.list_for_mission(m.get("mission_id", ""))
    except Exception:
        jobs = []
    return derive_status(worker_jobs=jobs, proposals=_linked_proposals(m.get("root_signature", "")),
                         cancelled=bool(m.get("cancelled")))


def create_mission(*, company: str, objective: str, root_signature: str, origin: str = "PROBLEM",
                   created_by: str = "kai", priority: str = "MEDIUM", risk: str = "UNKNOWN",
                   authority_level: str = "A0_OBSERVE", now: str = "", mission_id: str | None = None,
                   status_resolver=None) -> dict:
    """§27 create a THIN mission header + §28 flood control. If an ACTIVE mission already owns this
    root_signature, SUPPRESS (return {'suppressed': True, 'mission_id': <existing>}) and insert nothing.
    Header only — links to PlanTask/proposals/worker_jobs by root_signature + mission_id, copies nothing.
    Fails soft (returns error dict) if the DB is down. Never raises."""
    mid = mission_id or ("ms-" + uuid.uuid4().hex[:12])
    resolver = status_resolver or _default_status_resolver
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            existing = _rows_by_root(db, root_signature)
            decision, active = dedup_decision(root_signature, existing, resolver)
            if decision == "suppress":
                return {"suppressed": True, "mission_id": active, "root_signature": root_signature}
            try:
                db.execute(text(
                    "INSERT INTO holding_missions (mission_id, company, objective, origin, created_by, priority, "
                    "risk, authority_level, root_signature) VALUES (:m,:co,:ob,:og,:cb,:pr,:rk,:al,:rs) "
                    "ON CONFLICT (mission_id) DO NOTHING"),
                    {"m": mid, "co": company, "ob": objective, "og": origin, "cb": created_by, "pr": priority,
                     "rk": risk, "al": authority_level, "rs": root_signature})
                db.commit()
            except IntegrityError:
                # §28 atomic backstop fired: a concurrent insert already created the one active mission
                # for this root (the partial unique index rejected the duplicate). Suppress, don't crash —
                # return the active mission that won the race.
                db.rollback()
                won = next((r["mission_id"] for r in _rows_by_root(db, root_signature)
                            if not r.get("cancelled") and not r.get("completed_at")), None)
                return {"suppressed": True, "mission_id": won, "root_signature": root_signature}
            return {"suppressed": False, "mission_id": mid, "root_signature": root_signature}
        finally:
            db.close()
    except Exception:
        return {"suppressed": False, "mission_id": None, "error": "PERSIST_FAILED"}


def from_problem(problem, *, created_by: str = "kai", origin: str = "PROBLEM", now: str = "",
                 status_resolver=None) -> dict:
    """Create a mission from a §18 HoldingProblem (ties root_signature → the problem's, so §28 dedup and
    holding_problems.assigned_mission line up). Priority/risk carry the problem's severity."""
    p = _d(problem)
    return create_mission(
        company=p.get("company") or "holding",
        objective=p.get("observed_facts") or p.get("problem") or "investigate",
        root_signature=p.get("root_signature") or p.get("problem_id") or "",
        origin=origin, created_by=created_by, priority=p.get("severity", "MEDIUM"),
        risk=p.get("severity", "UNKNOWN"), now=now, status_resolver=status_resolver)


def get_mission(mission_id: str) -> dict | None:
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            r = db.execute(text(_SELECT + " WHERE mission_id = :m"), {"m": mission_id}).fetchone()
            return _row_to_header(r) if r else None
        finally:
            db.close()
    except Exception:
        return None


def list_missions(limit: int = 50) -> list:
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            rows = db.execute(text(_SELECT + " ORDER BY created_at DESC, mission_id DESC LIMIT :l"),
                              {"l": limit}).fetchall()
            return [_row_to_header(r) for r in rows]
        finally:
            db.close()
    except Exception:
        return []


def cancel_mission(mission_id: str, *, by: str = "owner") -> bool:
    """Durable operator cancellation (the one status act with no linked-record source). Never raises."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            r = db.execute(text("UPDATE holding_missions SET cancelled = true, updated_at = now() "
                                "WHERE mission_id = :m AND cancelled = false RETURNING mission_id"),
                           {"m": mission_id}).fetchone()
            db.commit()
            return bool(r)
        finally:
            db.close()
    except Exception:
        return False


def mark_completed(mission_id: str, verified_outcome: dict, *, now: str = "") -> bool:
    """§26 write-boundary guard: stamp completed_at ONLY with a REAL verified outcome — a code-only/empty
    'done' is refused. The LIVE status stays DERIVED from linked records; this is an audit stamp, not the
    source of truth. Never raises."""
    if not _outcome_is_verified(verified_outcome):
        return False
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            r = db.execute(text("UPDATE holding_missions SET completed_at = now(), updated_at = now() "
                                "WHERE mission_id = :m AND completed_at IS NULL RETURNING mission_id"),
                           {"m": mission_id}).fetchone()
            db.commit()
            return bool(r)
        finally:
            db.close()
    except Exception:
        return False


# header field set — used by the test to prove the header carries ONLY identity+linkage (no work data)
HEADER_FIELDS = frozenset(f.name for f in _dc_fields(MissionHeader))


if __name__ == "__main__":
    from app.services.holding.test_mission import run
    raise SystemExit(0 if run() else 1)
