"""§98/§99 dynamic "What can you do?" / "What can't you do?" — aggregated LIVE from the real registries
and policy, never a hard-coded marketing list.

Inputs (all existing, all injectable): the CapabilityRegistry manifests (availability / activation /
certification / risk / tier), the §119 worker-health snapshot (``worker_health.normalize`` over the same
CodingWorkerRouter manifests — Claude is AUTH_BLOCKED when its credential is absent, never a remembered
history), the holding services' real config flags (``self_model._flags`` — the ONE reader), the approved
connectors (MCP-type capabilities + ``status.telegram_status`` presence-only), the mission/cycle flags,
and runtime health (``status.autonomy_status``).

Every capability is tagged with exactly one of
    AVAILABLE / ACTIVE / DISABLED / BLOCKED / AUTH_REQUIRED / RESTRICTED / UNAVAILABLE / EXPERIMENTAL
by the versioned rule table ``status_of`` — a pure function of manifest fields + flags + the §97 STOP
record, so flipping a flag (e.g. KAI_CAPABILITY_EXECUTION_ENABLED) or engaging STOP observably changes the
answer. ACTIVE is claimed ONLY when execution authority exists right now (brakes on AND STOP released);
an observed-live worker with no authority is AVAILABLE, never ACTIVE. STOP unreadable → treated as
engaged (fail closed, brakes' own rule). "Can't / not allowed" is DERIVED from policy:
``self_model._derive_limitations`` (the invariants + live flag posture) — no second limitations list.
Money: MONEY_MODE is NOT declared in this app's Settings (readers default MOCK) → reported UNAVAILABLE,
never as an observed mode; the real money path (routers/sol.py → governance scope ``sol.transfer`` →
DwollaClient sandbox-lock) is reported from ITS switches. Deterministic; testable as a plain ``python3``
script (mirrors test_registry.py).
"""
from __future__ import annotations

import importlib.util
import re

from app.services.capability.manifest import (Availability as AV, Certification as CE, ActivationMode as AM,
                                              RiskClass as RK, CapabilityType as CT)
from app.services.capability.coding import coding_action_class
from app.services.holding.brakes import STOP                      # §97 — the ONE stop vocabulary
from app.services.holding.self_model import _derive_limitations
from app.services.holding.worker_health import LIVE_STATES, normalize as normalize_workers, stop_state

CAPABILITIES_ANSWER_VERSION = "1.1.0"
UNAVAILABLE = "UNAVAILABLE"
AREAS = ("observation", "analysis", "engineering", "browser-research", "files", "deployment",
         "marketing", "finance", "security", "systems-research", "communication")
STATUSES = ("AVAILABLE", "ACTIVE", "DISABLED", "BLOCKED", "AUTH_REQUIRED", "RESTRICTED", UNAVAILABLE, "EXPERIMENTAL")

# Versioned type → area table (a manifest's own type; keyword areas below refine from its declared verbs).
_TYPE_AREA = {
    CT.CODING_WORKER: "engineering", CT.CODING_CLI: "engineering", CT.CODING_IDE_ADAPTER: "engineering",
    CT.CODING_CLOUD_AGENT: "engineering", CT.CODE_TOOL: "engineering", CT.WORKSPACE_ADAPTER: "engineering",
    CT.AGENT_RUNTIME: "engineering",
    CT.BROWSER_TOOL: "browser-research", CT.OSINT_RESOURCE_PACK: "browser-research",
    CT.SECURITY_KNOWLEDGE_PACK: "security", CT.SECURITY_DATA_PACK: "security", CT.SECURITY_ROUTER: "security",
    CT.SECURITY_EXECUTION_FRAMEWORK: "security",
    CT.COLLABORATION_TOOL: "communication",
    CT.NATIVE_KAI_TOOL: "observation", CT.MEMORY_PROVIDER: "observation",
}
_KEYWORD_AREA = (   # (area, keywords) — matched against the manifest's OWN capabilities+triggers, in order
    ("finance", ("stripe", "finance", "payment", "payments", "billing", "invoice", "trading")),
    ("marketing", ("marketing", "seo", "ads", "campaign")),
    ("deployment", ("deploy", "railway", "cloudflare", "docker", "kubernetes")),
    ("communication", ("slack", "telegram", "email", "notify", "messaging")),
    ("files", ("file", "document", "pdf", "convert", "markdown")),
)
# §119 worker state → §98 status. Live states are AVAILABLE: liveness is an observation, ACTIVE is a claim of
# execution authority, which only the brakes + a released STOP grant (answer() upgrades to ACTIVE then).
_WORKER_STATUS = {"BUSY": "AVAILABLE", "IDLE": "AVAILABLE", "ONLINE": "AVAILABLE", "DEGRADED": "BLOCKED",
                  "AUTH_BLOCKED": "AUTH_REQUIRED", "OFFLINE": UNAVAILABLE, "QUARANTINED": "BLOCKED"}


