"""§97 global kill switch + brakes — a READ-ONLY projection of the REAL brakes that already exist, plus ONE
durable owner-only STOP record that the existing brake readers honor.

This module adds NO new authority flag and NO parallel policy. Every brake row below is derived from a
flag/policy that some EXISTING module enforces (named in ``enforced_by``), and reports honestly:

  ON             the activity is enabled by its real flag(s) (and, where §97 applies, STOP is not engaged)
  OFF            the activity is disabled by its real flag(s) / conditions / STOP
  UNAVAILABLE    the controlling flag could not be read (config unreadable) — never reported as a fake OFF
  POLICY_LOCKED  no switch in this app can enable the activity (disabled by construction/policy) — the
                 brake is NOT controllable here and never pretends to be

A switch may NEVER claim to disable something it does not control: each row lists exactly the flags it
reads (``controlled_by``) and what STOP does to it (``halted_by_stop``).

STOP_AUTONOMOUS_EXECUTION (§97): one durable record (``holding_brakes`` table, self-creating; injectable
store for tests). Engaged → ``stop_engaged()`` is True → the EXISTING composition points read it and force
their config-read brakes OFF: ``holding_cycle.build_live_engine`` (brakes #1/#2/#3) and
``a2_dispatch.enqueue_a2_coding_job`` (the A2 / self-improvement enqueue path). STOP halts NEW consequential work
(the next engine build / A2 enqueue refuses); it does NOT undo work already started — an already-built
engine finishes its bounded cycle and claimed/running worker jobs run to completion or lease expiry — and
the STOP report says so, listing the in-flight jobs truthfully (or UNAVAILABLE when the queue is unreadable).
Unreadable STOP record → treated as ENGAGED (fail closed, same convention as build_live_engine's
"config unavailable → every brake engaged" and cycle_store.try_lock "DB down → do not run").

Owner-only mutation: ``stop()``/``release()`` require an OWNER principal holding SCOPE_KAI_ULTRA (the same
identity model ``require_kai_ultra`` gates on); every mutation is audited via governance.audit_log. No
execution happens here. STOP never mutates config flags (a static test asserts it).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

BRAKES_VERSION = "1.0.0"

ON, OFF, UNAVAILABLE, POLICY_LOCKED = "ON", "OFF", "UNAVAILABLE", "POLICY_LOCKED"
ENGAGED, RELEASED = "ENGAGED", "RELEASED"
STOP = "STOP_AUTONOMOUS_EXECUTION"
_IN_FLIGHT = ("claimed", "running")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── the ONE durable STOP record ──────────────────────────────────────────────────────────────────
_DDL = ("CREATE TABLE IF NOT EXISTS holding_brakes (key TEXT PRIMARY KEY, record JSONB NOT NULL, "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")


class DbStopStore:
    """get() -> record dict ({} = never engaged) or None (UNREADABLE → callers fail closed). set() -> bool."""
    KEY = STOP

    def get(self):
        try:
            from sqlalchemy import text
            from app.database import SessionLocal
            db = SessionLocal()
            try:
                db.execute(text(_DDL)); db.commit()
                r = db.execute(text("SELECT record FROM holding_brakes WHERE key = :k"), {"k": self.KEY}).fetchone()
                if not r:
                    return {}
                return r[0] if isinstance(r[0], dict) else json.loads(r[0])
            finally:
                db.close()
        except Exception:   # noqa: BLE001 — unreadable, never guessed
            return None

    def set(self, rec: dict) -> bool:
        try:
            from sqlalchemy import text
            from app.database import SessionLocal
            db = SessionLocal()
            try:
                db.execute(text(_DDL))
                db.execute(text("INSERT INTO holding_brakes (key, record) VALUES (:k, CAST(:r AS JSONB)) "
                                "ON CONFLICT (key) DO UPDATE SET record = EXCLUDED.record, updated_at = now()"),
                           {"k": self.KEY, "r": json.dumps(rec, default=str)})
                db.commit()
                return True
            finally:
                db.close()
        except Exception:   # noqa: BLE001
            return False


class InMemoryStopStore:
    """Test store — same surface as DbStopStore. readable=False simulates an unreadable record."""
    def __init__(self, rec: dict | None = None, *, readable: bool = True, writable: bool = True):
        self.rec = dict(rec or {}); self.readable = readable; self.writable = writable

    def get(self):
        return dict(self.rec) if self.readable else None

    def set(self, rec: dict) -> bool:
        if not self.writable:
            return False
        self.rec = dict(rec)
        return True


def stop_record(store=None) -> dict | None:
    """The durable STOP record: {} never engaged, {"engaged": bool, ...}, or None when unreadable."""
    return (store or DbStopStore()).get()


def stop_engaged(store=None) -> bool:
    """§97 truth the existing brake readers consult. Unreadable → True (fail closed)."""
    rec = stop_record(store)
    return True if rec is None else bool(rec.get("engaged"))


# ── flag reading (never invents a value: unreadable → None → UNAVAILABLE) ───────────────────────
_ALL_FLAGS = (
    "KAI_HOLDING_WATCH_ENABLED", "KAI_HOLDING_CYCLE_ENABLED",
    "KAI_SELF_IMPROVEMENT_DETECT_ENABLED", "KAI_PROACTIVE_ENABLED",
    "KAI_CAPABILITY_EXECUTION_ENABLED", "HOLDING_AUTONOMY_ENABLED", "KAI_A2_EXECUTION_ENABLED",
    "KAI_SELF_IMPROVEMENT_ENABLED", "KAI_HOLDING_DELIVERY_ENABLED",
    "KAI_CYBER_OPS_ENABLED", "KAI_VOICE_ENABLED",
    "KAI_OS_LAB_ENABLED", "KAI_OS_LAB_ULTRON_RUNTIME_ENABLED", "KAI_OS_LAB_VIRTME_NG_ENABLED",
    "KAI_OS_LAB_SYZKALLER_ENABLED",
)


def _load_default_settings():
    from app.config import settings
    return settings


def _read_flags(settings) -> dict:
    """{flag: bool|None}. Flags absent from Settings (the OS-lab ones) are honestly False = OFF, exactly as
    their readers (getattr(settings, flag, False)) see them; a None settings → every flag None."""
    if settings is None:
        return {k: None for k in _ALL_FLAGS}
    out = {}
    for k in _ALL_FLAGS:
        try:
            out[k] = bool(getattr(settings, k, False))
        except Exception:   # noqa: BLE001
            out[k] = None
    return out


def _combine(flags: dict, names: tuple, mode: str):
    vals = [flags.get(n) for n in names]
    if any(v is None for v in vals):
        return None
    return any(vals) if mode == "any" else all(vals)


# (brake, flags, any|all, enforced_by, halted_by_stop)
_FLAG_BRAKES = (
    ("OBSERVATION", ("KAI_HOLDING_WATCH_ENABLED", "KAI_HOLDING_CYCLE_ENABLED"), "any",
     "workers.holding_tasks watch/cycle ticks (read-only observe→reconcile; grants no execution)", False),
    ("DETECTION", ("KAI_SELF_IMPROVEMENT_DETECT_ENABLED", "KAI_PROACTIVE_ENABLED"), "any",
     "self_improvement_detect.run + proactive_engine.run (read-only detection; no write authority)", False),
    ("A1_VERIFICATION", ("KAI_CAPABILITY_EXECUTION_ENABLED", "HOLDING_AUTONOMY_ENABLED"), "all",
     "holding_cycle.build_live_engine brakes #1 + #2 (A0/A1 certified reads only)", True),
    ("A2_PREPARATION", ("KAI_CAPABILITY_EXECUTION_ENABLED", "HOLDING_AUTONOMY_ENABLED", "KAI_A2_EXECUTION_ENABLED"),
     "all", "build_live_engine brake #3 + a2_dispatch.brakes_all_on (staging-only, prepare-only, never merges)", True),
    ("SELF_IMPROVEMENT", ("KAI_CAPABILITY_EXECUTION_ENABLED", "HOLDING_AUTONOMY_ENABLED", "KAI_A2_EXECUTION_ENABLED",
                          "KAI_SELF_IMPROVEMENT_ENABLED"), "all",
     "self_improvement.dispatch_self_improvement (brake #4, subordinate) → a2_dispatch", True),
)


def _row(brake, state, *, controlled_by, enforced_by, halted_by_stop, now, **extra) -> dict:
    return {"brake": brake, "state": state, "controlled_by": list(controlled_by), "enforced_by": enforced_by,
            "halted_by_stop": halted_by_stop, "observed_at": now, **extra}


def _flag_rows(flags: dict, settings, stopped: bool | None, now: str) -> list[dict]:
    env = str(getattr(settings, "APP_ENV", "") or "").lower() if settings is not None else None
    rows = []
    for brake, names, mode, enforced_by, halted in _FLAG_BRAKES:
        v = _combine(flags, names, mode)
        reasons = []
        if v is None:
            state = UNAVAILABLE
            reasons.append("controlling flag(s) unreadable — config unavailable")
        else:
            state = ON if v else OFF
            if not v:
                reasons.append("flag(s) off: " + ", ".join(n for n in names if not flags.get(n)))
            if brake in ("A2_PREPARATION", "SELF_IMPROVEMENT") and v and env != "staging":
                state = OFF
                reasons.append(f"APP_ENV={env or UNAVAILABLE!s} — a2_dispatch is STAGING_ONLY")
        stop_applied = False
        if halted and state != UNAVAILABLE and stopped is not False:
            # STOP engaged (or unreadable → treated engaged) forces the consequential brakes OFF
            if state == ON:
                stop_applied = True
            state = OFF
            reasons.append("STOP engaged" if stopped else "STOP record unreadable → treated as ENGAGED (fail closed)")
        rows.append(_row(brake, state, controlled_by=names, enforced_by=enforced_by, halted_by_stop=halted, now=now,
                         flags={n: (flags.get(n) if flags.get(n) is not None else UNAVAILABLE) for n in names},
                         stop_applied=stop_applied, reasons=reasons,
                         mutable_via="config/env (redeploy)" + (" + STOP record" if halted else "")))
    return rows


def _external_comm_row(flags: dict, env: dict, now: str) -> dict:
    flag = flags.get("KAI_HOLDING_DELIVERY_ENABLED")
    # channel PRESENCE only (delivery.py reads the same env keys) — values are never read into the report
    channel = bool(env.get("TELEGRAM_BOT_TOKEN")) and bool(env.get("TELEGRAM_CHAT_ID"))
    if flag is None:
        state, reason = UNAVAILABLE, "KAI_HOLDING_DELIVERY_ENABLED unreadable — config unavailable"
    elif flag and channel:
        state, reason = ON, "opt-in flag on and a channel is configured"
    elif flag:
        state, reason = OFF, "opt-in flag on but no channel configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID unset)"
    else:
        state, reason = OFF, "KAI_HOLDING_DELIVERY_ENABLED off (default)"
    return _row("EXTERNAL_COMMUNICATION", state, controlled_by=("KAI_HOLDING_DELIVERY_ENABLED", "TELEGRAM_* channel presence"),
                enforced_by="delivery.deliver_briefing / delivery.send_alert (the only senders)", halted_by_stop=False,
                now=now, flags={"KAI_HOLDING_DELIVERY_ENABLED": flag if flag is not None else UNAVAILABLE,
                                "channel_configured": channel},
                reasons=[reason], mutable_via="config/env (redeploy) — NOT controlled by STOP")


def _financial_row(settings, now: str) -> dict:
    """No switch in this app enables financial execution: Settings declares no MONEY_MODE field (App A /
    env owns it; readers default to MOCK), status.autonomy_status hardcodes financial_execution=DISABLED, and
    the privileged security caps never touch MONEY_MODE (§59). POLICY_LOCKED — never a controllable OFF."""
    observed = getattr(settings, "MONEY_MODE", None) if settings is not None else None
    return _row("FINANCIAL_EXECUTION", POLICY_LOCKED, controlled_by=(), halted_by_stop=False, now=now,
                enforced_by="no execution path exists in this app; MONEY_MODE is App A/env-owned; status.financial_execution=DISABLED",
                flags={"MONEY_MODE_observed": observed if observed is not None else "NOT_DECLARED_IN_THIS_APP (readers default MOCK)"},
                reasons=["disabled by construction — no flag here can enable it; STOP neither controls nor claims it"],
                mutable_via="NONE in this app")


def _restricted_security_row(flags: dict, now: str, *, manifests_loader=None) -> dict:
    """Read the REAL privileged security manifests: they ship DISABLED / never selectable by construction.
    If any ever became selectable this row would honestly say ON (it is derived, not asserted)."""
    try:
        load = manifests_loader or _default_security_manifests
        priv = load()
    except Exception:   # noqa: BLE001
        return _row("RESTRICTED_SECURITY", UNAVAILABLE, controlled_by=(), halted_by_stop=False, now=now,
                    enforced_by="security.capabilities privileged manifests", reasons=["manifests unreadable"],
                    flags={"KAI_CYBER_OPS_ENABLED (read-only surface)": flags.get("KAI_CYBER_OPS_ENABLED", UNAVAILABLE)},
                    mutable_via=UNAVAILABLE)
    selectable = sorted(m.id for m in priv if m.selectable())
    state = ON if selectable else POLICY_LOCKED
    return _row("RESTRICTED_SECURITY", state, controlled_by=(), halted_by_stop=False, now=now,
                enforced_by="security.capabilities: PRIVILEGED caps availability=DISABLED, activation=DISABLED (manifest.selectable() False)",
                flags={"KAI_CYBER_OPS_ENABLED (read-only surface only)": (flags.get("KAI_CYBER_OPS_ENABLED")
                                                                          if flags.get("KAI_CYBER_OPS_ENABLED") is not None else UNAVAILABLE),
                       "privileged_caps": sorted(m.id for m in priv), "selectable": selectable},
                reasons=([f"privileged caps selectable: {selectable}"] if selectable else
                         ["contain/block/revoke/rollback are DISABLED and never selectable — no flag enables them"]),
                mutable_via="NONE (manifest policy)")


def _default_security_manifests():
    from app.services.security.capabilities import list_security_capabilities, PRIVILEGED_CAP_IDS
    return [m for m in list_security_capabilities() if m.id in PRIVILEGED_CAP_IDS]


def _os_lab_row(settings, now: str) -> dict:
    try:
        from app.services.holding.os_lab.runtimes import (_runtime_on, _is_production, FLAG_OS_LAB, FLAG_ULTRON,
                                                          FLAG_VIRTME_NG, FLAG_SYZKALLER)
    except Exception:   # noqa: BLE001
        return _row("OS_LAB_ACTIVE_RUNTIME", UNAVAILABLE, controlled_by=(), halted_by_stop=False, now=now,
                    enforced_by="holding.os_lab.runtimes", reasons=["os_lab module unreadable"], mutable_via=UNAVAILABLE)
    names = (FLAG_OS_LAB, FLAG_ULTRON, FLAG_VIRTME_NG, FLAG_SYZKALLER)
    if settings is None:
        return _row("OS_LAB_ACTIVE_RUNTIME", UNAVAILABLE, controlled_by=names, halted_by_stop=False, now=now,
                    enforced_by="os_lab.runtimes._runtime_on", reasons=["config unavailable"], mutable_via=UNAVAILABLE)
    on = {f: _runtime_on(settings, f) for f in (FLAG_ULTRON, FLAG_VIRTME_NG, FLAG_SYZKALLER)}
    if _is_production(settings):
        state, reason = POLICY_LOCKED, "APP_ENV=production — lab runtimes are DISABLED regardless of flag (os_lab.runtimes._runtime_on)"
    else:
        state = ON if any(on.values()) else OFF
        reason = ("runtime flag(s) on: " + ", ".join(k for k, v in on.items() if v)) if any(on.values()) \
            else "lab master + runtime flags off (none declared in Settings → getattr False)"
    return _row("OS_LAB_ACTIVE_RUNTIME", state, controlled_by=names, halted_by_stop=False, now=now,
                enforced_by="os_lab.runtimes._runtime_on (not production AND master AND runtime flag) + RestrictedRuntime.can_run",
                flags={f: bool(getattr(settings, f, False)) for f in names}, reasons=[reason],
                mutable_via="config/env (non-production only) — NOT controlled by STOP")


def _stop_row(rec: dict | None, now: str) -> dict:
    halts = [b for b, _n, _m, _e, h in _FLAG_BRAKES if h]
    no_halt = [b for b, _n, _m, _e, h in _FLAG_BRAKES if not h] + \
              ["EXTERNAL_COMMUNICATION", "FINANCIAL_EXECUTION", "RESTRICTED_SECURITY", "OS_LAB_ACTIVE_RUNTIME",
               "owner-driven /admin/capabilities + /admin/holding/command invocations (not autonomous)"]
    if rec is None:
        state, treated = UNAVAILABLE, ENGAGED
    else:
        state, treated = (ENGAGED if rec.get("engaged") else RELEASED), (ENGAGED if rec.get("engaged") else RELEASED)
    return {"brake": STOP, "state": state, "treated_as": treated, "record": rec if rec else {},
            "controlled_by": ["holding_brakes durable record (brakes.stop / brakes.release, owner-only, audited)"],
            "honored_by": ["holding_cycle.build_live_engine (config-read brakes #1/#2/#3 forced OFF)",
                           "a2_dispatch.enqueue_a2_coding_job (A2 + self-improvement enqueue refused: STOP_ENGAGED)"],
            "halts": halts, "does_not_halt": no_halt,
            "latency": "next build_live_engine / A2 enqueue; an already-built engine finishes its bounded cycle; "
                       "claimed/running worker jobs run to completion or lease expiry (never undone, never hidden)",
            "observed_at": now}


def brakes(*, settings=None, load_settings: Callable | None = None, stop_store=None, env: dict | None = None,
           manifests_loader=None, now: str = "") -> dict:
    """§97 read-only brake board. Every row is derived from a real flag/policy/record — no invented state."""
    now = now or _now_iso()
    if settings is None:
        try:
            settings = (load_settings or _load_default_settings)()
        except Exception:   # noqa: BLE001 — config unreadable → UNAVAILABLE rows, never fake OFF
            settings = None
    flags = _read_flags(settings)
    rec = stop_record(stop_store)
    stopped = None if rec is None else bool(rec.get("engaged"))
    rows = [_stop_row(rec, now)]
    rows += _flag_rows(flags, settings, stopped, now)
    rows.append(_external_comm_row(flags, env if env is not None else os.environ, now))
    rows.append(_financial_row(settings, now))
    rows.append(_restricted_security_row(flags, now, manifests_loader=manifests_loader))
    rows.append(_os_lab_row(settings, now))
    return {"version": BRAKES_VERSION, "observed_at": now, "stop_engaged": (True if stopped is None else stopped),
            "stop_record_state": rows[0]["state"], "brakes": rows,
            "flags": {k: (v if v is not None else UNAVAILABLE) for k, v in flags.items()},
            "vocabulary": {"state": [ON, OFF, UNAVAILABLE, POLICY_LOCKED], "stop": [ENGAGED, RELEASED, UNAVAILABLE]}}


# ── owner-only mutation (§97 / §0#11) ────────────────────────────────────────────────────────────
def _require_owner(principal) -> str:
    """Same identity model require_kai_ultra gates on: OWNER role holding SCOPE_KAI_ULTRA. Fail closed."""
    try:
        from core.operator_session import ROLE_OWNER, SCOPE_KAI_ULTRA
    except Exception as e:   # noqa: BLE001
        raise PermissionError("owner gate unavailable — brakes mutation refused (fail closed)") from e
    has = getattr(principal, "has", None)
    if principal is None or getattr(principal, "role", None) != ROLE_OWNER or not callable(has) or not has(SCOPE_KAI_ULTRA):
        raise PermissionError("owner access required (kai.ultra) — brakes are owner-only (§97/§0#11)")
    return f"{principal.role}:{getattr(principal, 'source', '?')}"


def _in_flight(jobs_source=None) -> dict:
    """Already-started worker jobs, reported truthfully — or UNAVAILABLE when the queue is unreadable."""
    try:
        load = jobs_source or _default_worker_plane
        plane = load()
    except Exception:   # noqa: BLE001
        plane = None
    if not isinstance(plane, dict):
        return {"state": UNAVAILABLE, "reason": "holding_worker_jobs unreadable — in-flight work UNKNOWN, not assumed zero",
                "note": "STOP does not undo already-started work"}
    rows = [{"id": j.get("id"), "status": j.get("status"), "worker": j.get("worker"), "claimed_by": j.get("claimed_by"),
             "task_id": str((j.get("task") or {}).get("task_id") or ""), "created_at": j.get("created_at")}
            for j in (plane.get("rows") or []) if j.get("status") in _IN_FLIGHT]
    counts = plane.get("counts") or {}
    return {"state": "MEASURED", "counts": {s: int(counts.get(s, 0)) for s in _IN_FLIGHT}, "jobs": rows,
            "note": "already-started work is NOT undone by STOP — it runs to completion or lease expiry; listed as-is"}


def _default_worker_plane():
    from app.services.holding.resource_governor import _worker_plane
    return _worker_plane()


def _audit(audit, action: str, actor: str, *, inputs: dict, outputs: dict, success: bool) -> None:
    try:
        rec = audit or _default_audit
        rec(action=action, scope="holding.brakes", actor=actor, destructive=False, approved=True,
            inputs=inputs, outputs=outputs, success=success)
    except Exception:   # noqa: BLE001 — audit failure never blocks a STOP
        pass


def _default_audit(**kw):
    from app.services.governance.audit_log import record_action
    record_action(**kw)


def _mutate(principal, *, engaged: bool, reason: str, stop_store, jobs_source, audit, now: str) -> dict:
    actor = _require_owner(principal)          # raises before anything is read or written
    store = stop_store or DbStopStore()
    now = now or _now_iso()
    rec = {"engaged": engaged, "reason": str(reason or "")[:500], "actor": actor, "at": now}
    persisted = store.set(rec)
    verb = "stop" if engaged else "release"
    if not persisted:
        report = {"action": verb, "engaged": UNAVAILABLE, "state": UNAVAILABLE, "actor": actor, "at": now,
                  "error": "STOP_PERSIST_FAILED — the record was NOT written; nothing is claimed to have "
                           + ("stopped" if engaged else "resumed")}
        _audit(audit, f"holding.brakes.{verb}", actor, inputs={"reason": reason}, outputs=report, success=False)
        return report
    board = brakes(stop_store=store, now=now)
    stop_row = board["brakes"][0]
    report = {"action": verb, "engaged": engaged, "state": stop_row["state"], "actor": actor, "at": now,
              "reason": rec["reason"], "halts": stop_row["halts"], "does_not_halt": stop_row["does_not_halt"],
              "latency": stop_row["latency"], "in_flight": _in_flight(jobs_source),
              "brakes_after": {r["brake"]: r["state"] for r in board["brakes"]}}
    _audit(audit, f"holding.brakes.{verb}", actor, inputs={"reason": reason}, outputs=report, success=True)
    return report


def stop(principal, *, reason: str, stop_store=None, jobs_source=None, audit=None, now: str = "") -> dict:
    """§97 STOP AUTONOMOUS EXECUTION. Owner-only. Writes the one durable record; the existing brake readers
    refuse NEW consequential work from the next engine build / A2 enqueue. Reports in-flight work as-is."""
    return _mutate(principal, engaged=True, reason=reason, stop_store=stop_store, jobs_source=jobs_source,
                   audit=audit, now=now)


def release(principal, *, reason: str, stop_store=None, jobs_source=None, audit=None, now: str = "") -> dict:
    """Owner-only release of STOP. Grants nothing: the config flags stay authoritative."""
    return _mutate(principal, engaged=False, reason=reason, stop_store=stop_store, jobs_source=jobs_source,
                   audit=audit, now=now)


if __name__ == "__main__":
    from app.services.holding.test_brakes import run
    run()
