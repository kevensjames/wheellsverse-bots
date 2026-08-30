"""Hosted staging certification for the Holding OS — runs against the DEPLOYED App B.

Validates the live governed endpoints exactly like the in-process staging_cert.py, but over HTTP:
owner-only access, no operator-role escalation, truth-grounding (disclaim vs operator-confirmed),
and the real ranked priorities / KPI snapshot / movement.

Run it with the staging service's env injected so it can mint a matching owner cookie WITHOUT
the secret ever being printed:

    STAGING_URL=https://<staging-app-b>.up.railway.app \
      railway run --service <staging-app-b> python3 ops/holding-staging/hosted_cert.py

(`railway run` injects SESSION_SIGNING_SECRET from the service; this script only signs a cookie
with it and never logs it.)
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from core.operator_session import mint_session, ROLE_OWNER, ROLE_OPERATOR

URL = os.environ.get("STAGING_URL", "").rstrip("/")
SECRET = os.environ.get("SESSION_SIGNING_SECRET", "")
if not URL or not SECRET:
    print("FATAL: set STAGING_URL and run under `railway run` so SESSION_SIGNING_SECRET is injected.")
    sys.exit(2)

owner = "wv_session=" + mint_session(ROLE_OWNER, secret=SECRET)
operator = "wv_session=" + mint_session(ROLE_OPERATOR, secret=SECRET)

res = []
def ck(n, ok, d=""): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def get(path, cookie=None):
    req = urllib.request.Request(URL + path, headers={"User-Agent": "holding-staging-cert"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {"_err": str(e)[:120]}


print(f"STAGING HOLDING CERT → {URL}")
print("STEP 2 — flag-gated + owner-only access control")
st, _ = get("/admin/holding/overview")
ck("unauthenticated -> denied", st in (401, 403), f"HTTP {st}")
st, _ = get("/admin/holding/overview", operator)
ck("operator role -> denied (no kai.ultra escalation)", st == 403, f"HTTP {st}")

print("STEP 1 — owner (kai.ultra) executes read-only endpoints")
so, ov = get("/admin/holding/overview", owner)
ck("owner -> /overview 200", so == 200, f"HTTP {so}")
se, ent = get("/admin/holding/entities/solcircle", owner)
ck("owner -> /entities/solcircle 200", se == 200, f"HTTP {se}")
sb, brief = get("/admin/holding/briefing", owner)
ck("owner -> /briefing 200 (report-only)", sb == 200, f"HTTP {sb}")

print("STEP 3 — TRUTH GROUNDING (disclaim vs operator-confirmed)")
blob = json.dumps(ent).lower()
ck("solcircle banking/payment/compliance still disclaimed", "requires_operator_confirmation" in blob,
   "confirm-marker present" if "requires_operator_confirmation" in blob else "MISSING")

print("STEP 4 — real ranked priorities + KPI snapshot + movement (live)")
ps = brief.get("todays_priorities")
ck("priorities are a ranked, source-cited list", isinstance(ps, list) and len(ps) > 0
   and all("source" in p and "severity" in p for p in ps), f"{len(ps) if isinstance(ps, list) else 0} items")
ck("KPI snapshot present (source-backed counts)", isinstance(brief.get("kpis"), dict)
   and "entities_total" in brief.get("kpis", {}))
ck("KPI movement present (baseline or real deltas)", isinstance(brief.get("kpi_movement"), dict))
ck("live-signal health reported", "health" in brief.get("kpis", {}))

n = len(res); ok = sum(res)
print(f"\nHOSTED HOLDING STAGING CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
sys.exit(0 if ok == n else 1)
