"""§97 kill switch + brakes — honesty/composition guard. Zero-framework (mirrors test_registry.py). Settings,
STOP store, env, manifests and the job queue are injected; the real config/DB is touched read-only. Run (from backend/):
    python3 -m app.services.holding.test_brakes
"""
import inspect
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))   # repo root so `core.operator_session` resolves

from app.services.holding import brakes as br                                          # noqa: E402
from app.services.holding.brakes import (                                              # noqa: E402
    brakes, stop, release, stop_engaged, stop_state, InMemoryStopStore, DbStopStore,
    ON, OFF, UNAVAILABLE, POLICY_LOCKED, ENGAGED, RELEASED, STOP, STOP_ENGAGED, STOP_UNREADABLE)
from core.operator_session import (principal_for_role, ROLE_OWNER, ROLE_OPERATOR, ROLE_VIEWER,   # noqa: E402
                                   Principal, SCOPE_KAI_ULTRA)

NOW = "2026-09-04T12:00:00+00:00"
ALL_BRAKES = [STOP, "OBSERVATION", "DETECTION", "A1_VERIFICATION", "A2_PREPARATION", "SELF_IMPROVEMENT",
              "EXTERNAL_COMMUNICATION", "FINANCIAL_EXECUTION", "RESTRICTED_SECURITY", "OS_LAB_ACTIVE_RUNTIME"]
HALTED = ["A1_VERIFICATION", "A2_PREPARATION", "SELF_IMPROVEMENT"]
NOT_HALTED = ["OBSERVATION", "DETECTION", "EXTERNAL_COMMUNICATION", "FINANCIAL_EXECUTION",
              "RESTRICTED_SECURITY", "OS_LAB_ACTIVE_RUNTIME"]
OWNER = principal_for_role(ROLE_OWNER, "owner_key")
OPERATOR = principal_for_role(ROLE_OPERATOR, "admin_token")
VIEWER = principal_for_role(ROLE_VIEWER, "session")


def S(**over):
    """Injected settings: every real flag False, APP_ENV development — flip what a check needs."""
    base = {k: False for k in br._ALL_FLAGS}
    base.update(APP_ENV="development")
    base.update(over)
    return NS(**base)


def STAGING_ALL_ON(**over):
    on = dict(APP_ENV="staging", KAI_CAPABILITY_EXECUTION_ENABLED=True, HOLDING_AUTONOMY_ENABLED=True,
              KAI_A2_EXECUTION_ENABLED=True, KAI_SELF_IMPROVEMENT_ENABLED=True, KAI_HOLDING_WATCH_ENABLED=True,
              KAI_PROACTIVE_ENABLED=True)
    on.update(over)
    return S(**on)


def board(settings=S(), rec=None, *, readable=True, env=None, loader=None):
    b = brakes(settings=settings, stop_store=InMemoryStopStore(rec, readable=readable), env=env if env is not None else {},
               manifests_loader=loader, now=NOW)
    return b, {r["brake"]: r for r in b["brakes"]}


FIN_KEYS = ("KAI_SCOPE_SOL_TRANSFER", "KAI_SCOPE_SOL", "DWOLLA_KEY", "DWOLLA_SECRET", "DWOLLA_ENV", "DWOLLA_ALLOW_PRODUCTION")
CREDS = {"DWOLLA_KEY": "key-SECRET-abc", "DWOLLA_SECRET": "sec-SECRET-xyz"}
SOL_PATH = "/admin/sol/cycles/{id}/collect|payout|retry-failed"


def fin_env(**kv):
    """os.environ with ONLY the given Sol/Dwolla switches set (the other FIN_KEYS removed) — the FINANCIAL row
    composes the enforcers' own readers (governance.actions.is_scope_enabled / dwolla.client), which read os.environ."""
    env = {k: v for k, v in os.environ.items() if k not in FIN_KEYS}
    env.update(kv)
    return patch.dict(os.environ, env, clear=True)


JOB_ROWS = [   # worker_jobs.list_jobs shape
    {"id": 1, "status": "running", "worker": "coding", "claimed_by": "colima-1", "task": {"task_id": "a2:m1"}, "created_at": "t1"},
    {"id": 2, "status": "claimed", "worker": "coding", "claimed_by": "colima-1", "task": {"task_id": "a2:m2"}, "created_at": "t2"},
    {"id": 3, "status": "queued", "worker": "coding", "claimed_by": None, "task": {"task_id": "a2:m3"}, "created_at": "t3"},
    {"id": 4, "status": "succeeded", "worker": "coding", "claimed_by": "colima-1", "task": {"task_id": "a2:m0"}, "created_at": "t0"},
]
PLANE = {"counts": {"running": 1, "claimed": 1, "queued": 1, "succeeded": 1}, "rows": JOB_ROWS}


