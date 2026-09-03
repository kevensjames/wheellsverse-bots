"""Holding OS staging certification (production untouched, flags ON in isolation).

Steps 1-4 against the REAL FastAPI app (app.main:app) via TestClient:
  1. owner (kai.ultra) executes the read-only endpoints
  2. flag-gated + owner-only access control (unauth 403, operator role 403 — no escalation)
  3. TRUTH GROUNDING: money/customer/banking fields DISCLAIMED, never fabricated
  4. flag OFF -> holding surface is dark (zero routes)

Run (needs local Postgres + the backend deps):
  cd backend && DATABASE_URL=... python3 app/services/holding/staging_cert.py
Prints N/N PASS and exits non-zero on any failure. Never deploys; APP_ENV forced to 'staging'.
"""
import os, sys, json, subprocess

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
os.chdir(BACKEND); sys.path.insert(0, BACKEND)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://jhonwheeler@/wheellsverse_test?host=/tmp")
os.environ.update({
    "APP_ENV": "staging",                       # never 'production'
    "KAI_HOLDING_ENABLED": "true",
    "KAI_HOLDING_BRIEFING_ENABLED": "true",
    "OPERATOR_SESSION_ENABLED": "true",         # exercise the real owner-principal gate
    "SESSION_SIGNING_SECRET": os.environ.get("SESSION_SIGNING_SECRET", "ephemeral-staging-secret-not-committed"),
    "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", "sk-unused-holding-is-readonly"),
})

import app.main as m
from core.operator_session import mint_session, ROLE_OWNER, ROLE_OPERATOR
from fastapi.testclient import TestClient

res = []
def ck(n, ok, d=""): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))

c = TestClient(m.app)
SECRET = os.environ["SESSION_SIGNING_SECRET"]
owner = {"wv_session": mint_session(ROLE_OWNER, secret=SECRET)}
operator = {"wv_session": mint_session(ROLE_OPERATOR, secret=SECRET)}

print("STEP 2 — flag-gated + owner-only access control")
ck("unauthenticated -> denied", c.get("/admin/holding/overview").status_code in (401, 403))
ck("operator role -> denied (no kai.ultra escalation)",
   c.get("/admin/holding/overview", cookies=operator).status_code == 403)

print("STEP 1 — owner (kai.ultra) executes read-only endpoints")
ro = c.get("/admin/holding/overview", cookies=owner)
ck("owner -> /overview 200", ro.status_code == 200, f"HTTP {ro.status_code}")
re = c.get("/admin/holding/entities/solcircle", cookies=owner)
ck("owner -> /entities/solcircle 200", re.status_code == 200, f"HTTP {re.status_code}")
ck("owner -> /briefing 200 (report-only)", c.get("/admin/holding/briefing", cookies=owner).status_code == 200)

print("STEP 3 — TRUTH GROUNDING: money/customer/banking fields DISCLAIMED, never fabricated")
body = re.json(); blob = json.dumps(body).lower()
disclaimed = ("requires_operator_confirmation" in blob) or ("not source-backed" in blob)
ck("solcircle money/customer/banking fields disclaimed", disclaimed,
   "confirm-marker present" if disclaimed else "NO disclaimer — possible fabrication!")
def _dig(o, key):
    if isinstance(o, dict):
        if key in o: return o[key]
        for v in o.values():
            r = _dig(v, key)
            if r is not None: return r
    return None
for f in ("revenue_metrics", "customers", "banking_provider_reference", "payment_provider_reference"):
    print(f"      solcircle.{f} = {_dig(body, f)!r}")

print("STEP 4 — flag OFF -> holding surface is DARK (routes absent)")
off = subprocess.run([sys.executable, "-c",
    "import app.main as m; print([p for p in [r.path for r in m.app.routes] if 'holding' in p])"],
    cwd=BACKEND, capture_output=True, text=True,
    env={**os.environ, "KAI_HOLDING_ENABLED": "false", "KAI_HOLDING_BRIEFING_ENABLED": "false"})
ck("KAI_HOLDING_ENABLED=false -> zero holding routes", off.stdout.strip() == "[]",
   off.stdout.strip() or off.stderr[-160:])

n = len(res); ok = sum(res)
print(f"\nHOLDING STAGING CERTIFICATION: {ok}/{n} —", "PASS" if ok == n else "FAIL")
sys.exit(0 if ok == n else 1)
