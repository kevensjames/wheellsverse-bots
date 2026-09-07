"""§78 unified resource governor + §118 resource observability — COMPOSED over the existing primitives.

This module adds NO limiter, NO cap of its own, NO daemon. It is one bounded, on-demand snapshot that
reads the primitives that already enforce resource limits and re-projects them onto the §78
dimensions (per-day / per-month / per-provider / per-minute / per-mission / per-company /
self-improvement-per-day) plus a deterministic spike-vs-baseline anomaly surface:

  cap / enforcement                     existing primitive (the ONLY authority; nothing here re-enforces)
  ─────────────────────────────────     ─────────────────────────────────────────────────────────────
  daily / monthly USD (per user)        router/spend_tracker.SpendTracker  (DEFAULT_DAILY_CAP / _MONTHLY_CAP, >= semantics)
  capability invocations / minute       capability/execution.CapabilityExecutionService.rate_limit_per_min (_rate_ok)
  self-improvement preparations / day   holding/self_improvement_guardrails.DAILY_PREPARATION_CEILING (preparation_admission)
                                        == holding/holding_cycle.SELF_IMPROVE_DAILY_CEILING
  per-mission cost                      capability/coding.CodingTask.cost_budget (declared per task; surfaced, not re-enforced)
  per-provider / per-company            NO cap exists today -> reported NO_CAP_DECLARED (never an invented cap)

  ⚠ core/budget_manager.py is a NarAI AD-SPEND controller — a false friend for §78. Deliberately not used.

§118 observability: every metric is REAL from an authoritative source (os / cgroup / llm_call_log /
audit_log / holding_worker_jobs / the live execution service) or UNAVAILABLE with a reason — never a
fabricated number (§0 #16-19). Sources are injectable so the whole module is a plain python3 self-test
(mirrors test_registry.py); each default source fails SOFT to None -> UNAVAILABLE.
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from datetime import datetime, timezone, timedelta, date
from typing import Any, Callable

GOVERNOR_VERSION = "1.0.0"
UNAVAILABLE = "UNAVAILABLE"
NO_CAP_DECLARED = "NO_CAP_DECLARED"

# budget states (versioned with the formula)
WITHIN_CAP, OVER_CAP = "WITHIN_CAP", "OVER_CAP"

_RATE_WINDOWS_UNOBSERVABLE = "rate windows are in-process state of the API worker; not observable from this process"

# §78 anomaly rule (deterministic, versioned): today >= max(min_abs, factor * mean(prior baseline days))
ANOMALY_FACTOR = 3.0
ANOMALY_MIN_ABS = 10.0
ANOMALY_MIN_BASELINE_DAYS = 3
ANOMALY_WINDOW_DAYS = 7


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── default sources (each fails SOFT -> None; a None source is reported UNAVAILABLE, never zero) ─────
def _spend_caps() -> dict:
    """The real caps, straight from spend_tracker (the only enforcer of them)."""
    from app.services.router import spend_tracker as st
    return {"daily_usd": float(st.DEFAULT_DAILY_CAP), "monthly_usd": float(st.DEFAULT_MONTHLY_CAP),
            "scope": "per user_id", "rule": ">= cap blocks (over_daily_cap / over_monthly_cap)",
            "enforced_by": "router.spend_tracker.SpendTracker"}


def _llm_usage() -> dict | None:
    """Aggregates over spend_tracker's own table (llm_call_log). Read-only; bounded (GROUP BY only)."""
    from sqlalchemy import text
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        users = db.execute(text(
            "SELECT user_id::text,"
            " COALESCE(SUM(cost_usd) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours'), 0),"
            " COALESCE(SUM(cost_usd) FILTER (WHERE created_at >= DATE_TRUNC('month', NOW())), 0)"
            " FROM llm_call_log"
            " WHERE created_at >= LEAST(DATE_TRUNC('month', NOW()), NOW() - INTERVAL '24 hours')"
            " GROUP BY user_id")).fetchall()
        providers = db.execute(text(
            "SELECT adapter, COUNT(*), COALESCE(SUM(input_tokens + output_tokens), 0), COALESCE(SUM(cost_usd), 0),"
            " AVG(latency_ms), SUM(CASE WHEN success THEN 1 ELSE 0 END)"
            " FROM llm_call_log WHERE created_at >= NOW() - INTERVAL '24 hours' GROUP BY adapter")).fetchall()
        models = db.execute(text(
            "SELECT model, COUNT(*), AVG(latency_ms), MAX(latency_ms) FROM llm_call_log"
            " WHERE created_at >= NOW() - INTERVAL '24 hours' AND latency_ms IS NOT NULL GROUP BY model")).fetchall()
        days = db.execute(text(
            "SELECT (created_at AT TIME ZONE 'UTC')::date, COUNT(*), COALESCE(SUM(cost_usd), 0)"
            " FROM llm_call_log WHERE created_at >= NOW() - INTERVAL '8 days' GROUP BY 1 ORDER BY 1")).fetchall()
        return {
            "per_user": {r[0]: {"day_usd": float(r[1]), "month_usd": float(r[2])} for r in users},
            "per_provider": {r[0]: {"calls": int(r[1]), "tokens": int(r[2]), "usd": float(r[3]),
                                    "avg_latency_ms": (round(float(r[4])) if r[4] is not None else UNAVAILABLE),
                                    "success": int(r[5] or 0)} for r in providers},
            "per_model_latency": {r[0]: {"calls": int(r[1]), "avg_ms": round(float(r[2])), "max_ms": int(r[3])}
                                  for r in models},
            "daily": [{"day": str(r[0]), "calls": int(r[1]), "usd": float(r[2])} for r in days],
            "window": "24h / month-to-date / 8 days",
        }
    finally:
        db.close()


