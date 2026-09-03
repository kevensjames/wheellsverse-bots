"""PREPARE_ALLOWED admission guardrails (§5/§12/§23) — the bounds a CONTINUOUS self-improvement preparation
must pass BEFORE it may originate an A2 coding job. Undeployed until PREPARE_ALLOWED is approved; enforced
only when dispatch_self_improvement is called with enforce_guardrails=True (the future continuous path).
Manual owner-triggered dispatch is unaffected (an explicit owner action, not autonomous).

Four bounds, checked in priority order against the CURRENT coding-job queue:
  1. YIELD_TO_OPERATIONAL — operational (customer/holding) coding work outranks self-improvement; if any is
     active/queued, self-improvement yields the single worker slot.
  2. CONCURRENCY_LIMIT   — at most ONE self-improvement preparation in flight at a time.
  3. DUPLICATE_ROOT      — one active/recent preparation per root problem (no repeat branches for one defect).
  4. BUDGET_EXHAUSTED    — at most `ceiling` (default 3) self-improvement preparations dispatched per day.
Pure + injectable (job views passed in) so it is a plain python3 self-test. It can only ever make dispatch
MORE restrictive — it never admits something the A2 brakes/grant would refuse.
"""
from __future__ import annotations

from dataclasses import dataclass

_ACTIVE = ("queued", "claimed", "running")
DAILY_PREPARATION_CEILING = 3


@dataclass
class JobView:
    origin: str          # "self_improvement" | "operational"
    root: str            # root-problem signature (self-improvement jobs); "" for operational
    status: str          # queued/claimed/running/succeeded/failed/...
    created_date: str     # "YYYY-MM-DD"


def _task_id(job: dict) -> str:
    t = job.get("task") or {}
    return str(t.get("task_id") or job.get("mission_id") or "")


def classify_origin(task_id: str) -> str:
    """A self-improvement preparation tags its mission/task_id with an 'si:' marker (possibly behind the
    enqueue 'a2:' wrapper). Everything else is operational A2 work."""
    tid = str(task_id)
    return "self_improvement" if ("si:" in tid) else "operational"


def _root(task_id: str) -> str:
    tid = str(task_id)
    if "si:" in tid:
        return tid.split("si:", 1)[1]
    return ""


def describe(job_rows: list) -> list:
    """Adapt worker_jobs coding rows into pure JobViews (coding worker only)."""
    views = []
    for j in job_rows or []:
        if j.get("worker") != "coding":
            continue
        tid = _task_id(j)
        views.append(JobView(origin=classify_origin(tid), root=_root(tid),
                             status=str(j.get("status") or ""),
                             created_date=str(j.get("created_at") or "")[:10]))
    return views


def preparation_admission(*, root_signature: str, jobs: list, now_date: str,
                          ceiling: int = DAILY_PREPARATION_CEILING) -> dict:
    """Decide whether a self-improvement PREPARATION may proceed. Returns {admit, reason}. Fail-closed:
    an unparseable/negative ceiling admits nothing."""
    if ceiling <= 0:
        return {"admit": False, "reason": "BUDGET_EXHAUSTED"}
    active = [v for v in jobs if v.status in _ACTIVE]
    # 1. operational work outranks self-improvement for the single slot
    if any(v.origin == "operational" for v in active):
        return {"admit": False, "reason": "YIELD_TO_OPERATIONAL"}
    # 2. one self-improvement preparation at a time
    if any(v.origin == "self_improvement" for v in active):
        return {"admit": False, "reason": "CONCURRENCY_LIMIT"}
    # 3. one active/recent preparation per root problem
    if root_signature and any(v.origin == "self_improvement" and v.root == root_signature
                              and (v.status in _ACTIVE or v.created_date == now_date) for v in jobs):
        return {"admit": False, "reason": "DUPLICATE_ROOT"}
    # 4. daily budget
    today = [v for v in jobs if v.origin == "self_improvement" and v.created_date == now_date]
    if len(today) >= ceiling:
        return {"admit": False, "reason": "BUDGET_EXHAUSTED"}
    return {"admit": True, "reason": "ADMIT"}


def demo() -> None:
    """Pure self-check — no DB. Proves each bound refuses, and a clean queue admits."""
    def sv(root, status, date): return JobView("self_improvement", root, status, date)
    def ov(status, date): return JobView("operational", "", status, date)
    D = "2026-09-03"

    # clean queue -> ADMIT
    assert preparation_admission(root_signature="failing_suite:x", jobs=[], now_date=D)["admit"] is True
    # operational active -> YIELD
    assert preparation_admission(root_signature="r", jobs=[ov("running", D)], now_date=D)["reason"] == "YIELD_TO_OPERATIONAL"
    # self-imp active -> CONCURRENCY
    assert preparation_admission(root_signature="r", jobs=[sv("other", "running", D)], now_date=D)["reason"] == "CONCURRENCY_LIMIT"
    # same root today (terminal) -> DUPLICATE_ROOT
    assert preparation_admission(root_signature="r", jobs=[sv("r", "succeeded", D)], now_date=D)["reason"] == "DUPLICATE_ROOT"
    # budget: 3 today already -> BUDGET_EXHAUSTED
    three = [sv(f"r{i}", "succeeded", D) for i in range(3)]
    assert preparation_admission(root_signature="rnew", jobs=three, now_date=D)["reason"] == "BUDGET_EXHAUSTED"
    # yesterday's jobs do NOT count against today's budget
    old = [sv(f"r{i}", "succeeded", "2026-09-02") for i in range(5)]
    assert preparation_admission(root_signature="rnew", jobs=old, now_date=D)["admit"] is True
    # describe() classifies from worker_jobs rows
    rows = [{"worker": "coding", "status": "running", "task": {"task_id": "si:failing_suite:x"}},
            {"worker": "coding", "status": "queued", "task": {"task_id": "op-123"}},
            {"worker": "github", "status": "running", "task": {"task_id": "si:ignored"}}]
    v = describe(rows)
    assert len(v) == 2 and v[0].origin == "self_improvement" and v[0].root == "failing_suite:x"
    assert v[1].origin == "operational"
    print("self_improvement_guardrails.demo OK — YIELD/CONCURRENCY/DUPLICATE_ROOT/BUDGET all refuse; clean admits")


if __name__ == "__main__":
    demo()
