"""Per-project engineering state (backlog, roadmap, issues, cycles) plus the
factory-wide audit log and approval queue. Atomic writes + a module lock around
the compare-and-set task claim so a crashed/concurrent cycle never double-claims."""
from __future__ import annotations

import threading
import uuid

from core.portfolio.actions import Action
from factory import paths

_CLAIM_LOCK = threading.Lock()


# ---- backlog -------------------------------------------------------------
def _backlog_file(slug: str):
    return paths.project_dir(slug) / "backlog.json"


def load_backlog(slug: str) -> list[dict]:
    data = paths.load_json(_backlog_file(slug), {"tasks": []}) or {"tasks": []}
    return data.get("tasks", [])


def save_backlog(slug: str, tasks: list[dict]) -> None:
    paths.save_json_atomic(_backlog_file(slug), {"tasks": tasks})


def _by_id(tasks: list[dict]) -> dict[str, dict]:
    return {t["id"]: t for t in tasks}


def next_ready_task(slug: str) -> dict | None:
    tasks = load_backlog(slug)
    done = {t["id"] for t in tasks if t.get("status") == "done"}
    ready = [
        t for t in tasks
        if t.get("status") == "pending"
        and all(dep in done for dep in t.get("depends_on", []))
    ]
    if not ready:
        return None
    ready.sort(key=lambda t: (t.get("priority", 0), t["id"]))
    return ready[0]


def claim_task(slug: str, task_id: str, cycle_id: str) -> bool:
    with _CLAIM_LOCK:
        tasks = load_backlog(slug)
        idx = _by_id(tasks)
        t = idx.get(task_id)
        if t is None or t.get("status") != "pending":
            return False
        t["status"] = "in_progress"
        t["cycle_id"] = cycle_id
        save_backlog(slug, tasks)
        return True


def _set_status(slug: str, task_id: str, status: str, *, clear_cycle: bool) -> None:
    with _CLAIM_LOCK:
        tasks = load_backlog(slug)
        for t in tasks:
            if t["id"] == task_id:
                t["status"] = status
                if clear_cycle:
                    t["cycle_id"] = None
        save_backlog(slug, tasks)


def complete_task(slug: str, task_id: str) -> None:
    _set_status(slug, task_id, "done", clear_cycle=False)


def block_task(slug: str, task_id: str) -> None:
    _set_status(slug, task_id, "blocked", clear_cycle=False)


def release_task(slug: str, task_id: str) -> None:
    _set_status(slug, task_id, "pending", clear_cycle=True)


def requeue_oldest_blocked(slug: str) -> str | None:
    """Reset the first 'blocked' task back to 'pending' so it is re-attempted next
    cycle. Returns its id, or None if nothing is blocked."""
    with _CLAIM_LOCK:
        tasks = load_backlog(slug)
        for t in tasks:
            if t.get("status") == "blocked":
                t["status"] = "pending"
                t["cycle_id"] = None
                save_backlog(slug, tasks)
                return t["id"]
    return None


def reclaim_orphans(slug: str, current_cid: str) -> list[str]:
    """Reset tasks left 'in_progress' by a PRIOR (dead) cycle back to 'pending'.
    A task whose cycle_id != current_cid was claimed by a cycle that crashed before
    completing/blocking it; reclaim it so the daemon can retry. Returns reclaimed ids."""
    with _CLAIM_LOCK:
        tasks = load_backlog(slug)
        reclaimed: list[str] = []
        for t in tasks:
            if t.get("status") == "in_progress" and t.get("cycle_id") != current_cid:
                t["status"] = "pending"
                t["cycle_id"] = None
                reclaimed.append(t["id"])
        if reclaimed:
            save_backlog(slug, tasks)
        return reclaimed


# ---- roadmap -------------------------------------------------------------
def _roadmap_file(slug: str):
    return paths.project_dir(slug) / "roadmap.json"


def load_roadmap(slug: str) -> dict:
    return paths.load_json(_roadmap_file(slug), {"milestones": []}) or {"milestones": []}


def save_roadmap(slug: str, data: dict) -> None:
    paths.save_json_atomic(_roadmap_file(slug), data)


def roadmap_complete(slug: str) -> bool:
    ms = load_roadmap(slug).get("milestones", [])
    return bool(ms) and all(m.get("status") == "done" for m in ms)


# ---- issues + cycles -----------------------------------------------------
def append_known_issue(slug: str, issue: dict) -> None:
    paths.append_jsonl(paths.project_dir(slug) / "known_issues.jsonl", issue)


def append_cycle(slug: str, record: dict) -> None:
    paths.append_jsonl(paths.project_dir(slug) / "cycles.jsonl", record)


# ---- factory-wide audit + approvals -------------------------------------
def audit(record: dict, *, now_iso: str) -> None:
    enriched = dict(record)
    enriched["at"] = now_iso
    paths.append_jsonl(paths.data_root() / "audit.jsonl", enriched)


def queue_approval(action: Action, *, now_iso: str) -> str:
    aid = uuid.uuid4().hex[:12]
    paths.append_jsonl(paths.data_root() / "approvals.jsonl", {
        "id": aid,
        "status": "pending",
        "business": action.business,
        "verb": action.verb,
        "agent": action.agent,
        "action_class": action.action_class.value,
        "preconditions": list(action.preconditions),
        "payload": action.payload,
        "at": now_iso,
    })
    return aid