def _rate_limit() -> dict:
    """The capability rate limiter: its configured cap always; its LIVE 60-second windows only when the
    real execution service (the router singleton) is ALREADY LOADED in this process — never imported here:
    importing the router would BUILD a fresh, empty service and report used=0 as if measured. Elsewhere
    the windows are the API worker's in-process state and honestly UNAVAILABLE."""
    import inspect
    from app.services.capability.execution import CapabilityExecutionService
    default = inspect.signature(CapabilityExecutionService.__init__).parameters["rate_limit_per_min"].default
    out = {"limit_per_min": int(default), "windows": None, "windows_reason": _RATE_WINDOWS_UNOBSERVABLE,
           "enforced_by": "capability.execution.CapabilityExecutionService._rate_ok"}
    router = sys.modules.get("app.routers.admin_capabilities")     # look, don't import
    try:
        _service = router._service
        now = _service._clock()
        out["limit_per_min"] = int(_service._rate_limit)
        out["windows"] = {f"{p}/{c}": sum(1 for t in ts if now - t < 60.0) for (p, c), ts in _service._rate.items()}
        out.pop("windows_reason")
    except Exception:   # noqa: BLE001 — no live service here -> windows honestly UNAVAILABLE
        pass
    return out


def jobs_by_status() -> dict | None:
    """Queue truth from holding_worker_jobs. Returns None when the DB/table is unreadable — the
    existing worker_jobs readers return [] on failure, which would be indistinguishable from an
    honestly-empty queue, so this probe is what lets the governor (and brakes) say UNAVAILABLE."""
    from sqlalchemy import text
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        rows = db.execute(text("SELECT status, COUNT(*) FROM holding_worker_jobs GROUP BY status")).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}
    finally:
        db.close()


def _worker_plane() -> dict | None:
    """Queue counts + the recent job rows (via the EXISTING reader, gated by the probe above)."""
    counts = jobs_by_status()
    if counts is None:
        return None
    from app.services.holding import worker_jobs
    return {"counts": counts, "rows": worker_jobs.list_jobs(limit=500)}


