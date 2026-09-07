"""§34 KAI Evaluation Harness — deterministic, versioned, over REAL records only. NO LLM.

CLONES the ``security/risk_score.py`` / ``holding/health_score.py`` versioned-formula pattern: a pure
function over injected record lists; identical inputs -> byte-identical snapshot; the number is NEVER
invented by a model (§0 #16-19). Every metric is exactly one of:
  REAL         a direct count/sum over records that carry the field
  DERIVED      pure integer arithmetic over REAL counts (a ratio, a median)
  UNAVAILABLE  the source is not connected (None) or holds no measurable sample — never a guessed 0/100

Sources are the SHAPES the existing modules already emit (nothing new is recorded, §79 bounded):
  audit      governance.audit_log.list_actions()   {ts, action, actor, destructive, approved, success, duration_ms}
  jobs       holding.worker_jobs.list_jobs()       {created_at, done_at, status, attempt, evidence, worker}
  cycles     cycle_store.DbCycleStore.list_runs()  manual_cycle.normalize_record() {auto_actions_failed,
                                                   duration_ms, completed_at, ...} (a raw CycleRecord.as_dict()
                                                   {tasks_failed, cost} is read tolerantly too)
  missions   holding.mission.list_missions()       header {created_at, completed_at, cancelled}
  proposals  holding.proposals_store.list_proposals() {status, created_at, decided_at}
``None`` = source NOT_CONNECTED -> every metric over it is UNAVAILABLE. ``[]`` = connected but empty ->
still UNAVAILABLE (n=0 is no sample; an empty log never proves "0 violations / 0 regressions").

The DB readers above return [] when the DB is DOWN (their fail-soft contract), which is indistinguishable
from "connected and empty" — so ``collect_sources`` probes DB reachability ONCE (SELECT 1) and hands the
four DB-backed feeds over as None when it fails; the audit log likewise is None when its file exists but
cannot be read (an ABSENT file is an honest [] — nothing was ever recorded). ponytail: a reader that fails
on its own table while the DB is up still returns []; upgrade path is for the readers to return None.

Improvement over time = ``compare(prev_snapshot, cur_snapshot)`` — a pure per-metric delta with a versioned
better/worse direction; snapshots from different formula versions are NOT_COMPARABLE. Persisting snapshots
is the router/scheduler step (not here — this module reads no DB/net, like its risk_score sibling).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.holding.mission import _job_verified   # the ONE §26 verified-evidence rule (no fork)

EVAL_FORMULA_VERSION = "1.0.0"

UNAVAILABLE = "UNAVAILABLE"
REAL = "REAL"
DERIVED = "DERIVED"
NOT_COMPARABLE = "NOT_COMPARABLE"

_TERMINAL_JOB = ("succeeded", "failed", "expired")
_CLOSED_PROPOSAL = ("approved", "executed", "rejected", "superseded")
_FALSE_POSITIVE = ("rejected", "superseded")          # owner said no / blocker vanished on its own
_OWNER_DECIDED = ("approved", "executed", "rejected")


# ── helpers (pure) ────────────────────────────────────────────────────────────────────────────────────
def _ts(s):
    """Tolerant ISO parse for the two formats the sources emit (audit isoformat 'T…+00:00' and
    Postgres str(timestamptz) 'YYYY-MM-DD HH:MM:SS.ffffff+00:00'). None if unparseable/absent."""
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip().replace("Z", "+00:00")
    if " " in t and "T" not in t:
        t = t.replace(" ", "T", 1)
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _median_int(xs: list) -> int:
    xs = sorted(xs)
    return int(xs[(len(xs) - 1) // 2])          # lower-middle: deterministic, no float averaging


def _num(x):
    """A real number carried by a record (bool excluded). Numeric strings are accepted only if they parse."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x)
        except ValueError:
            return None
    return None


def _pct(part: int, whole: int) -> int:
    return part * 100 // whole                  # integer floor percent


