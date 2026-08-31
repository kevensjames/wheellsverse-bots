"""Live per-entity status collector — PUBLIC endpoints only, NO secrets, source-backed.

Fetches the real status each product publishes (the endpoints surveyed in-repo) and returns a
per-entity overlay the briefing carries alongside the curated registry. This is what makes the
Holding OS AUTONOMOUS: deploy/activity state self-updates from live sources instead of staying
operator-confirmed. No fabrication — an unreachable or unparseable probe is reported as such,
never guessed. Prod-compatible (urllib + short timeouts, best-effort; never raises).

Honest gaps (no public probe): solcircle (legal wrapper), nurtelle (no deployed env), siteboost /
wmos (real state lives in App-A-volume files with no JSON endpoint yet).
"""
from __future__ import annotations
import json
import urllib.request

APP_A = "https://app.wheellsverse.com"
KAI = "https://kai-prod-production.up.railway.app"
SOL = "https://sol-api-production.up.railway.app"

# entity_id -> (url, fields-to-surface | None for reachability-only)
_PROBES: dict[str, tuple[str, list | None]] = {
    "kai": (KAI + "/health", ["status", "env"]),
    "wheellsverse_holdings": (APP_A + "/api/health", ["status", "git_sha", "uptime_human"]),
    "wheellsverse_bots": (APP_A + "/api/health", ["git_sha", "build_time", "deploy_id"]),
    # Nexora is the only entity publishing real customer-adjacent numbers over plain HTTP:
    "nexora": (APP_A + "/api/nexora/status",
               ["subscribers", "leads", "spots_taken", "pages_built", "posts_today", "mrr", "stripe_set"]),
    "narai": (APP_A + "/api/narai/status", ["online", "status", "posts", "videos", "images"]),
    "sol": (SOL + "/", None),   # reachability only (public liveness of the SOL API)
}


def _get(url: str, timeout: int = 8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
            try:
                return r.status, json.loads(body)
            except Exception:
                return r.status, {}
    except Exception as e:
        return 0, {"_err": str(e)[:80]}


def collect_live_entity_status() -> dict:
    """Return {entity_id: {ok, http, source, detail}}. Best-effort; never raises."""
    out: dict[str, dict] = {}
    for eid, (url, fields) in _PROBES.items():
        code, data = _get(url)
        detail = {}
        if fields and isinstance(data, dict):
            detail = {f: data[f] for f in fields if f in data}
        out[eid] = {"ok": code == 200, "http": code, "source": url, "detail": detail}
    return out


def demo() -> None:
    """Self-check against the live public endpoints (no secrets)."""
    st = collect_live_entity_status()
    assert set(st) >= {"kai", "nexora", "narai", "sol"}, st
    assert all(set(v) >= {"ok", "http", "source", "detail"} for v in st.values())
    up = [e for e, v in st.items() if v["ok"]]
    print(f"entity_status.demo OK — {len(up)}/{len(st)} entities live:",
          {e: v.get("detail") or v["http"] for e, v in st.items()})


if __name__ == "__main__":
    demo()