def _missions() -> list | None:
    """Mission headers + their linked jobs (existing readers, bounded to 20 missions)."""
    if jobs_by_status() is None:
        return None
    from app.services.holding import mission, worker_jobs
    out = []
    for h in mission.list_missions(limit=20):
        mid = h.get("mission_id")
        out.append({"mission_id": mid, "company": h.get("company"), "status": h.get("status"),
                    "jobs": worker_jobs.list_for_mission(mid)})
    return out


def _invocations() -> dict | None:
    """Capability invocation volume from the audit sink table (admin_capabilities._audit_sink -> audit_log)."""
    from sqlalchemy import text
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        by_action = db.execute(text(
            "SELECT action, COUNT(*) FROM audit_log WHERE created_at >= NOW() - INTERVAL '24 hours'"
            " AND action LIKE 'capability.invoke_%' GROUP BY action")).fetchall()
        days = db.execute(text(
            "SELECT (created_at AT TIME ZONE 'UTC')::date, COUNT(*) FROM audit_log"
            " WHERE created_at >= NOW() - INTERVAL '8 days' AND action LIKE 'capability.invoke_%'"
            " GROUP BY 1 ORDER BY 1")).fetchall()
        return {"by_action_24h": {str(r[0]): int(r[1]) for r in by_action},
                "daily": [{"day": str(r[0]), "count": int(r[1])} for r in days]}
    finally:
        db.close()


