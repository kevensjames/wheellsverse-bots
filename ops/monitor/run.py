"""Production monitor — tick orchestration, evaluation, CLI.

Modes:
  --once                 one dry tick (TestAdapter): print snapshot + alerts + would-deliver
  --live                 deliver real alerts via Telegram (only if any fire)
  --send-test            send ONE labeled INFO delivery-certification alert (item 13) + verify
  --soak N --interval S  loop N ticks every S seconds, append JSONL soak log
  --no-canary            skip governed canaries (cheap public-surface-only tick)

evaluate() is PURE (snapshot dict -> [Alert]) so it is unit-tested with synthetic snapshots.
Reuses the existing Telegram owner channel (ops/monitor/delivery.py). Never prints secrets.
"""
from __future__ import annotations
import os, sys, json, time, argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from ops.monitor.core import (Alert, AlertState, THRESHOLDS, RUNBOOKS,
                              INFO, WARNING, HIGH, CRITICAL)
from ops.monitor.delivery import TelegramAdapter, TestAdapter, deliver
from ops.monitor import collectors

REGISTRY_EXPECTED = 39
MONITOR_VERSION = "1.0.0"
STATE_DIR = os.environ.get("MONITOR_STATE_DIR", "/tmp")


def _iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_json(path, obj):
    try:
        with open(path, "w") as f:
            json.dump(obj, f)
    except OSError:
        pass


def is_stale(prior_epoch, now_epoch, interval):
    """True if the previous scheduled tick is older than 2 expected intervals (missed ticks)."""
    return bool(prior_epoch) and (now_epoch - prior_epoch) > 2 * interval