# ── per-metric scorers: each maps REAL records to (value, n, detail) or None (=UNAVAILABLE) ───────────
def _task_success(jobs):
    term = [j for j in jobs if j.get("status") in _TERMINAL_JOB]
    if not term:
        return None
    ok = sum(1 for j in term if _job_verified(j))   # §26: succeeded AND verified evidence, never code-only
    return (_pct(ok, len(term)), len(term), f"{ok}/{len(term)} terminal jobs succeeded with VERIFIED evidence")


def _false_positive_rate(props):
    closed = [p for p in props if p.get("status") in _CLOSED_PROPOSAL]
    if not closed:
        return None
    fp = sum(1 for p in closed if p.get("status") in _FALSE_POSITIVE)
    return (_pct(fp, len(closed)), len(closed), f"{fp}/{len(closed)} closed proposals rejected or superseded")


def _time_to_resolution(missions):
    secs = []
    for m in missions:
        if m.get("cancelled"):
            continue
        a, b = _ts(m.get("created_at")), _ts(m.get("completed_at"))
        if a and b and b >= a:
            secs.append(int((b - a).total_seconds()))
    if not secs:
        return None
    return (_median_int(secs), len(secs), f"median over {len(secs)} completed mission(s)")


def _operator_interventions(props, missions):
    if not props and not missions:
        return None                             # nothing recorded -> UNAVAILABLE, never "0 interventions"
    decided = sum(1 for p in props if p.get("status") in _OWNER_DECIDED)
    cancelled = sum(1 for m in missions if m.get("cancelled"))
    return (decided + cancelled, len(props) + len(missions),
            f"{decided} owner proposal decision(s) + {cancelled} cancelled mission(s)")


def _tool_selection(jobs):
    term = [j for j in jobs if j.get("status") in _TERMINAL_JOB]
    if not term:
        return None
    first = sum(1 for j in term if j.get("status") == "succeeded" and j.get("attempt") == 1)
    return (_pct(first, len(term)), len(term), f"{first}/{len(term)} terminal jobs succeeded on attempt 1")


def _cost(jobs, cycles):
    found = []
    for j in jobs:
        ev = j.get("evidence")
        c = _num(ev.get("cost")) if isinstance(ev, dict) else None
        if c is not None:
            found.append(c)
    for c in cycles:
        v = _num(c.get("cost"))                 # CycleRecord.cost is "UNAVAILABLE" unless a real figure was set
        if v is not None:
            found.append(v)
    if not found:
        return None                             # no record carries a real cost -> UNAVAILABLE, never 0.00
    return (round(sum(found), 4), len(found), f"sum over {len(found)} record(s) carrying a real cost")


def _latency(audit):
    ms = [a["duration_ms"] for a in audit
          if isinstance(a.get("duration_ms"), int) and not isinstance(a.get("duration_ms"), bool)]
    if not ms:
        return None
    return (_median_int(ms), len(ms), f"median over {len(ms)} timed audit action(s)")


def _reliability(audit):
    if not audit:
        return None
    ok = sum(1 for a in audit if a.get("success") is True)
    return (_pct(ok, len(audit)), len(audit), f"{ok}/{len(audit)} audited actions succeeded")


def _failed_in(c: dict):
    """Stored runs are normalize_record() shape (auto_actions_failed); a raw CycleRecord says tasks_failed."""
    v = c.get("auto_actions_failed", c.get("tasks_failed"))
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _regressions(cycles):
    counted = [c for c in cycles if _failed_in(c) is not None]
    if not counted:
        return None                             # no run carries a failure count -> UNAVAILABLE, never "0 regressions"
    n = sum(1 for c in counted if _failed_in(c) > 0)
    return (n, len(counted), f"{n} of {len(counted)} cycle(s) had failed tasks")