def _system() -> dict:
    """Host/container resources from the OS. Each sub-metric is real or None (-> UNAVAILABLE)."""
    out: dict[str, Any] = {}
    try:
        la = os.getloadavg()
        out["cpu"] = {"load_1m": round(la[0], 2), "load_5m": round(la[1], 2), "load_15m": round(la[2], 2),
                      "cpu_count": os.cpu_count(), "source": "os.getloadavg"}
    except Exception:   # noqa: BLE001 — non-POSIX
        out["cpu"] = None
    mem = None
    try:   # cgroup v2 (the container's own limit — more authoritative than the host's /proc/meminfo)
        with open("/sys/fs/cgroup/memory.current") as f:
            cur = int(f.read().strip())
        with open("/sys/fs/cgroup/memory.max") as f:
            mx = f.read().strip()
        mem = {"used_mb": cur // 2**20, "limit_mb": (int(mx) // 2**20 if mx != "max" else UNAVAILABLE),
               "source": "cgroup v2 memory.current/max"}
    except Exception:   # noqa: BLE001
        try:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    info[k.strip()] = int(v.strip().split()[0])   # kB
            mem = {"used_mb": (info["MemTotal"] - info["MemAvailable"]) // 1024,
                   "limit_mb": info["MemTotal"] // 1024, "source": "/proc/meminfo"}
        except Exception:   # noqa: BLE001 — e.g. macOS: no cgroup, no /proc
            mem = None
    out["memory"] = mem
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        out["process_peak_rss_mb"] = (rss // 2**20) if platform.system() == "Darwin" else (rss // 1024)
    except Exception:   # noqa: BLE001
        out["process_peak_rss_mb"] = None
    try:
        du = shutil.disk_usage(os.getcwd())
        out["disk"] = {"path": os.getcwd(), "free_gb": round(du.free / 2**30, 1), "total_gb": round(du.total / 2**30, 1),
                       "used_pct": round(100 * (du.total - du.free) / du.total) if du.total else UNAVAILABLE,
                       "source": "shutil.disk_usage"}
    except Exception:   # noqa: BLE001
        out["disk"] = None
    return out


def _browser_sessions():
    """No browser-session registry exists: browser/session.py launches Playwright per call and the
    external ops/browser-worker is a separate host. There is nothing authoritative to count -> None."""
    return None


_DEFAULT_SOURCES: dict[str, Callable[[], Any]] = {
    "spend_caps": _spend_caps, "llm_usage": _llm_usage, "rate_limit": _rate_limit,
    "worker_plane": _worker_plane, "missions": _missions, "invocations": _invocations,
    "system": _system, "browser_sessions": _browser_sessions,
}


def _get(sources: dict, name: str):
    fn = sources.get(name)
    if fn is None:
        return None
    try:
        return fn()
    except Exception:   # noqa: BLE001 — a failing source is honestly UNAVAILABLE, never a guess
        return None


# ── budget rows ───────────────────────────────────────────────────────────────────────────────────
def budget_state(used, cap) -> str:
    """Mirror the spend tracker's rule exactly: used >= cap is over (never a softer re-implementation)."""
    if cap is None or cap == NO_CAP_DECLARED:
        return NO_CAP_DECLARED
    if cap == UNAVAILABLE or used is None or used == UNAVAILABLE:
        return UNAVAILABLE
    return OVER_CAP if float(used) >= float(cap) else WITHIN_CAP


def _row(dimension, key, *, cap, cap_source, enforced_by, used, used_source, now, unit="usd") -> dict:
    return {"dimension": dimension, "key": key, "unit": unit,
            "cap": cap if cap is not None else NO_CAP_DECLARED, "cap_source": cap_source,
            "enforced_by": enforced_by, "used": used if used is not None else UNAVAILABLE,
            "used_source": used_source, "state": budget_state(used, cap), "observed_at": now}


def _cost_of(job: dict):
    ev = job.get("evidence") if isinstance(job, dict) else None
    c = ev.get("cost") if isinstance(ev, dict) else None
    return float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else None


def _declared_budget(job: dict):
    t = job.get("task") if isinstance(job, dict) else None
    b = t.get("cost_budget") if isinstance(t, dict) else None
    return float(b) if isinstance(b, (int, float)) and not isinstance(b, bool) else None


def budgets(*, sources: dict | None = None, now: str = "", today: str = "") -> list[dict]:
    """§78 budget rows across every dimension. Caps come ONLY from the real primitives; a dimension
    without a real cap is NO_CAP_DECLARED; a dimension whose usage cannot be read is UNAVAILABLE."""
    src = {**_DEFAULT_SOURCES, **(sources or {})}
    now = now or _now_iso()
    today = today or now[:10]
    rows: list[dict] = []

    # per-day / per-month USD (spend_tracker caps, per user_id). The cap EXISTS (spend_tracker enforces it);
    # if it cannot be read it is UNAVAILABLE — never NO_CAP_DECLARED (that would claim no cap exists).
    caps = _get(src, "spend_caps")
    usage = _get(src, "llm_usage")
    st_name = (caps or {}).get("enforced_by", UNAVAILABLE)
    per_user = (usage or {}).get("per_user") if isinstance(usage, dict) else None
    keys = sorted(per_user) if per_user else (["*"] if isinstance(per_user, dict) else [UNAVAILABLE])
    for uid in keys:
        u = (per_user or {}).get(uid, {"day_usd": 0.0, "month_usd": 0.0}) if per_user is not None else {}
        for dim, cap_key, used_key in (("per_day", "daily_usd", "day_usd"), ("per_month", "monthly_usd", "month_usd")):
            rows.append(_row(dim, uid, cap=(caps.get(cap_key, UNAVAILABLE) if caps else UNAVAILABLE),
                             cap_source=f"spend_tracker.DEFAULT_{cap_key.upper()}",
                             enforced_by=st_name, used=u.get(used_key) if per_user is not None else None,
                             used_source="llm_call_log" if per_user is not None else "llm_call_log unreadable", now=now))

    # per-provider (adapter) — real usage, NO cap exists
    per_provider = (usage or {}).get("per_provider") if isinstance(usage, dict) else None
    if per_provider is None:
        rows.append(_row("per_provider", UNAVAILABLE, cap=None, cap_source="none exists", enforced_by="NOT_ENFORCED",
                         used=None, used_source="llm_call_log unreadable", now=now))
    for adapter in sorted(per_provider or {}):
        rows.append(_row("per_provider", adapter, cap=None, cap_source="none exists", enforced_by="NOT_ENFORCED",
                         used=per_provider[adapter]["usd"], used_source="llm_call_log (24h)", now=now))

    # per-minute capability invocations (execution service rate limiter)
    rl = _get(src, "rate_limit")            # the limiter EXISTS: unreadable → UNAVAILABLE, never NO_CAP_DECLARED
    windows = (rl or {}).get("windows")
    peak = max(windows.values()) if windows else (0 if windows == {} else None)
    rows.append(_row("per_minute", "capability_invocations", unit="calls",
                     cap=(rl.get("limit_per_min", UNAVAILABLE) if rl else UNAVAILABLE),
                     cap_source="CapabilityExecutionService.rate_limit_per_min",
                     enforced_by=(rl or {}).get("enforced_by", UNAVAILABLE), used=peak,
                     used_source="live service 60s windows, this process only (peak principal/capability)"
                     if windows is not None else _RATE_WINDOWS_UNOBSERVABLE, now=now))

    # self-improvement preparations per day (guardrails ceiling; used = today's SI jobs, same classifier)
    from app.services.holding.self_improvement_guardrails import DAILY_PREPARATION_CEILING, describe
    from app.services.holding.holding_cycle import SELF_IMPROVE_DAILY_CEILING
    plane = _get(src, "worker_plane")
    si_used = None
    if isinstance(plane, dict):
        si_used = sum(1 for v in describe(plane.get("rows") or []) if v.origin == "self_improvement" and v.created_date == today)
    rows.append(_row("per_day_self_improvement", today, unit="preparations",
                     cap=min(DAILY_PREPARATION_CEILING, SELF_IMPROVE_DAILY_CEILING),
                     cap_source="self_improvement_guardrails.DAILY_PREPARATION_CEILING == holding_cycle.SELF_IMPROVE_DAILY_CEILING",
                     enforced_by="self_improvement_guardrails.preparation_admission", used=si_used,
                     used_source="holding_worker_jobs (si: tagged, today)" if si_used is not None else "holding_worker_jobs unreadable",
                     now=now))

    # per-mission (declared CodingTask.cost_budget vs summed worker evidence cost) + per-company roll-up
    missions = _get(src, "missions")
    if missions is None:
        rows.append(_row("per_mission", UNAVAILABLE, cap=None, cap_source="coding.CodingTask.cost_budget",
                         enforced_by="NOT_ENFORCED_AT_RUNTIME (declared per task)", used=None,
                         used_source="holding_missions/holding_worker_jobs unreadable", now=now))
        rows.append(_row("per_company", UNAVAILABLE, cap=None, cap_source="none exists", enforced_by="NOT_ENFORCED",
                         used=None, used_source="holding_missions unreadable", now=now))
    else:
        companies: dict[str, dict] = {}
        for m in missions:
            jobs = m.get("jobs") or []
            declared = [b for b in (_declared_budget(j) for j in jobs) if b is not None]
            costs = [c for c in (_cost_of(j) for j in jobs) if c is not None]
            used = round(sum(costs), 6) if costs else None
            rows.append(_row("per_mission", m.get("mission_id"), cap=(min(declared) if declared else None),
                             cap_source="coding.CodingTask.cost_budget (job.task.cost_budget)",
                             enforced_by="NOT_ENFORCED_AT_RUNTIME (declared per task)", used=used,
                             used_source=f"worker evidence.cost ({len(costs)}/{len(jobs)} jobs report cost)", now=now))
            c = companies.setdefault(m.get("company") or UNAVAILABLE, {"missions": 0, "jobs": 0, "costs": []})
            c["missions"] += 1; c["jobs"] += len(jobs); c["costs"].extend(costs)
        for name in sorted(companies):
            c = companies[name]
            r = _row("per_company", name, cap=None, cap_source="none exists", enforced_by="NOT_ENFORCED",
                     used=(round(sum(c["costs"]), 6) if c["costs"] else None),
                     used_source=f"worker evidence.cost across {c['missions']} mission(s) / {c['jobs']} job(s)", now=now)
            r["missions"], r["jobs"] = c["missions"], c["jobs"]
            rows.append(r)
    return rows


# ── §78 anomaly surface: deterministic spike-vs-baseline ─────────────────────────────────────────
def anomaly(metric: str, series: list[dict], *, today: str, value_key: str = "value",
            factor: float = ANOMALY_FACTOR, min_abs: float = ANOMALY_MIN_ABS,
            min_baseline_days: int = ANOMALY_MIN_BASELINE_DAYS, window_days: int = ANOMALY_WINDOW_DAYS) -> dict:
    """SPIKE / NORMAL / INSUFFICIENT_BASELINE for one daily series. Baseline = mean over the OBSERVED
    prior days inside the ``window_days`` window (a day with no row is not assumed to be 0 — it is simply
    not a baseline point). Fewer than ``min_baseline_days`` observed prior days -> no verdict, never a
    guessed one. Same inputs -> byte-identical output."""
    by_day = {str(p.get("day")): float(p.get(value_key) or 0.0) for p in (series or []) if isinstance(p, dict)}
    t = date.fromisoformat(today[:10])
    prior_days = [(t - timedelta(days=i)).isoformat() for i in range(1, window_days + 1)]
    observed = [d for d in prior_days if d in by_day]
    base = {"metric": metric, "version": GOVERNOR_VERSION, "today": today[:10],
            "today_value": by_day.get(t.isoformat(), 0.0),
            "rule": f"today >= max({min_abs}, {factor} x mean(observed prior days within {window_days}d))"}
    if len(observed) < min_baseline_days:
        return {**base, "verdict": "INSUFFICIENT_BASELINE", "baseline_days": len(observed), "baseline_mean": UNAVAILABLE}
    mean = round(sum(by_day[d] for d in observed) / len(observed), 6)
    threshold = max(min_abs, factor * mean)
    return {**base, "verdict": "SPIKE" if base["today_value"] >= threshold else "NORMAL",
            "baseline_days": len(observed), "baseline_mean": mean, "threshold": round(threshold, 6)}


def anomalies(*, sources: dict | None = None, today: str = "") -> list[dict]:
    src = {**_DEFAULT_SOURCES, **(sources or {})}
    today = today or _now_iso()[:10]
    out = []
    usage = _get(src, "llm_usage")
    inv = _get(src, "invocations")
    for metric, series, key in (("llm_calls_per_day", (usage or {}).get("daily") if isinstance(usage, dict) else None, "calls"),
                                ("llm_usd_per_day", (usage or {}).get("daily") if isinstance(usage, dict) else None, "usd"),
                                ("capability_invocations_per_day", (inv or {}).get("daily") if isinstance(inv, dict) else None, "count")):
        if series is None:
            out.append({"metric": metric, "version": GOVERNOR_VERSION, "verdict": UNAVAILABLE, "reason": "source unreadable"})
        else:
            out.append(anomaly(metric, series, today=today, value_key=key,
                               # cost spikes are dollar-scale: use the daily cap as the absolute floor
                               min_abs=(float((_get(src, "spend_caps") or {}).get("daily_usd", ANOMALY_MIN_ABS))
                                        if key == "usd" else ANOMALY_MIN_ABS)))
    return out


# ── §118 observability ───────────────────────────────────────────────────────────────────────────
def _metric(name, value, *, source, now, unit="", reason="") -> dict:
    if value is None:
        return {"metric": name, "state": UNAVAILABLE, "value": UNAVAILABLE, "unit": unit, "source": source,
                "observed_at": now, "freshness": UNAVAILABLE, "reason": reason or "no authoritative source readable"}
    return {"metric": name, "state": "MEASURED", "value": value, "unit": unit, "source": source,
            "observed_at": now, "freshness": "FRESH"}


def observability(*, sources: dict | None = None, now: str = "") -> list[dict]:
    """§118: cpu / memory / disk / queue / browser-sessions / provider-usage / token-cost / model-latency /
    invocation-volume — each measured from its real source at call time, or UNAVAILABLE with a reason."""
    src = {**_DEFAULT_SOURCES, **(sources or {})}
    now = now or _now_iso()
    sysm = _get(src, "system") or {}
    usage = _get(src, "llm_usage")
    inv = _get(src, "invocations")
    plane = _get(src, "worker_plane")
    rl = _get(src, "rate_limit") or {}
    u = usage if isinstance(usage, dict) else {}
    counts = plane.get("counts") if isinstance(plane, dict) else None
    return [
        _metric("cpu", sysm.get("cpu"), source="os.getloadavg / os.cpu_count", now=now, unit="load",
                reason="load average not available on this platform"),
        _metric("memory", sysm.get("memory"), source="cgroup v2 / proc meminfo", now=now, unit="MB",
                reason="no cgroup or /proc/meminfo on this host (e.g. macOS) — only process RSS is measurable"),
        _metric("process_peak_rss", sysm.get("process_peak_rss_mb"), source="resource.getrusage(RUSAGE_SELF)", now=now, unit="MB"),
        _metric("disk", sysm.get("disk"), source="shutil.disk_usage", now=now, unit="GB"),
        _metric("queue", (({"queued": counts.get("queued", 0), "running": counts.get("running", 0),
                            "claimed": counts.get("claimed", 0), "by_status": counts}) if counts is not None else None),
                source="holding_worker_jobs", now=now, unit="jobs", reason="holding_worker_jobs unreadable"),
        _metric("browser_sessions", _get(src, "browser_sessions"), source="none", now=now, unit="sessions",
                reason="no browser-session registry exists (browser/session.py runs per call; ops/browser-worker is external)"),
        _metric("provider_usage", u.get("per_provider") if usage is not None else None, source="llm_call_log (24h, by adapter)",
                now=now, unit="calls/tokens/usd", reason="llm_call_log unreadable"),
        _metric("token_cost", ({"per_user_day_month_usd": u.get("per_user"),
                                "total_24h_usd": round(sum(p["usd"] for p in (u.get("per_provider") or {}).values()), 6)}
                               if usage is not None else None),
                source="llm_call_log", now=now, unit="usd", reason="llm_call_log unreadable"),
        _metric("model_latency", u.get("per_model_latency") if usage is not None else None,
                source="llm_call_log.latency_ms (24h, by model)", now=now, unit="ms", reason="llm_call_log unreadable"),
        _metric("invocation_volume", ({"audit_24h": inv.get("by_action_24h"),
                                       "live_60s_windows": rl.get("windows") if rl.get("windows") is not None else UNAVAILABLE}
                                      if isinstance(inv, dict) else None),
                source="audit_log (capability.invoke_*) + CapabilityExecutionService windows", now=now, unit="calls",
                reason="audit_log unreadable"),
    ]


def snapshot(*, sources: dict | None = None, now: str = "") -> dict:
    """One bounded, on-demand governor snapshot (no loop, no daemon — §79). Never raises."""
    now = now or _now_iso()
    return {"version": GOVERNOR_VERSION, "observed_at": now,
            "composes": ["router.spend_tracker", "capability.execution.rate_limit_per_min",
                         "self_improvement_guardrails.DAILY_PREPARATION_CEILING", "coding.CodingTask.cost_budget"],
            "ignores": ["core/budget_manager.py (NarAI ad controller — false friend)"],
            "budgets": budgets(sources=sources, now=now),
            "anomalies": anomalies(sources=sources, today=now[:10]),
            "observability": observability(sources=sources, now=now)}


if __name__ == "__main__":
    from app.services.holding.test_resource_governor import run
    run()
