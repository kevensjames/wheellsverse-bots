"""Zero-framework guard + demo for the CurrentAttentionModel (§17). No DB, no pytest.
Run:  python3 backend/app/services/holding/test_attention_model.py
  or: python3 -m app.services.holding.attention_model   (module __main__ delegates here)

Proves: attention is BOUNDED + SOURCED (each field traces to a real source or UNAVAILABLE), the IDLE
state is HONEST (no invented mission), and only real source values are emitted (no hidden reasoning).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding.attention_model import (          # noqa: E402
    CurrentAttentionModel, UNAVAILABLE, _MAX_SECONDARY,
    SRC_PLAN, SRC_PORTFOLIO, SRC_PROPOSALS, SRC_WORKERS,
)
from app.services.holding.plan import PlanTask, Assignee, TaskStatus, AutonomyClass  # noqa: E402

_KNOWN_SOURCES = {SRC_PLAN, SRC_PORTFOLIO, SRC_PROPOSALS, SRC_WORKERS,
                  "holding.plan:PlanTask(status=BLOCKED)", UNAVAILABLE,
                  SRC_PORTFOLIO + "+" + SRC_PLAN}

_res = []


def ck(name, ok):
    _res.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")


def _model(**src):
    return CurrentAttentionModel(sources=src)


def run():
    # ── FIXTURES ────────────────────────────────────────────────────────────────────────────────
    kai_task = PlanTask(task_id="INCIDENT_OPENED:sol", company_id="sol",
                        goal="Investigate incident on sol", reason="sol health probe not OK (HTTP 503)",
                        source_key="INCIDENT_OPENED:sol", horizon="TODAY", priority=0,
                        assigned_to=Assignee.KAI.value, status=TaskStatus.ACTIVE.value,
                        autonomy=int(AutonomyClass.A0_OBSERVE))
    low_task = PlanTask(task_id="DEPLOYMENT_CHANGED:kai", company_id="kai",
                        goal="Verify deployment on kai", reason="deploy sha changed",
                        source_key="DEPLOYMENT_CHANGED:kai", horizon="7_DAY", priority=2,
                        assigned_to=Assignee.KAI.value, status=TaskStatus.PROPOSED.value)
    blocked_task = PlanTask(task_id="OWNER_BLOCKER_ADDED:nurtelle", company_id="nurtelle",
                            goal="Owner decision required on nurtelle", reason="awaiting legal sign-off",
                            source_key="OWNER_BLOCKER_ADDED:nurtelle", priority=1,
                            assigned_to=Assignee.OWNER.value, status=TaskStatus.BLOCKED.value,
                            autonomy=int(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT))
    proposal = {"id": 7, "entity": "sol", "title": "Approve prepared staging cert",
                "severity": "HIGH", "source_key": "cert:sol", "status": "proposed"}
    proposal_crit = {"id": 9, "entity": "kai", "title": "Rotate exposed API key",
                     "severity": "CRITICAL", "source_key": "sec:kai", "status": "proposed"}
    worker_busy = {"worker_id": "codex-1", "online": True, "current_job": 42}
    worker_idle = {"worker_id": "codex-2", "online": True, "current_job": None}
    worker_off = {"worker_id": "codex-3", "online": False, "current_job": 99}

    def sources_map_valid(snap):
        srcs = snap["sources"]
        for f in ("primary_mission", "secondary_observations", "current_company", "current_blocker",
                  "current_owner_request", "active_worker_jobs", "pending_approval", "priority_reason"):
            if f not in srcs or srcs[f] not in _KNOWN_SOURCES:
                return False
            # a valued field must NOT be sourced UNAVAILABLE; an UNAVAILABLE value must be
            val = snap[f]
            is_unavail_val = (val == UNAVAILABLE) or (val == [] ) or (val == {})
            if srcs[f] == UNAVAILABLE and not is_unavail_val:
                return False
        return True

    # ── ACTIVE: KAI has real planned work ────────────────────────────────────────────────────────
    snap = _model(plan_tasks=lambda: [kai_task, low_task],
                  portfolio=lambda: {"needs_attention": ["sol"]},
                  owner_requests=lambda: [proposal], workers=lambda: [worker_busy, worker_idle, worker_off],
                  posture=lambda: "Operational posture: AUTONOMOUS_READ_ONLY.").snapshot()

    ck("§17 ACTIVE focus_state when a KAI task is active", snap["focus_state"] == "ACTIVE")
    ck("§17 primary_mission is the top task's goal VERBATIM (passthrough, not synthesized)",
       snap["primary_mission"] == "Investigate incident on sol")
    ck("§17 current_company traces to the task", snap["current_company"] == "sol")
    ck("§17 priority_reason carries the task's REAL reason (no invented rationale)",
       "sol health probe not OK (HTTP 503)" in snap["priority_reason"] and snap["priority_reason"].startswith("CRITICAL"))
    ck("§17 secondary_observations holds the lower-priority task (bounded)",
       any(o["observation"] == "Verify deployment on kai" for o in snap["secondary_observations"])
       and len(snap["secondary_observations"]) <= _MAX_SECONDARY)
    ck("§17 active_worker_jobs = only online workers holding a job id (REAL)",
       snap["active_worker_jobs"] == [{"worker_id": "codex-1", "job_id": 42}])
    ck("§17 current_owner_request = the open proposal", snap["current_owner_request"]["proposal_id"] == 7)
    ck("§17 pending_approval counts open proposals", snap["pending_approval"] == 1)
    ck("§17 every field traces to a real source or UNAVAILABLE (mechanical)", sources_map_valid(snap))
    ck("§17/§87 no hidden reasoning exposed", snap["hidden_reasoning_exposed"] is False)

    # ── BLOCKER: a BLOCKED plan task surfaces as current_blocker ──────────────────────────────────
    snap_b = _model(plan_tasks=lambda: [kai_task, blocked_task],
                    portfolio=lambda: {"needs_attention": []}, owner_requests=lambda: [],
                    workers=lambda: []).snapshot()
    ck("§17 current_blocker = the BLOCKED task, sourced",
       "awaiting legal sign-off" in snap_b["current_blocker"]
       and snap_b["sources"]["current_blocker"] == "holding.plan:PlanTask(status=BLOCKED)")

    # ── MONITORING: no active mission, but observations/owner-work exist — honest, no invented mission ─
    snap_m = _model(plan_tasks=lambda: [], portfolio=lambda: {"needs_attention": ["sol", "kai"]},
                    owner_requests=lambda: [proposal, proposal_crit], workers=lambda: []).snapshot()
    ck("§17 MONITORING when flagged companies/owner-work but no active task", snap_m["focus_state"] == "MONITORING")
    ck("§17 MONITORING does NOT fabricate a mission", snap_m["primary_mission"] == UNAVAILABLE)
    ck("§17 MONITORING current_company from portfolio needs_attention", snap_m["current_company"] == "sol")
    ck("§17 owner_request ranks CRITICAL over HIGH (most severe first)",
       snap_m["current_owner_request"]["proposal_id"] == 9)
    ck("§17 MONITORING priority_reason is portfolio-derived, not invented",
       snap_m["sources"]["priority_reason"] == SRC_PORTFOLIO)
    ck("§17 MONITORING sources map valid", sources_map_valid(snap_m))

    # ── IDLE: nothing anywhere → honest empty state, NO invented mission (the key honesty test) ────
    snap_i = _model(plan_tasks=lambda: [], portfolio=lambda: {"needs_attention": []},
                    owner_requests=lambda: [], workers=lambda: [],
                    posture=lambda: "Operational posture: AUTONOMOUS_READ_ONLY.").snapshot()
    ck("§17 IDLE focus_state when truly idle", snap_i["focus_state"] == "IDLE")
    ck("§17 IDLE never fabricates a mission/company/reason",
       snap_i["primary_mission"] == UNAVAILABLE and snap_i["current_company"] == UNAVAILABLE
       and snap_i["priority_reason"] == UNAVAILABLE and snap_i["current_blocker"] == UNAVAILABLE
       and snap_i["current_owner_request"] == UNAVAILABLE)
    ck("§17 IDLE summary is honest 'no active focus'", "No active focus" in snap_i["summary"])
    ck("§17 IDLE secondary_observations empty + worker jobs empty", snap_i["secondary_observations"] == []
       and snap_i["active_worker_jobs"] == [] and snap_i["pending_approval"] == 0)
    ck("§17 IDLE sources map valid (UNAVAILABLE fields sourced UNAVAILABLE)", sources_map_valid(snap_i))

    # ── FAIL-OPEN: every source raises → no crash, honest IDLE (§0#16-19) ──────────────────────────
    def boom():
        raise RuntimeError("db down")
    snap_f = _model(plan_tasks=boom, portfolio=boom, owner_requests=boom, workers=boom, posture=boom).snapshot()
    ck("§17 fail-open on broken subsystems → IDLE, never a crash",
       snap_f["focus_state"] == "IDLE" and snap_f["primary_mission"] == UNAVAILABLE)

    # ── BOUNDED: secondary observations never exceed the cap (§79) ─────────────────────────────────
    many = [f"co{i}" for i in range(20)]
    snap_c = _model(plan_tasks=lambda: [], portfolio=lambda: {"needs_attention": many},
                    owner_requests=lambda: [], workers=lambda: []).snapshot()
    ck("§79 secondary_observations is bounded (never an unbounded scan)",
       len(snap_c["secondary_observations"]) <= _MAX_SECONDARY)

    n = len(_res)
    ok = sum(_res)
    print(f"\nCURRENT ATTENTION MODEL TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    raise SystemExit(0 if ok == n else 1)


if __name__ == "__main__":
    run()