def evaluate(snap, thresholds=THRESHOLDS, registry_expected=REGISTRY_EXPECTED):
    """Pure: map a signal snapshot to a list of Alerts across the 9 signal families."""
    A = []
    def add(signal, sev, summary, service="", observed=None, thr=None, window="", runbook_key=None):
        A.append(Alert(signal=signal, severity=sev, summary=summary, service=service,
                       observed_value=observed, threshold=thr, window=window,
                       runbook=RUNBOOKS.get(runbook_key or signal, "")))

    lat = thresholds["health_latency_ms"]

    # A. App A 5xx / reachability
    a = snap.get("appA_status")
    if a == 0:
        add("app_a_5xx", HIGH, "App A /api/health unreachable", "app_a", observed="unreachable", runbook_key="app_a_5xx")
    elif a and a >= 500:
        add("app_a_5xx", HIGH, f"App A 5xx on /api/health ({a})", "app_a", observed=a, runbook_key="app_a_5xx")

    # B. App B 5xx / reachability (fail-closed 404 is NOT a B 5xx)
    b = snap.get("appB_status")
    if b == 0:
        add("app_b_5xx", HIGH, "App B /health unreachable", "app_b", observed="unreachable", runbook_key="app_b_5xx")
    elif b and b >= 500:
        add("app_b_5xx", HIGH, f"App B 5xx on /health ({b})", "app_b", observed=b, runbook_key="app_b_5xx")

    # I. Latency
    for svc, key in (("app_a", "appA_ms"), ("app_b", "appB_ms")):
        ms = snap.get(key)
        if ms is None:
            continue
        if ms > lat["crit"]:
            add("latency", HIGH, f"{svc} health latency {ms}ms > {lat['crit']}ms", svc, observed=ms, thr=lat["crit"])
        elif ms > lat["warn"]:
            add("latency", WARNING, f"{svc} health latency {ms}ms > {lat['warn']}ms", svc, observed=ms, thr=lat["warn"])

    # Control-plane drift + kill-switch intent distinction (item 9)
    if snap.get("bridge_enabled") is False:
        # bridge OFF: could be intentional kill-switch — WARNING, clearly labeled, not CRITICAL
        add("bridge_disabled", WARNING, "KAI bridge is DISABLED (intentional kill-switch or unexpected) — governed KAI unavailable, fail-closed", "bridge",
            observed="disabled", runbook_key="app_b_5xx")
    elif snap.get("bridge_enabled") is True and snap.get("canary_ran") and snap.get("stream_status") in (502, 504, 0):
        # bridge ENABLED but governed path failing = unexpected unavailability
        add("app_b_5xx", HIGH, f"Bridge ENABLED but governed path failing (stream {snap.get('stream_status')}) — unexpected unavailability", "bridge",
            observed=snap.get("stream_status"), runbook_key="app_b_5xx")
    rc = snap.get("registry_count")
    if rc is not None and rc != registry_expected:
        add("registry_drift", WARNING, f"Command Center registry={rc} (expected {registry_expected}) — partial deploy/drift", "app_a", observed=rc, thr=registry_expected)

    if not snap.get("canary_ran"):
        # E (proxy). If owner probes ran, spend/pg may still be present
        _spend_signals(snap, thresholds, add)
        _self_health(snap, [], add)
        return A

    # C. Auth anomalies / BYPASS (security-critical)
    if snap.get("auth_anon_status") not in (401, None) and snap.get("auth_anon_status") == 200:
        add("auth_bypass", CRITICAL, "ANON reached governed KAI (expected 401) — authorization bypass", "bridge",
            observed=snap.get("auth_anon_status"), thr=401, runbook_key="auth_bypass")
    if snap.get("auth_operator_status") == 200:
        add("auth_bypass", CRITICAL, "OPERATOR reached kai.ultra (expected 403) — privilege escalation", "bridge",
            observed=snap.get("auth_operator_status"), thr=403, runbook_key="auth_bypass")

    # H. SSE / streaming (owner canary) + owner-access regression
    ss = snap.get("stream_status")
    if ss in (502, 504):
        add("sse", HIGH, f"Governed stream {ss} (upstream timeout/unreachable)", "app_b", observed=ss, runbook_key="sse")
    elif ss in (401, 403):
        add("auth_bypass", HIGH, f"OWNER denied governed stream ({ss}) — owner-access regression", "bridge", observed=ss, runbook_key="auth_bypass")
    elif ss == 200 and snap.get("stream_frames", 0) == 0:
        add("sse", WARNING, "Governed stream 200 but 0 SSE frames (empty/malformed)", "app_b", observed=0, runbook_key="sse")
    elif ss and ss >= 500:
        add("sse", HIGH, f"Governed stream server error ({ss})", "app_b", observed=ss, runbook_key="sse")

    # F. Audit / usage gap (executed-but-unaudited)
    if snap.get("stream_status") == 200 and snap.get("usage_incremented") is False:
        add("audit_gap", CRITICAL, "Governed call succeeded but usage/audit row did NOT persist (executed-but-unaudited)", "app_b",
            observed="no_row", runbook_key="audit_gap")

    # E. Postgres reachability (spend reads llm_call_log)
    if snap.get("pg_reachable") is False:
        add("db_redis", HIGH, "Postgres unreachable (/admin/spend failed for a valid owner session)", "app_b",
            observed=snap.get("spend_status"), runbook_key="db_redis")

    _spend_signals(snap, thresholds, add)
    _self_health(snap, [], add)
    return A


def _spend_signals(snap, thresholds, add):
    # D. Provider spend + failures
    cost = snap.get("openai_cost_today")
    if cost is not None:
        c = thresholds["openai_daily_cost_usd"]
        if cost > c["crit"]:
            add("spend", HIGH, f"OpenAI daily cost ${cost} > ${c['crit']}", "app_b", observed=cost, thr=c["crit"], window="24h")
        elif cost > c["warn"]:
            add("spend", WARNING, f"OpenAI daily cost ${cost} > ${c['warn']}", "app_b", observed=cost, thr=c["warn"], window="24h")
    fails = snap.get("failures_24h")
    if fails is not None:
        if fails >= 20:
            add("provider", HIGH, f"Provider failures_24h={fails}", "app_b", observed=fails, thr=20, window="24h")
        elif fails >= 5:
            add("provider", WARNING, f"Provider failures_24h={fails}", "app_b", observed=fails, thr=5, window="24h")


