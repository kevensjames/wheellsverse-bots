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
    # New App-A read-only stat shims (real outbound/loop state that previously lived only in
    # App-A-volume files); captured whole since their shape is a nested {ok, stats/businesses}.
    "siteboost": (APP_A + "/api/siteboost/stats", "ALL"),
    "wmos": (APP_A + "/api/wmos/stats", "ALL"),
}
# sol + suprema live in App B's own services, so the Holding OS reads them IN-PROCESS (below) —
# no HTTP/auth needed. (The public sol-api liveness probe was unreliable, so it was dropped.)


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


def collect_internal_status() -> dict:
    """In-process live status for App-B-local entities (sol, suprema) whose data lives in App B's own
    services — no HTTP/auth needed since the Holding OS runs in App B. Best-effort, fail-open."""
    out: dict[str, dict] = {}
    try:
        from app.services.sol import storage as st
        circles = st.list_circles()
        by_status: dict[str, int] = {}
        for c in circles:
            by_status[c.status] = by_status.get(c.status, 0) + 1
        out["sol"] = {"ok": True, "source": "in-process app.services.sol.storage",
                      "detail": {"total_circles": len(circles), "by_status": by_status}}
    except Exception as e:
        out["sol"] = {"ok": False, "source": "in-process sol", "detail": {"_err": str(e)[:80]}}
    try:
        from app.services.supreme.scheduler import is_running
        from app.services.supreme import load_map
        smap = load_map()
        out["suprema"] = {"ok": True, "source": "in-process app.services.supreme",
                          "detail": {"scheduler_running": bool(is_running()), "map_loaded": bool(smap)}}
    except Exception as e:
        out["suprema"] = {"ok": False, "source": "in-process suprema", "detail": {"_err": str(e)[:80]}}
    return out


def collect_live_entity_status() -> dict:
    """Return {entity_id: {ok, http?, source, detail}} for all probeable entities. Best-effort; never
    raises. HTTP probes + in-process App-B-local reads (sol, suprema) merged."""
    out: dict[str, dict] = {}
    for eid, (url, fields) in _PROBES.items():
        code, data = _get(url)
        detail = {}
        if fields == "ALL" and isinstance(data, dict):
            detail = {k: v for k, v in data.items() if k != "_err"}   # capture the whole small response
        elif fields and isinstance(data, dict):
            detail = {f: data[f] for f in fields if f in data}
        out[eid] = {"ok": code == 200, "http": code, "source": url, "detail": detail}
    out.update(collect_internal_status())   # sol + suprema, in-process (take precedence)
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