def _stop_why(stopped) -> str:
    """The §97 reason text; ``stopped`` None = record unreadable → treated as engaged (fail closed)."""
    return f"{STOP} engaged (brakes)" + ("" if stopped else " — record unreadable, treated as engaged (fail closed)")


def area_of(m) -> str:
    toks = set(re.findall(r"[a-z0-9]+", " ".join(list(m.capabilities or []) + list(m.triggers or [])).lower()))
    for area, kws in _KEYWORD_AREA:
        if toks & set(kws):   # whole-token EXACT match: 'payloads' is not 'ads', 'documentation' is not 'document'
            return area
    return _TYPE_AREA.get(m.type, "analysis")


def _module_present(mod: str) -> bool:
    """A pure holding module is AVAILABLE only if it is importable in THIS runtime — never a static claim."""
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:      # noqa: BLE001
        return False


def status_of(m, flags: dict, stopped=None) -> tuple[str, str]:
    """THE versioned rule table: (status, why) from the manifest's real fields + the execution brake + §97
    STOP (``stopped`` True/None → never ACTIVE)."""
    if m.availability == AV.QUARANTINED:
        return "BLOCKED", "QUARANTINED after a policy/health violation (§52) — cleared only explicitly"
    if m.availability == AV.EXTERNAL_BLOCKED or m.certification in (CE.EXTERNAL_BLOCKED, CE.REJECTED):
        return "BLOCKED", f"availability={m.availability.value}, certification={m.certification.value}"
    if m.availability == AV.DISABLED or m.activation == AM.DISABLED:
        return "DISABLED", f"availability={m.availability.value}, activation={m.activation.value}"
    if m.availability != AV.AVAILABLE:
        return UNAVAILABLE, f"catalog availability {m.availability.value} (not installed/verified)"
    restricted = (m.risk_class == RK.RESTRICTED or not m.automatic_activation_allowed or m.security_tier >= 3
                  or m.operator_approval_required or m.authorized_context_required)
    if restricted:
        return "RESTRICTED", "never auto-selected; needs an authorized mission / explicit operator approval (§23/§31)"
    if m.certification in (CE.EXPERIMENTAL, CE.PARTIAL, CE.UPSTREAM_UNRESOLVED):
        return "EXPERIMENTAL", f"available but certification={m.certification.value}"
    if (flags or {}).get("KAI_CAPABILITY_EXECUTION_ENABLED"):
        if stopped is False:
            return "ACTIVE", "certified + selectable, and the execution plane (brake #1) is ON"
        return "AVAILABLE", (f"certified + selectable; brake #1 is ON but {_stop_why(stopped)} — no autonomous "
                             "execution (owner-driven invocation is not halted by STOP)")
    return "AVAILABLE", "certified + selectable; execution plane (brake #1 KAI_CAPABILITY_EXECUTION_ENABLED) is OFF"


def _flag_status(flags: dict, key: str, *, on="ACTIVE", off="DISABLED") -> tuple[str, str]:
    on_ = bool((flags or {}).get(key))
    return (on if on_ else off), f"config.{key}={on_}"