def _self_health(snap, delivery_failures, add):
    # 14. Observability self-failure — never report healthy when evidence is missing
    core_errs = [e for e in snap.get("errors", []) if not e.startswith("no_secret")]
    if core_errs:
        add("monitor_self", HIGH, f"Monitor collection errors: {','.join(core_errs)}", "monitor",
            observed=core_errs, runbook_key="monitor_self")


def tick(secret, adapter, state, do_canary=True):
    snap = collectors.collect(secret=secret, do_canary=do_canary)
    alerts = evaluate(snap)
    now = int(snap.get("ts", time.time()))
    to_send = state.decide(alerts, now)
    for a in to_send:
        if not a.timestamp:
            a.timestamp = _iso(); a.alert_id = a.compute_id()
    results = deliver(to_send, adapter)
    delivery_failures = [r for _, r in results if not r.ok]
    if delivery_failures:
        # surface delivery failure into self-health (do not silently pass)
        alerts.append(Alert(signal="monitor_self", severity=HIGH, service="monitor",
                            summary=f"Alert delivery FAILED via {adapter.name}: {[r.detail for r in delivery_failures]}",
                            runbook=RUNBOOKS["monitor_self"]))
    healthy = (not [e for e in snap.get("errors", []) if not e.startswith("no_secret")]
               and not delivery_failures)
    state.save()
    return {"snap": snap, "alerts": alerts, "sent": to_send, "results": results,
            "delivery_failures": delivery_failures, "healthy": healthy}


