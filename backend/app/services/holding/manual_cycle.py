"""Manual single-cycle control (owner-only, staging-cert). Runs EXACTLY ONE existing Holding cycle.

This is a thin bridge — it creates NO new engine/planner/queue/scheduler. It reuses build_live_engine
(both brakes authoritative) + run_persistent_cycle over the HoldingDigitalTwin, loads the authoritative
PRIOR snapshot server-side (the client can never manufacture a MaterialChange), persists the current
snapshot for the next cycle, and returns a normalized CycleRecord. Single-flight + idempotency +
timeout are enforced via an injected store (DB in prod, in-memory in tests). It grants no authority:
autonomy-off ⇒ 0 auto actions; capability-off ⇒ blocked tasks — no loophole.
"""
from __future__ import annotations


class ManualCycleDenied(Exception):
    """Malformed/forbidden request (arbitrary task/capability/company/snapshot/authority override)."""


class CycleRunning(Exception):
    """A cycle is already running for this holding (single-flight) → 409."""


# §3 — the request may carry ONLY a non-authoritative idempotency_key. Everything else is refused so the
# endpoint can never inject work, choose a capability/company, override a brake, or supply prior state.
_FORBIDDEN_BODY_KEYS = frozenset({
    "company", "company_id", "task", "task_type", "capability", "capability_id", "operation", "command",
    "shell", "prompt", "action_class", "autonomy", "autonomy_override", "execution", "execution_override",
    "snapshot", "prior_snapshot", "evidence", "worker", "environment", "app_env", "role", "approved",
    "scopes", "scope", "grant", "money_mode", "force"})


def validate_request(body: dict | None) -> dict:
    """Return the safe request (only idempotency_key) or raise ManualCycleDenied."""
    body = body or {}
    if not isinstance(body, dict):
        raise ManualCycleDenied("body must be an object")
    bad = _FORBIDDEN_BODY_KEYS & {str(k).lower() for k in body}
    if bad:
        raise ManualCycleDenied(f"forbidden field(s): {sorted(bad)[:5]}")
    key = body.get("idempotency_key")
    return {"idempotency_key": str(key)[:128] if key else ""}


# §11 — normalized, SAFE cycle-record fields (never secrets/cookies/env/raw logs/reasoning/prompts).
def normalize_record(rec: dict) -> dict:
    r = rec or {}
    disp = r.get("plan_dispositions") or {}
    return {
        "cycle_id": r.get("cycle_id"), "status": r.get("status") or r.get("verdict"),
        "started_at": r.get("started_at"), "completed_at": r.get("completed_at"),
        "companies_reviewed": r.get("companies_reviewed", 0),
        "material_changes_count": r.get("material_changes", 0),
        "plan_updates_count": sum(disp.values()) if isinstance(disp, dict) else r.get("plan_changes", 0),
        "tasks_considered": r.get("tasks_considered", 0),
        "auto_actions_executed": r.get("tasks_executed", r.get("auto_executed", 0)),
        "auto_actions_failed": r.get("tasks_failed", r.get("failed", 0)),
        "owner_actions_created": r.get("owner_actions_created", r.get("owner_queued", 0)),
        "owner_actions_resolved": r.get("owner_actions_resolved", 0),
        "autonomy_off": r.get("autonomy_off", 0),
        "evidence_refs": (r.get("evidence_refs") or [])[:50],
        "duration_ms": r.get("duration_ms", 0),
    }


class InMemoryCycleStore:
    """Test store — the DB store (cycle_store.DbCycleStore) has the same surface."""
    def __init__(self):
        self._prior = {}; self._runs = {}; self._locks = {}; self._seq = 0

    def next_cycle_id(self, holding_id, now):
        self._seq += 1
        return f"cy-{holding_id}-{self._seq}"

    def get_run(self, key):
        return self._runs.get(key)

    def save_run(self, key, rec):
        self._runs[key] = rec

    def try_lock(self, holding_id, lease_s, now):
        if self._locks.get(holding_id):
            return None
        import secrets
        token = secrets.token_hex(4)
        self._locks[holding_id] = token
        return token

    def release_lock(self, holding_id, token=None):
        if self._locks.get(holding_id) == token:   # lease-scoped: only the holder releases
            self._locks.pop(holding_id, None)

    def load_prior(self, holding_id):
        return self._prior.get(holding_id)

    def save_snapshot(self, holding_id, snapshot, cycle_id):
        self._prior[holding_id] = snapshot


def run_manual_cycle(store, engine, snapshot_fn, *, holding_id: str = "wheellsverse", now: str = "",
                     idempotency_key: str = "", lock_lease_s: int = 120) -> dict:
    """Run ONE cycle. §8 idempotent replay, §7 single-flight (409), §9 authoritative prior snapshot,
    §10 exactly one cycle (no scheduler/loop). Returns a normalized record. The brakes live in the
    engine (build_live_engine) — this never overrides them."""
    from app.services.holding.holding_cycle import run_persistent_cycle
    if idempotency_key:
        prior_run = store.get_run(idempotency_key)
        if prior_run is not None:
            return {**prior_run, "replayed": True}
    token = store.try_lock(holding_id, lock_lease_s, now)   # lease token (None if already running)
    if not token:
        raise CycleRunning("a holding cycle is already running")
    try:
        prior = store.load_prior(holding_id)            # authoritative prior state (None on first run)
        current = snapshot_fn()                          # live twin snapshot — client cannot supply it
        cycle_id = store.next_cycle_id(holding_id, now)
        companies = len((current or {}).get("companies", []))
        rec = run_persistent_cycle(prior, current, engine=engine, cycle_id=cycle_id, now=now,
                                   companies_reviewed=companies)
        store.save_snapshot(holding_id, current, cycle_id)   # persist for the NEXT cycle's comparison
        out = normalize_record(rec.as_dict() if hasattr(rec, "as_dict") else rec)
        if idempotency_key:
            store.save_run(idempotency_key, out)
        return out
    finally:
        store.release_lock(holding_id, token)            # §10 token-scoped: only clears OUR lease


if __name__ == "__main__":
    from app.services.holding.test_manual_cycle import run
    run()
