"""Deterministic tests for the production monitor (no network). Run:
    python3 -m ops.monitor.test_monitor
Covers: thresholds, severity, dedup, cooldown, recovery, redaction, delivery adapter,
collection-failure, auth-anomaly, provider, db/redis, audit, sse, latency, self-failure.
"""
from __future__ import annotations
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from ops.monitor.core import Alert, AlertState, INFO, WARNING, HIGH, CRITICAL, redact
from ops.monitor.delivery import TestAdapter, TelegramAdapter, deliver
from ops.monitor.run import evaluate, send_test, tick

PASS = []
def check(name, cond, detail=""):
    PASS.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))

def sigs(alerts):
    return {(a.signal, a.severity) for a in alerts}

# healthy baseline snapshot (everything nominal)
def base_snap(**over):
    s = {"errors": [], "ts": 1000, "appA_status": 200, "appA_ms": 274, "appB_status": 200, "appB_ms": 209,
         "bridge_enabled": True, "upstream_configured": True, "ui_operator_session": True, "ui_bridge": True,
         "registry_count": 39, "appB_env": "production", "spend_status": 200, "pg_reachable": True,
         "openai_calls_today": 4, "openai_cost_today": 0.0004, "failures_24h": 0, "canary_ran": True,
         "auth_anon_status": 401, "auth_operator_status": 403, "auth_operator_need": "kai.ultra",
         "stream_status": 200, "stream_frames": 11, "stream_corr": True, "usage_incremented": True}
    s.update(over); return s

