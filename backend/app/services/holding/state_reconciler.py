"""Holding State Reconciler (§8-10, §17) — the material-change engine.

Diffs a PRIOR HoldingDigitalTwin snapshot against a NEW one and emits typed MaterialChange[].
Materiality is DETERMINISTIC (§9): status/health transitions are always material, identical values
never are, and numeric metrics cross explicit versioned rules — no LLM is asked whether a tiny diff
"matters". Only material changes are emitted; a materially-identical cycle yields [] (§17). This
extends the pure-diff discipline of holding/watch.py to the twin's per-company + holding-level state;
it does NOT create a second observer or task queue.

Pure + injectable: reconcile() takes two snapshot dicts and never touches a DB.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

MATERIALITY_VERSION = "1.0.0"   # §9/§14: version the formula, don't hide it behind an opaque score

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}

# Statuses that mean a company/plane is degraded — a transition INTO one of these ranks HIGH (§9).
_DEGRADED_STATUS = {"DEGRADED", "DOWN", "OFFLINE", "BLOCKED", "FAILED", "INCIDENT", "PAUSED"}


@dataclass
class MaterialChange:
    change_type: str
    scope: str          # "holding" or a company_id
    key: str
    prev: Any
    now: Any
    severity: str       # CRITICAL | HIGH | MEDIUM | INFO
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def fingerprint(snapshot: dict) -> dict:
    """Flatten a twin snapshot into comparable (scope, key) → value facts. Only fields with defined
    materiality rules are included, so the diff can be fully deterministic. Best-effort / fail-open."""
    fp: dict[tuple, Any] = {}
    if not isinstance(snapshot, dict) or not snapshot:
        return fp                                   # empty/None ⇒ no fingerprint ⇒ baseline (§17)
    for c in snapshot.get("companies", []) or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("company_id", "?")
        fp[(cid, "status")] = c.get("status")
        fp[(cid, "incident_count")] = len(c.get("active_incidents", []) or [])
        fp[(cid, "owner_action_count")] = len(c.get("owner_actions_required", []) or [])
        fp[(cid, "present")] = True
    sr = snapshot.get("shared_resources", {}) or {}
    fp[("holding", "workers_online")] = sr.get("workers_online")
    fp[("holding", "capabilities_available")] = sr.get("capabilities_available")
    fp[("holding", "autonomy_overall")] = snapshot.get("autonomy_overall")
    return fp


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def reconcile(prev_snapshot: dict | None, cur_snapshot: dict) -> list[MaterialChange]:
    """PRIOR twin snapshot + NEW twin snapshot → MaterialChange[]. Empty on first run (no prior) and
    empty when nothing material changed (§17). Deterministic; a polling cycle alone creates no work."""
    prev, cur = fingerprint(prev_snapshot or {}), fingerprint(cur_snapshot)
    if not prev:
        return []                                   # baseline (first observation) is silent (§17)

    changes: list[MaterialChange] = []

    def emit(ct, scope, key, was, now, sev, reason):
        changes.append(MaterialChange(ct, scope, key, was, now, sev, reason))

    # company appearing / disappearing between cycles
    prev_ids = {s for (s, k) in prev if k == "present"}
    cur_ids = {s for (s, k) in cur if k == "present"}
    for cid in sorted(cur_ids - prev_ids):
        emit("COMPANY_ADDED", cid, "present", False, True, "INFO", f"{cid} entered the twin")
    for cid in sorted(prev_ids - cur_ids):
        emit("COMPANY_REMOVED", cid, "present", True, False, "MEDIUM", f"{cid} left the twin")

    for (scope, key), now in cur.items():
        if key == "present" or (scope, key) not in prev:
            continue
        was = prev[(scope, key)]
        if was == now:
            continue                                # §9: same value is never material

        if key == "status":
            sev = "HIGH" if str(now).upper() in _DEGRADED_STATUS else "MEDIUM"
            emit("STATUS_CHANGED", scope, key, was, now, sev, f"{scope} status {was} → {now}")

        elif key == "incident_count" and _num(was) and _num(now):
            if now > was:
                emit("INCIDENT_OPENED", scope, key, was, now, "CRITICAL", f"{scope} incidents {was} → {now}")
            else:
                emit("INCIDENT_RESOLVED", scope, key, was, now, "INFO", f"{scope} incidents {was} → {now}")

        elif key == "owner_action_count" and _num(was) and _num(now):
            if now > was:
                emit("OWNER_BLOCKER_ADDED", scope, key, was, now, "HIGH", f"{scope} owner actions {was} → {now}")
            else:
                emit("OWNER_BLOCKER_RESOLVED", scope, key, was, now, "INFO", f"{scope} owner actions {was} → {now}")

        elif key == "workers_online" and _num(was) and _num(now):
            if was > 0 and now == 0:
                emit("WORKER_PLANE_DEGRADED", scope, key, was, now, "HIGH", "worker plane went offline")
            elif was == 0 and now > 0:
                emit("WORKER_PLANE_RECOVERED", scope, key, was, now, "INFO", "worker plane back online")
            # was>0 and now>0 (e.g. 3→2) is NOT material by itself (§9)

        elif key == "capabilities_available" and _num(was) and _num(now):
            if now < was:
                emit("CAPABILITY_UNAVAILABLE", scope, key, was, now, "HIGH", f"available capabilities {was} → {now}")
            else:
                emit("CAPABILITY_RECOVERED", scope, key, was, now, "INFO", f"available capabilities {was} → {now}")

        elif key == "autonomy_overall":
            sev = "HIGH" if str(now).upper() in _DEGRADED_STATUS else "INFO"
            emit("AUTONOMY_CHANGED", scope, key, was, now, sev, f"autonomy {was} → {now}")

    changes.sort(key=lambda c: _SEV_ORDER.get(c.severity, 9))
    return changes


def reconcile_result(prev_snapshot: dict | None, cur_snapshot: dict) -> dict:
    """Envelope for the continuous cycle: changes + a NO_MATERIAL_CHANGE verdict (§17) + the formula
    version so the caller can audit materiality decisions. This is what the cycle records/acts on."""
    changes = reconcile(prev_snapshot, cur_snapshot)
    return {
        "materiality_version": MATERIALITY_VERSION,
        "baseline": not fingerprint(prev_snapshot or {}),
        "material_change": bool(changes),
        "verdict": "MATERIAL_CHANGE" if changes else "NO_MATERIAL_CHANGE",
        "changes": [c.as_dict() for c in changes],
    }


if __name__ == "__main__":
    from app.services.holding.test_state_reconciler import run
    run()
