"""§97 kill switch + brakes — honesty/composition guard. Zero-framework (mirrors test_registry.py). Settings,
STOP store, env, manifests and the job queue are injected; the real config/DB is touched read-only. Run (from backend/):
    python3 -m app.services.holding.test_brakes
"""
import inspect
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))   # repo root so `core.operator_session` resolves

from app.services.holding import brakes as br                                          # noqa: E402
from app.services.holding.brakes import (                                              # noqa: E402
    brakes, stop, release, stop_engaged, InMemoryStopStore, DbStopStore,
    ON, OFF, UNAVAILABLE, POLICY_LOCKED, ENGAGED, RELEASED, STOP)
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


JOB_ROWS = [   # worker_jobs.list_jobs shape
    {"id": 1, "status": "running", "worker": "coding", "claimed_by": "colima-1", "task": {"task_id": "a2:m1"}, "created_at": "t1"},
    {"id": 2, "status": "claimed", "worker": "coding", "claimed_by": "colima-1", "task": {"task_id": "a2:m2"}, "created_at": "t2"},
    {"id": 3, "status": "queued", "worker": "coding", "claimed_by": None, "task": {"task_id": "a2:m3"}, "created_at": "t3"},
    {"id": 4, "status": "succeeded", "worker": "coding", "claimed_by": "colima-1", "task": {"task_id": "a2:m0"}, "created_at": "t0"},
]
PLANE = {"counts": {"running": 1, "claimed": 1, "queued": 1, "succeeded": 1}, "rows": JOB_ROWS}


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
    bu = brakes(load_settings=_boom, stop_store=InMemoryStopStore({}), env={}, now=NOW)
    ru = {r["brake"]: r for r in bu["brakes"]}
    ck("settings unreadable → flag brakes + EXTERNAL + OS_LAB UNAVAILABLE (never OFF); FINANCIAL/RESTRICTED stay POLICY_LOCKED",
       all(ru[k]["state"] == UNAVAILABLE for k in ("OBSERVATION", "DETECTION", "A1_VERIFICATION", "A2_PREPARATION",
                                                    "SELF_IMPROVEMENT", "EXTERNAL_COMMUNICATION", "OS_LAB_ACTIVE_RUNTIME"))
       and ru["FINANCIAL_EXECUTION"]["state"] == POLICY_LOCKED and ru["RESTRICTED_SECURITY"]["state"] == POLICY_LOCKED
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

    # ── FINANCIAL_EXECUTION: POLICY_LOCKED, uncontrolled, MONEY_MODE observed never flipped ──────────
    fin = rows["FINANCIAL_EXECUTION"]
    ck("FINANCIAL_EXECUTION is POLICY_LOCKED with NO controlling flag (never a controllable OFF); Settings declares no MONEY_MODE",
       fin["state"] == POLICY_LOCKED and fin["controlled_by"] == [] and fin["mutable_via"] == "NONE in this app"
       and "MONEY_MODE" not in declared and fin["flags"]["MONEY_MODE_observed"].startswith("NOT_DECLARED"))
    _, fm = board(S(MONEY_MODE="MOCK"), rec={"engaged": True})
    ck("MONEY_MODE=MOCK is REPORTED as observed and stays POLICY_LOCKED even with STOP engaged",
       fm["FINANCIAL_EXECUTION"]["flags"]["MONEY_MODE_observed"] == "MOCK" and fm["FINANCIAL_EXECUTION"]["state"] == POLICY_LOCKED)

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
    ck("enqueue_a2_coding_job (A2 + self-improvement path): released → enqueued; STOP engaged/unreadable → refused STOP_ENGAGED, enqueue never called",
       a_rel["enqueued"] is True and len(calls) == 1 and a_stop == {"enqueued": False, "reason": "STOP_ENGAGED"}
       and a_unr["reason"] == "STOP_ENGAGED" and len(calls) == 1)
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
    ck("stop report: halts == A1/A2/SI, does_not_halt lists the uncontrolled brakes, brakes_after shows A1/A2/SI OFF",
       set(rep["halts"]) == set(HALTED) and set(NOT_HALTED) <= set(rep["does_not_halt"])
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
