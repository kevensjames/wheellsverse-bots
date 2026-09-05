"""§34 KAI Evaluation Harness — no-fabrication guard. Zero-framework — mirrors test_health_score.py /
test_approval_dialog.py. Injected record fixtures in the EXACT shapes the real readers emit. Run (from backend/):
    python3 -m app.services.holding.test_eval_harness
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding import eval_harness as eh            # noqa: E402
from app.services.holding.eval_harness import (                 # noqa: E402
    evaluate, compare, EVAL_FORMULA_VERSION, METRIC_KEYS, UNAVAILABLE, REAL, DERIVED)
from app.services.holding import mission as mission_mod         # noqa: E402

# ── fixtures in the emitted shapes ────────────────────────────────────────────────────────────────────
AUDIT = [   # governance.audit_log.record_action shape
    {"ts": "2026-09-01T10:00:00+00:00", "action": "read", "actor": "kai", "destructive": False,
     "approved": True, "success": True, "duration_ms": 120},
    {"ts": "2026-09-01T10:01:00+00:00", "action": "patch", "actor": "kai", "destructive": False,
     "approved": True, "success": False, "duration_ms": 300},
    {"ts": "2026-09-01T10:02:00+00:00", "action": "merge", "actor": "worker-x", "destructive": True,
     "approved": False, "success": False, "duration_ms": None},              # refused by the gate
    {"ts": "2026-09-01T10:03:00+00:00", "action": "read", "actor": "kai", "destructive": False,
     "approved": True, "success": True, "duration_ms": 80},
]
JOBS = [    # holding.worker_jobs.list_jobs shape
    {"id": 1, "created_at": "2026-09-01 09:00:00+00:00", "done_at": "2026-09-01 09:10:00+00:00",
     "worker": "codex", "status": "succeeded", "attempt": 1, "evidence": {"verified": True, "cost": 0.25}},
    {"id": 2, "created_at": "2026-09-01 09:00:00+00:00", "done_at": "2026-09-01 09:20:00+00:00",
     "worker": "codex", "status": "succeeded", "attempt": 2, "evidence": {"branch": "kai/x"}},   # code-only
    {"id": 3, "created_at": "2026-09-01 09:00:00+00:00", "done_at": "2026-09-01 09:30:00+00:00",
     "worker": "cline", "status": "failed", "attempt": 1, "evidence": {"error": "tests"}},
    {"id": 4, "created_at": "2026-09-01 09:40:00+00:00", "done_at": None,
     "worker": "cline", "status": "queued", "attempt": 0, "evidence": None},                      # not terminal
]
CYCLES = [  # manual_cycle.normalize_record shape (what DbCycleStore.list_runs really returns)
    {"cycle_id": "cy-h-1", "status": "OK", "completed_at": "2026-09-01T08:00:00+00:00",
     "auto_actions_failed": 0, "duration_ms": 900},
    {"cycle_id": "cy-h-2", "status": "OK", "completed_at": "2026-09-01T09:00:00+00:00",
     "auto_actions_failed": 2, "duration_ms": 1200},
]
MISSIONS = [  # holding.mission._row_to_header shape
    {"mission_id": "ms-1", "created_at": "2026-09-01 07:00:00+00:00", "completed_at": "2026-09-01 08:00:00+00:00",
     "cancelled": False},
    {"mission_id": "ms-2", "created_at": "2026-09-01 07:00:00+00:00", "completed_at": "2026-09-01 10:00:00+00:00",
     "cancelled": False},
    {"mission_id": "ms-3", "created_at": "2026-09-01 07:30:00+00:00", "completed_at": "", "cancelled": True},
]
PROPOSALS = [  # holding.proposals_store.list_proposals shape
    {"id": 10, "created_at": "2026-09-01 06:00:00+00:00", "status": "approved", "decided_at": "2026-09-01 06:30:00+00:00"},
    {"id": 11, "created_at": "2026-09-01 06:00:00+00:00", "status": "rejected", "decided_at": "2026-09-01 06:40:00+00:00"},
    {"id": 12, "created_at": "2026-09-01 06:00:00+00:00", "status": "proposed", "decided_at": None},
]
ALL = dict(audit=AUDIT, jobs=JOBS, cycles=CYCLES, missions=MISSIONS, proposals=PROPOSALS)


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    def m(snap, key):
        return next(x for x in snap["metrics"] if x["metric"] == key)

    # ── deterministic + versioned ─────────────────────────────────────────────────────────────────
    a, b = evaluate(**ALL), evaluate(**ALL)
    ck("same inputs -> byte-identical snapshot", a == b)
    ck("carries EVAL_FORMULA_VERSION", a["version"] == EVAL_FORMULA_VERSION == "1.0.0")
    ck("all 11 §34 metrics present, each exactly REAL / DERIVED / UNAVAILABLE",
       [x["metric"] for x in a["metrics"]] == list(METRIC_KEYS) and len(METRIC_KEYS) == 11
       and all(x["status"] in (REAL, DERIVED, UNAVAILABLE) for x in a["metrics"]))
    ck("as_of is the newest RECORD timestamp, not the wall clock", a["as_of"] == "2026-09-01T10:03:00+00:00")
    src = Path(eh.__file__).read_text()
    ck("module reads no clock and runs no model (pure function of its inputs)",
       "datetime.now" not in src and "time.time" not in src
       and all(t not in src for t in ("capability.brain", "nai_brain", "openai", "ollama", "httpx", "requests")))

    # ── UNAVAILABLE, never an invented KPI ─────────────────────────────────────────────────────────
    none = evaluate()
    ck("no source connected -> every metric UNAVAILABLE with value None (no invented KPI)",
       none["measured"] == 0 and set(none["unavailable"]) == set(METRIC_KEYS)
       and all(x["value"] is None and x["status"] == UNAVAILABLE for x in none["metrics"])
       and set(none["sources"].values()) == {"NOT_CONNECTED"} and none["as_of"] == UNAVAILABLE)
    empty = evaluate(audit=[], jobs=[], cycles=[], missions=[], proposals=[])
    ck("connected-but-empty -> still UNAVAILABLE (an empty log never proves 0 violations/regressions)",
       empty["measured"] == 0 and all(x["value"] is None for x in empty["metrics"])
       and set(empty["sources"].values()) == {"CONNECTED"})
    ck("a metric names the disconnected source in its detail",
       "jobs" in m(evaluate(audit=AUDIT), "task_success")["detail"])
    ck("cost is UNAVAILABLE when no record carries a real figure (never 0.00)",
       m(evaluate(jobs=[{**JOBS[1]}], cycles=[{"cost": "UNAVAILABLE"}]), "cost")["status"] == UNAVAILABLE)

    # ── REAL/DERIVED values are pure counts over the records ───────────────────────────────────────
    ck("task_success counts only VERIFIED-evidence successes: 1/3 terminal -> 33 (code-only 'done' excluded)",
       m(a, "task_success") | {} == {**m(a, "task_success"), "value": 33, "n": 3, "status": DERIVED})
    ck("§26 verified rule is mission._job_verified itself (no second copy)",
       eh._job_verified is mission_mod._job_verified)
    ck("false_positive_rate over CLOSED proposals: 1 rejected / 2 closed -> 50 (open ones excluded)",
       m(a, "false_positive_rate")["value"] == 50 and m(a, "false_positive_rate")["n"] == 2)
    ck("time_to_resolution = lower-median seconds over completed, non-cancelled missions (3600, 10800 -> 3600)",
       m(a, "time_to_resolution")["value"] == 3600 and m(a, "time_to_resolution")["n"] == 2)
    ck("operator_interventions = owner decisions + cancelled missions = 2 + 1 (REAL)",
       m(a, "operator_interventions")["value"] == 3 and m(a, "operator_interventions")["status"] == REAL)
    ck("tool_selection = first-attempt successes / terminal = 1/3 -> 33",
       m(a, "tool_selection")["value"] == 33)
    ck("cost sums ONLY records carrying a real number: 0.25 over 1 record (REAL)",
       m(a, "cost")["value"] == 0.25 and m(a, "cost")["n"] == 1 and m(a, "cost")["status"] == REAL)
    ck("latency = lower-median duration_ms over timed audit actions (80,120,300 -> 120); None skipped",
       m(a, "latency")["value"] == 120 and m(a, "latency")["n"] == 3)
    ck("reliability = audited successes 2/4 -> 50", m(a, "reliability")["value"] == 50)
    ck("regressions reads the STORED normalize_record shape (auto_actions_failed): 1 of 2 cycles",
       m(a, "regressions")["value"] == 1 and m(a, "regressions")["n"] == 2)
    ck("regressions also reads a raw CycleRecord (tasks_failed)",
       m(evaluate(cycles=[{"tasks_failed": 3}]), "regressions")["value"] == 1)
    ck("security_violations = destructive AND not approved (refused by the gate) = 1 (REAL)",
       m(a, "security_violations")["value"] == 1 and m(a, "security_violations")["status"] == REAL)
    ck("decision_usefulness = accepted / owner-decided = 1/2 -> 50", m(a, "decision_usefulness")["value"] == 50)
    ck("measured + unavailable partition the metric set", a["measured"] == 11 and a["unavailable"] == [])
    ck("non-dict junk rows are ignored, not crashed on",
       evaluate(audit=[None, "x", 3, AUDIT[0]])["measured"] >= 1)

    # ── improvement over time: comparable snapshots ────────────────────────────────────────────────
    later = evaluate(**{**ALL, "audit": AUDIT + [{**AUDIT[0], "ts": "2026-09-02T00:00:00+00:00"}],
                        "jobs": JOBS + [{**JOBS[0], "id": 5}]})
    d = compare(a, later)
    by = {x["metric"]: x for x in d["deltas"]}
    ck("compare is comparable across same-version snapshots and carries from/to as_of",
       d["comparable"] is True and d["from"] == a["as_of"] and d["to"] == later["as_of"])
    ck("higher task_success -> IMPROVED (direction table, higher_is_better)",
       by["task_success"]["verdict"] == "IMPROVED" and by["task_success"]["delta"] > 0)
    ck("higher reliability -> IMPROVED; unchanged metric -> UNCHANGED",
       by["reliability"]["verdict"] == "IMPROVED" and by["regressions"]["verdict"] == "UNCHANGED")
    worse = evaluate(**{**ALL, "audit": AUDIT + [{**AUDIT[2], "ts": "2026-09-02T00:00:00+00:00"}]})
    ck("more security_violations -> REGRESSED (lower_is_better)",
       {x["metric"]: x for x in compare(a, worse)["deltas"]}["security_violations"]["verdict"] == "REGRESSED")
    ck("a metric UNAVAILABLE on either side compares as UNAVAILABLE (no delta invented)",
       {x["metric"]: x for x in compare(a, evaluate(audit=AUDIT))["deltas"]}["cost"]["verdict"] == UNAVAILABLE)
    ck("formula-version mismatch -> NOT_COMPARABLE (a formula change never masquerades as progress)",
       compare({**a, "version": "0.9.0"}, a)["comparable"] is False
       and "NOT_COMPARABLE" in compare({**a, "version": "0.9.0"}, a)["reason"])
    ck("compare tally sums to the metric count",
       sum(d["summary"].values()) == len(METRIC_KEYS))
    ck("collect_sources reads the five REAL readers only (no new recorder, §79 bounded)",
       all(s in src for s in ("audit_log import list_actions", "worker_jobs import list_jobs",
                              "DbCycleStore", "mission import list_missions",
                              "proposals_store import list_proposals")))

    n = len(res); ok = sum(res)
    print(f"\nEVAL HARNESS (§34) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
