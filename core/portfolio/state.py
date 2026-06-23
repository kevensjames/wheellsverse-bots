"""W-MOS persistence: per-business state, artifact files, the portfolio-wide audit
log, and the approval queue (the AMBER one-click surface, stored as JSONL)."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from core.portfolio import paths
from core.portfolio.actions import Action

_DEFAULT_STATE = {"phase": "planning", "completed_verbs": [], "pending_verbs": []}


def _state_file(slug: str):
    return paths.business_dir(slug) / "state.json"


def load_state(slug: str) -> dict:
    base = {k: (list(v) if isinstance(v, list) else v) for k, v in _DEFAULT_STATE.items()}
    stored = paths.load_json(_state_file(slug), {})
    base.update(stored or {})
    base["completed_verbs"] = base.get("completed_verbs") or []
    base["pending_verbs"] = base.get("pending_verbs") or []
    return base


def save_state(slug: str, state: dict) -> None:
    paths.save_json_atomic(_state_file(slug), state)


def mark_pending(slug: str, verb: str) -> None:
    s = load_state(slug)
    if verb not in s["pending_verbs"] and verb not in s["completed_verbs"]:
        s["pending_verbs"].append(verb)
    save_state(slug, s)


def mark_completed(slug: str, verb: str) -> None:
    s = load_state(slug)
    s["pending_verbs"] = [v for v in s["pending_verbs"] if v != verb]
    if verb not in s["completed_verbs"]:
        s["completed_verbs"].append(verb)
    save_state(slug, s)


def record_artifact(slug: str, kind: str, name: str, content: str) -> Path:
    target = paths.business_dir(slug) / "artifacts" / kind / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _audit_file():
    return paths.data_root() / "audit.jsonl"


def audit(record: dict) -> None:
    enriched = dict(record)
    enriched["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    paths.append_jsonl(_audit_file(), enriched)


def _approvals_file():
    return paths.data_root() / "approvals.jsonl"


def queue_approval(action: Action) -> str:
    aid = uuid.uuid4().hex[:12]
    paths.append_jsonl(_approvals_file(), {
        "id": aid,
        "status": "pending",
        "business": action.business,
        "verb": action.verb,
        "agent": action.agent,
        "action_class": action.action_class.value,
        "preconditions": list(action.preconditions),
        "payload": action.payload,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return aid


def list_approvals(status: str | None = None) -> list[dict]:
    rows = paths.read_jsonl(_approvals_file())
    # Collapse to the latest record per id (resolve_approval rewrites the file,
    # but guard against partial states defensively).
    latest: dict[str, dict] = {}
    for r in rows:
        latest[r["id"]] = r
    out = list(latest.values())
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    return out


def resolve_approval(approval_id: str, status: str) -> bool:
    f = _approvals_file()
    rows = paths.read_jsonl(f)
    found = False
    for r in rows:
        if r.get("id") == approval_id:
            r["status"] = status
            found = True
    if not found:
        return False
    # Rewrite the whole file atomically as JSONL.
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(f)
    return True
