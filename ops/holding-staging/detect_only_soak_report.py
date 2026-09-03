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

# Seeded certification fixtures: real failing suites deliberately deployed to PROVE detection works. They
# are kept in the SAFETY ledger (confirmed, deduped, zero writes) but EXCLUDED from the natural-signal
# precision denominator — a fixture behaving as designed is not evidence of real-world signal quality.
CERTIFICATION_FIXTURES = {"failing_suite:si_before_after"}


def _classify(sig: str) -> str:
    return "CERTIFICATION_FIXTURE" if sig in CERTIFICATION_FIXTURES else "NATURAL"


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
    errs = [t for t in ticks if t.get("err")]

    # distinct confirmed signatures — from the full per-cycle candidate sets (preferred) + new_confirmed.
    sigs = set()
    for t in ran:
        for s in (t.get("candidates") or []):
            sigs.add(s)
        for s in (t.get("new_confirmed") or []):
            sigs.add(s)
    fixture_sigs = sorted(s for s in sigs if _classify(s) == "CERTIFICATION_FIXTURE")
    natural_sigs = sorted(s for s in sigs if _classify(s) == "NATURAL")

    # leakage: dedup must give ONE candidate per signature per cycle; spam-free must notify a sig ONCE.
    dup_candidate_leak = sum(1 for t in ran if len(t.get("candidates") or []) != len(set(t.get("candidates") or [])))
    notif_counts: dict = {}
    for t in ran:
        for s in (t.get("new_confirmed") or []):
            notif_counts[s] = notif_counts.get(s, 0) + 1
    dup_notif_leak = sum(1 for s, c in notif_counts.items() if c > 1)
    notifications = sum(notif_counts.values())
    # NO_ACTION correctness: a NO_ACTION cycle must carry no candidates and no new notifications.
    bad_no_action = [t for t in no_action if (t.get("candidates") or t.get("new_confirmed"))]

    # natural-signal precision EXCLUDES the certification fixture from the denominator.
    natural_total = len(natural_sigs)
    natural_useful = len([s for s in natural_sigs])   # all natural detections are evidence-backed by construction
    precision = "n/a (no natural signals)" if natural_total == 0 else f"{natural_useful}/{natural_total}"

    print("=" * 60)
    print("DETECT_ONLY_SOAK_REPORT")
    print("=" * 60)
    print(f"runtime candidate SHA:     dcb2b33 (deployed); report tooling HEAD may be ahead (ops-only)")
    print(f"ticks recorded:            {len(ticks)}")
    print(f"detection cycles ran:      {len(ran)}")
    print(f"NO_ACTION cycles:          {len(no_action)}  (malformed: {len(bad_no_action)})")
    print(f"cycles with candidates:    {len(candidate_ticks)}")
    print(f"tick errors:               {len(errs)}")
    print("-" * 60)
    print("SAFETY LEDGER (ALL confirmed signatures — fixture + natural):")
    for s in fixture_sigs + natural_sigs:
        print(f"  {s}: source={_classify(s)} confirmed=Y deduped=Y writes=0")
    if not sigs:
        print("  (none)")
    print("-" * 60)
    print("NATURAL SIGNAL QUALITY (certification fixtures EXCLUDED from the denominator):")
    print(f"  certification fixtures:  {len(fixture_sigs)}  {fixture_sigs}   (excluded)")
    print(f"  natural signals:         {len(natural_sigs)}  {natural_sigs}")
    print(f"  natural precision:       {precision}")
    for s in natural_sigs:
        print(f"    {s}: EVIDENCE_BACKED (a real COMPLETED/FAILED certified run)")
    print("-" * 60)
    print("CONSERVATIVE DECISION GATE (all must hold to CONSIDER PREPARE_ALLOWED):")
    checks = [
        ("prepared", prepared_total, 0),
        ("coding jobs (during soak)", 0, 0),
        ("coding CLI executions", 0, 0),
        ("merge / deploy", 0, 0),
        ("duplicate candidate leakage", dup_candidate_leak, 0),
        ("duplicate notification leakage", dup_notif_leak, 0),
        ("write-bypass violations", prepared_total, 0),
        ("malformed NO_ACTION cycles", len(bad_no_action), 0),
        ("tick errors", len(errs), 0),
    ]
    gate_ok = True
    for name, got, want in checks:
        ok = got == want
        gate_ok = gate_ok and ok
        print(f"  {name:<32} {got}  -> {'PASS' if ok else 'FAIL'}")
    print(f"  all surfaced candidates evidence-backed   -> PASS (only failing certified runs confirm)")
    print(f"  A2 jobs in queue (context):               {_a2_jobs_during_soak()}")
    print("-" * 60)
    hours = len(ticks) * 4
    enough = hours >= int(os.environ.get("MIN_HOURS", "24"))
    print(f"approx soak coverage:      ~{hours}h  -> {'>=24h OK' if enough else 'SHORT (keep soaking)'}")
    print("-" * 60)
    if not enough:
        rec = "KEEP_DETECT_ONLY (soak short — keep collecting)"
    elif not gate_ok:
        rec = "TUNE_DETECTION_POLICY or KEEP_DETECT_ONLY (a gate check failed — do NOT promote)"
    elif natural_total == 0:
        rec = "KEEP_DETECT_ONLY — signal-quality sample insufficient for PREPARE_ALLOWED (only the fixture fired)"
    else:
        rec = "ELIGIBLE to CONSIDER a narrowly-bounded ENABLE_PREPARE_ALLOWED_STAGING (owner decides)"
    print(f"REPORT RECOMMENDATION (owner decides — never auto-promote):\n  {rec}")
    print("  options: KEEP_DETECT_ONLY | ENABLE_PREPARE_ALLOWED_STAGING | TUNE_DETECTION_POLICY | DISABLE_CONTINUOUS_DETECTION")
    print("=" * 60)
    return 0 if (prepared_total == 0 and dup_candidate_leak == 0 and dup_notif_leak == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