_BRAKES_SRC = __import__("pathlib").Path(__file__).with_name("brakes.py").read_text()


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    src = inspect.getsource(br)

    # ── the board: 10 brakes, closed vocabulary, every row names what it reads ───────────────────────
    b, rows = board()
    ck("board lists exactly the 10 §97 brakes in order",
       [r["brake"] for r in b["brakes"]] == ALL_BRAKES)
    ck("every state is ON/OFF/UNAVAILABLE/POLICY_LOCKED (STOP: ENGAGED/RELEASED/UNAVAILABLE); every row names enforced_by (STOP: honored_by) + controlled_by",
       all(r["state"] in (ON, OFF, UNAVAILABLE, POLICY_LOCKED) for r in b["brakes"][1:]) and rows[STOP]["state"] in (ENGAGED, RELEASED, UNAVAILABLE)
       and all("enforced_by" in r and "controlled_by" in r and r["observed_at"] == NOW for r in b["brakes"][1:])
       and rows[STOP]["honored_by"] and rows[STOP]["controlled_by"] and rows[STOP]["observed_at"] == NOW)

    # ── each brake maps to a REAL flag / policy (no invented switch) ─────────────────────────────────
    from app.config import Settings
    from app.services.holding.self_model import FLAG_KEYS
    from app.services.holding.holding_cycle import build_live_engine
    from app.services.holding.a2_dispatch import brakes_all_on, enqueue_a2_coding_job
    from app.services.holding.os_lab.runtimes import FLAG_OS_LAB, FLAG_ULTRON, FLAG_VIRTME_NG, FLAG_SYZKALLER, _runtime_on
    declared = set(Settings.model_fields)
    flag_ctrl = {n for k in ("OBSERVATION", "DETECTION", "A1_VERIFICATION", "A2_PREPARATION", "SELF_IMPROVEMENT")
                 for n in rows[k]["controlled_by"]} | {"KAI_HOLDING_DELIVERY_ENABLED"}
    ck("flag brakes are controlled ONLY by flags declared in app.config.Settings AND in self_model.FLAG_KEYS (one flag vocabulary)",
       flag_ctrl <= declared and flag_ctrl <= set(FLAG_KEYS))
    ck("L1: brakes._ALL_FLAGS ⊆ self_model.FLAG_KEYS ∪ os_lab.runtimes FLAG_* — COMPOSED from those constants, no literal second list in brakes.py",
       set(br._ALL_FLAGS) <= set(FLAG_KEYS) | set(br.OS_LAB_FLAGS)
       and br.OS_LAB_FLAGS == (FLAG_OS_LAB, FLAG_ULTRON, FLAG_VIRTME_NG, FLAG_SYZKALLER)
       and re.search(r"_ALL_FLAGS\s*=\s*tuple\(k for k in FLAG_KEYS", src) and not re.search(r'_ALL_FLAGS\s*=\s*\(\s*"', src)
       and (flag_ctrl | set(rows["OS_LAB_ACTIVE_RUNTIME"]["controlled_by"])) <= set(br._ALL_FLAGS)
       and all(k.endswith("_ENABLED") for k in br._ALL_FLAGS) and "MONEY_MODE" not in br._ALL_FLAGS)
    ble = inspect.getsource(build_live_engine)
    ck("A1/A2/SELF_IMPROVEMENT read the SAME flags build_live_engine + a2_dispatch.brakes_all_on enforce",
       all(f in ble and f in inspect.getsource(brakes_all_on) for f in rows["A2_PREPARATION"]["controlled_by"])
       and "build_live_engine" in rows["A1_VERIFICATION"]["enforced_by"] and "a2_dispatch" in rows["A2_PREPARATION"]["enforced_by"])
    ck("OS_LAB brake reads os_lab.runtimes' own flag constants (absent from Settings by design → getattr False)",
       rows["OS_LAB_ACTIVE_RUNTIME"]["controlled_by"] == [FLAG_OS_LAB, FLAG_ULTRON, FLAG_VIRTME_NG, FLAG_SYZKALLER]
       and not ({FLAG_OS_LAB, FLAG_ULTRON} & declared))

    # ── flip the injected settings → status changes (ON/OFF are derived, not asserted) ───────────────
    ck("all flags off → OBSERVATION/DETECTION/A1/A2/SI OFF with the off flags named",
       all(rows[k]["state"] == OFF for k in ("OBSERVATION", "DETECTION", "A1_VERIFICATION", "A2_PREPARATION", "SELF_IMPROVEMENT"))
       and "KAI_HOLDING_WATCH_ENABLED" in rows["OBSERVATION"]["reasons"][0])
    _, r1 = board(S(KAI_HOLDING_WATCH_ENABLED=True, KAI_PROACTIVE_ENABLED=True))
    ck("watch flag on → OBSERVATION ON; proactive flag on → DETECTION ON (any-of, read-only, halted_by_stop False)",
       r1["OBSERVATION"]["state"] == ON and r1["DETECTION"]["state"] == ON
       and r1["OBSERVATION"]["halted_by_stop"] is False and r1["DETECTION"]["halted_by_stop"] is False)
    _, r2 = board(S(KAI_CAPABILITY_EXECUTION_ENABLED=True, HOLDING_AUTONOMY_ENABLED=True))
    ck("brakes #1+#2 on (development) → A1_VERIFICATION ON; A2 still OFF (brake #3 off)",
       r2["A1_VERIFICATION"]["state"] == ON and r2["A2_PREPARATION"]["state"] == OFF
       and "KAI_A2_EXECUTION_ENABLED" in r2["A2_PREPARATION"]["reasons"][0])
    _, r3 = board(S(KAI_CAPABILITY_EXECUTION_ENABLED=True, HOLDING_AUTONOMY_ENABLED=True, KAI_A2_EXECUTION_ENABLED=True))
    ck("all 3 brakes on but APP_ENV=development → A2 OFF: STAGING_ONLY (a2_dispatch's own rule, reported not re-invented)",
       r3["A2_PREPARATION"]["state"] == OFF and "STAGING_ONLY" in r3["A2_PREPARATION"]["reasons"][0])
    _, r4 = board(STAGING_ALL_ON(KAI_SELF_IMPROVEMENT_ENABLED=False))
    ck("staging + 3 brakes → A2 ON; SELF_IMPROVEMENT OFF until its own subordinate flag",
       r4["A2_PREPARATION"]["state"] == ON and r4["SELF_IMPROVEMENT"]["state"] == OFF)
    _, r5 = board(STAGING_ALL_ON())
    ck("staging + 3 brakes + SI flag → SELF_IMPROVEMENT ON (all-of)", r5["SELF_IMPROVEMENT"]["state"] == ON)

    # ── config unreadable → UNAVAILABLE, never a fake OFF ────────────────────────────────────────────
    def _boom():
        raise RuntimeError("config down")
    with fin_env():
        bu = brakes(load_settings=_boom, stop_store=InMemoryStopStore({}), env={}, now=NOW)
    ru = {r["brake"]: r for r in bu["brakes"]}
    ck("settings unreadable → flag brakes + EXTERNAL + OS_LAB UNAVAILABLE (never OFF); RESTRICTED stays POLICY_LOCKED; FINANCIAL is env-derived (OFF here, not Settings-dependent)",
       all(ru[k]["state"] == UNAVAILABLE for k in ("OBSERVATION", "DETECTION", "A1_VERIFICATION", "A2_PREPARATION",
                                                    "SELF_IMPROVEMENT", "EXTERNAL_COMMUNICATION", "OS_LAB_ACTIVE_RUNTIME"))
       and ru["FINANCIAL_EXECUTION"]["state"] == OFF and ru["RESTRICTED_SECURITY"]["state"] == POLICY_LOCKED
       and all(v == UNAVAILABLE for v in bu["flags"].values()))

    # ── EXTERNAL_COMMUNICATION: opt-in flag AND a configured channel; secrets never read into the report ─
    _, e1 = board(S(KAI_HOLDING_DELIVERY_ENABLED=True), env={})
    _, e2 = board(S(KAI_HOLDING_DELIVERY_ENABLED=True), env={"TELEGRAM_BOT_TOKEN": "tok-SECRET-123", "TELEGRAM_CHAT_ID": "42"})
    _, e3 = board(S(), env={"TELEGRAM_BOT_TOKEN": "tok-SECRET-123", "TELEGRAM_CHAT_ID": "42"})
    ck("EXTERNAL_COMMUNICATION: flag on/no channel → OFF; flag on + channel → ON; flag off → OFF; not controlled by STOP",
       e1["EXTERNAL_COMMUNICATION"]["state"] == OFF and e2["EXTERNAL_COMMUNICATION"]["state"] == ON
       and e3["EXTERNAL_COMMUNICATION"]["state"] == OFF and e2["EXTERNAL_COMMUNICATION"]["halted_by_stop"] is False)
    ck("channel PRESENCE only — the token value never appears in the board",
       "tok-SECRET-123" not in json.dumps(e2) and e2["EXTERNAL_COMMUNICATION"]["flags"]["channel_configured"] is True)

    # ── FINANCIAL_EXECUTION (H1): a REAL env-controlled path in THIS app — app/main.py mounts routers/sol.py whose
    #    collect/payout/retry-failed → DwollaClient are gated by @audited(scope=sol.transfer) + the sandbox-lock.
    #    The row is DERIVED from those enforcers' own readers, never asserted POLICY_LOCKED / 'no execution path'. ─
    from app.services.governance.actions import is_scope_enabled
    from app.services.dwolla.client import is_configured
    import app.main as _main
    from app.routers import sol as _sol
    FIN_CTRL = ["KAI_SCOPE_SOL_TRANSFER", "DWOLLA_ENV", "DWOLLA_ALLOW_PRODUCTION", "DWOLLA credentials (presence only)"]
    with fin_env():
        bf0, f0 = board()
    with fin_env(KAI_SCOPE_SOL_TRANSFER="1", **CREDS):
        real_on = is_scope_enabled("sol.transfer") and is_configured()
        bf1, f1 = board()
        _, fstop = board(rec={"engaged": True})
    with fin_env(KAI_SCOPE_SOL_TRANSFER="1"):
        _, f2 = board()
    with fin_env(**CREDS):
        _, f3 = board()
    with fin_env(KAI_SCOPE_SOL_TRANSFER="1", DWOLLA_ENV="production", **CREDS):
        _, f4 = board()
    with fin_env(KAI_SCOPE_SOL_TRANSFER="1", DWOLLA_ENV="production", DWOLLA_ALLOW_PRODUCTION="1", **CREDS):
        bf5, f5 = board()
    with fin_env(KAI_SCOPE_SOL="true", **CREDS):
        _, f6 = board()
    with fin_env(KAI_SCOPE_SOL_TRANSFER="1", DWOLLA_ENV="bogus", **CREDS):
        _, f7 = board()
    with patch("app.services.dwolla.client.is_configured", side_effect=RuntimeError("reader down")):
        _, fu = board()
    fin0 = json.dumps(f0["FINANCIAL_EXECUTION"])
    ck("the money path is REAL here: app.main mounts routers/sol.py; _collect/_payout/_retry_failed are @audited(scope=sol.transfer, destructive)",
       any(getattr(r, "path", "").startswith("/admin/sol") for r in _main.app.routes)
       and all(getattr(getattr(_sol, f), "__kai_action__", {}) == {"scope": "sol.transfer", "destructive": True, "name": f}
               for f in ("_collect", "_payout", "_retry_failed")))
    ck("FINANCIAL_EXECUTION: scope off + creds absent → OFF, env-controlled (controlled_by = the 4 real switches, mutable_via env) — never POLICY_LOCKED / 'no execution path' / 'NONE in this app'",
       f0["FINANCIAL_EXECUTION"]["state"] == OFF and f0["FINANCIAL_EXECUTION"]["controlled_by"] == FIN_CTRL
       and f0["FINANCIAL_EXECUTION"]["mutable_via"] == "env" and f0["FINANCIAL_EXECUTION"]["halted_by_stop"] is False
       and not any(s in fin0 for s in ("POLICY_LOCKED", "no execution path", "NONE in this app", "MONEY_MODE"))
       and SOL_PATH in f0["FINANCIAL_EXECUTION"]["path"])
    ck("KAI_SCOPE_SOL_TRANSFER=1 + creds present → ON (matches is_scope_enabled ∧ is_configured), mode SANDBOX (DWOLLA_ENV default), enforced_by = audited(sol.transfer) + sandbox-lock",
       real_on and f1["FINANCIAL_EXECUTION"]["state"] == ON and f1["FINANCIAL_EXECUTION"]["flags"]["mode"] == "SANDBOX"
       and f1["FINANCIAL_EXECUTION"]["flags"]["dwolla_credentials_present"] is True
       and f1["FINANCIAL_EXECUTION"]["enforced_by"] == "governance.actions.audited(scope=sol.transfer) + dwolla.client sandbox-lock")
    ck("scope on / creds absent → OFF naming the missing creds; creds present / scope off → OFF naming ScopeDenied (each real gate named, none invented)",
       f2["FINANCIAL_EXECUTION"]["state"] == OFF and any("DWOLLA_KEY" in r for r in f2["FINANCIAL_EXECUTION"]["reasons"])
       and f3["FINANCIAL_EXECUTION"]["state"] == OFF and any("ScopeDenied" in r for r in f3["FINANCIAL_EXECUTION"]["reasons"]))
    ck("DWOLLA_ENV=production without DWOLLA_ALLOW_PRODUCTION → OFF PRODUCTION_LOCKED (DwollaClient's sandbox-lock, reported not re-invented); with allow → ON PRODUCTION; unknown host → OFF INVALID_DWOLLA_ENV",
       f4["FINANCIAL_EXECUTION"]["state"] == OFF and f4["FINANCIAL_EXECUTION"]["flags"]["mode"] == "PRODUCTION_LOCKED"
       and any("DwollaProductionLocked" in r for r in f4["FINANCIAL_EXECUTION"]["reasons"])
       and f5["FINANCIAL_EXECUTION"]["state"] == ON and f5["FINANCIAL_EXECUTION"]["flags"]["mode"] == "PRODUCTION"
       and f7["FINANCIAL_EXECUTION"]["state"] == OFF and f7["FINANCIAL_EXECUTION"]["flags"]["mode"] == "INVALID_DWOLLA_ENV")
    ck("wildcard KAI_SCOPE_SOL enables the scope exactly as governance.actions.is_scope_enabled does (one rule, composed)",
       f6["FINANCIAL_EXECUTION"]["state"] == ON and f6["FINANCIAL_EXECUTION"]["flags"]["KAI_SCOPE_SOL_TRANSFER (is_scope_enabled)"] is True)
    ck("credential PRESENCE only — neither secret VALUE appears anywhere in any board (OFF, ON sandbox, ON production); the row reads is_configured() → bool, never the vars",
       not any(v in json.dumps(bx) for v in CREDS.values() for bx in (bf0, bf1, bf5))
       and not re.search(r"DWOLLA_KEY\"\)|DWOLLA_SECRET\"\)|environ", inspect.getsource(br._financial_row)))
    ck("STOP engaged leaves FINANCIAL_EXECUTION unchanged (ON stays ON) — STOP does not control money and never claims to",
       fstop["FINANCIAL_EXECUTION"]["state"] == ON and fstop["FINANCIAL_EXECUTION"]["halted_by_stop"] is False
       and fstop[STOP]["state"] == ENGAGED)
    ck("scope/dwolla readers unreadable → UNAVAILABLE (never a guessed OFF), still naming its controls and env mutability",
       fu["FINANCIAL_EXECUTION"]["state"] == UNAVAILABLE and fu["FINANCIAL_EXECUTION"]["controlled_by"] == FIN_CTRL
       and fu["FINANCIAL_EXECUTION"]["mutable_via"] == "env")

    # ── RESTRICTED_SECURITY: derived from the REAL privileged manifests ──────────────────────────────
    from app.services.security.capabilities import PRIVILEGED_CAP_IDS
    rs = rows["RESTRICTED_SECURITY"]
    ck("RESTRICTED_SECURITY: the 4 real privileged caps are DISABLED/never selectable → POLICY_LOCKED, selectable []",
       rs["state"] == POLICY_LOCKED and rs["flags"]["privileged_caps"] == sorted(PRIVILEGED_CAP_IDS)
       and rs["flags"]["selectable"] == [] and rs["controlled_by"] == [])
    _, rsel = board(loader=lambda: [NS(id="SECURITY_CONTAIN", selectable=lambda: True)])
    _, rerr = board(loader=_boom)
    ck("derived, not asserted: a selectable privileged cap → ON; manifests unreadable → UNAVAILABLE",
       rsel["RESTRICTED_SECURITY"]["state"] == ON and rsel["RESTRICTED_SECURITY"]["flags"]["selectable"] == ["SECURITY_CONTAIN"]
       and rerr["RESTRICTED_SECURITY"]["state"] == UNAVAILABLE)

    # ── ACTUAL RELEASE BEHAVIOUR: restricted security is DEFERRED ────────────────────────────────
    # This release ships ONLY the pure policy manifests (security/models.py, security/capabilities.py).
    # No executor, router, worker or activation path ships. These pin that the absence is reported
    # truthfully and that any request is DENIED — never a fake OFF, never a swallowed ImportError.
    import importlib.util as _ilu
    from app.services.holding.brakes import (security_provider_state, restricted_security_request,
                                             NOT_INSTALLED)
    st, why = security_provider_state()
    ck("provider probe: the policy manifests ARE present in this release (INSTALLED, read-only)",
       st == "INSTALLED" and "no executor" in why)
    req = restricted_security_request("SECURITY_CONTAIN")
    ck("a restricted-security request is DENIED even with the policy present → DEFERRED, no execution",
       req["allowed"] is False and req["state"] == "DEFERRED" and "no executor" in req["reason"].lower())

    _real = _ilu.find_spec
    try:   # simulate the provider genuinely absent
        _ilu.find_spec = lambda n, *a, **k: None if n.startswith("app.services.security") else _real(n, *a, **k)
        st2, why2 = security_provider_state()
        req2 = restricted_security_request("SECURITY_CONTAIN")
        _, rmissing = board()
        ck("provider absent → NOT_INSTALLED (a distinct state, never collapsed into OFF)",
           st2 == NOT_INSTALLED and rmissing["RESTRICTED_SECURITY"]["state"] == NOT_INSTALLED
           and rmissing["RESTRICTED_SECURITY"]["state"] != OFF)
        ck("provider absent → the request is DENIED with a truthful NOT_INSTALLED reason",
           req2["allowed"] is False and req2["state"] == NOT_INSTALLED
           and "not installed" in req2["reason"].lower())
    finally:
        _ilu.find_spec = _real
    ck("no broad swallowed ImportError: the provider is probed with find_spec, not try/except import",
       "find_spec" in _BRAKES_SRC and "except ImportError" not in _BRAKES_SRC)
    ck("this release ships NO restricted-security executor (policy files only)",
       not any(__import__("pathlib").Path("backend/app/services/security").joinpath(f).exists()
               for f in ("evidence_bus.py", "posture.py", "aikido_adapter.py", "risk_score.py", "__init__.py")))

    # ── OS_LAB_ACTIVE_RUNTIME: composes os_lab.runtimes._runtime_on / _is_production ─────────────────
    lab_on = S(APP_ENV="staging", **{FLAG_OS_LAB: True, FLAG_ULTRON: True})
    lab_no_master = S(APP_ENV="staging", **{FLAG_ULTRON: True})
    lab_prod = S(APP_ENV="production", **{FLAG_OS_LAB: True, FLAG_ULTRON: True})
    _, l1 = board(lab_on); _, l2 = board(lab_no_master); _, l3 = board(lab_prod)
    ck("OS_LAB: master+runtime on (staging) → ON == _runtime_on; runtime without master → OFF; default → OFF",
       l1["OS_LAB_ACTIVE_RUNTIME"]["state"] == ON and _runtime_on(lab_on, FLAG_ULTRON)
       and l2["OS_LAB_ACTIVE_RUNTIME"]["state"] == OFF and not _runtime_on(lab_no_master, FLAG_ULTRON)
       and rows["OS_LAB_ACTIVE_RUNTIME"]["state"] == OFF)
    ck("OS_LAB in production → POLICY_LOCKED regardless of flags (never a controllable ON/OFF); not controlled by STOP",
       l3["OS_LAB_ACTIVE_RUNTIME"]["state"] == POLICY_LOCKED and l3["OS_LAB_ACTIVE_RUNTIME"]["halted_by_stop"] is False)

    # ── STOP_AUTONOMOUS_EXECUTION: the record, fail closed, halts only what it really controls ───────
    ck("STOP record {} → RELEASED, stop_engaged False; engaged → ENGAGED, True",
       rows[STOP]["state"] == RELEASED and b["stop_engaged"] is False
       and board(rec={"engaged": True})[1][STOP]["state"] == ENGAGED and stop_engaged(InMemoryStopStore({"engaged": True})) is True)
    ck("L2: stop_state names WHY — {} → None, engaged → STOP_ENGAGED, unreadable → STOP_UNREADABLE; stop_engaged composes it (one reader)",
       stop_state(InMemoryStopStore({})) is None and stop_state(InMemoryStopStore({"engaged": True})) == STOP_ENGAGED
       and stop_state(InMemoryStopStore(readable=False)) == STOP_UNREADABLE
       and "stop_state(store) is not None" in inspect.getsource(br.stop_engaged))
    bun, run_ = board(readable=False)
    ck("STOP record UNREADABLE → state UNAVAILABLE, treated_as ENGAGED, stop_engaged True (fail closed, never assumed released)",
       run_[STOP]["state"] == UNAVAILABLE and run_[STOP]["treated_as"] == ENGAGED and bun["stop_engaged"] is True
       and stop_engaged(InMemoryStopStore(readable=False)) is True)
    _, live = board(STAGING_ALL_ON())
    _, stopped = board(STAGING_ALL_ON(), rec={"engaged": True})
    ck("STOP engaged flips ONLY the consequential brakes A1/A2/SI ON→OFF (stop_applied True, reason 'STOP engaged')",
       all(live[k]["state"] == ON for k in HALTED)
       and all(stopped[k]["state"] == OFF and stopped[k]["stop_applied"] is True and "STOP engaged" in stopped[k]["reasons"] for k in HALTED))
    ck("STOP does NOT claim OBSERVATION/DETECTION/EXTERNAL/FINANCIAL/RESTRICTED/OS_LAB — their state is unchanged and halted_by_stop False",
       all(stopped[k]["state"] == live[k]["state"] and stopped[k]["halted_by_stop"] is False for k in NOT_HALTED)
       and stopped["OBSERVATION"]["state"] == ON
       and set(stopped[STOP]["halts"]) == set(HALTED) and set(NOT_HALTED) <= set(stopped[STOP]["does_not_halt"]))
    ck("STOP does_not_halt NAMES the Sol money path (routers/sol.py collect|payout|retry-failed) and says STOP does not control it",
       any(SOL_PATH in x and "STOP does NOT control it" in x for x in stopped[STOP]["does_not_halt"])
       and not any(SOL_PATH in x for x in stopped[STOP]["halts"]))
    _, unr = board(STAGING_ALL_ON(), readable=False)
    ck("STOP unreadable → A1/A2/SI OFF with the fail-closed reason (not silently ON)",
       all(unr[k]["state"] == OFF and "fail closed" in unr[k]["reasons"][-1] for k in HALTED))
    bx = brakes(load_settings=_boom, stop_store=InMemoryStopStore({"engaged": True}), env={}, now=NOW)
    ck("config unreadable + STOP engaged → A1 stays UNAVAILABLE (STOP never fabricates an OFF over an unreadable flag)",
       {r["brake"]: r for r in bx["brakes"]}["A1_VERIFICATION"]["state"] == UNAVAILABLE)

    # ── STOP is HONORED by the real composition points (halts NEW consequential work) ─────────────────
    import app.config as cfg
    eng_store = InMemoryStopStore({"engaged": True}); rel_store = InMemoryStopStore({})
    saved = {k: getattr(cfg.settings, k) for k in ("HOLDING_AUTONOMY_ENABLED", "KAI_CAPABILITY_EXECUTION_ENABLED")}
    try:
        for k in saved:
            setattr(cfg.settings, k, True)                    # config says ON …
        e_rel = build_live_engine(stop_store=rel_store)
        e_stop = build_live_engine(stop_store=eng_store)
        e_unr = build_live_engine(stop_store=InMemoryStopStore(readable=False))
        e_override = build_live_engine(autonomy_on=True, execution_on=True, stop_store=eng_store)
    finally:
        for k, v in saved.items():
            setattr(cfg.settings, k, v)
    # probe the REAL certified internal-read cap id (task_resolver.default_providers; registry-backed, no network) —
    # an unregistered id is honestly CAPABILITY_UNAVAILABLE (RUNTIME_PENDING, §16) on a LIVE executor too
    disabled = lambda e: getattr(e._execute("holding.capability_health", "read", {}), "status", "") == "CAPABILITY_UNAVAILABLE"
    ck("build_live_engine: config ON + STOP released → engine live; STOP engaged → global_autonomy False AND brake #1 executor disabled",
       e_rel._global is True and not disabled(e_rel) and e_stop._global is False and disabled(e_stop))
    ck("build_live_engine: STOP record unreadable → fail closed (every config-read brake OFF); explicit test overrides untouched",
       e_unr._global is False and disabled(e_unr) and e_override._global is True and not disabled(e_override))
    ck("L2: build_live_engine RECORDS why — brake_override None (released), STOP_ENGAGED, STOP_UNREADABLE (distinguished, never a silent 0-execution); "
       "partial overrides still record it for the config-read brake (a2) they forced",
       e_rel.brake_override is None and e_stop.brake_override == STOP_ENGAGED and e_unr.brake_override == STOP_UNREADABLE
       and e_override.brake_override == STOP_ENGAGED
       and build_live_engine(autonomy_on=False, execution_on=False, a2_on=False).brake_override is None)
    ck("config flags are NOT mutated by STOP (restored/unchanged real settings)",
       all(getattr(cfg.settings, k) == v for k, v in saved.items()))
    calls = []
    reg = NS(is_granted=lambda *a: True)
    enq = lambda *a, **k: calls.append((a, k)) or {"id": 1}
    stg = STAGING_ALL_ON()
    a_rel = enqueue_a2_coding_job(mission_id="m", base_sha="abc", settings=stg, grant_registry=reg, enqueue_fn=enq, stop_store=rel_store)
    a_stop = enqueue_a2_coding_job(mission_id="m", base_sha="abc", settings=stg, grant_registry=reg, enqueue_fn=enq, stop_store=eng_store)
    a_unr = enqueue_a2_coding_job(mission_id="m", base_sha="abc", settings=stg, grant_registry=reg, enqueue_fn=enq,
                                  stop_store=InMemoryStopStore(readable=False))
    ck("enqueue_a2_coding_job (A2 + self-improvement path): released → enqueued; STOP engaged → refused STOP_ENGAGED; unreadable → refused STOP_UNREADABLE (distinguished); enqueue never called",
       a_rel["enqueued"] is True and len(calls) == 1 and a_stop == {"enqueued": False, "reason": STOP_ENGAGED}
       and a_unr == {"enqueued": False, "reason": STOP_UNREADABLE} and len(calls) == 1)
    ck("the board's honored_by names exactly these two composition points",
       any("build_live_engine" in h for h in rows[STOP]["honored_by"]) and any("enqueue_a2_coding_job" in h for h in rows[STOP]["honored_by"]))

    # ── mutation: owner-only (§97 / §0#11), audited, fail closed ─────────────────────────────────────
    audits = []
    def audit(**kw): audits.append(kw)
    for who, label in ((OPERATOR, "operator"), (VIEWER, "viewer"), (None, "anonymous"), (object(), "no-.has object"),
                       (Principal(role="owner", scopes=frozenset(), source="spoof"), "owner-role without kai.ultra")):
        store = InMemoryStopStore({})
        try:
            stop(who, reason="x", stop_store=store, audit=audit, now=NOW); refused = False
        except PermissionError:
            refused = True
        ck(f"stop() by {label} → PermissionError; record untouched; nothing audited",
           refused and store.rec == {} and audits == [])
    ck("owner principal holds kai.ultra (the same identity model require_kai_ultra gates on)",
       OWNER.role == ROLE_OWNER and OWNER.has(SCOPE_KAI_ULTRA) and not OPERATOR.has(SCOPE_KAI_ULTRA))

    store = InMemoryStopStore({})
    rep = stop(OWNER, reason="incident 42", stop_store=store, jobs_source=lambda: PLANE, audit=audit, now=NOW)
    ck("owner stop() → durable record engaged, state ENGAGED, actor owner:owner_key, reason kept",
       store.rec["engaged"] is True and rep["engaged"] is True and rep["state"] == ENGAGED
       and rep["actor"] == "owner:owner_key" and rep["reason"] == "incident 42" and stop_engaged(store) is True)
    ck("stop report: halts == A1/A2/SI, does_not_halt lists the uncontrolled brakes + the Sol money path, brakes_after shows A1/A2/SI OFF",
       set(rep["halts"]) == set(HALTED) and set(NOT_HALTED) <= set(rep["does_not_halt"])
       and any(SOL_PATH in x for x in rep["does_not_halt"])
       and all(rep["brakes_after"][k] == OFF for k in HALTED) and rep["brakes_after"][STOP] == ENGAGED)
    inf = rep["in_flight"]
    ck("STOP does NOT claim to undo started work: in-flight running+claimed jobs listed truthfully (2), queued/succeeded excluded",
       inf["state"] == "MEASURED" and inf["counts"] == {"claimed": 1, "running": 1}
       and [j["id"] for j in inf["jobs"]] == [1, 2] and "NOT undone" in inf["note"]
       and "never undone" in rep["latency"])
    ck("audited via governance.audit_log.record_action shape (action holding.brakes.stop, scope holding.brakes, success True)",
       len(audits) == 1 and audits[0]["action"] == "holding.brakes.stop" and audits[0]["scope"] == "holding.brakes"
       and audits[0]["success"] is True and audits[0]["actor"] == "owner:owner_key"
       and "audit_log import record_action" in inspect.getsource(br._default_audit))
    rep_u = stop(OWNER, reason="q down", stop_store=InMemoryStopStore({}), jobs_source=_boom, audit=audit, now=NOW)
    ck("queue unreadable → in_flight UNAVAILABLE ('not assumed zero'), no counts/jobs invented",
       rep_u["in_flight"]["state"] == UNAVAILABLE and "counts" not in rep_u["in_flight"] and "jobs" not in rep_u["in_flight"])
    ro = InMemoryStopStore({}, writable=False)
    rep_f = stop(OWNER, reason="x", stop_store=ro, audit=audit, now=NOW)
    ck("persist failure → reported STOP_PERSIST_FAILED with engaged/state UNAVAILABLE (nothing claimed stopped); audited success=False",
       rep_f["engaged"] == UNAVAILABLE and rep_f["state"] == UNAVAILABLE and "STOP_PERSIST_FAILED" in rep_f["error"]
       and ro.rec == {} and audits[-1]["success"] is False)
    rel = release(OWNER, reason="cleared", stop_store=store, jobs_source=lambda: PLANE, audit=audit, now=NOW)
    ck("owner release() → RELEASED; grants nothing (brakes_after reflects the config flags, all OFF here)",
       rel["state"] == RELEASED and store.rec["engaged"] is False and stop_engaged(store) is False
       and all(rel["brakes_after"][k] == OFF for k in HALTED) and audits[-1]["action"] == "holding.brakes.release")
    try:
        release(OPERATOR, reason="x", stop_store=store, audit=audit, now=NOW); ok_rel = False
    except PermissionError:
        ok_rel = True
    ck("release() is owner-only too", ok_rel and store.rec["engaged"] is False)

    # ── static honesty: STOP touches no config flag, no MONEY_MODE, runs nothing, no daemon ─────────
    ck("STOP never mutates config/env/MONEY_MODE: no setattr / settings assignment / os.environ write in brakes.py",
       not re.search(r"setattr\(|settings\.\w+\s*=[^=]|os\.environ\[[^\]]+\]\s*=|MONEY_MODE\s*=[^=]", src))
    ck("no execution and no daemon in brakes.py (no subprocess/threading/asyncio/loop/sleep)",
       not re.search(r"\b(subprocess|threading|asyncio|while True|time\.sleep)\b", src))
    ck("in-flight reader composes the EXISTING worker-plane reader (resource_governor._worker_plane → worker_jobs.list_jobs)",
       "resource_governor import _worker_plane" in inspect.getsource(br._default_worker_plane))
    ck("STOP is ONE durable record (holding_brakes) — no new authority flag added to Settings",
       "holding_brakes" in br._DDL and not any(k.startswith("KAI_STOP") or "BRAKE" in k for k in declared))
    ck("DDL runs ONCE per process: DbStopStore.get/set compose _ensure_table (module guard); text(_DDL) is executed in exactly one place",
       "_ensure_table(db)" in inspect.getsource(DbStopStore.get) and "_ensure_table(db)" in inspect.getsource(DbStopStore.set)
       and src.count("text(_DDL)") == 1 and "global _ddl_done" in inspect.getsource(br._ensure_table))

    # ── [db] the durable store, if a DB is reachable here: readable or honestly None ─────────────────
    got = DbStopStore().get()
    ck("[db] DbStopStore.get() → dict (record) or None (unreadable) — never raises, never a guessed value",
       got is None or isinstance(got, dict))
    if isinstance(got, dict) and not got.get("engaged"):
        ok_rt = DbStopStore().set({"engaged": False, "reason": "test_brakes roundtrip", "actor": "test", "at": NOW})
        back = DbStopStore().get()
        ck("[db] RELEASED roundtrip persists + reads back (never engages the real record from a test)",
           ok_rt and isinstance(back, dict) and back.get("engaged") is False and stop_engaged() is False)

    n = len(res); ok = sum(res)
    print(f"\nBRAKES (§97) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