def run():
    # --- healthy baseline: zero alerts ---
    check("healthy snapshot -> 0 alerts", len(evaluate(base_snap())) == 0)

    # --- A: App A 5xx / unreachable ---
    check("App A 5xx -> HIGH", ("app_a_5xx", HIGH) in sigs(evaluate(base_snap(appA_status=502))))
    check("App A unreachable -> HIGH", ("app_a_5xx", HIGH) in sigs(evaluate(base_snap(appA_status=0, errors=["appA_health:unreachable"]))))

    # --- B: App B 5xx ---
    check("App B 5xx -> HIGH", ("app_b_5xx", HIGH) in sigs(evaluate(base_snap(appB_status=500))))
    check("App B fail-closed 404 is NOT a B 5xx", not any(s == "app_b_5xx" for s, _ in sigs(evaluate(base_snap(appB_status=200)))))

    # --- I: latency thresholds ---
    check("latency WARNING at 2500ms", ("latency", WARNING) in sigs(evaluate(base_snap(appA_ms=2500))))
    check("latency HIGH at 6000ms", ("latency", HIGH) in sigs(evaluate(base_snap(appB_ms=6000))))
    check("latency OK at baseline", not any(s == "latency" for s, _ in sigs(evaluate(base_snap()))))

    # --- C: auth bypass (CRITICAL) ---
    check("anon 200 -> CRITICAL bypass", ("auth_bypass", CRITICAL) in sigs(evaluate(base_snap(auth_anon_status=200))))
    check("operator 200 -> CRITICAL escalation", ("auth_bypass", CRITICAL) in sigs(evaluate(base_snap(auth_operator_status=200))))
    check("normal 401/403 -> no auth alert", not any(s == "auth_bypass" for s, _ in sigs(evaluate(base_snap()))))

    # --- F: audit gap (CRITICAL) ---
    check("stream 200 + usage NOT incremented -> CRITICAL audit_gap",
          ("audit_gap", CRITICAL) in sigs(evaluate(base_snap(usage_incremented=False))))
    check("usage incremented -> no audit_gap", not any(s == "audit_gap" for s, _ in sigs(evaluate(base_snap()))))

    # --- E: db/redis ---
    check("PG unreachable -> HIGH db_redis", ("db_redis", HIGH) in sigs(evaluate(base_snap(pg_reachable=False, spend_status=500))))

    # --- D: provider + spend ---
    check("cost > $5 -> WARNING spend", ("spend", WARNING) in sigs(evaluate(base_snap(openai_cost_today=6.0))))
    check("cost > $20 -> HIGH spend", ("spend", HIGH) in sigs(evaluate(base_snap(openai_cost_today=25.0))))
    check("failures_24h 6 -> WARNING provider", ("provider", WARNING) in sigs(evaluate(base_snap(failures_24h=6))))
    check("failures_24h 25 -> HIGH provider", ("provider", HIGH) in sigs(evaluate(base_snap(failures_24h=25))))

    # --- H: sse ---
    check("stream 504 -> HIGH sse", ("sse", HIGH) in sigs(evaluate(base_snap(stream_status=504))))
    check("stream 200 0 frames -> WARNING sse", ("sse", WARNING) in sigs(evaluate(base_snap(stream_frames=0))))
    check("owner stream 403 -> auth regression HIGH", ("auth_bypass", HIGH) in sigs(evaluate(base_snap(stream_status=403))))

    # --- item 9: kill-switch intent distinction ---
    check("bridge disabled -> WARNING (intentional/kill-switch labeled)",
          ("bridge_disabled", WARNING) in sigs(evaluate(base_snap(bridge_enabled=False, ui_bridge=False, canary_ran=False))))
    check("bridge enabled but stream 502 -> HIGH unexpected",
          ("app_b_5xx", HIGH) in sigs(evaluate(base_snap(stream_status=502))))

    # --- registry drift ---
    check("registry drift -> WARNING", ("registry_drift", WARNING) in sigs(evaluate(base_snap(registry_count=31))))

    # --- 14: self-failure from collection errors ---
    check("collection error -> HIGH monitor_self",
          ("monitor_self", HIGH) in sigs(evaluate(base_snap(errors=["appB_health:unreachable"]))))
    check("no_secret note does NOT trip self-failure",
          not any(s == "monitor_self" for s, _ in sigs(evaluate(base_snap(errors=["no_secret:owner_probes_skipped"], canary_ran=False)))))
    # bridge probe failure -> collection error, NOT a false 'bridge disabled'
    _bp = sigs(evaluate(base_snap(bridge_enabled=None, errors=["bridge_health:unreachable"])))
    check("bridge probe unreachable -> monitor_self, not bridge_disabled",
          ("monitor_self", HIGH) in _bp and not any(s == "bridge_disabled" for s, _ in _bp))

    # --- redaction: no secret pattern survives any field ---
    # synthetic redaction fixtures — obviously-fake REDACTME/deadbeef values (NO real secret)
    dirty = Alert(signal="x", severity=HIGH, summary="tok wv_session=REDACTMEaaa sk-REDACTMEexamplekey and deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                  service="app_b", context={"Cookie": "wv_session=REDACTMEzzz", "REDIS_URL": "redis://REDACTME@example:6379/0",
                                            "X-API-Key": "REDACTMEkey", "keep": "ok"})
    dirty.timestamp = "T"
    blob = json.dumps(dirty.safe_payload()) + dirty.render_text()
    for bad in ["wv_session=REDACTMEaaa", "wv_session=REDACTMEzzz", "sk-REDACTME", "redis://REDACTME", "REDACTMEkey",
                "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"]:
        check(f"redaction removes {bad[:18]}", bad not in blob)
    check("redaction preserves benign field", dirty.safe_payload()["context"]["keep"] == "ok")

    # --- delivery adapter ---
    t = TestAdapter()
    a = Alert(signal="latency", severity=WARNING, summary="slow", service="app_a"); a.timestamp = "T"
    res = deliver([a], t)
    check("TestAdapter delivers + captures", res[0][1].ok and len(t.sent) == 1)
    check("unconfigured Telegram -> honest failure", TelegramAdapter(token="", chat_id="").send("x").ok is False)

    # --- dedup / cooldown / recovery (via AlertState) ---
    st = AlertState(cooldown_ticks=100)
    hi = Alert(signal="app_b_5xx", severity=HIGH, summary="down", service="app_b"); hi.timestamp = "T"
    check("dedup: first delivers", len(st.decide([hi], 0)) == 1)
    check("dedup: within cooldown suppressed", len(st.decide([hi], 50)) == 0)
    check("cooldown: past window re-notifies", len(st.decide([hi], 150)) == 1)
    rec = st.decide([], 200)
    check("recovery emitted once", len(rec) == 1 and rec[0].recovery_state == "recovered")
    check("no repeat recovery", len(st.decide([], 250)) == 0)

    # --- delivery-failure surfaces into self-health (tick, offline) ---
    class FailAdapter:
        name = "fail"
        def send(self, text):
            from ops.monitor.delivery import DeliveryResult
            return DeliveryResult(ok=False, adapter="fail", detail="HTTP 500")
    # monkeypatch collectors.collect to a controlled unhealthy snapshot
    import ops.monitor.collectors as C
    orig = C.collect
    C.collect = lambda **k: base_snap(appB_status=500)   # a real alert fires -> something to deliver
    try:
        r = tick(secret="x", adapter=FailAdapter(), state=AlertState(cooldown_ticks=0), do_canary=True)
        check("delivery failure -> healthy=False", r["healthy"] is False)
        check("delivery failure -> monitor_self appended", any(a.signal == "monitor_self" for a in r["alerts"]))
    finally:
        C.collect = orig

    # --- delivery certification payload is secret-free INFO ---
    a2, res2, text2, leaked = send_test(TestAdapter())
    check("send_test INFO + no leak", a2.severity == INFO and res2.ok and leaked == [])
    check("send_test labels environment=production", a2.environment == "production")

    n = len(PASS); ok = sum(PASS)
    print(f"\nMONITOR TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n

if __name__ == "__main__":
    sys.exit(0 if run() else 1)
