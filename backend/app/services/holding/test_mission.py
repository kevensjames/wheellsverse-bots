"""No-fabrication guard for §27 Mission system + §28 flood control. Run (from backend/):
    DATABASE_URL=... python3 -m app.services.holding.test_mission

Mirrors test_registry.py: a flat ck() ledger. Proves the mission HEADER wraps (never duplicates) the
existing PlanTask/proposals/worker_jobs records, that status is DERIVED from their real state (not a
stored guess), that COMPLETE requires real verified evidence (§26 — a code-only 'done' does NOT count),
and that a 2nd mission for a root with an active mission is suppressed (§28). Pure core is DB-free; a
guarded Postgres smoke exercises the durable header + dedup end-to-end when a DB is reachable.
"""
import uuid

from app.services.holding import mission
from app.services.holding.mission import (MissionHeader, MissionStatus, TERMINAL,
                                          derive_status, dedup_decision, mission_view)

res = []
def ck(n, ok): res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


# shared record fixtures (shapes match the real stores' dict outputs) ─────────────────────────────────────
CODE_ONLY = {"status": "succeeded", "worker": "coding",
             "evidence": {"branch": "kai/x", "diff": "--- a", "files_changed": ["a.py"]}}   # no verification
VERIFIED = {"status": "succeeded", "worker": "coding", "correlation_id": "corr-1",
            "evidence": {"execution": "COMPLETED", "tests_passed": True, "result": "ok"}}


def _db_up() -> bool:
    try:
        from sqlalchemy import text as _t
        from app.database import SessionLocal
        db = SessionLocal(); db.execute(_t("select 1")); db.close(); return True
    except Exception:
        return False


