#!/usr/bin/env bash
# Part 3 — MAC MINI REBOOT SURVIVAL verifier (operator runs this AFTER a reboot/login cycle).
# Read-only. Confirms the STAGING worker came back on its own with the right identity/config/auth, a fresh
# heartbeat, and NO invented/replayed jobs — WITHOUT dispatching any write. A2/self-improvement authority is
# a server-side brake unaffected by a worker-host reboot; this checks the WORKER-side survival invariants.
#
#   bash ops/holding-worker-runner/verify-reboot-survival.sh
#
# Env: KAI_WORKER_REPO (default ~/kai-worker/repositories/wheellsverse), EXPECT_SHA (default: checkout HEAD),
#      BASE_URL (default staging App B).
set -uo pipefail

LABEL="com.wheellsverse.kai-holding-worker-staging"
REPO="${KAI_WORKER_REPO:-$HOME/kai-worker/repositories/wheellsverse}"
BASE_URL="${BASE_URL:-https://kai-staging-appb-production.up.railway.app}"
KEYCHAIN_SVC="kai-holding-worker-staging"
EXPECT_SHA="${EXPECT_SHA:-$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null)}"
pass=0; fail=0
ck(){ if [ "$1" = "1" ]; then echo "  [PASS] $2"; pass=$((pass+1)); else echo "  [FAIL] $2"; fail=$((fail+1)); fi; }

echo "REBOOT SURVIVAL VERIFY — $LABEL"
# 1. LaunchAgent auto-loaded + a running PID (RunAtLoad brought it back with no manual start)
PID=$(launchctl list | awk -v l=$LABEL '$3==l{print $1}')
ck "$([ -n "$PID" ] && [ "$PID" != "-" ] && echo 1 || echo 0)" "LaunchAgent auto-loaded + running (PID ${PID:-none})"
# 2. stable checkout intact + correct SHA
RSHA=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null)
ck "$([ -n "$RSHA" ] && [ "$RSHA" = "$EXPECT_SHA" ] && echo 1 || echo 0)" "stable checkout at expected SHA ($RSHA == $EXPECT_SHA)"
# 3. Keychain worker credential survived
security find-generic-password -s "$KEYCHAIN_SVC" -a SESSION_SIGNING_SECRET >/dev/null 2>&1
ck "$([ $? -eq 0 ] && echo 1 || echo 0)" "Keychain worker secret present ($KEYCHAIN_SVC)"
# 4-7. server view: worker online + fresh heartbeat + right identity + NO invented/queued jobs.
#     Mint an owner cookie locally from the Keychain secret (never printed) and query read-only.
python3 - "$REPO" "$BASE_URL" "$KEYCHAIN_SVC" <<'PY'
import json, subprocess, sys, urllib.request, urllib.error
repo, base, svc = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo)
def out(ok, msg): print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")
try:
    secret = subprocess.run(["security","find-generic-password","-s",svc,"-a","SESSION_SIGNING_SECRET","-w"],
                            capture_output=True, text=True, timeout=5).stdout.strip()
    from core.operator_session import mint_session, ROLE_OWNER
    cookie = "wv_session=" + mint_session(ROLE_OWNER, secret=secret)
    def get(path):
        req = urllib.request.Request(base+path, headers={"Cookie": cookie})
        with urllib.request.urlopen(req, timeout=30) as r: return json.loads(r.read() or b"{}")
    st = get("/admin/holding/status")
    workers = st if isinstance(st, list) else st.get("workers", [])
    me = next((w for w in workers if w.get("worker_id")=="macmini-a2-01"), None)
    out(bool(me and me.get("online")), f"worker macmini-a2-01 ONLINE (heartbeat {me.get('last_heartbeat_secs_ago') if me else '?'}s ago)")
    out(bool(me and me.get("last_heartbeat_secs_ago",999) < 120), "heartbeat is FRESH (<120s)")
    dupes = [w for w in workers if w.get("worker_id")=="macmini-a2-01"]
    out(len(dupes)==1, f"exactly ONE worker identity (no duplicate) — found {len(dupes)}")
    jobs = get("/admin/holding/worker-jobs").get("jobs", [])
    active = [j for j in jobs if j.get("status") in ("queued","running")]
    out(len(active)==0, f"NO invented/replayed jobs (queued/running = {len(active)})")
except Exception as e:
    out(False, f"server-side verify failed: {str(e)[:120]}")
PY
echo
echo "NOTE: A2 + self-improvement authority are SERVER-side brakes (App B), unaffected by a worker reboot."
echo "      Confirm they are still OFF in Railway → kai-staging-appb → Variables if desired."
echo "SUMMARY: $pass local checks passed, $fail failed (plus the 5 server checks above)."
[ "$fail" -eq 0 ] && echo "LOCAL: PASS" || echo "LOCAL: FAIL"