def _service_entries(flags: dict, *, stopped, telegram: dict, autonomy: dict, finance_available: bool,
                     os_lab_present, money_switches) -> list[dict]:
    """Holding services / mission system / connectors / authority — each derived from a REAL flag or probe."""
    f = flags or {}
    brakes = f.get("KAI_CAPABILITY_EXECUTION_ENABLED") and f.get("HOLDING_AUTONOMY_ENABLED")
    a2 = brakes and f.get("KAI_A2_EXECUTION_ENABLED")
    rows = []

    def add(area, cid, name, status, why, source):
        rows.append({"area": area, "id": cid, "name": name, "status": status, "why": why, "source": source})

    def halted(on, why):
        """§97: the three autonomous-execution rows are DISABLED while STOP is engaged or unreadable."""
        if stopped is not False:
            return "DISABLED", f"{_stop_why(stopped)}; {why}"
        return ("ACTIVE" if on else "DISABLED"), why

    for area, cid, name, key in (
        ("observation", "holding.view", "Holding view (read-only twin/registry)", "KAI_HOLDING_ENABLED"),
        ("observation", "holding.watch", "Continuous watch (change/anomaly detection)", "KAI_HOLDING_WATCH_ENABLED"),
        ("observation", "holding.cycle", "Bounded holding cycle (mission system beat, §30)", "KAI_HOLDING_CYCLE_ENABLED"),
        ("observation", "holding.proactive", "Proactive briefing engine (§11)", "KAI_PROACTIVE_ENABLED"),
        ("analysis", "holding.command", "Typed holding command API (§90)", "KAI_HOLDING_COMMAND_ENABLED"),
        ("analysis", "self_improvement.detect", "Self-improvement detection (read-only)", "KAI_SELF_IMPROVEMENT_DETECT_ENABLED"),
        ("communication", "holding.briefing", "Daily briefing routine", "KAI_HOLDING_BRIEFING_ENABLED"),
        ("communication", "voice.command_center", "Voice command center (§7, PTT, never authorizes)", "KAI_VOICE_ENABLED"),
        ("security", "cyber.read_only_ops", "Cyber operations (defensive, read-only)", "KAI_CYBER_OPS_ENABLED"),
    ):
        s, why = _flag_status(f, key)
        add(area, cid, name, s, why, f"config.{key}")
    for name, key in (("priorities", "§22 ladder"), ("holding_problems", "§18"), ("health_score", "§57"),
                      ("eval_harness", "§34"), ("explain", "§87")):
        present = _module_present(f"app.services.holding.{name}")
        add("analysis", f"holding.{name}", f"{name} ({key}, deterministic)", "AVAILABLE" if present else UNAVAILABLE,
            "pure deterministic function over real records — no flag, no execution" if present
            else "module not importable in this runtime", f"holding.{name}")
    present = _module_present("app.services.holding.mission")
    add("observation", "holding.missions", "Mission headers (§27, read-only store)", "AVAILABLE" if present else UNAVAILABLE,
        "read-only records; execution of mission work needs the brakes" if present
        else "module not importable in this runtime", "holding.mission")
    add("engineering", "holding.autonomous_work", "Autonomous work engine (A0/A1)",
        *halted(brakes, f"brake #1 KAI_CAPABILITY_EXECUTION_ENABLED={bool(f.get('KAI_CAPABILITY_EXECUTION_ENABLED'))}, "
                        f"brake #2 HOLDING_AUTONOMY_ENABLED={bool(f.get('HOLDING_AUTONOMY_ENABLED'))}"),
        "holding.holding_cycle.build_live_engine")
    add("engineering", "a2.prepare_only", "A2 isolated-worktree prepare (never merge/deploy)",
        *halted(a2, f"needs brakes #1+#2 and #3 KAI_A2_EXECUTION_ENABLED={bool(f.get('KAI_A2_EXECUTION_ENABLED'))}"),
        "holding.a2_framework")
    add("engineering", "self_improvement.prepare", "Self-improvement preparation (READY_FOR_REVIEW only)",
        *halted(a2 and f.get("KAI_SELF_IMPROVEMENT_ENABLED"),
                f"needs the three A2 brakes + KAI_SELF_IMPROVEMENT_ENABLED={bool(f.get('KAI_SELF_IMPROVEMENT_ENABLED'))}"),
        "holding.self_improvement_guardrails")
    for op in ("merge", "deploy", "branch_protection"):
        ac = coding_action_class(op).value
        add("deployment", f"code.{op}", f"{op} (action class {ac})",
            "DISABLED" if ac == "PROHIBITED" else "RESTRICTED",
            f"governed action class {ac}: owner-only approval; a worker never {op}s independently (§14)",
            "capability.coding.coding_action_class")
    present = _module_present("app.services.holding.deployment_status")
    add("deployment", "deployment.status", "Deployment SHA/status read adapter", "AVAILABLE" if present else UNAVAILABLE,
        "read-only provider adapter; no write path" if present else "module not importable in this runtime",
        "holding.deployment_status")
    money = f.get("MONEY_MODE")
    policy = "money never moves without owner authority (§99 policy — owner-only FINANCIAL action class)"
    if money is None:            # this app's Settings declares no MONEY_MODE: a reader default is not an observation
        add("finance", "money.move", "Move / pay / trade / change budgets", UNAVAILABLE,
            f"MONEY_MODE not declared in this app's Settings (readers default MOCK); {policy}", "config.MONEY_MODE")
    else:
        add("finance", "money.move", "Move / pay / trade / change budgets",
            "DISABLED" if money == "MOCK" else "RESTRICTED", f"MONEY_MODE={money} (declared); {policy}", "config.MONEY_MODE")
    sw = money_switches if isinstance(money_switches, dict) else None
    if sw is None:
        add("finance", "finance.sol_transfer", "Sol ROSCA money movement (Dwolla ACH collect / payout)", UNAVAILABLE,
            f"money-path switches unreadable (governance scope sol.transfer / Dwolla env); {policy}",
            "config.env:KAI_SCOPE_SOL_TRANSFER,DWOLLA_ENV,DWOLLA_ALLOW_PRODUCTION")
    else:
        scope = bool(sw.get("scope_sol_transfer"))
        add("finance", "finance.sol_transfer", "Sol ROSCA money movement (Dwolla ACH collect / payout)",
            "RESTRICTED" if scope else "DISABLED",
            f"KAI_SCOPE_SOL_TRANSFER={'on' if scope else 'off'} (governance scope sol.transfer on routers/sol.py"
            f"{'' if scope else ' → ScopeDenied'}); every call also needs approved=True (destructive) + the DwollaClient "
            f"sandbox-lock: DWOLLA_ENV={sw.get('dwolla_env') or UNAVAILABLE}, "
            f"DWOLLA_ALLOW_PRODUCTION={bool(sw.get('dwolla_allow_production'))}, "
            f"Dwolla credentials present={sw.get('dwolla_credentials_present')} (presence only); {policy}",
            "config.env:KAI_SCOPE_SOL_TRANSFER,DWOLLA_ENV,DWOLLA_ALLOW_PRODUCTION")
    add("finance", "finance.feed", "Live authoritative finance/revenue feed",
        "AVAILABLE" if finance_available else UNAVAILABLE,
        "authoritative source wired" if finance_available else "no live Stripe/CRM/billing source — figures UNAVAILABLE, never estimated",
        "holding.registry.report_value")
    tg = (telegram or {}).get("state")
    add("communication", "connector.telegram", "Telegram delivery channel",
        {"CONNECTED": "ACTIVE", "DEGRADED": "DISABLED"}.get(tg, "AUTH_REQUIRED"),
        {"CONNECTED": "token present + delivery opted in", "DEGRADED": "token present, KAI_HOLDING_DELIVERY_ENABLED off"}
        .get(tg, "no bot token/chat id present (presence only)"), "holding.status.telegram_status")
    add("systems-research", "os_lab", "OS / kernel research lab (§39-44)",
        "RESTRICTED" if os_lab_present else UNAVAILABLE,
        "RESTRICTED_SECURITY_LAB / EDUCATIONAL_SANDBOX only, default OFF, production=NO; needs operator sign-off"
        if os_lab_present else "os_lab catalog not present", "holding.os_lab.catalog")
    overall = (autonomy or {}).get("overall") if isinstance(autonomy, dict) else None
    add("observation", "runtime.autonomy_status", "Runtime posture",
        {"AUTONOMOUS_READ_ONLY": "AVAILABLE", "DEGRADED": "BLOCKED"}.get(overall, UNAVAILABLE),   # stays in STATUSES
        f"status.autonomy_status overall={overall or UNAVAILABLE} (DEGRADED when the worker plane is offline)",
        "holding.status.autonomy_status")
    return rows