def send_test(adapter, recovery=False):
    """Item 13: one clearly-labeled harmless delivery certification (INFO alert or recovery)."""
    a = Alert(signal="delivery_certification", severity=INFO, service="monitor",
              summary=("Recovery-notification certification (TEST) — action required: none" if recovery
                       else "Alert-delivery certification — action required: none"),
              recovery_state=("recovered" if recovery else "firing"),
              context={"purpose": "alert-delivery certification", "test_id": f"cert-{int(time.time())}"},
              runbook="none")
    a.timestamp = _iso(); a.alert_id = a.compute_id()
    text = a.render_text()
    res = adapter.send(text)
    leaked = [s for s in ("wv_session", "Bearer ", "postgres://", "redis://", "sk-", "TELEGRAM_BOT_TOKEN")
              if s in text]
    return a, res, text, leaked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--send-test", action="store_true")
    ap.add_argument("--send-recovery", action="store_true")
    ap.add_argument("--cron", action="store_true", help="one scheduled tick: smart cadence + heartbeat + staleness")
    ap.add_argument("--soak", type=int, default=0)
    ap.add_argument("--interval", type=int, default=300, help="expected seconds between cron runs (staleness calc; default matches */5)")
    ap.add_argument("--canary-minute", type=int, default=5, help="run the governed canary only when UTC minute < this (default: top-of-hour)")
    ap.add_argument("--no-canary", action="store_true")
    ap.add_argument("--state", default=os.path.join(STATE_DIR, "wv_monitor_state.json"))
    ap.add_argument("--heartbeat", default=os.path.join(STATE_DIR, "wv_monitor_heartbeat.json"))
    ap.add_argument("--soak-log", default=os.path.join(STATE_DIR, "wv_monitor_soak.jsonl"))
    args = ap.parse_args()

    secret = os.environ.get("SESSION_SIGNING_SECRET")
    adapter = TelegramAdapter() if (args.live or args.send_test or args.send_recovery) else TestAdapter()
    do_canary = not args.no_canary

    if args.send_test or args.send_recovery:
        a, res, text, leaked = send_test(adapter, recovery=args.send_recovery)
        print(json.dumps({"delivered": res.ok, "adapter": res.adapter, "detail": res.detail,
                          "leaked_secret_tokens": leaked, "alert_id": a.alert_id,
                          "environment": a.environment, "service": a.service}, indent=2))
        print("--- rendered (secret-free) ---"); print(text)
        return

    state = AlertState(path=args.state, cooldown_ticks=900)

    if args.cron:
        # one scheduled invocation: live delivery, smart cadence, heartbeat, staleness
        adapter = TelegramAdapter()
        now_dt = datetime.now(timezone.utc)
        now_epoch = time.time()
        # governed canary (OpenAI cost) only in the top-of-hour window ≈ once/hour; cheap otherwise
        cron_canary = (not args.no_canary) and (now_dt.minute < args.canary_minute)
        prior = _read_json(args.heartbeat)
        stale = None
        # Fire staleness ONLY on a real gap (> 2x the expected interval) AND not within a 15-min
        # cooldown — so a normal cadence never trips it and a persistent gap can't storm the channel.
        if is_stale(prior.get("last_tick_epoch"), now_epoch, args.interval) \
                and (now_epoch - float(prior.get("last_stale_epoch", 0))) > 900:
            gap = int(now_epoch - prior["last_tick_epoch"])
            stale = Alert(signal="monitor_stale", severity=HIGH, service="monitor",
                          summary=f"Monitor resumed after {gap}s gap (> 2x{args.interval}s expected) — scheduled ticks were missed",
                          runbook=RUNBOOKS["monitor_self"])
        r = tick(secret, adapter, state, do_canary=cron_canary)
        if stale:
            stale.timestamp = _iso(); stale.alert_id = stale.compute_id()
            deliver([stale], adapter)
        _write_json(args.heartbeat, {
            "last_tick_at": _iso(), "last_tick_epoch": now_epoch,
            "last_tick_status": "healthy" if r["healthy"] else "unhealthy",
            "last_delivery_status": "ok" if not r["delivery_failures"] else "failed",
            "consecutive_failures": 0 if r["healthy"] else int(prior.get("consecutive_failures", 0)) + 1,
            "last_stale_epoch": now_epoch if stale else float(prior.get("last_stale_epoch", 0)),
            "monitor_version": MONITOR_VERSION, "did_canary": cron_canary,
            "environment": os.environ.get("ENVIRONMENT", "unknown")})
        print(json.dumps({"cron_tick": True, "environment": os.environ.get("ENVIRONMENT", "unknown"),
                          "healthy": r["healthy"], "did_canary": cron_canary, "alerts": len(r["alerts"]),
                          "sent": len(r["sent"]), "delivery_failures": len(r["delivery_failures"]),
                          "stale_detected": bool(stale), "monitor_version": MONITOR_VERSION}, default=str))
        return

    if args.soak:
        for i in range(args.soak):
            r = tick(secret, adapter, state, do_canary=do_canary)
            row = {"i": i + 1, "ts": _iso(), "healthy": r["healthy"],
                   "n_alerts": len(r["alerts"]), "n_sent": len(r["sent"]),
                   "delivery_failures": len(r["delivery_failures"]),
                   "snap": {k: r["snap"].get(k) for k in
                            ("appA_status", "appA_ms", "appB_status", "appB_ms", "bridge_enabled",
                             "registry_count", "openai_cost_today", "failures_24h",
                             "stream_status", "usage_incremented", "auth_anon_status", "auth_operator_status")}}
            with open(args.soak_log, "a") as f:
                f.write(json.dumps(row, default=str) + "\n")
            print(f"[{i+1}/{args.soak}] healthy={r['healthy']} alerts={len(r['alerts'])} sent={len(r['sent'])}")
            if i + 1 < args.soak:
                time.sleep(args.interval)
        return

    # default: one dry/once tick
    r = tick(secret, adapter, state, do_canary=do_canary)
    out = {"healthy": r["healthy"],
           "snapshot": r["snap"],
           "alerts": [{"signal": a.signal, "severity": a.severity, "summary": a.summary,
                       "service": a.service} for a in r["alerts"]],
           "would_deliver": [a.signal for a in r["sent"]]}
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
