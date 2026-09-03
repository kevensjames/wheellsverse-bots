"""Trigger the in-container self-cert endpoint and print the DEPLOYED CONTAINER's A0/A1 results.

    STAGING_URL=https://<app-b>.up.railway.app \
      railway run --service kai-staging-appb python3 ops/holding-staging/hosted_selfcert_client.py

This client runs LOCALLY (railway run injects SESSION_SIGNING_SECRET to mint an owner cookie), but the
A0/A1 certification programs execute INSIDE the deployed container via GET /admin/holding/self-cert —
so the pass/fail + STEP-0 server-state you see below is the deployed container's, not your laptop's.
Requires KAI_HOLDING_SELFCERT_ENABLED=true + APP_ENV=staging on the service, and the endpoint deployed.
The secret is only used to sign a cookie; it is never printed.
"""
import json
import os
import sys
import urllib.request
import urllib.error

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from core.operator_session import mint_session, ROLE_OWNER   # noqa: E402

URL = os.environ.get("STAGING_URL", "").rstrip("/")
SECRET = os.environ.get("SESSION_SIGNING_SECRET", "")
if not URL or not SECRET:
    print("FATAL: set STAGING_URL and run under `railway run` so SESSION_SIGNING_SECRET is injected.")
    sys.exit(2)

req = urllib.request.Request(URL + "/admin/holding/self-cert",
                            headers={"Cookie": "wv_session=" + mint_session(ROLE_OWNER, secret=SECRET),
                                     "User-Agent": "selfcert-client"})
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read() or b"{}")
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: is KAI_HOLDING_SELFCERT_ENABLED=true, APP_ENV=staging, and the endpoint deployed?")
    sys.exit(1)
except Exception as e:
    print(f"request failed: {str(e)[:200]}")
    sys.exit(1)

print(f"RAN IN: {d.get('ran_in')}  host={d.get('hostname')}  app_env={d.get('app_env')}  "
      f"deployed_sha={d.get('deployed_sha')}")
all_ok = True
for name in ("a0", "a1"):
    res = d.get("results", {}).get(name, {})
    print(f"\n===== {name.upper()}  exit={res.get('exit')}  {res.get('verdict', '')} =====")
    print((res.get("output_tail") or res.get("error") or "")[-3500:])
    all_ok = all_ok and bool(res.get("passed"))
print("\nHOSTED SELF-CERT (executed in the deployed container):", "PASS" if all_ok else "FAIL")
sys.exit(0 if all_ok else 1)