def answer(*, manifests, flags, worker_snapshot=None, telegram=None, autonomy=None,
           finance_available: bool = False, os_lab_present: bool = False, stopped=None, money_switches=None) -> dict:
    """§98/§99 pure answer. ``manifests`` = registry manifests; ``flags`` = self_model._flags() shape;
    ``worker_snapshot`` = worker_health.normalize(...) (built here from the manifests when None);
    ``stopped`` = §97 STOP tri-state (True engaged / False released / None unreadable → treated as engaged);
    ``money_switches`` = sol_money_switches() (None → the Sol money row is UNAVAILABLE)."""
    flags = flags or {}
    ws = worker_snapshot or normalize_workers(manifests=manifests, flags=flags, stopped=stopped)
    wstate = {w["worker"]: w for w in ws.get("workers", [])}
    rows = []
    for m in manifests or []:
        if m.id in wstate:                       # §119/§120 real worker truth wins over the catalog row
            w = wstate[m.id]
            status = _WORKER_STATUS[w["state"]]
            if status == "AVAILABLE" and w["execution_authority"] != "NONE" and stopped is False:
                status = "ACTIVE"                # observed live AND holds execution authority right now
            rows.append({"area": "engineering", "id": m.id, "name": m.name, "status": status,
                         "why": f"worker {w['state']}: " + "; ".join(w["reasons"]),
                         "source": "holding.worker_health", "worker_state": w["state"],
                         "execution_authority": w["execution_authority"]})
            continue
        s, why = status_of(m, flags, stopped)
        rows.append({"area": area_of(m), "id": m.id, "name": m.name, "status": s, "why": why,
                     "source": f"capability.registry:{m.id}", "type": m.type.value})
    rows += _service_entries(flags, stopped=stopped, telegram=telegram or {}, autonomy=autonomy or {},
                             finance_available=finance_available, os_lab_present=os_lab_present,
                             money_switches=money_switches)
    areas = []
    for a in AREAS:
        items = sorted((r for r in rows if r["area"] == a), key=lambda r: r["id"])
        areas.append({"area": a, "capabilities": items,
                      "summary": {s: sum(1 for r in items if r["status"] == s) for s in STATUSES if any(r["status"] == s for r in items)}})
    can = [f"{r['name']} [{r['status']}] — {r['why']}" for r in rows if r["status"] in ("ACTIVE", "AVAILABLE")]
    restricted = [f"{r['name']} — {r['why']}" for r in rows if r["status"] == "RESTRICTED"]
    coding_workers = [{"id": w["worker"], "name": w["name"], "available": w["state"] in LIVE_STATES,
                       "state": w["state"]} for w in ws.get("workers", [])]
    cannot = _derive_limitations(flags, finance_available=finance_available, coding_workers=coding_workers)
    connectors = [r["id"] for r in rows if r.get("type") == CT.MCP.value or r["id"].startswith("connector.")]
    return {"version": CAPABILITIES_ANSWER_VERSION,
            "areas": areas, "can": can, "restricted": restricted,
            "cannot": cannot, "cannot_source": "self_model._derive_limitations (policy invariants + live flags)",
            "authority": {**{k: flags.get(k) for k in ("MONEY_MODE", "KAI_CAPABILITY_EXECUTION_ENABLED",
                                                        "HOLDING_AUTONOMY_ENABLED", "KAI_A2_EXECUTION_ENABLED",
                                                        "KAI_SELF_IMPROVEMENT_ENABLED", "APP_ENV")},
                          STOP: stop_state(stopped)},
            "workers": ws, "connectors": connectors,
            "counts": {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES},
            "derived_from": ["capability.registry (seed manifests)", "holding.worker_health", "self_model._flags",
                             "holding.brakes.stop_record (§97 STOP)", "holding.status.telegram_status",
                             "holding.status.autonomy_status", "holding.registry.report_value",
                             "governance.actions.is_scope_enabled + dwolla.client (Sol money-path switches)",
                             "self_model._derive_limitations"],
            "hardcoded_list": False}


