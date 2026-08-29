"""Live signal collection for the production monitor (external, read-only).

Polls App A + App B public surfaces and the owner-scoped /admin/spend; optional
canaries verify the auth matrix (bypass detection) and audit/usage persistence
(executed-but-unaudited detection). A probe failure is itself a signal, never hidden.

Owner session is minted in-memory from the shared SESSION_SIGNING_SECRET (App A env,
matches App B); the secret and token are never printed or returned.
"""
from __future__ import annotations
import json, time, urllib.request, urllib.error

APP_A = "https://app.wheellsverse.com"
APP_B = "https://kai-prod-production.up.railway.app"


def _probe(url, method="GET", cookie=None, body=None, timeout=30, stream=False):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if data else {}
    if cookie:
        h["Cookie"] = f"wv_session={cookie}"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.monotonic()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        if stream:
            frames = 0; text = False
            for raw in resp:
                line = raw.decode(errors="replace")
                if line.startswith("data:"):
                    frames += 1
                    if any(c.isalnum() for c in line[5:]):
                        text = True
                if frames >= 200:
                    break
            ms = (time.monotonic() - t0) * 1000
            return resp.status, ms, resp.headers, {"frames": frames, "text": text}
        raw = resp.read().decode()
        ms = (time.monotonic() - t0) * 1000
        try:
            b = json.loads(raw) if raw else {}
        except ValueError:
            b = {}
        return resp.status, ms, resp.headers, b
    except urllib.error.HTTPError as e:
        ms = (time.monotonic() - t0) * 1000
        try:
            b = json.loads(e.read().decode())
        except Exception:
            b = {}
        return e.code, ms, e.headers, b
    except Exception as e:
        ms = (time.monotonic() - t0) * 1000
        return 0, ms, None, {"_probe_error": type(e).__name__}


def collect(secret=None, do_canary=True, app_a=APP_A, app_b=APP_B):
    """Return a signal snapshot dict. Never raises; collection errors are recorded."""
    snap = {"errors": [], "ts": time.time()}

    def rec(name, fn):
        try:
            return fn()
        except Exception as e:
            snap["errors"].append(f"{name}:{type(e).__name__}")
            return None

    # --- App A public liveness + control plane ---
    st, ms, _, b = _probe(f"{app_a}/api/health")
    snap["appA_status"], snap["appA_ms"] = st, round(ms)
    if st == 0:
        snap["errors"].append("appA_health:unreachable")
    st, ms, _, b = _probe(f"{app_a}/admin/kai-bridge/health")
    if st == 0:
        # probe failure must NOT masquerade as an intentional "bridge disabled" state
        snap["errors"].append("bridge_health:unreachable")
        snap["bridge_enabled"] = None
        snap["upstream_configured"] = None
    else:
        snap["bridge_enabled"] = bool(b and b.get("enabled"))
        snap["upstream_configured"] = bool(b and b.get("upstream_configured"))
    st, ms, _, b = _probe(f"{app_a}/admin/ui-config")
    snap["ui_operator_session"] = bool(b and b.get("operator_session_enabled"))
    snap["ui_bridge"] = bool(b and b.get("kai_bridge_enabled"))
    st, ms, _, b = _probe(f"{app_a}/admin/registry.json")
    snap["registry_count"] = (b or {}).get("counts", {}).get("total") if isinstance(b, dict) else None

    # --- App B liveness ---
    st, ms, _, b = _probe(f"{app_b}/health")
    snap["appB_status"], snap["appB_ms"] = st, round(ms)
    snap["appB_env"] = (b or {}).get("env") if isinstance(b, dict) else None
    if st == 0:
        snap["errors"].append("appB_health:unreachable")

    if not secret:
        snap["errors"].append("no_secret:owner_probes_skipped")
        snap["canary_ran"] = False
        return snap

    # owner session (shared secret) for governed-internal signals
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from core.operator_session import mint_session, ROLE_OWNER, ROLE_OPERATOR
        owner = mint_session(ROLE_OWNER, secret=secret)
        operator = mint_session(ROLE_OPERATOR, secret=secret)
    except Exception as e:
        snap["errors"].append(f"mint_session:{type(e).__name__}")
        snap["canary_ran"] = False
        return snap

    # --- spend / provider / db-health proxy (PG reachable if this reads) ---
    st, ms, _, sp = _probe(f"{app_b}/admin/spend", cookie=owner)
    snap["spend_status"] = st
    if st == 200 and isinstance(sp, dict):
        today = sp.get("today") or []
        oa = [x for x in today if x.get("adapter") == "openai"]
        snap["openai_calls_today"] = sum(x.get("calls", 0) for x in oa)
        snap["openai_cost_today"] = round(sum(x.get("cost_usd", 0.0) for x in oa), 6)
        snap["failures_24h"] = sp.get("failures_24h", 0)
        snap["pg_reachable"] = True   # /admin/spend reads llm_call_log from Postgres
    else:
        snap["pg_reachable"] = False
        snap["errors"].append(f"spend:{st}")

    if not do_canary:
        snap["canary_ran"] = False
        return snap
    snap["canary_ran"] = True

    # --- auth-matrix canary through the bridge (bypass detection) ---
    st, _, _, _ = _probe(f"{app_a}/admin/kai/kai-chat", method="POST", body={"message": "x"})
    snap["auth_anon_status"] = st         # expect 401
    st, _, _, bb = _probe(f"{app_a}/admin/kai/kai-chat", method="POST", cookie=operator, body={"message": "x"})
    snap["auth_operator_status"] = st     # expect 403
    snap["auth_operator_need"] = (bb or {}).get("need")

    # --- governed audit-gap + SSE canary (owner) ---
    base = snap.get("openai_calls_today", 0)
    st, ms, hdrs, s = _probe(f"{app_a}/admin/kai/kai-chat/stream", method="POST", cookie=owner,
                             body={"message": "monitor canary: reply OK.", "use_tools": False, "prefer_local": False},
                             stream=True, timeout=90)
    snap["stream_status"] = st
    snap["stream_frames"] = s.get("frames", 0) if isinstance(s, dict) else 0
    snap["stream_corr"] = bool(hdrs and hdrs.get("x-correlation-id"))
    # re-read spend to verify the canary's usage row persisted (audit-gap detection)
    st2, _, _, sp2 = _probe(f"{app_b}/admin/spend", cookie=owner)
    if st2 == 200 and isinstance(sp2, dict):
        after = sum(x.get("calls", 0) for x in (sp2.get("today") or []) if x.get("adapter") == "openai")
        snap["usage_incremented"] = after > base if snap.get("stream_status") == 200 else None
    else:
        snap["usage_incremented"] = None
    return snap


if __name__ == "__main__":
    import os
    snap = collect(secret=os.environ.get("SESSION_SIGNING_SECRET"), do_canary=bool(os.environ.get("SESSION_SIGNING_SECRET")))
    # snapshot carries only statuses/counts/latencies — no secret fields by construction
    print(json.dumps(snap, indent=2, default=str))
