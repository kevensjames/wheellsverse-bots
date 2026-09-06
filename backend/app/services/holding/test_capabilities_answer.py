"""§98/§99 dynamic 'What can you do / what can't you do' — live-derivation guard. Zero-framework (mirrors
test_registry.py). Manifests are real CapabilityManifest objects; flags are the self_model._flags shape.
Run (from backend/):  python3 -m app.services.holding.test_capabilities_answer
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.capability.manifest import (CapabilityManifest as CM, CapabilityType as CT, Availability as AV,   # noqa: E402
                                              Certification as CE, ActivationMode as AM, RiskClass as RK, WorkerProfile)
from app.services.capability.seed import seed_registry                                    # noqa: E402
from app.services.holding import capabilities_answer as ca                                 # noqa: E402
from app.services.holding.capabilities_answer import answer, status_of, area_of, STATUSES, AREAS, UNAVAILABLE  # noqa: E402
from app.services.holding.self_model import FLAG_KEYS, _flags, _derive_limitations, _INVARIANT_LIMITATIONS   # noqa: E402
from app.services.holding.worker_health import normalize                                   # noqa: E402

# ── fixtures ──────────────────────────────────────────────────────────────────────────────────────────
CLAUDE = CM(id="claude-code", name="Claude Code", type=CT.CODING_WORKER, availability=AV.AVAILABLE, certification=CE.CERTIFIED,
            activation=AM.ALWAYS_AVAILABLE, risk_class=RK.MEDIUM, capabilities=["implement"], triggers=["write code"],
            worker_profile=WorkerProfile(coding_modes=["implement"], headless_support=True, model_provider="anthropic"))
CODEX = CM(id="codex", name="OpenAI Codex", type=CT.CODING_WORKER, availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL,
           capabilities=["implement"], worker_profile=WorkerProfile(coding_modes=["implement"], headless_support=True,
                                                                    model_provider="openai"))
CTX7 = CM(id="context7", name="Context7 MCP", type=CT.MCP, availability=AV.AVAILABLE, certification=CE.CERTIFIED,
          activation=AM.ON_DEMAND, risk_class=RK.LOW, capabilities=["library_docs"], triggers=["documentation"])
EMPIRE = CM(id="empire", name="Empire", type=CT.SECURITY_EXECUTION_FRAMEWORK, availability=AV.AVAILABLE, certification=CE.CERTIFIED,
            risk_class=RK.RESTRICTED, security_tier=4, automatic_activation_allowed=False, capabilities=["adversary_emulation"])
PAYLOADS = CM(id="payloads-all-the-things", name="PayloadsAllTheThings", type=CT.SECURITY_KNOWLEDGE_PACK,
              availability=AV.DISCOVERED, capabilities=["payloads", "web_attack_reference"], triggers=["payloads"])
QUAR = CM(id="quarantined-x", name="Quarantined X", type=CT.MCP, availability=AV.QUARANTINED)
EXPER = CM(id="exp-tool", name="Experimental tool", type=CT.CODE_TOOL, availability=AV.AVAILABLE, certification=CE.EXPERIMENTAL)
DIS = CM(id="off-tool", name="Disabled tool", type=CT.MCP, availability=AV.DISABLED)
STRIPE = CM(id="stripe-mcp", name="Stripe MCP", type=CT.MCP, availability=AV.DISCOVERED, capabilities=["payments", "billing"])
YTDLP = CM(id="yt-dlp", name="yt-dlp", type=CT.CODE_TOOL, availability=AV.AVAILABLE, certification=CE.CERTIFIED,
           capabilities=["download_video"], triggers=["download"])
MANIFESTS = [CLAUDE, CODEX, CTX7, EMPIRE, PAYLOADS, QUAR, EXPER, DIS, STRIPE, YTDLP]
OFF = {**{k: False for k in FLAG_KEYS}, "MONEY_MODE": "MOCK", "APP_ENV": "staging"}
BRAKES_ON = {**OFF, "KAI_CAPABILITY_EXECUTION_ENABLED": True, "HOLDING_AUTONOMY_ENABLED": True, "KAI_A2_EXECUTION_ENABLED": True}
AUTH_ALL = {"anthropic": True, "openai": True}


SW_OFF = {"scope_sol_transfer": False, "dwolla_env": "sandbox", "dwolla_allow_production": False, "dwolla_credentials_present": False}
SW_ON = {**SW_OFF, "scope_sol_transfer": True, "dwolla_credentials_present": True}


def ans(flags=OFF, *, auth=AUTH_ALL, health=None, heartbeats=None, jobs=None, stopped=False, **kw):
    """stopped=False = the §97 STOP record was READ and is RELEASED — the only value that can grant authority."""
    ws = normalize(manifests=MANIFESTS, auth=auth, health=health, heartbeats=heartbeats, jobs=jobs, flags=flags, stopped=stopped)
    return answer(manifests=MANIFESTS, flags=flags, worker_snapshot=ws, stopped=stopped, **kw)


def rows(a):
    return [r for ar in a["areas"] for r in ar["capabilities"]]


def row(a, cid):
    return next(r for r in rows(a) if r["id"] == cid)


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    a = ans()

    # ── deterministic, versioned, every row tagged with exactly one of the 8 statuses ───────────
    ck("same inputs -> byte-identical answer, versioned", ans() == a and a["version"] == ca.CAPABILITIES_ANSWER_VERSION == "1.1.0")
    ck("EVERY row carries one of the 8 §98 statuses and the counts partition the rows",
       all(r["status"] in STATUSES for r in rows(a)) and sum(a["counts"].values()) == len(rows(a))
       and all(ar["area"] in AREAS for ar in a["areas"]))
    ck("every row cites its source (a config flag, a holding module, or the registry) — none is a bare claim",
       all(r["source"] and r["source"].split(":")[0].startswith(("config.", "holding.", "capability.")) for r in rows(a)))
    ck("manifest rows == manifests given (nothing added, nothing hidden)",
       sorted(r["id"] for r in rows(a) if r["source"].startswith("capability.registry") or r["source"] == "holding.worker_health")
       == sorted(m.id for m in MANIFESTS))

    # ── status_of: the versioned rule table over REAL manifest fields ─────────────────────────────
    st = {m.id: status_of(m, OFF, False)[0] for m in MANIFESTS}
    ck("rule table: QUARANTINED->BLOCKED, DISABLED->DISABLED, DISCOVERED->UNAVAILABLE, RESTRICTED/tier-4->RESTRICTED, "
       "EXPERIMENTAL cert->EXPERIMENTAL, certified+selectable->AVAILABLE while brake #1 is OFF",
       st["quarantined-x"] == "BLOCKED" and st["off-tool"] == "DISABLED" and st["payloads-all-the-things"] == UNAVAILABLE
       and st["empire"] == "RESTRICTED" and st["exp-tool"] == "EXPERIMENTAL" and st["context7"] == "AVAILABLE")
    # ── §98: flip an injected flag -> the status observably changes ───────────────────────────────
    on = ans({**OFF, "KAI_CAPABILITY_EXECUTION_ENABLED": True})
    ck("flip KAI_CAPABILITY_EXECUTION_ENABLED -> certified capability AVAILABLE -> ACTIVE (why cites brake #1)",
       row(a, "context7")["status"] == "AVAILABLE" and row(on, "context7")["status"] == "ACTIVE"
       and "brake #1" in row(a, "context7")["why"])
    hv = ans({**OFF, "KAI_HOLDING_ENABLED": True})
    ck("flip KAI_HOLDING_ENABLED -> holding.view DISABLED -> ACTIVE, source config.KAI_HOLDING_ENABLED",
       row(a, "holding.view")["status"] == "DISABLED" and row(hv, "holding.view")["status"] == "ACTIVE"
       and row(hv, "holding.view")["source"] == "config.KAI_HOLDING_ENABLED" and "True" in row(hv, "holding.view")["why"])
    br = ans(BRAKES_ON)
    ck("three brakes ON (STOP released) -> autonomous_work + a2.prepare_only ACTIVE; OFF -> DISABLED (why names each brake)",
       row(a, "holding.autonomous_work")["status"] == "DISABLED" and row(br, "holding.autonomous_work")["status"] == "ACTIVE"
       and row(a, "a2.prepare_only")["status"] == "DISABLED" and row(br, "a2.prepare_only")["status"] == "ACTIVE"
       and "brake #2 HOLDING_AUTONOMY_ENABLED" in row(a, "holding.autonomous_work")["why"])
    # ── review H2: §97 STOP is consulted — engaged OR unreadable overrides every brake ────────────
    SI_ON = {**BRAKES_ON, "KAI_SELF_IMPROVEMENT_ENABLED": True}
    st_rel, st_eng, st_unr = ans(SI_ON, health={"claude-code": True}), ans(SI_ON, health={"claude-code": True}, stopped=True), \
        ans(SI_ON, health={"claude-code": True}, stopped=None)
    gated = ("holding.autonomous_work", "a2.prepare_only", "self_improvement.prepare")
    ck("H2: STOP engaged -> autonomous_work / a2.prepare_only / self_improvement.prepare DISABLED with why 'STOP_AUTONOMOUS_EXECUTION engaged (brakes)' (all four brakes ON)",
       all(row(st_rel, g)["status"] == "ACTIVE" for g in gated)
       and all(row(st_eng, g)["status"] == "DISABLED" and row(st_eng, g)["why"].startswith("STOP_AUTONOMOUS_EXECUTION engaged (brakes)")
               for g in gated))
    ck("H2: STOP unreadable (None) -> the same three rows DISABLED, why says unreadable -> treated as engaged (fail closed)",
       all(row(st_unr, g)["status"] == "DISABLED" and row(st_unr, g)["why"].startswith("STOP_AUTONOMOUS_EXECUTION engaged (brakes)")
           and "unreadable" in row(st_unr, g)["why"] for g in gated))
    ck("H2: status_of under brake #1 ON: STOP released -> ACTIVE; engaged / unreadable -> AVAILABLE (why cites STOP, owner-driven use not halted)",
       status_of(CTX7, BRAKES_ON, False)[0] == "ACTIVE" and status_of(CTX7, BRAKES_ON, True) [0] == "AVAILABLE"
       and status_of(CTX7, BRAKES_ON, None)[0] == "AVAILABLE" and status_of(CTX7, BRAKES_ON)[0] == "AVAILABLE"
       and "STOP_AUTONOMOUS_EXECUTION engaged (brakes)" in status_of(CTX7, BRAKES_ON, True)[1]
       and row(st_rel, "context7")["status"] == "ACTIVE" and row(st_eng, "context7")["status"] == "AVAILABLE")
    ck("H2: STOP engaged / unreadable -> every worker row execution_authority NONE and NO row anywhere is ACTIVE; authority block carries STOP in brakes' vocabulary",
       all(r["execution_authority"] == "NONE" for r in rows(st_eng) if "execution_authority" in r)
       and all(r["execution_authority"] == "NONE" for r in rows(st_unr) if "execution_authority" in r)
       and st_eng["counts"]["ACTIVE"] == 0 and st_unr["counts"]["ACTIVE"] == 0
       and st_eng["authority"]["STOP_AUTONOMOUS_EXECUTION"] == "ENGAGED" and st_unr["authority"]["STOP_AUTONOMOUS_EXECUTION"] == "UNAVAILABLE"
       and st_rel["authority"]["STOP_AUTONOMOUS_EXECUTION"] == "RELEASED"
       and any(r["execution_authority"] == "A2_PREPARE_ONLY" for r in rows(st_rel) if "execution_authority" in r))

    # ── §119/§120: real worker truth wins over the catalog; flip a worker to AUTH_BLOCKED ─────────
    live = ans(health={"claude-code": True})
    blocked = ans(auth={"anthropic": False, "openai": True})            # nothing observed live + no local credential
    ck("observed-live Claude -> worker ONLINE -> AVAILABLE, but execution_authority NONE (brakes off)",
       row(live, "claude-code")["worker_state"] == "ONLINE" and row(live, "claude-code")["status"] == "AVAILABLE"
       and row(live, "claude-code")["execution_authority"] == "NONE" and row(live, "claude-code")["source"] == "holding.worker_health")
    ck("flip Claude to AUTH_BLOCKED (no credential, nothing observed live) -> status AUTH_REQUIRED and the why says so",
       row(blocked, "claude-code")["worker_state"] == "AUTH_BLOCKED" and row(blocked, "claude-code")["status"] == "AUTH_REQUIRED"
       and "no anthropic credential" in row(blocked, "claude-code")["why"])
    # ── review M7/M8: liveness is an observation, ACTIVE is an authority claim ───────────────────
    HB_IDLE = [{"worker_id": "claude-code:host1", "online": True, "current_job": None}]
    JOB_RUN = [{"id": 1, "status": "running", "worker": "claude-code", "claimed_by": "claude-code:host1"}]
    idle, busy = ans(heartbeats=HB_IDLE), ans(heartbeats=HB_IDLE, jobs=JOB_RUN)
    ck("M7: IDLE worker (heartbeat, brakes off) -> AVAILABLE not ACTIVE; BUSY (running job, brakes off) -> AVAILABLE not ACTIVE",
       row(idle, "claude-code")["worker_state"] == "IDLE" and row(idle, "claude-code")["status"] == "AVAILABLE"
       and row(busy, "claude-code")["worker_state"] == "BUSY" and row(busy, "claude-code")["status"] == "AVAILABLE"
       and idle["counts"]["ACTIVE"] == 0 and busy["counts"]["ACTIVE"] == 0)
    ck("M7: the SAME idle worker with brakes ON + STOP released -> ACTIVE; brakes ON + STOP engaged -> AVAILABLE (authority, not liveness, makes ACTIVE)",
       row(ans(BRAKES_ON, heartbeats=HB_IDLE), "claude-code")["status"] == "ACTIVE"
       and row(ans(BRAKES_ON, heartbeats=HB_IDLE), "claude-code")["execution_authority"] == "A2_PREPARE_ONLY"
       and row(ans(BRAKES_ON, heartbeats=HB_IDLE, stopped=True), "claude-code")["status"] == "AVAILABLE"
       and row(ans(BRAKES_ON, heartbeats=HB_IDLE, stopped=None), "claude-code")["status"] == "AVAILABLE")
    nocred_busy = ans(heartbeats=HB_IDLE, jobs=JOB_RUN, auth={"anthropic": False, "openai": True})
    ck("M8: observed running job + no LOCAL credential -> worker BUSY -> AVAILABLE (not AUTH_REQUIRED); why keeps the 'in this process' credential fact",
       row(nocred_busy, "claude-code")["worker_state"] == "BUSY" and row(nocred_busy, "claude-code")["status"] == "AVAILABLE"
       and "runner env not observable" in row(nocred_busy, "claude-code")["why"]
       and next(w for w in nocred_busy["workers"]["workers"] if w["worker"] == "claude-code")["credential_present"] is False)
    ck("...and the 'cannot' answer CHANGES: the Claude limitation appears only when it is not live",
       not any("Claude Code coding worker" in l for l in live["cannot"])
       and any("Claude Code coding worker is not AVAILABLE (AUTH_BLOCKED)" in l for l in blocked["cannot"]))
    ck("catalog-DISCOVERED codex is OFFLINE (never OBSERVED) -> UNAVAILABLE even with a credential present",
       row(a, "codex")["worker_state"] == "OFFLINE" and row(a, "codex")["status"] == UNAVAILABLE)
    ck("no manifest row is ACTIVE while brake #1 is OFF (nothing over-claims execution)",
       not any(r["status"] == "ACTIVE" for r in rows(live) if r["source"].startswith(("capability.registry", "holding.worker_health"))))
    ck("with the brakes ON every worker row reports A2_PREPARE_ONLY — still never merge/deploy",
       all(r["execution_authority"] == "A2_PREPARE_ONLY" for r in rows(br) if "execution_authority" in r)
       and row(br, "code.merge")["status"] == "RESTRICTED" and row(br, "code.deploy")["status"] == "RESTRICTED"
       and row(br, "code.branch_protection")["status"] == "DISABLED")

    # ── §99: 'cannot' is self_model._derive_limitations, nothing else ─────────────────────────────
    cw = [{"id": w["worker"], "name": w["name"], "available": w["state"] in ca.LIVE_STATES, "state": w["state"]}
          for w in a["workers"]["workers"]]
    ck("cannot == self_model._derive_limitations(flags, finance, workers) — no second limitations list",
       a["cannot"] == _derive_limitations(OFF, finance_available=False, coding_workers=cw)
       and a["cannot_source"].startswith("self_model._derive_limitations"))
    ck("the policy invariants (§0 #11 / §99) lead the 'cannot' list, always",
       a["cannot"][:len(_INVARIANT_LIMITATIONS)] == _INVARIANT_LIMITATIONS and len(_INVARIANT_LIMITATIONS) == 6)
    ck("flip HOLDING_AUTONOMY_ENABLED -> the autonomy-OFF limitation disappears (live-derived, not static)",
       any("Holding autonomy is OFF" in l for l in a["cannot"])
       and not any("Holding autonomy is OFF" in l for l in ans({**OFF, "HOLDING_AUTONOMY_ENABLED": True})["cannot"]))

    # ── no hardcoded capability list beyond the policy invariants ─────────────────────────────────
    src = Path(ca.__file__).read_text()
    seed = seed_registry().list()
    ck("no seed capability NAME or ID is written into the module (the registry is the only catalog)",
       a["hardcoded_list"] is False and not any((m.id in src) or (m.name in src) for m in seed))
    ck("every flag the answer reads is one of self_model.FLAG_KEYS (the ONE reader)",
       set(re.findall(r"\"((?:KAI_|HOLDING_)[A-Z_]+|MONEY_MODE|APP_ENV)\"", src)) <= set(FLAG_KEYS))
    ck("self_model.FLAG_KEYS extension: every key is a real Settings field (MONEY_MODE is env/App-A-owned) and _flags() returns exactly them",
       set(_flags()) == set(FLAG_KEYS) and len(FLAG_KEYS) == 16
       and all(hasattr(__import__("app.config", fromlist=["settings"]).settings, k) for k in FLAG_KEYS if k != "MONEY_MODE"))
    pure_rows = ("holding.priorities", "holding.holding_problems", "holding.health_score", "holding.eval_harness",
                 "holding.explain", "holding.missions", "deployment.status")
    orig = ca._module_present
    try:
        ca._module_present = lambda mod: False
        absent = ans()
    finally:
        ca._module_present = orig
    ck("deterministic-module rows are derived from runtime presence: present -> AVAILABLE, absent -> UNAVAILABLE",
       all(row(a, r)["status"] == "AVAILABLE" for r in pure_rows) and all(row(absent, r)["status"] == UNAVAILABLE for r in pure_rows)
       and ca._module_present("app.services.holding.priorities") and not ca._module_present("app.services.holding.does_not_exist"))

    # ── runtime posture / connectors / finance / money — each from a real probe or flag ───────────
    ck("runtime posture stays inside the 8 statuses: AUTONOMOUS_READ_ONLY->AVAILABLE, DEGRADED->BLOCKED, unknown->UNAVAILABLE",
       row(ans(autonomy={"overall": "AUTONOMOUS_READ_ONLY"}), "runtime.autonomy_status")["status"] == "AVAILABLE"
       and row(ans(autonomy={"overall": "DEGRADED"}), "runtime.autonomy_status")["status"] == "BLOCKED"
       and row(a, "runtime.autonomy_status")["status"] == UNAVAILABLE
       and "overall=DEGRADED" in row(ans(autonomy={"overall": "DEGRADED"}), "runtime.autonomy_status")["why"])
    ck("telegram from status.telegram_status presence: CONNECTED->ACTIVE, DEGRADED->DISABLED, absent->AUTH_REQUIRED",
       row(ans(telegram={"state": "CONNECTED"}), "connector.telegram")["status"] == "ACTIVE"
       and row(ans(telegram={"state": "DEGRADED"}), "connector.telegram")["status"] == "DISABLED"
       and row(a, "connector.telegram")["status"] == "AUTH_REQUIRED")
    ck("finance feed UNAVAILABLE unless a live source is wired (figures never estimated); money.move DISABLED under a DECLARED MOCK",
       row(a, "finance.feed")["status"] == UNAVAILABLE and row(ans(finance_available=True), "finance.feed")["status"] == "AVAILABLE"
       and row(a, "money.move")["status"] == "DISABLED" and row(ans({**OFF, "MONEY_MODE": "LIVE"}), "money.move")["status"] == "RESTRICTED")
    # ── review M6: MONEY_MODE is not a Settings field here; the real money path has its own switches ──
    nomode = ans({**OFF, "MONEY_MODE": None})
    ck("M6: MONEY_MODE None (not declared in this app's Settings) -> money.move UNAVAILABLE with the honest why, never a fabricated MOCK observation",
       row(nomode, "money.move")["status"] == UNAVAILABLE
       and row(nomode, "money.move")["why"].startswith("MONEY_MODE not declared in this app's Settings (readers default MOCK)")
       and nomode["authority"]["MONEY_MODE"] is None)
    ck("M1: MONEY_MODE None -> the 'cannot' list carries NO 'MONEY_MODE=MOCK' / 'never move money' claim beside the UNAVAILABLE money.move row; a declared MOCK still does",
       not any("MONEY_MODE=MOCK" in l or "never move money" in l for l in nomode["cannot"])
       and any("MONEY_MODE is not declared" in l for l in nomode["cannot"]) and any("MONEY_MODE=MOCK" in l for l in a["cannot"]))
    ck("M6: the false 'no money moves' observation is gone; the §99 invariant is phrased as POLICY ('without owner authority') on every finance row",
       not any("no money moves" in r["why"] for r in rows(a) + rows(nomode))
       and all("without owner authority" in row(x, cid)["why"] for x in (a, nomode) for cid in ("money.move", "finance.sol_transfer")))
    sol_off, sol_on = ans(money_switches=SW_OFF), ans(money_switches=SW_ON)
    ck("M6: finance.sol_transfer is derived from the REAL switches: switches unreadable -> UNAVAILABLE; scope off -> DISABLED (ScopeDenied); scope on -> RESTRICTED (approved=True + sandbox-lock still required)",
       row(a, "finance.sol_transfer")["status"] == UNAVAILABLE and "unreadable" in row(a, "finance.sol_transfer")["why"]
       and row(sol_off, "finance.sol_transfer")["status"] == "DISABLED" and "KAI_SCOPE_SOL_TRANSFER=off" in row(sol_off, "finance.sol_transfer")["why"]
       and "ScopeDenied" in row(sol_off, "finance.sol_transfer")["why"]
       and row(sol_on, "finance.sol_transfer")["status"] == "RESTRICTED" and "KAI_SCOPE_SOL_TRANSFER=on" in row(sol_on, "finance.sol_transfer")["why"]
       and "approved=True" in row(sol_on, "finance.sol_transfer")["why"])
    ck("M6: the why reports each switch's posture (DWOLLA_ENV, DWOLLA_ALLOW_PRODUCTION, credential PRESENCE) and the source names the env switches",
       "DWOLLA_ENV=sandbox" in row(sol_on, "finance.sol_transfer")["why"] and "DWOLLA_ALLOW_PRODUCTION=False" in row(sol_on, "finance.sol_transfer")["why"]
       and "Dwolla credentials present=True" in row(sol_on, "finance.sol_transfer")["why"]
       and "Dwolla credentials present=False" in row(sol_off, "finance.sol_transfer")["why"]
       and row(sol_on, "finance.sol_transfer")["source"] == "config.env:KAI_SCOPE_SOL_TRANSFER,DWOLLA_ENV,DWOLLA_ALLOW_PRODUCTION"
       and row(ans(money_switches={**SW_ON, "dwolla_env": "production", "dwolla_allow_production": True}), "finance.sol_transfer")["why"]
       .count("DWOLLA_ENV=production, DWOLLA_ALLOW_PRODUCTION=True") == 1)
    live_sw = ca.sol_money_switches()
    ck("sol_money_switches() composes governance.is_scope_enabled + dwolla.client (presence only, no key value) over the REAL env",
       set(live_sw) == {"scope_sol_transfer", "dwolla_env", "dwolla_allow_production", "dwolla_credentials_present"}
       and all(isinstance(live_sw[k], bool) for k in ("scope_sol_transfer", "dwolla_allow_production", "dwolla_credentials_present"))
       and isinstance(live_sw["dwolla_env"], str))
    ck("os_lab RESTRICTED when its catalog is present, UNAVAILABLE otherwise",
       row(ans(os_lab_present=True), "os_lab")["status"] == "RESTRICTED" and row(a, "os_lab")["status"] == UNAVAILABLE)
    ck("connectors = MCP-type manifests + connector.* rows", set(a["connectors"]) == {"context7", "quarantined-x", "off-tool",
                                                                                      "stripe-mcp", "connector.telegram"})

    # ── areas: whole-token match, never a substring accident ──────────────────────────────────────
    ck("area_of: 'payloads' is security (not 'ads'->marketing), 'download_video' is engineering, stripe is finance",
       area_of(PAYLOADS) == "security" and area_of(YTDLP) == "engineering" and area_of(STRIPE) == "finance"
       and area_of(CTX7) == "analysis")

    # ── live smoke over the REAL registry + flags (DB-less: every probe fails soft) ───────────────
    la = ca.live_answer()
    ck("live_answer(): real 126+ manifests, every row inside the 8 statuses, counts partition, cannot led by the invariants",
       len(rows(la)) >= 126 and all(r["status"] in STATUSES for r in rows(la))
       and sum(la["counts"].values()) == len(rows(la)) and la["cannot"][:2] == _INVARIANT_LIMITATIONS[:2]
       and la["authority"]["KAI_CAPABILITY_EXECUTION_ENABLED"] is False)
    from app.services.holding.worker_health import read_stop, stop_state
    real_stop = read_stop()          # DB-less run: unreadable -> None -> treated as engaged everywhere
    ck("live_answer(): the REAL MONEY_MODE is None in this app -> money.move UNAVAILABLE; the §97 STOP is read once via brakes and threaded (never assumed RELEASED)",
       _flags()["MONEY_MODE"] is None and row(la, "money.move")["status"] == UNAVAILABLE
       and la["authority"]["STOP_AUTONOMOUS_EXECUTION"] == stop_state(real_stop) == la["workers"]["stop_record_state"]
       and (real_stop is not None or la["authority"]["STOP_AUTONOMOUS_EXECUTION"] == "UNAVAILABLE")
       and all(row(la, g)["status"] == "DISABLED" for g in ("holding.autonomous_work", "a2.prepare_only", "self_improvement.prepare"))
       and la["counts"]["ACTIVE"] == 0 or la["authority"]["KAI_CAPABILITY_EXECUTION_ENABLED"])
    ck("live_answer(): the Sol money row is derived from the real switches (DISABLED / RESTRICTED, never UNAVAILABLE when the env is readable)",
       row(la, "finance.sol_transfer")["status"] in ("DISABLED", "RESTRICTED") and "KAI_SCOPE_SOL_TRANSFER=" in row(la, "finance.sol_transfer")["why"])

    # ── consolidation + purity ────────────────────────────────────────────────────────────────────
    ck("composes self_model._derive_limitations, worker_health.normalize, coding.coding_action_class, brakes STOP vocabulary, governance/dwolla readers (no forks)",
       "from app.services.holding.self_model import _derive_limitations" in src
       and "from app.services.holding.worker_health import LIVE_STATES, normalize" in src
       and "from app.services.capability.coding import coding_action_class" in src
       and "from app.services.holding.brakes import STOP" in src
       and "from app.services.governance.actions import is_scope_enabled" in src
       and "from app.services.dwolla.client import _env, _truthy, is_configured" in src
       and "from app.services.holding.worker_health import read_stop" in src)
    ck("no LLM / network / clock", all(t not in src for t in ("datetime.now", "time.time", "openai", "ollama", "httpx",
                                                              "requests", "capability.brain", "nai_brain", "subprocess")))

    n = len(res); ok = sum(res)
    print(f"\nCAPABILITIES ANSWER (§98/§99) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
