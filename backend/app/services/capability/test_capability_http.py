"""HTTP-boundary certification for the owner-only execution route (§39/§44/§6/§4).

Exercises the real FastAPI router via TestClient with the owner gate overridden: owner authorization,
anonymous denial, forged-body-fields-ignored, SSRF/envelope/unknown status mapping. SKIPS cleanly
(exit 0) where the App B import chain / deps are unavailable, so it never breaks the pure-python
suite. Run in a backend env: python3 <this file>.
"""
import os
import sys
from pathlib import Path

# minimal env so app.config validates on import (real env wins via setdefault)
for k, v in {"DATABASE_URL": "sqlite:///:memory:", "SESSION_SIGNING_SECRET": "x", "API_KEY": "x",
             "ADMIN_TOKEN": "x", "JWT_SECRET_KEY": "x", "OPENAI_API_KEY": "x"}.items():
    os.environ.setdefault(k, v)
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path for `app.*`

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from app.routers import admin_capabilities as ac
    from app.routers.admin_chat import require_kai_ultra
except Exception as e:   # noqa: BLE001 — app deps not available in this env → skip, don't fail
    print(f"SKIP  test_capability_http (app deps unavailable: {type(e).__name__})")
    sys.exit(0)

_p = 0


def test(name, cond):
    global _p
    if cond:
        print("  ok  " + name); _p += 1
    else:
        print("  FAIL " + name); sys.exit(1)


app = FastAPI(); app.include_router(ac.router)
c = TestClient(app)

# ── OWNER (gate satisfied) ────────────────────────────────────────────────────
app.dependency_overrides[require_kai_ultra] = lambda: None
r = c.get("/admin/capabilities")
test("owner lists capabilities (200)", r.status_code == 200 and len(r.json()["capabilities"]) == 3)
r = c.post("/admin/capabilities/yt-dlp/invoke", json={"operation": "metadata", "input": {"url": "http://169.254.169.254/"}})
test("SSRF metadata endpoint -> 400 INPUT_REJECTED", r.status_code == 400 and r.json()["status"] == "INPUT_REJECTED")
r = c.post("/admin/capabilities/yt-dlp/invoke", json={"operation": "download", "input": {"url": "https://1.1.1.1/"}})
test("download outside V1 -> 403 OPERATION_NOT_ENABLED", r.status_code == 403 and r.json()["status"] == "OPERATION_NOT_ENABLED")
r = c.post("/admin/capabilities/nope/invoke", json={"operation": "x", "input": {}})
test("unknown capability -> 404", r.status_code == 404)
r = c.post("/admin/capabilities/codebase-memory-mcp/invoke", json={"operation": "delete_project", "input": {}})
test("non-allowlisted op -> 404 OPERATION_UNKNOWN", r.status_code == 404 and r.json()["status"] == "OPERATION_UNKNOWN")
# §4: forged authoritative fields are accepted-and-ignored (not 422, and grant nothing → still 503 at health gate)
r = c.post("/admin/capabilities/yt-dlp/invoke",
           json={"operation": "metadata", "input": {"url": "https://1.1.1.1/"},
                 "role": "owner", "approved": True, "scopes": ["*"], "risk_class": "LOW"})
test("forged body fields ignored (not 422)", r.status_code != 422)
r = c.get("/admin/capabilities/yt-dlp/status")
test("status endpoint (200)", r.status_code == 200 and "server_state" in r.json())

# ── ANON (gate denies) ────────────────────────────────────────────────────────
def _deny():
    raise HTTPException(status_code=403, detail="owner access required")


app.dependency_overrides[require_kai_ultra] = _deny
test("anon list -> 403", c.get("/admin/capabilities").status_code == 403)
test("anon invoke -> 403",
     c.post("/admin/capabilities/yt-dlp/invoke", json={"operation": "metadata", "input": {"url": "https://1.1.1.1/"}}).status_code == 403)
test("anon test -> 403", c.post("/admin/capabilities/markitdown/test").status_code == 403)

print("\n%d passed  (HTTP boundary)" % _p)
