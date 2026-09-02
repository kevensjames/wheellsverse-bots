"""Hosted autonomy-layer certification for the Holding OS — runs against the DEPLOYED App B staging.

Certifies the NEW autonomy view + owner boundary + emergency-brake state over HTTP, owner-authenticated,
without ever printing the secret. Complements ops/holding-staging/hosted_cert.py (read-only Holding OS).

    STAGING_URL=https://<staging-app-b>.up.railway.app \
      railway run --service <staging-app-b> python3 ops/holding-staging/autonomy_cert.py

(`railway run` injects SESSION_SIGNING_SECRET; this script only signs a cookie with it and never logs it.)

Run it in each brake state to prove the progression:
  • DARK  (KAI_CAPABILITY_EXECUTION_ENABLED=false): /admin/capabilities is 404 (router not mounted).
  • BRAKE#1 lifted (=true): /admin/capabilities becomes 403 (mounted, owner-gated).
Autonomy (brake #2) is a backend flag reflected in the view; the live cycle needs a trigger/cron (see report).
"""
import json
import os
import sys
import urllib.request
import urllib.error

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
def ck(n, ok, d=""): res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def get(path, cookie=None):
    req = urllib.request.Request(URL + path, headers={"User-Agent": "autonomy-cert"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return 0, {"_err": str(e)[:120]}


print(f"AUTONOMY HOSTED CERT → {URL}")

print("STEP 1 — owner-only access control on the autonomy view")
st, _ = get("/admin/holding/view")
ck("unauthenticated -> denied", st in (401, 403), f"HTTP {st}")
st, _ = get("/admin/holding/view", operator)
ck("operator role -> denied (no kai.ultra escalation)", st == 403, f"HTTP {st}")

print("STEP 2 — owner reads the view-model")
so, v = get("/admin/holding/view", owner)
ck("owner -> /view 200", so == 200, f"HTTP {so}")
for key in ("today_for_you", "kai_working", "company_cards", "operational_self_model", "autonomy"):
    ck(f"view section '{key}' present", key in v)

print("STEP 3 — Operational Self Model is operational, NEVER sentient")
osm = v.get("operational_self_model", {})
ck("label = Operational Self Model", osm.get("label") == "Operational Self Model")
ck("claims_consciousness is False", osm.get("claims_consciousness") is False)
ck("no consciousness/sentience wording in view", "sentient" not in json.dumps(v).lower()
   and "conscious" not in json.dumps(v).lower())

print("STEP 4 — companies are DISCOVERED dynamically + money mode truth")
cc = v.get("company_cards", [])
ck("company cards discovered from registry (>0)", isinstance(cc, list) and len(cc) > 0, f"{len(cc)} companies")
ck("MONEY_MODE = MOCK", v.get("autonomy", {}).get("money_mode") == "MOCK")

print("STEP 5 — operational status endpoint")
ss, _ = get("/admin/holding/status", owner)
ck("owner -> /status 200", ss == 200, f"HTTP {ss}")

print("STEP 6 — EMERGENCY BRAKE #1 state (capability execution)")
cs, _ = get("/admin/capabilities", owner)
brake1_off = cs == 404          # router not mounted -> execution disabled (dark)
brake1_on = cs == 403           # mounted + owner-gated -> execution enabled
ck("capability-execution brake state readable", brake1_off or brake1_on,
   f"HTTP {cs} -> {'DARK (disabled)' if brake1_off else 'ENABLED' if brake1_on else 'UNEXPECTED'}")

n = len(res); ok = sum(res)
print(f"\nAUTONOMY HOSTED CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
print("(Live autonomy CYCLE certification — cycle 1 execute + cycle 2 quiet — needs the on-demand"
      " cycle trigger or the cron; see KAI_HOLDING_OS_STAGING_CERTIFICATION.md.)")
sys.exit(0 if ok == n else 1)
