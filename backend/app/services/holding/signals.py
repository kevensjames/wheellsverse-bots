"""App B's self-observed LIVE signals — public probes only, NO secrets.

The prod observability monitor is a separate Railway service whose internal state (its /data
volume) App B cannot read. So the briefing observes what it CAN reach itself: the public health
endpoints. app.wheellsverse.com/api/health exposes real operational signals (status + cpu/mem),
kai-prod /health exposes status+env. Failing signals feed the briefing as ranked priorities.

Complementary to the external monitor (which additionally checks governed-internal signals that
need the session secret). Every signal here is source-backed by a live probe; nothing is invented.
"""
from __future__ import annotations
import json
import time
import urllib.request

APP_A = "https://app.wheellsverse.com"
APP_B = "https://kai-prod-production.up.railway.app"
CPU_CRIT, CPU_HIGH = 90.0, 80.0            # resource thresholds (ops defaults)
MEM_CRIT, MEM_HIGH = 90.0, 80.0
LATENCY_HIGH_MS = 5000


def _get(url: str, timeout: int = 10):
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(), int((time.time() - t0) * 1000)
    except Exception as e:
        return 0, str(e).encode(), int((time.time() - t0) * 1000)


def _res_sig(name: str, pct, crit: float, high: float) -> dict:
    sev = "CRITICAL" if pct >= crit else "HIGH" if pct >= high else "OK"
    return {"name": name, "ok": sev == "OK", "severity": sev, "detail": f"{pct}%"}


def collect_live_signals(app_a: str = APP_A, app_b: str = APP_B) -> list[dict]:
    """Return a list of live signal dicts {name, ok, severity, detail}. Never raises."""
    out: list[dict] = []

    st, body, ms = _get(app_a + "/api/health")
    if st != 200:
        out.append({"name": "appA_health", "ok": False, "severity": "CRITICAL", "detail": f"unreachable/HTTP {st}"})
    else:
        try:
            h = json.loads(body)
        except Exception:
            h = {}
        status_ok = h.get("status") == "ok"
        out.append({"name": "appA_health", "ok": status_ok, "severity": "OK" if status_ok else "CRITICAL",
                    "detail": f"status={h.get('status')} git={h.get('git_sha')}"})
        if ms > LATENCY_HIGH_MS:
            out.append({"name": "appA_latency", "ok": False, "severity": "HIGH", "detail": f"{ms}ms"})
        sysd = h.get("system") or {}
        if isinstance(sysd.get("cpu_pct"), (int, float)):
            out.append(_res_sig("appA_cpu", sysd["cpu_pct"], CPU_CRIT, CPU_HIGH))
        if isinstance(sysd.get("mem_pct"), (int, float)):
            out.append(_res_sig("appA_mem", sysd["mem_pct"], MEM_CRIT, MEM_HIGH))

    st, body, ms = _get(app_b + "/health")
    if st != 200:
        out.append({"name": "appB_health", "ok": False, "severity": "CRITICAL", "detail": f"unreachable/HTTP {st}"})
    else:
        try:
            h = json.loads(body)
        except Exception:
            h = {}
        status_ok = h.get("status") == "ok"
        out.append({"name": "appB_health", "ok": status_ok, "severity": "OK" if status_ok else "CRITICAL",
                    "detail": f"status={h.get('status')} env={h.get('env')}"})
    return out


def health_block(signals: list[dict]) -> dict:
    """Compact {app_a/app_b: {http}} health block derived from the two health signals."""
    hb = {}
    for s in signals:
        if s["name"] == "appA_health":
            hb["app_a"] = {"http": 200 if s["ok"] else 0}
        elif s["name"] == "appB_health":
            hb["app_b"] = {"http": 200 if s["ok"] else 0}
    return hb


def demo() -> None:
    """Self-check against the live prod endpoints (no secrets)."""
    sig = collect_live_signals()
    assert any(s["name"] == "appA_health" for s in sig) and any(s["name"] == "appB_health" for s in sig), sig
    assert all(set(s) >= {"name", "ok", "severity", "detail"} for s in sig)
    print(f"signals.demo OK — {len(sig)} live signals:",
          [(s["name"], s["severity"]) for s in sig])


if __name__ == "__main__":
    demo()