def _security_violations(audit):
    if not audit:
        return None                             # an empty log proves nothing -> UNAVAILABLE, never "0 violations"
    n = sum(1 for a in audit if a.get("destructive") is True and a.get("approved") is False)
    return (n, len(audit), f"{n} destructive action(s) attempted without approval (refused by the gate)")


def _decision_usefulness(props):
    decided = [p for p in props if p.get("status") in _OWNER_DECIDED]
    if not decided:
        return None
    acc = sum(1 for p in decided if p.get("status") in ("approved", "executed"))
    return (_pct(acc, len(decided)), len(decided), f"{acc}/{len(decided)} owner-decided proposals accepted")


# (key, status_kind, unit, higher_is_better, sources, scorer) — versioned with EVAL_FORMULA_VERSION.
_METRICS = [
    ("task_success",           DERIVED, "percent", True,  ("jobs",),               _task_success),
    ("false_positive_rate",    DERIVED, "percent", False, ("proposals",),          _false_positive_rate),
    ("time_to_resolution",     DERIVED, "seconds", False, ("missions",),           _time_to_resolution),
    ("operator_interventions", REAL,    "count",   False, ("proposals", "missions"), _operator_interventions),
    ("tool_selection",         DERIVED, "percent", True,  ("jobs",),               _tool_selection),
    ("cost",                   REAL,    "usd",     False, ("jobs", "cycles"),      _cost),
    ("latency",                DERIVED, "ms",      False, ("audit",),              _latency),
    ("reliability",            DERIVED, "percent", True,  ("audit",),              _reliability),
    ("regressions",            REAL,    "count",   False, ("cycles",),             _regressions),
    ("security_violations",    REAL,    "count",   False, ("audit",),              _security_violations),
    ("decision_usefulness",    DERIVED, "percent", True,  ("proposals",),          _decision_usefulness),
]
METRIC_KEYS = tuple(m[0] for m in _METRICS)
_DIRECTION = {m[0]: m[3] for m in _METRICS}


def evaluate(*, audit=None, jobs=None, cycles=None, missions=None, proposals=None) -> dict:
    """Deterministic §34 snapshot. Kwargs only; each is a list of record dicts in its module's emitted
    shape, or None (source not connected). A metric whose source is None, or with no measurable sample, is
    UNAVAILABLE with value None — never an invented KPI. ``as_of`` is the newest timestamp found IN the
    records (not the wall clock), so the snapshot is a pure function of its inputs."""
    src = {"audit": audit, "jobs": jobs, "cycles": cycles, "missions": missions, "proposals": proposals}
    lists = {k: [r for r in (v or []) if isinstance(r, dict)] for k, v in src.items()}
    metrics = []
    unavailable = []
    for key, kind, unit, _hib, needs, scorer in _METRICS:
        missing = [s for s in needs if src[s] is None]
        base = {"metric": key, "unit": unit, "source": "+".join(needs)}
        if missing:
            metrics.append({**base, "status": UNAVAILABLE, "value": None, "n": 0,
                            "detail": f"source not connected: {', '.join(missing)}"})
            unavailable.append(key)
            continue
        out = scorer(*[lists[s] for s in needs])
        if out is None:
            metrics.append({**base, "status": UNAVAILABLE, "value": None, "n": 0,
                            "detail": "no measurable sample in the connected source"})
            unavailable.append(key)
            continue
        value, n, detail = out
        metrics.append({**base, "status": kind, "value": value, "n": n, "detail": detail})
    stamps = [_ts(r.get(f)) for k, rs in lists.items() for r in rs
              for f in ("ts", "done_at", "created_at", "completed_at", "decided_at", "updated_at")]
    stamps = [s for s in stamps if s]
    return {"version": EVAL_FORMULA_VERSION,
            "as_of": max(stamps).isoformat() if stamps else UNAVAILABLE,
            "sources": {k: ("NOT_CONNECTED" if v is None else "CONNECTED") for k, v in src.items()},
            "measured": len(metrics) - len(unavailable), "unavailable": unavailable, "metrics": metrics}


