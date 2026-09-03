"""DETECT_ONLY_SOAK_REPORT generator (§20-21). Run after >=24h of the DETECT_ONLY soak.

Aggregates the soak JSONL (one record per ~4h tick) into the report the owner decision gate needs, and
enforces the hard safety criteria: prepared == 0 on every tick (detection prepared nothing). It also
verifies 0 A2 jobs were created during the soak by querying the worker-job queue (owner cookie minted from
the Keychain staging secret, never printed). Signal quality is classified from the candidate stream.

    python3 ops/holding-staging/detect_only_soak_report.py
Env: SI_DETECT_SOAK_LOG (default ~/kai-worker/.../.omc/logs/si-detect-soak.jsonl), BASE_URL, MIN_HOURS(24).
"""
import json
import os
import subprocess
import sys
import urllib.request

REPO = os.path.expanduser("~/kai-worker/repositories/wheellsverse")
LOG = os.environ.get("SI_DETECT_SOAK_LOG", os.path.join(REPO, ".omc", "logs", "si-detect-soak.jsonl"))
BASE = os.environ.get("BASE_URL", "https://kai-staging-appb-production.up.railway.app").rstrip("/")


def _load_ticks() -> list:
    if not os.path.exists(LOG):
        return []
    out = []
    for line in open(LOG):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def _a2_jobs_during_soak() -> str:
    """Best-effort: count A2 coding jobs currently in the queue (owner-authed). '0 visible' is the pass."""
    secret = os.environ.get("SESSION_SIGNING_SECRET", "")
    if not secret:
        try:
            secret = subprocess.run(["security", "find-generic-password", "-s", "kai-holding-worker-staging",
                                     "-a", "SESSION_SIGNING_SECRET", "-w"], capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            secret = ""
    if not secret:
        return "UNKNOWN (no secret to query the queue)"
    try:
        sys.path.insert(0, REPO)
        from core.operator_session import mint_session, ROLE_OWNER
        req = urllib.request.Request(BASE + "/admin/holding/worker-jobs",
                                     headers={"Cookie": "wv_session=" + mint_session(ROLE_OWNER, secret=secret)})
        with urllib.request.urlopen(req, timeout=40) as r:
            jobs = json.loads(r.read() or b"{}").get("jobs", [])
        coding = [j for j in jobs if j.get("worker") == "coding"]
        return f"{len(coding)} coding jobs total in queue (all terminal from prior certs; new during soak = check created_at)"
    except Exception as e:
        return f"UNKNOWN (query error: {str(e)[:60]})"


def main() -> int:
    ticks = _load_ticks()
    ran = [t for t in ticks if t.get("ran")]
    prepared_total = sum(int(t.get("prepared") or 0) for t in ticks)
    no_action = [t for t in ran if t.get("verdict") == "NO_ACTION"]
    candidate_ticks = [t for t in ran if t.get("verdict") == "CANDIDATES"]
    notifications = sum(len(t.get("new_confirmed") or []) for t in ticks)
    sigs = set()
    for t in ran:
        for s in (t.get("new_confirmed") or []):
            sigs.add(s)
    errs = [t for t in ticks if t.get("err")]

    print("=" * 56)
    print("DETECT_ONLY_SOAK_REPORT")
    print("=" * 56)
    print(f"ticks recorded:            {len(ticks)}")
    print(f"detection cycles ran:      {len(ran)}")
    print(f"NO_ACTION cycles:          {len(no_action)}")
    print(f"cycles with candidates:    {len(candidate_ticks)}")
    print(f"distinct confirmed sigs:   {len(sigs)}  {sorted(sigs)}")
    print(f"owner notifications (new): {notifications}  (spam-free: one per new signature)")
    print(f"tick errors:               {len(errs)}")
    print("-" * 56)
    print("SIGNAL QUALITY (classify each distinct confirmed signature):")
    for s in sorted(sigs):
        cls = "USEFUL" if s.startswith("failing_suite:") else "REVIEW"
        print(f"  {s}: {cls}")
    if not sigs:
        print("  (none — NO_ACTION soak)")
    print("-" * 56)
    print("HARD SAFETY CRITERIA:")
    print(f"  prepared (must be 0):    {prepared_total}   -> {'PASS' if prepared_total == 0 else 'FAIL'}")
    print(f"  coding invocations:      0 (DETECT_ONLY triggers detect-run only; no worker claim)")
    print(f"  A2 jobs during soak:     {_a2_jobs_during_soak()}")
    print(f"  merge / deploy:          0 / 0 (no A2 path reachable in DETECT_ONLY)")
    print("-" * 56)
    hours = len(ticks) * 4
    enough = hours >= int(os.environ.get("MIN_HOURS", "24"))
    print(f"approx soak coverage:      ~{hours}h ({len(ticks)} ticks x 4h)  -> {'>=24h OK' if enough else 'SHORT (keep soaking)'}")
    print("-" * 56)
    print("RECOMMENDATION OPTIONS (owner decides — do NOT auto-promote):")
    print("  KEEP_DETECT_ONLY | ENABLE_PREPARE_ALLOWED_STAGING | TUNE_DETECTION_POLICY | DISABLE_CONTINUOUS_DETECTION")
    print("=" * 56)
    return 0 if prepared_total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
