"""§78 unified resource governor + §118 observability — no-fabrication + composition guard. Zero-framework
(mirrors test_registry.py). Every source is injected in the EXACT shape the real reader emits. Run (from backend/):
    python3 -m app.services.holding.test_resource_governor
"""
import inspect
import json
import platform
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path so `app` is a package

from app.services.holding import resource_governor as rg                        # noqa: E402
from app.services.holding.resource_governor import (                            # noqa: E402
    budgets, anomaly, anomalies, observability, snapshot, budget_state,
    UNAVAILABLE, NO_CAP_DECLARED, WITHIN_CAP, OVER_CAP, GOVERNOR_VERSION)

NOW = "2026-09-04T12:00:00+00:00"
TODAY = "2026-09-04"
NONE_SOURCES = {k: (lambda: None) for k in rg._DEFAULT_SOURCES}                 # every source unreadable


def _raise():
    raise RuntimeError("source down")


RAISING_SOURCES = {k: _raise for k in rg._DEFAULT_SOURCES}

# ── fixtures in the emitted shapes ────────────────────────────────────────────────────────────────────
USAGE = {   # _llm_usage() shape
    "per_user": {"u1": {"day_usd": 1.5, "month_usd": 10.0}, "u2": {"day_usd": 2.0, "month_usd": 5.0}},
    "per_provider": {"openai": {"calls": 4, "tokens": 900, "usd": 0.7, "avg_latency_ms": 400, "success": 4},
                     "ollama": {"calls": 9, "tokens": 5000, "usd": 0.0, "avg_latency_ms": 900, "success": 8}},
    "per_model_latency": {"gpt-4o-mini": {"calls": 4, "avg_ms": 400, "max_ms": 700}},
    "daily": [{"day": f"2026-09-0{d}", "calls": 10, "usd": 0.5} for d in range(1, 4)] +
             [{"day": "2026-08-31", "calls": 10, "usd": 0.5}, {"day": "2026-08-30", "calls": 10, "usd": 0.5},
              {"day": "2026-08-29", "calls": 10, "usd": 0.5}, {"day": "2026-08-28", "calls": 10, "usd": 0.5},
              {"day": TODAY, "calls": 30, "usd": 1.9}],
    "window": "24h / month-to-date / 8 days",
}
JOBS = [    # worker_jobs.list_jobs shape (coding worker rows carry task.task_id; si: = self-improvement)
    {"id": 1, "created_at": f"{TODAY} 09:00:00+00:00", "worker": "coding", "status": "succeeded",
     "task": {"task_id": "a2:si:failing_suite:x", "cost_budget": 0.5}, "evidence": {"cost": 0.25}},
    {"id": 2, "created_at": f"{TODAY} 10:00:00+00:00", "worker": "coding", "status": "running",
     "task": {"task_id": "a2:si:flaky:y", "cost_budget": 1.0}, "evidence": None},
    {"id": 3, "created_at": "2026-09-03 10:00:00+00:00", "worker": "coding", "status": "succeeded",
     "task": {"task_id": "a2:si:old:z"}, "evidence": {"cost": 0.1}},                         # yesterday
    {"id": 4, "created_at": f"{TODAY} 11:00:00+00:00", "worker": "coding", "status": "queued",
     "task": {"task_id": "op-123"}, "evidence": None},                                        # operational
    {"id": 5, "created_at": f"{TODAY} 11:30:00+00:00", "worker": "github", "status": "running",
     "task": {"task_id": "si:not-coding"}, "evidence": None},                                 # not the coding worker
]
PLANE = {"counts": {"queued": 1, "running": 2, "claimed": 0, "succeeded": 2}, "rows": JOBS}
MISSIONS = [   # _missions() shape: mission headers + linked jobs (worker_jobs.list_for_mission rows)
    {"mission_id": "m1", "company": "sol", "status": None, "jobs": [JOBS[0], JOBS[1]]},
    {"mission_id": "m2", "company": "kai", "status": None, "jobs": []},
]
RATE = {"limit_per_min": 30, "windows": {"owner/health": 3, "owner/repo": 1},
        "enforced_by": "capability.execution.CapabilityExecutionService._rate_ok"}
INV = {"by_action_24h": {"capability.invoke_health": 3},
       "daily": [{"day": f"2026-09-0{d}", "count": 5} for d in range(1, 4)] + [{"day": TODAY, "count": 5}]}