def compare(prev: dict, cur: dict) -> dict:
    """Pure improvement-over-time delta between two snapshots of the SAME formula version. Per metric:
    IMPROVED / REGRESSED / UNCHANGED by the versioned direction table, or UNAVAILABLE when either side has
    no value. A version mismatch is NOT_COMPARABLE (a formula change must never masquerade as progress)."""
    if not isinstance(prev, dict) or not isinstance(cur, dict):
        return {"comparable": False, "reason": "snapshot missing"}
    if prev.get("version") != cur.get("version") or cur.get("version") != EVAL_FORMULA_VERSION:
        return {"comparable": False, "reason": f"{NOT_COMPARABLE}: formula version mismatch "
                                               f"({prev.get('version')} vs {cur.get('version')})"}
    pv = {m["metric"]: m for m in prev.get("metrics", [])}
    cv = {m["metric"]: m for m in cur.get("metrics", [])}
    deltas, tally = [], {"IMPROVED": 0, "REGRESSED": 0, "UNCHANGED": 0, UNAVAILABLE: 0}
    for key in METRIC_KEYS:
        a, b = (pv.get(key) or {}).get("value"), (cv.get(key) or {}).get("value")
        if a is None or b is None:
            verdict, delta = UNAVAILABLE, None
        else:
            delta = round(b - a, 4)
            if delta == 0:
                verdict = "UNCHANGED"
            else:
                verdict = "IMPROVED" if ((delta > 0) == _DIRECTION[key]) else "REGRESSED"
        tally[verdict] += 1
        deltas.append({"metric": key, "prev": a, "cur": b, "delta": delta, "verdict": verdict})
    return {"comparable": True, "version": EVAL_FORMULA_VERSION, "from": prev.get("as_of"),
            "to": cur.get("as_of"), "summary": tally, "deltas": deltas}


def db_reachable() -> bool:
    """ONE SELECT 1 through the app's own session factory (looked up at call time so a test can patch it).
    False = the DB-backed feeds are NOT_CONNECTED, never "connected and empty"."""
    try:
        import app.database as _db
        from sqlalchemy import text
        s = _db.SessionLocal()
        try:
            s.execute(text("SELECT 1"))
        finally:
            s.close()
        return True
    except Exception:   # noqa: BLE001 — unreachable is a fact to report, not to guess around
        return False


def _read_audit(limit: int):
    """audit_log.list_actions, but a read FAILURE is None (NOT_CONNECTED) — the reader itself swallows it
    into []. An absent file is [] (nothing has ever been recorded — honest empty)."""
    from app.services.governance.audit_log import list_actions, AUDIT_LOG_PATH
    if not AUDIT_LOG_PATH.exists():
        return []
    try:
        with AUDIT_LOG_PATH.open():        # the same open() list_actions performs; if it fails, so did the read
            pass
    except OSError:
        return None
    return list_actions(limit=limit)


def collect_sources(limit: int = 500) -> dict:
    """Pull the five REAL feeds from their existing readers (lazy imports). A feed is None (NOT_CONNECTED)
    when its store is unreachable — the DB probed once for the four DB-backed feeds, the audit file for its
    own. This is the only place the harness touches storage; ``evaluate(**collect_sources())`` is the live
    snapshot."""
    from app.services.holding.worker_jobs import list_jobs
    from app.services.holding.cycle_store import DbCycleStore
    from app.services.holding.mission import list_missions
    from app.services.holding.proposals_store import list_proposals
    up = db_reachable()
    return {"audit": _read_audit(limit),
            "jobs": list_jobs(limit=limit) if up else None,
            "cycles": DbCycleStore().list_runs(limit=limit) if up else None,
            "missions": list_missions(limit=limit) if up else None,
            "proposals": list_proposals(limit=limit) if up else None}


if __name__ == "__main__":
    from app.services.holding.test_eval_harness import run
    run()