def sol_money_switches() -> dict:
    """The REAL switches on the only money path in this app (routers/sol.py collect/payout → governance
    ``@audited(scope="sol.transfer", destructive=True)`` → DwollaClient sandbox-lock), read by the modules
    that enforce them — presence/posture only, never a key value (§120)."""
    from app.services.governance.actions import is_scope_enabled
    from app.services.dwolla.client import _env, _truthy, is_configured
    return {"scope_sol_transfer": is_scope_enabled("sol.transfer"), "dwolla_env": _env(),
            "dwolla_allow_production": _truthy("DWOLLA_ALLOW_PRODUCTION"), "dwolla_credentials_present": is_configured()}


def live_answer() -> dict:
    """The live §98/§99 answer from the REAL sources (each fail-soft → UNAVAILABLE/empty, never a guess).
    §97 STOP is read ONCE (worker_health.read_stop over brakes.stop_record) and threaded everywhere."""
    from app.services.capability.seed import seed_registry
    from app.services.holding import self_model as sm
    from app.services.holding.worker_health import read_stop, snapshot as worker_snapshot
    manifests = seed_registry().list()
    def _try(fn, default):
        try:
            return fn()
        except Exception:      # noqa: BLE001 — a failing subsystem is honestly UNAVAILABLE
            return default
    flags = _try(sm._flags, {})
    stopped = read_stop()                      # None = unreadable → treated as engaged downstream
    try:
        from app.services.holding.os_lab import catalog as _os_lab   # noqa: F401
        os_lab_present = True
    except Exception:
        os_lab_present = False
    from app.services.holding import status as hstat
    return answer(manifests=manifests, flags=flags,
                  worker_snapshot=_try(lambda: worker_snapshot(flags=flags, stopped=stopped), None),
                  telegram=_try(hstat.telegram_status, {}), autonomy=_try(hstat.autonomy_status, {}),
                  finance_available=_try(sm._finance_available, False), os_lab_present=os_lab_present,
                  stopped=stopped, money_switches=_try(sol_money_switches, None))


if __name__ == "__main__":
    from app.services.holding.test_capabilities_answer import run
    raise SystemExit(0 if run() else 1)
