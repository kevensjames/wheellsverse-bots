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


def post(path, cookie=None, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(URL + path, data=data, method="POST",
                                 headers={"User-Agent": "autonomy-cert", "Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
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
# exclude the honest 'claims_consciousness' field name from the wording scan
_scan = json.dumps(v).lower().replace("claims_consciousness", "")
ck("no consciousness/sentience wording in view", "sentient" not in _scan and "conscious" not in _scan)

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
brake1_on = cs in (200, 403)    # mounted -> enabled (owner=200 authorized, non-owner=403)
ck("capability-execution brake state readable", brake1_off or brake1_on,
   f"HTTP {cs} -> {'DARK (disabled)' if brake1_off else 'ENABLED' if brake1_on else 'UNEXPECTED'}")

print("STEP 7 — manual single-cycle trigger (owner-only, POST-only, staging-gated)")
gs, _ = get("/admin/holding/run-cycle")   # GET must not run a cycle
ck("GET /run-cycle -> not allowed (405/404, never runs)", gs in (404, 405), f"HTTP {gs}")
ps_anon, _ = post("/admin/holding/run-cycle")   # anonymous POST denied
ck("anonymous POST -> denied", ps_anon in (401, 403, 404), f"HTTP {ps_anon}")
pf, _ = post("/admin/holding/run-cycle", operator, {})
ck("operator POST -> denied (no escalation)", pf in (403, 404), f"HTTP {pf}")
# forbidden body field rejected (or 404 if the manual-cycle flag is off)
pb, _ = post("/admin/holding/run-cycle", owner, {"capability_id": "financial.wire", "task": "x"})
ck("forbidden body field -> 400 (or 404 if flag off)", pb in (400, 404), f"HTTP {pb}")

st_cyc, c1 = post("/admin/holding/run-cycle", owner, {})
if st_cyc == 404:
    print("  [SKIP] manual cycle disabled — set KAI_HOLDING_MANUAL_CYCLE_ENABLED=true (staging) to certify the loop")
elif st_cyc == 200:
    ck("owner POST -> 200 CycleRecord", isinstance(c1, dict) and "cycle_id" in c1, c1.get("status"))
    print("STEP 8 — QUIET CYCLE (mandatory): a second cycle with no change does 0 work")
    st2, c2 = post("/admin/holding/run-cycle", owner, {})
    ck("second cycle -> 0 material changes", st2 == 200 and c2.get("material_changes_count") == 0,
       f"changes={c2.get('material_changes_count')}")
    ck("second cycle -> 0 auto actions", c2.get("auto_actions_executed") == 0)
    ck("second cycle -> 0 owner actions created", c2.get("owner_actions_created") == 0)
    ck("second cycle -> 0 plan updates", c2.get("plan_updates_count") == 0)
    print("STEP 9 — idempotency + single-flight")
    _, cidem = post("/admin/holding/run-cycle", owner, {"idempotency_key": "cert-key-1"})
    _, cidem2 = post("/admin/holding/run-cycle", owner, {"idempotency_key": "cert-key-1"})
    ck("idempotency replay -> same cycle_id", cidem.get("cycle_id") == cidem2.get("cycle_id"))
else:
    ck("owner POST -> 200/404", False, f"HTTP {st_cyc}")

n = len(res); ok = sum(res)
print(f"\nAUTONOMY HOSTED CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
print("(A0-live execute + owner-boundary + A1/A2/self-improve: certify in order after brake #2 is lifted;"
      " see KAI_HOLDING_OS_STAGING_CERTIFICATION.md §Phase-2.)")
sys.exit(0 if ok == n else 1)