def run() -> bool:
    # ── §27 status DERIVED from linked records, never a stored guess ────────────────────────────────────
    ck("running worker job -> ACTIVE", derive_status(worker_jobs=[{"status": "running"}]) == "ACTIVE")
    ck("open proposal (owner decision pending) -> WAITING_FOR_APPROVAL",
       derive_status(proposals=[{"status": "proposed"}]) == "WAITING_FOR_APPROVAL")
    ck("owner-required plan task -> WAITING_FOR_APPROVAL",
       derive_status(plan_tasks=[{"status": "BLOCKED", "assigned_to": "OWNER", "autonomy": 3}]) == "WAITING_FOR_APPROVAL")
    ck("queued job (awaiting a worker) -> WAITING", derive_status(worker_jobs=[{"status": "queued"}]) == "WAITING")
    ck("blocked work result -> BLOCKED", derive_status(work_results=[{"outcome": "BLOCKED_CAPABILITY"}]) == "BLOCKED")
    ck("succeeded job with NO evidence (done-claim, no proof) -> VERIFYING",
       derive_status(worker_jobs=[{"status": "succeeded"}]) == "VERIFYING")
    ck("all-terminal failed/expired jobs, no success -> FAILED",
       derive_status(worker_jobs=[{"status": "failed"}, {"status": "expired"}]) == "FAILED")
    ck("scoped plan, nothing in flight -> PLANNING",
       derive_status(plan_tasks=[{"status": "PROPOSED", "assigned_to": "KAI", "autonomy": 0}]) == "PLANNING")
    ck("no linked records -> PROPOSED", derive_status() == "PROPOSED")
    ck("cancelled -> CANCELLED", derive_status(cancelled=True) == "CANCELLED")

    # status is a pure function of the linked records — the header identity contributes nothing to it
    s_active = derive_status(worker_jobs=[{"status": "running"}])
    s_wait = derive_status(proposals=[{"status": "proposed"}])
    ck("status is DERIVED from records, not stored (same header, different records -> different status)",
       s_active == "ACTIVE" and s_wait == "WAITING_FOR_APPROVAL" and s_active != s_wait)

    # ── §26 COMPLETE requires REAL verified evidence — a code-only 'done' is NEVER COMPLETE ──────────────
    ck("code-only 'done' (diff/branch, no verification) is NOT COMPLETE -> READY_FOR_REVIEW (§26)",
       derive_status(worker_jobs=[CODE_ONLY]) == "READY_FOR_REVIEW")
    ck("verified evidence + no open steps -> COMPLETE (§26)",
       derive_status(worker_jobs=[VERIFIED]) == "COMPLETE")
    ck("verified job but a plan step still open -> NOT COMPLETE (more work) ",
       derive_status(worker_jobs=[VERIFIED],
                     plan_tasks=[{"status": "PROPOSED", "assigned_to": "KAI", "autonomy": 0}]) != "COMPLETE")
    ck("mark_completed() refuses a code-only outcome at the write boundary (§26)",
       mission.mark_completed("no-such", {"branch": "x", "diff": "y"}) is False)

    # ── §28 flood control — one active mission per root_signature ────────────────────────────────────────
    existing = [{"mission_id": "m1", "root_signature": "R", "cancelled": False, "completed_at": ""}]
    ck("2nd mission for a root with an ACTIVE mission is SUPPRESSED (§28)",
       dedup_decision("R", existing, lambda m: "ACTIVE") == ("suppress", "m1"))
    ck("a TERMINAL existing mission does NOT block a new one",
       dedup_decision("R", existing, lambda m: "COMPLETE") == ("insert", None))
    ck("a CANCELLED existing mission does NOT block a new one",
       dedup_decision("R", [{**existing[0], "cancelled": True}], lambda m: "ACTIVE") == ("insert", None))
    ck("a different root is never blocked", dedup_decision("OTHER", existing, lambda m: "ACTIVE") == ("insert", None))
    ck("TERMINAL set is exactly the three end states",
       TERMINAL == {"COMPLETE", "FAILED", "CANCELLED"})

    # ── header WRAPS (does not duplicate) — identity+linkage only; work data is DERIVED in the view ──────
    work_cols = {"status", "plan", "steps", "evidence", "workers", "artifacts", "verified_outcome",
                 "capabilities", "approvals", "progress", "next_step", "proposals"}
    ck("header carries ONLY identity+linkage (no PlanTask/worker_jobs/status/evidence columns)",
       not (mission.HEADER_FIELDS & work_cols) and "root_signature" in mission.HEADER_FIELDS)
    from app.services.holding import worker_jobs as wj
    ck("mission links worker_jobs via the EXISTING mission_id column (no copy) — list_for_mission reader present",
       hasattr(wj, "list_for_mission") and "mission_id" in wj._DDL)

    hdr = MissionHeader(mission_id="m2", company="kai", objective="fix deploy", root_signature="R2")
    v = mission_view(hdr, worker_jobs=[VERIFIED, {"status": "queued", "worker": "coding",
                                                  "task": {"capability": "deploy"}}],
                     proposals=[{"id": 9, "status": "proposed", "title": "approve deploy"}])
    ck("view DERIVES workers from the linked jobs (not stored on the header)", len(v["workers"]) == 2)
    ck("view DERIVES status from linked records (queued + open proposal -> WAITING_FOR_APPROVAL)",
       v["status"] == "WAITING_FOR_APPROVAL")
    ck("view DERIVES capabilities from the linked job tasks", "deploy" in v["capabilities"])
    ck("view reflects the header identity verbatim", v["mission_id"] == "m2" and v["root_signature"] == "R2")

    vc = mission_view(MissionHeader(mission_id="m3", company="kai", objective="x", root_signature="R3"),
                      worker_jobs=[VERIFIED])
    ck("a COMPLETE mission exposes a real verified_outcome (§26)",
       vc["status"] == "COMPLETE" and vc["verified_outcome"] and vc["verified_outcome"]["verified"] is True)
    vr = mission_view(MissionHeader(mission_id="m4", company="kai", objective="x", root_signature="R4"),
                      worker_jobs=[CODE_ONLY])
    ck("a non-COMPLETE mission has NO verified_outcome (§26 — no evidence, no completion)",
       vr["status"] == "READY_FOR_REVIEW" and vr["verified_outcome"] is None)

    # ── §26 invariant: COMPLETE ⟺ non-empty evidence AND a verified_outcome (has_verified/_linked_evidence
    #    now use IDENTICAL criteria). Regression guard for the old inconsistency: an EXECUTED+verified
    #    work_result with NO correlation_id used to derive COMPLETE while evidence was [] / verified_outcome
    #    None. It must now contribute evidence. ──────────────────────────────────────────────────────────
    WR_NO_CORR = {"outcome": "EXECUTED", "verified": True}    # verified work result, correlation_id absent
    ck("verified work_result (no correlation_id) still derives COMPLETE",
       derive_status(work_results=[WR_NO_CORR]) == "COMPLETE")
    vwr = mission_view(MissionHeader(mission_id="m5", company="kai", objective="x", root_signature="R5"),
                       work_results=[WR_NO_CORR])
    ck("§26 a COMPLETE mission ALWAYS has non-empty evidence (old inconsistency gone)",
       vwr["status"] == "COMPLETE" and bool(vwr["evidence"]))
    ck("§26 a COMPLETE mission ALWAYS has a verified_outcome (never None while COMPLETE)",
       vwr["verified_outcome"] is not None)
    # the invariant holds for EVERY COMPLETE view we built — fail-closed: no COMPLETE without surfaced evidence
    for _mv in (vc, vwr):
        _done = _mv["status"] == "COMPLETE"
        ck(f"§26 invariant on {_mv['mission_id']}: COMPLETE ⟹ evidence AND verified_outcome",
           (not _done) or (bool(_mv["evidence"]) and _mv["verified_outcome"] is not None))

    # ── §29 KAI WORKING NOW — enriched per-mission fields, writes reflect reality (NONE when read-only) ──
    from app.services.holding.mission import working_now
    HDR29 = MissionHeader(mission_id="m29", company="sol", objective="Investigate incident on sol",
                          root_signature="R29")
    # read-only mission: an ACTIVE running probe (A0), one open owner proposal, no writes
    RO_JOB = {"status": "running", "worker": "kai", "task": {"capability": "holding.health", "autonomy": 0},
              "id": 51, "created_at": "2026-09-03T08:00:00"}
    v29 = mission_view(HDR29, worker_jobs=[RO_JOB],
                       plan_tasks=[{"task_id": "t1", "goal": "probe health", "status": "ACTIVE",
                                    "assigned_to": "KAI", "autonomy": 0}])
    ck("§29 mission_view exposes action + writes",
       "action" in v29 and "writes" in v29)
    ck("§29 action = live running worker capability (not the objective)",
       v29["action"] == "holding.health")
    ck("§29 a read-only (A0) mission has NO writes (writes=[] → panel shows NONE)", v29["writes"] == [])
    rows = working_now([v29])
    ck("§29 working_now surfaces the active mission with the full field set",
       len(rows) == 1 and set(("mission_id", "company", "action", "capability", "worker",
                               "started_at", "progress", "next_step", "writes")) <= set(rows[0]))
    ck("§29 working_now writes='NONE' when the mission is read-only (no fabrication)",
       rows[0]["writes"] == "NONE")
    ck("§29 working_now progress is live-derived (not fabricated) — 0/1 with one open step",
       rows[0]["progress"] == "0/1" and rows[0]["company"] == "sol")

    # a real A2 mutation (executed reversible write) DOES surface as a write — not NONE
    A2_WR = {"outcome": "EXECUTED", "verified": True, "autonomy": 2, "capability_id": "repo.reversible_write",
             "operation": "apply", "correlation_id": "corr-w1"}
    vw = mission_view(MissionHeader(mission_id="m30", company="kai", objective="apply fix", root_signature="R30"),
                      work_results=[A2_WR],
                      plan_tasks=[{"task_id": "t", "goal": "apply", "status": "ACTIVE",
                                   "assigned_to": "KAI", "autonomy": 2}])
    ck("§29 an A2 EXECUTED+verified effect IS a write (reflects reality, not NONE)",
       vw["writes"] and vw["writes"][0]["capability"] == "repo.reversible_write")
    ck("§29 working_now renders the real write list for a mutating mission",
       working_now([vw])[0]["writes"] != "NONE")

    # working_now excludes terminal + PROPOSED missions (only active work is 'working now')
    vdone = mission_view(MissionHeader(mission_id="m31", company="kai", objective="x", root_signature="R31"),
                         worker_jobs=[VERIFIED])
    vprop = mission_view(MissionHeader(mission_id="m32", company="kai", objective="x", root_signature="R32"))
    ck("§29 working_now excludes COMPLETE (terminal) and PROPOSED (no scope) missions",
       vdone["status"] == "COMPLETE" and vprop["status"] == "PROPOSED"
       and working_now([vdone, vprop]) == [])

    # ── guarded Postgres smoke: durable header + §28 dedup end-to-end (default DERIVED resolver) ─────────
    if _db_up():
        from sqlalchemy import text as _t
        from app.database import SessionLocal
        ROOT = "test-root-" + uuid.uuid4().hex[:8]
        mission.create_mission(company="kai", objective="_ensure", root_signature=ROOT)   # create table

        def _clean():
            db = SessionLocal(); db.execute(_t("DELETE FROM holding_missions WHERE root_signature=:r"), {"r": ROOT})
            db.commit(); db.close()

        _clean()
        r1 = mission.create_mission(company="kai", objective="investigate incident", root_signature=ROOT, priority="HIGH")
        ck("[db] create_mission inserts a header", r1["suppressed"] is False and bool(r1["mission_id"]))
        r2 = mission.create_mission(company="kai", objective="investigate incident (again)", root_signature=ROOT)
        ck("[db] §28 2nd mission for the same active root is SUPPRESSED (derived resolver)",
           r2["suppressed"] is True and r2["mission_id"] == r1["mission_id"])
        ck("[db] get_mission round-trips the header", (mission.get_mission(r1["mission_id"]) or {}).get("root_signature") == ROOT)
        ck("[db] cancel_mission marks it cancelled", mission.cancel_mission(r1["mission_id"]) is True)
        r3 = mission.create_mission(company="kai", objective="after cancel", root_signature=ROOT)
        ck("[db] once the first is terminal (cancelled), a new mission is allowed",
           r3["suppressed"] is False and r3["mission_id"] != r1["mission_id"])
        ck("[db] mark_completed with REAL verified evidence stamps completed_at",
           mission.mark_completed(r3["mission_id"], {"execution": "COMPLETED", "tests_passed": True}) is True)
        ck("[db] mark_completed refuses a code-only 'done' (§26)",
           mission.mark_completed(r3["mission_id"], {"branch": "x", "diff": "y"}) is False)
        ck("[db] a completed mission no longer blocks a fresh one for the root",
           mission.create_mission(company="kai", objective="post-complete", root_signature=ROOT)["suppressed"] is False)
        _clean()

        # ── §28 atomic backstop: the partial unique index + concurrent-duplicate suppression ─────────────
        db = SessionLocal()
        try:
            idx = db.execute(_t("SELECT 1 FROM pg_indexes WHERE indexname = 'holding_missions_active_root'")).fetchone()
        finally:
            db.close()
        ck("[db] §28 partial unique index holding_missions_active_root exists", bool(idx))
        RC = "race-root-" + uuid.uuid4().hex[:8]
        ra = mission.create_mission(company="kai", objective="race first", root_signature=RC)
        # simulate the race: a resolver that (wrongly) sees the active mission as terminal → dedup_decision
        # says INSERT, but the DB partial unique index atomically rejects the 2nd active row for the root.
        rb = mission.create_mission(company="kai", objective="race dup", root_signature=RC,
                                    status_resolver=lambda m: "COMPLETE")
        ck("[db] §28 a concurrent duplicate-root insert is SUPPRESSED, not crashed",
           rb.get("suppressed") is True and rb.get("mission_id") == ra["mission_id"] and "error" not in rb)
        db = SessionLocal(); db.execute(_t("DELETE FROM holding_missions WHERE root_signature=:r"), {"r": RC})
        db.commit(); db.close()
    else:
        ck("[db] Postgres smoke skipped (no DB reachable) — pure logic fully covered above", True)

    n = len(res); ok = sum(res)
    print(f"\nHOLDING MISSION TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
