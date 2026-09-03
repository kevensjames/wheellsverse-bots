"""Staging DETECT_ONLY soak tick — the STAGING scheduler for the existing detect cycle.

Prod drives the Holding cycle with a Railway cron; on staging this launchd StartInterval timer plays the
same role: every ~4h it triggers ONE read-only detection pass in App B by POSTing /admin/holding/detect-run
(owner cookie minted locally from the Keychain staging secret, never printed). Detection itself runs in
App B (where the DB lives) — this is just the trigger, not a second detection engine. Appends one JSON line
per tick to a soak log for the DETECT_ONLY_SOAK_REPORT. Report-only; it can never cause a write (the server
enforces DETECT_ONLY: prepare brakes off, prepared=0).
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)                                   # core.operator_session
BASE = os.environ.get("BASE_URL", "https://kai-staging-appb-production.up.railway.app").rstrip("/")
KEYCHAIN_SVC = os.environ.get("KAI_WORKER_KEYCHAIN_SVC", "kai-holding-worker-staging")
LOG = os.environ.get("SI_DETECT_SOAK_LOG", os.path.join(ROOT, ".omc", "logs", "si-detect-soak.jsonl"))


def _secret() -> str:
    s = os.environ.get("SESSION_SIGNING_SECRET", "")
    if s:
        return s
    try:
        return subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SVC,
                               "-a", "SESSION_SIGNING_SECRET", "-w"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def main() -> int:
    from core.operator_session import mint_session, ROLE_OWNER
    secret = _secret()
    if not secret:
        print("detect_tick: no secret (Keychain/env)"); return 2
    cookie = "wv_session=" + mint_session(ROLE_OWNER, secret=secret)
    req = urllib.request.Request(BASE + "/admin/holding/detect-run", data=b"{}", method="POST",
                                 headers={"Cookie": cookie, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        out = {"_http_error": e.code, "_body": e.read().decode()[:120]}
    except Exception as e:
        out = {"_error": str(e)[:120]}
    from datetime import datetime, timezone
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "ran": out.get("ran"), "mode": out.get("mode"), "verdict": out.get("verdict"),
           "confirmed": out.get("confirmed_count"),
           "candidates": [c.get("signature") for c in (out.get("candidates") or [])],   # full per-cycle set
           "new_confirmed": out.get("new_confirmed"),
           "prepared": out.get("prepared"), "err": out.get("_http_error") or out.get("_error")}
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print("detect_tick:", json.dumps(rec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