SYSTEM_STUB = {"cpu": {"load_1m": 1.0, "load_5m": 1.0, "load_15m": 1.0, "cpu_count": 8, "source": "os.getloadavg"},
               "memory": None, "process_peak_rss_mb": 120, "disk": {"path": "/", "free_gb": 10.0, "total_gb": 100.0,
                                                                    "used_pct": 90, "source": "shutil.disk_usage"}}
FULL = {"spend_caps": rg._spend_caps,      # the REAL caps (spend_tracker constants) — the only cap source
        "llm_usage": lambda: USAGE, "worker_plane": lambda: PLANE, "missions": lambda: MISSIONS,
        "rate_limit": lambda: RATE, "invocations": lambda: INV, "system": lambda: SYSTEM_STUB,
        "browser_sessions": lambda: None}


def _rows(rows, dim):
    return {r["key"]: r for r in rows if r["dimension"] == dim}


def run() -> bool:
    res = []
    def ck(n, ok):
        res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    src = inspect.getsource(rg)

    # ── §78 composition: caps come ONLY from the real primitives (no parallel limiter) ────────────────
    from app.services.router import spend_tracker as st
    caps = rg._spend_caps()
    ck("§78 daily/monthly caps are READ from router.spend_tracker (DEFAULT_DAILY_CAP / DEFAULT_MONTHLY_CAP)",
       caps["daily_usd"] == float(st.DEFAULT_DAILY_CAP) and caps["monthly_usd"] == float(st.DEFAULT_MONTHLY_CAP)
       and "SpendTracker" in caps["enforced_by"])
    ck("budget_state mirrors SpendTracker's >= rule exactly (used == cap → OVER_CAP)",
       budget_state(2.0, 2.0) == OVER_CAP and budget_state(1.99, 2.0) == WITHIN_CAP
       and ">= self.daily_cap" in inspect.getsource(st.SpendTracker.over_daily_cap))

    from app.services.capability.execution import CapabilityExecutionService
    from app.services.capability.registry import CapabilityRegistry
    default_rl = inspect.signature(CapabilityExecutionService.__init__).parameters["rate_limit_per_min"].default
    rl = rg._rate_limit()
    ck("per-minute cap is READ from CapabilityExecutionService.rate_limit_per_min (its _rate_ok enforces)",
       rl["limit_per_min"] == int(default_rl) and rl["enforced_by"].endswith("_rate_ok"))
    # live windows: the governor reads the REAL service's _rate windows — never its own counter
    import app.routers.admin_capabilities as ac
    t = [1000.0]
    svc = CapabilityExecutionService(CapabilityRegistry(), clock=lambda: t[0], rate_limit_per_min=5)
    for _ in range(3):
        svc._rate_ok("owner", "health")
    saved = ac._service
    try:
        ac._service = svc
        live = rg._rate_limit()
        t[0] += 61.0                        # the same window, aged out by the real limiter's 60s rule
        aged = rg._rate_limit()
    finally:
        ac._service = saved
    ck("live 60s windows are the execution service's own (_rate) — 3 calls seen, then aged out at 61s",
       live["limit_per_min"] == 5 and live["windows"] == {"owner/health": 3} and aged["windows"] == {"owner/health": 0})

    from app.services.holding.self_improvement_guardrails import DAILY_PREPARATION_CEILING
    from app.services.holding.holding_cycle import SELF_IMPROVE_DAILY_CEILING
    rows = budgets(sources={**NONE_SOURCES, **FULL}, now=NOW, today=TODAY)
    si = _rows(rows, "per_day_self_improvement")[TODAY]
    ck("self-improvement/day cap == guardrails.DAILY_PREPARATION_CEILING == holding_cycle.SELF_IMPROVE_DAILY_CEILING",
       si["cap"] == DAILY_PREPARATION_CEILING == SELF_IMPROVE_DAILY_CEILING
       and "preparation_admission" in si["enforced_by"])
    ck("self-improvement used = today's si: coding jobs via guardrails.describe (2; not yesterday/operational/github)",
       si["used"] == 2 and si["state"] == WITHIN_CAP)

    from app.services.capability.coding import CodingTask
    ck("per-mission cap is coding.CodingTask.cost_budget (a declared field, surfaced not re-enforced)",
       "cost_budget" in inspect.signature(CodingTask).parameters
       and _rows(rows, "per_mission")["m1"]["cap_source"].startswith("coding.CodingTask.cost_budget")
       and "NOT_ENFORCED_AT_RUNTIME" in _rows(rows, "per_mission")["m1"]["enforced_by"])
    ck("no parallel limiter: budget_manager (NarAI ads) not imported; no enforce/raise-on-cap; no new cap constant",
       "from core.budget_manager" not in src and "import budget_manager" not in src
       and not re.search(r"\bdef (enforce|block|limit)\w*\(", src) and "raise " not in src)
    ck("§79 bounded: no daemon/loop/thread/sleep in the governor",
       not re.search(r"\b(threading|asyncio|schedule|while True|time\.sleep|sleep\()", src))
    ck("snapshot names the 4 composed primitives and the ignored false friend",
       {"router.spend_tracker", "capability.execution.rate_limit_per_min",
        "self_improvement_guardrails.DAILY_PREPARATION_CEILING", "coding.CodingTask.cost_budget"}
       <= set(snapshot(sources=NONE_SOURCES, now=NOW)["composes"])
       and any("budget_manager" in s for s in snapshot(sources=NONE_SOURCES, now=NOW)["ignores"]))

    # ── §78 budget views: per-day / per-month / per-provider / per-minute / per-mission / per-company ──
    day, month = _rows(rows, "per_day"), _rows(rows, "per_month")
    ck("per-day per user: u1 1.5 < cap WITHIN_CAP; u2 2.0 >= cap OVER_CAP (the tracker's own rule)",
       day["u1"]["state"] == WITHIN_CAP and day["u2"]["state"] == OVER_CAP and day["u2"]["cap"] == caps["daily_usd"]
       and day["u1"]["used_source"] == "llm_call_log")
    ck("per-month per user rows carry the monthly cap + used from llm_call_log",
       month["u1"]["used"] == 10.0 and month["u1"]["cap"] == caps["monthly_usd"] and month["u1"]["state"] == WITHIN_CAP)
    prov = _rows(rows, "per_provider")
    ck("per-provider: real 24h usage per adapter, NO cap exists → NO_CAP_DECLARED (never an invented cap)",
       prov["openai"]["used"] == 0.7 and prov["ollama"]["used"] == 0.0
       and all(r["cap"] == NO_CAP_DECLARED and r["state"] == NO_CAP_DECLARED for r in prov.values()))
    pm = _rows(rows, "per_minute")["capability_invocations"]
    ck("per-minute: cap 30 (service), used = peak live window (3), calls unit",
       pm["cap"] == 30 and pm["used"] == 3 and pm["unit"] == "calls" and pm["state"] == WITHIN_CAP)
    mis = _rows(rows, "per_mission")
    ck("per-mission: cap = min declared task.cost_budget (0.5), used = summed worker evidence.cost (0.25)",
       mis["m1"]["cap"] == 0.5 and mis["m1"]["used"] == 0.25 and mis["m1"]["state"] == WITHIN_CAP
       and "1/2 jobs report cost" in mis["m1"]["used_source"])
    ck("per-mission with no jobs → used UNAVAILABLE + NO_CAP_DECLARED (never 0)",
       mis["m2"]["used"] == UNAVAILABLE and mis["m2"]["cap"] == NO_CAP_DECLARED and mis["m2"]["state"] == NO_CAP_DECLARED)
    co = _rows(rows, "per_company")
    ck("per-company roll-up: sol = 0.25 over 1 mission/2 jobs; kai (no cost evidence) UNAVAILABLE",
       co["sol"]["used"] == 0.25 and co["sol"]["missions"] == 1 and co["sol"]["jobs"] == 2
       and co["kai"]["used"] == UNAVAILABLE and co["sol"]["cap"] == NO_CAP_DECLARED)
    ck("every budget row is versioned/observed and uses only the closed state vocabulary",
       all(r["observed_at"] == NOW and r["state"] in (WITHIN_CAP, OVER_CAP, UNAVAILABLE, NO_CAP_DECLARED) for r in rows))

    # ── unreadable sources → UNAVAILABLE, never zero, never a false 'no cap' ─────────────────────────
    dark = budgets(sources=NONE_SOURCES, now=NOW, today=TODAY)
    dd = _rows(dark, "per_day")
    ck("every source unreadable → per-day/month usage UNAVAILABLE and cap UNAVAILABLE (the cap exists; it is unreadable — NOT NO_CAP_DECLARED)",
       list(dd) == [UNAVAILABLE] and dd[UNAVAILABLE]["used"] == UNAVAILABLE and dd[UNAVAILABLE]["cap"] == UNAVAILABLE
       and dd[UNAVAILABLE]["state"] == UNAVAILABLE)
    ck("unreadable → per-provider / per-mission / per-company / per-minute / self-improvement all UNAVAILABLE (no 0)",
       _rows(dark, "per_provider")[UNAVAILABLE]["used"] == UNAVAILABLE
       and _rows(dark, "per_mission")[UNAVAILABLE]["used"] == UNAVAILABLE
       and _rows(dark, "per_company")[UNAVAILABLE]["used"] == UNAVAILABLE
       and _rows(dark, "per_minute")["capability_invocations"]["used"] == UNAVAILABLE
       and _rows(dark, "per_minute")["capability_invocations"]["cap"] == UNAVAILABLE
       and _rows(dark, "per_day_self_improvement")[TODAY]["used"] == UNAVAILABLE
       and not any(r["used"] == 0 for r in dark))
    mixed = budgets(sources={**NONE_SOURCES, **FULL, "spend_caps": lambda: None}, now=NOW, today=TODAY)
    ck("cap unreadable but usage readable → used stays REAL, state UNAVAILABLE (never guessed against a missing cap)",
       _rows(mixed, "per_day")["u1"]["used"] == 1.5 and _rows(mixed, "per_day")["u1"]["state"] == UNAVAILABLE)
    empty = budgets(sources={**NONE_SOURCES, "spend_caps": rg._spend_caps,
                             "llm_usage": lambda: {"per_user": {}, "per_provider": {}, "daily": []}},
                    now=NOW, today=TODAY)
    ck("readable-but-empty llm_call_log → a real 0.0 for '*' (source readable), not UNAVAILABLE",
       _rows(empty, "per_day")["*"]["used"] == 0.0 and _rows(empty, "per_day")["*"]["state"] == WITHIN_CAP)
    ck("a RAISING source is UNAVAILABLE (caught), and snapshot() never raises",
       _rows(budgets(sources=RAISING_SOURCES, now=NOW, today=TODAY), "per_day")[UNAVAILABLE]["used"] == UNAVAILABLE
       and snapshot(sources=RAISING_SOURCES, now=NOW)["version"] == GOVERNOR_VERSION)

    # ── §78 anomaly: spike vs baseline ONLY when a baseline exists ───────────────────────────────────
    seven = [{"day": f"2026-08-{d}", "value": 10} for d in range(28, 32)] + \
            [{"day": f"2026-09-0{d}", "value": 10} for d in range(1, 4)]
    spike = anomaly("m", seven + [{"day": TODAY, "value": 30}], today=TODAY)
    normal = anomaly("m", seven + [{"day": TODAY, "value": 29.9}], today=TODAY)
    ck("7 observed prior days at 10: today 30 (== 3x mean) → SPIKE; 29.9 → NORMAL (deterministic >= rule)",
       spike["verdict"] == "SPIKE" and spike["baseline_mean"] == 10.0 and spike["threshold"] == 30.0
       and normal["verdict"] == "NORMAL" and spike["baseline_days"] == 7)
    ck("same inputs → byte-identical output (versioned, no clock/randomness)",
       json.dumps(spike, sort_keys=True) == json.dumps(anomaly("m", seven + [{"day": TODAY, "value": 30}], today=TODAY), sort_keys=True)
       and spike["version"] == GOVERNOR_VERSION)
    thin = anomaly("m", seven[-2:] + [{"day": TODAY, "value": 1000}], today=TODAY)
    ck("only 2 observed prior days → INSUFFICIENT_BASELINE, baseline_mean UNAVAILABLE, no threshold — no guessed verdict",
       thin["verdict"] == "INSUFFICIENT_BASELINE" and thin["baseline_mean"] == UNAVAILABLE and "threshold" not in thin
       and thin["baseline_days"] == 2)
    sparse = anomaly("m", [{"day": d, "value": 100} for d in ("2026-09-01", "2026-09-02", "2026-09-03")]
                     + [{"day": TODAY, "value": 250}], today=TODAY)
    ck("baseline = mean over OBSERVED days only (3 x 100 → 100.0): absent days are NOT invented as 0",
       sparse["baseline_mean"] == 100.0 and sparse["verdict"] == "NORMAL" and sparse["threshold"] == 300.0)
    ck("stale series (no day inside the 7d window) → INSUFFICIENT_BASELINE",
       anomaly("m", [{"day": "2026-08-01", "value": 5}] * 10, today=TODAY)["verdict"] == "INSUFFICIENT_BASELINE")
    an = {a["metric"]: a for a in anomalies(sources={**NONE_SOURCES, **FULL}, today=TODAY)}
    ck("anomalies over readable sources: llm calls 30 vs 10/day → SPIKE; usd 1.9 < daily-cap floor → NORMAL; invocations (3 days) NORMAL",
       an["llm_calls_per_day"]["verdict"] == "SPIKE" and an["llm_usd_per_day"]["verdict"] == "NORMAL"
       and an["llm_usd_per_day"]["threshold"] == caps["daily_usd"]
       and an["capability_invocations_per_day"]["verdict"] == "NORMAL")
    dark_an = anomalies(sources=NONE_SOURCES, today=TODAY)
    ck("anomalies with unreadable sources → verdict UNAVAILABLE + reason for all 3 metrics (never NORMAL by default)",
       len(dark_an) == 3 and all(a["verdict"] == UNAVAILABLE and a["reason"] and a["version"] == GOVERNOR_VERSION for a in dark_an))

    # ── §118 observability: real from an authoritative source or UNAVAILABLE with freshness ──────────
    METRICS = {"cpu", "memory", "process_peak_rss", "disk", "queue", "browser_sessions",
               "provider_usage", "token_cost", "model_latency", "invocation_volume"}
    dark_obs = observability(sources=NONE_SOURCES, now=NOW)
    ck("§118 metric set is complete", {m["metric"] for m in dark_obs} == METRICS)
    ck("sources returning nothing → EVERY metric UNAVAILABLE with a reason + freshness UNAVAILABLE (never 0 / fabricated)",
       all(m["state"] == UNAVAILABLE and m["value"] == UNAVAILABLE and m["freshness"] == UNAVAILABLE
           and m["reason"] and m["observed_at"] == NOW for m in dark_obs)
       and not any(isinstance(m["value"], (int, float)) for m in dark_obs))
    obs = {m["metric"]: m for m in observability(sources={**NONE_SOURCES, **FULL}, now=NOW)}
    ck("measured metrics carry FRESH freshness, a named source and the observation time",
       all(obs[k]["state"] == "MEASURED" and obs[k]["freshness"] == "FRESH" and obs[k]["source"] and obs[k]["observed_at"] == NOW
           for k in ("cpu", "disk", "queue", "provider_usage", "token_cost", "model_latency", "invocation_volume")))
    ck("queue counts come from holding_worker_jobs by status (queued 1 / running 2 / claimed 0)",
       obs["queue"]["value"]["queued"] == 1 and obs["queue"]["value"]["running"] == 2 and obs["queue"]["value"]["claimed"] == 0
       and obs["queue"]["source"] == "holding_worker_jobs")
    ck("token_cost = per-user day/month + 24h total from llm_call_log (0.7); model_latency by model",
       obs["token_cost"]["value"]["total_24h_usd"] == 0.7 and obs["token_cost"]["value"]["per_user_day_month_usd"]["u1"]["day_usd"] == 1.5
       and obs["model_latency"]["value"]["gpt-4o-mini"]["max_ms"] == 700)
    ck("invocation_volume = audit_log capability.invoke_* + the live service windows",
       obs["invocation_volume"]["value"]["audit_24h"] == {"capability.invoke_health": 3}
       and obs["invocation_volume"]["value"]["live_60s_windows"] == RATE["windows"])
    ck("browser_sessions: no registry exists → UNAVAILABLE with the reason (never a count)",
       obs["browser_sessions"]["state"] == UNAVAILABLE and "no browser-session registry" in obs["browser_sessions"]["reason"])
    ck("memory None from the OS source → UNAVAILABLE (a metric is per-source honest, not all-or-nothing)",
       obs["memory"]["state"] == UNAVAILABLE and obs["cpu"]["state"] == "MEASURED")
    real = {m["metric"]: m for m in observability(now=NOW)}          # the real default sources on THIS host
    ck("real host: every metric is MEASURED or UNAVAILABLE (closed vocabulary), cpu from os.getloadavg",
       all(m["state"] in ("MEASURED", UNAVAILABLE) for m in real.values())
       and real["cpu"]["state"] == "MEASURED" and real["cpu"]["value"]["source"] == "os.getloadavg"
       and (real["memory"]["state"] == UNAVAILABLE if platform.system() == "Darwin" else True))
    snap = snapshot(sources={**NONE_SOURCES, **FULL}, now=NOW)
    ck("snapshot = one bounded on-demand read: version + budgets + anomalies + observability, no state kept",
       snap["version"] == GOVERNOR_VERSION and snap["observed_at"] == NOW and len(snap["anomalies"]) == 3
       and len(snap["observability"]) == len(METRICS) and len(snap["budgets"]) == len(rows)
       and not re.search(r"^_[a-z_]*(cache|state|last)\b", src, re.M))

    n = len(res); ok = sum(res)
    print(f"\nRESOURCE GOVERNOR (§78/§118) TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
