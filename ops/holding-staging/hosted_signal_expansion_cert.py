"""DETECTION SIGNAL EXPANSION certification (local, pure) — REPEATED_JOB_FAILURE + CAPABILITY_HEALTH.

Certifies the two new read-only signal sources and their integration into the EXISTING DETECT_ONLY pipeline:
threshold/root-dedup/window/exclusions (§8), capability transitions/transient-filter/classification (§15),
provenance (§19), fixture-not-reclassified (§18), default-OFF (§16/§17), and the zero-write invariant (§20).

    python3 ops/holding-staging/hosted_signal_expansion_cert.py
"""
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "backend"))

from app.services.holding.self_improvement_signals import (detect_repeated_job_failures,   # noqa: E402
    detect_capability_degradation, classify_degradation)
from app.services.holding.self_improvement_detect import run_detection, InMemoryDetectionStore   # noqa: E402

N = "2026-09-03T12:00:00"
res = []
def ck(n, ok, d=""):
    res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def jf(jid, cap, state="BLOCKED", status="failed", created=N, company="wheellsverse", worker="coding",
       reason="", error=""):
    ev = {"state": state}
    if reason:
        ev["reason"] = reason
    if error:
        ev["error"] = error
    return {"id": jid, "status": status, "created_at": created, "worker": worker,
            "task": {"company_id": company, "capability": cap}, "evidence": ev}


print("SIGNAL EXPANSION CERT (local, pure)")

print("STEP 1 — REPEATED_JOB_FAILURE threshold + root dedup (§3/§8)")
ck("1 failure -> 0", detect_repeated_job_failures([jf(1, "c", "BLOCKED")], now_iso=N) == [])
ck("2 failures -> 0", len(detect_repeated_job_failures([jf(1, "c", "BLOCKED"), jf(2, "c", "BLOCKED")], now_iso=N)) == 0)
r3 = detect_repeated_job_failures([jf(i, "c", "BLOCKED") for i in range(3)], now_iso=N)
ck("3 same-root -> 1 candidate", len(r3) == 1 and r3[0].evidence["failure_count"] == 3)
ck("candidate is REPEATED_JOB_FAILURE / NATURAL / confirmed", r3[0].signal_type == "REPEATED_JOB_FAILURE"
   and r3[0].source == "NATURAL" and r3[0].confirmed)
ck("3 different roots -> 0 combined", detect_repeated_job_failures([jf(1, "a", "BLOCKED"), jf(2, "b", "BLOCKED"), jf(3, "c", "BLOCKED")], now_iso=N) == [])

print("STEP 2 — ROOT NORMALIZATION: retries/timestamps collapse to ONE root (§4)")
retries = [jf(1, "c", "BLOCKED", created="2026-09-03T09:00:00"),
           jf(2, "c", "BLOCKED", created="2026-09-03T10:30:00"),
           jf(3, "c", "BLOCKED", created="2026-09-03T11:45:00")]
rr = detect_repeated_job_failures(retries, now_iso=N)
ck("same root across different timestamps -> 1 candidate, count 3", len(rr) == 1 and rr[0].evidence["failure_count"] == 3)

print("STEP 3 — NON-DEFECT EXCLUSIONS (§5): operational failures are NOT self-improvement candidates")
# structured (authoritative) operational states/decisions
for label, state in [("owner-required", "OWNER_REQUIRED"), ("no material change", "NO_MATERIAL_CHANGE")]:
    ck(f"3x {label} (structured) -> 0 candidates", detect_repeated_job_failures([jf(i, "c", state=state) for i in range(3)], now_iso=N) == [])
# free-text operational reasons (best-effort, fail-safe soft exclusion)
for label, reason in [("credential", "AUTH_PENDING: missing token, 401"), ("external outage", "provider 503 outage"),
                      ("deployment stale", "deployment_behind stale")]:
    got = detect_repeated_job_failures([jf(i, "c", state="BLOCKED", reason=reason) for i in range(3)], now_iso=N)
    ck(f"3x {label} (free-text reason) -> 0 candidates", got == [])

print("STEP 4 — TIME WINDOW (§3): out-of-window failures excluded")
old = [jf(i, "c", "BLOCKED", created="2026-09-01T00:00:00") for i in range(3)]
ck("3 failures 2 days ago -> 0 (24h window)", detect_repeated_job_failures(old, now_iso=N) == [])

print("STEP 5 — CAPABILITY_HEALTH transitions + transient filter (§9/§10/§15)")
ck("healthy -> 0", detect_capability_degradation({"x": {"state": "READY"}}, {}, now_iso=N) == ([], []))
ck("single transient degraded -> 0 (suppressed)",
   detect_capability_degradation({"x": {"state": "DEGRADED"}}, {"x": {"state": "READY"}}, now_iso=N) == ([], []))
cands, ops = detect_capability_degradation({"x": {"state": "DEGRADED", "certified": True, "classification": "LOCAL_RUNTIME_DEFECT", "reason": "TypeError in handler"}},
                                           {"x": {"state": "DEGRADED"}}, now_iso=N)
ck("persistent internal degraded (2 checks, positive evidence) -> 1 candidate", len(cands) == 1 and cands[0].signal_type == "CAPABILITY_HEALTH_DEGRADATION")
ck("certification regression tracked separately", cands[0].evidence.get("certification_regression") is True and cands[0].evidence.get("runtime_health") == "DEGRADED")

print("STEP 6 — CAPABILITY classification (§11): credential/external are operational, not self-code")
ck("AUTH_PENDING -> CREDENTIAL_BLOCKER", classify_degradation("OFFLINE", "AUTH_PENDING: no token") == "CREDENTIAL_BLOCKER")
ck("provider outage -> EXTERNAL_PROVIDER_OUTAGE", classify_degradation("FAILED", "provider 503 outage") == "EXTERNAL_PROVIDER_OUTAGE")
cc, oo = detect_capability_degradation({"y": {"state": "OFFLINE", "reason": "AUTH_PENDING"}}, {"y": {"state": "OFFLINE"}}, now_iso=N)
ck("credential blocker -> 0 candidate, 1 operational blocker", cc == [] and len(oo) == 1 and oo[0]["classification"] == "CREDENTIAL_BLOCKER")

print("STEP 7 — FALLBACK (§13): primary degraded + fallback used -> one record, no duplicate")
fc, fo = detect_capability_degradation({"p": {"state": "DEGRADED", "certified": True, "fallback_used": "codex", "classification": "LOCAL_RUNTIME_DEFECT", "reason": "AttributeError in primary adapter"}},
                                       {"p": {"state": "DEGRADED"}}, now_iso=N)
ck("one candidate records fallback_used", len(fc) == 1 and fc[0].evidence.get("fallback_used") == "codex")

print("STEP 8 — INTEGRATION into DETECT_ONLY: gated ON merges signals; provenance; fixture not reclassified")
def suite_fixture_fails(sid):
    return ({"execution": "COMPLETED", "test_result": "FAILED", "passed": 6, "failed": 1, "commit_sha": "x"}
            if sid == "si_before_after" else {"execution": "COMPLETED", "test_result": "PASSED", "passed": 7, "failed": 0})
jobs3 = [jf(i, "c", "BLOCKED") for i in range(3)]
r = run_detection(run_suite_fn=suite_fixture_fails, store=InMemoryDetectionStore(), now=N, detect_on=True, prepare_on=False,
                  sig_repeated_on=True, sig_health_on=False, jobs_fn=lambda: jobs3, deliver_fn=lambda m: None)
sigs = {c["signature"]: c for c in r["candidates"]}
ck("merged: fixture + repeated-job both present", "failing_suite:si_before_after" in sigs and any(s.startswith("jobfail:") for s in sigs))
ck("fixture stays CERTIFICATION_FIXTURE (not reclassified)", sigs["failing_suite:si_before_after"]["source"] == "CERTIFICATION_FIXTURE")
ck("repeated-job is NATURAL", [c for s, c in sigs.items() if s.startswith("jobfail:")][0]["source"] == "NATURAL")
ck("prepared=0 even with signals on (§20 zero-write)", r["prepared"] == 0)

print("STEP 9 — DEFAULT OFF (§16/§17): gates off -> only the base suite detection (soak behavior unchanged)")
r_off = run_detection(run_suite_fn=suite_fixture_fails, store=InMemoryDetectionStore(), now=N, detect_on=True, prepare_on=False,
                      sig_repeated_on=False, sig_health_on=False, jobs_fn=lambda: jobs3, deliver_fn=lambda m: None)
ck("signals off -> no jobfail candidate", not any(c["signature"].startswith("jobfail:") for c in r_off["candidates"]))

print("STEP 10 — STRUCTURAL NO-WRITE (§20): the signals module imports no write/dispatch path")
src = open(os.path.join(REPO, "backend/app/services/holding/self_improvement_signals.py")).read()
for tok in ("dispatch_self_improvement", "enqueue_a2_coding_job", "a2_dispatch", "a2_wiring", "make_git_worktree", "coding-cli"):
    ck(f"no write path '{tok}'", tok not in src)

print("STEP 11 — ADVERSARIAL FIXES (A3/A4/A7/A8) closed")
# A3 scatter: same structured fields but DIFFERENT free-text errors -> ONE root (identity is structured only)
scatter = [jf(1, "c", state="BLOCKED", error="timeout waiting"), jf(2, "c", state="BLOCKED", error="unexpected error X"),
           jf(3, "c", state="BLOCKED", error="weird glitch Z")]
rs = detect_repeated_job_failures(scatter, now_iso=N)
ck("A3: varied free-text error cannot scatter one defect -> 1 candidate", len(rs) == 1 and rs[0].evidence["failure_count"] == 3)
# A3 over-broad: a genuine BLOCKED failure with benign text (no exclusion token) stays eligible
ck("A3: benign-text real failures still detected", len(detect_repeated_job_failures([jf(i, "c", state="BLOCKED", error="row mismatch") for i in range(3)], now_iso=N)) == 1)
# A4: different companies never aggregate; same company groups; absent company never merges
diffco = [jf(1, "gh", worker="github", company="nurtelle"), jf(2, "gh", worker="github", company="sol"),
          jf(3, "gh", worker="github", company="nexora")]
ck("A4: 3 github failures across 3 companies -> 0 combined", detect_repeated_job_failures(diffco, now_iso=N) == [])
sameco = [jf(i, "gh", worker="github", company="sol") for i in range(3)]
ck("A4: 3 github failures for ONE company -> 1 candidate", len(detect_repeated_job_failures(sameco, now_iso=N)) == 1)
absent = [{"id": i, "status": "failed", "created_at": N, "worker": "github", "task": {"repo": "r"}, "evidence": {"state": "BLOCKED"}} for i in range(3)]
ck("A4: absent company_id -> per-job sentinel, 0 false merge", detect_repeated_job_failures(absent, now_iso=N) == [])
# A7/A8: unrecognized + external reasons never become self-code candidates
uk, uko = detect_capability_degradation({"q": {"state": "FAILED", "reason": "mysterious wobble"}}, {"q": {"state": "FAILED"}}, now_iso=N)
ck("A7/A8: unrecognized degradation -> UNKNOWN operational, 0 candidate", uk == [] and uko[0]["classification"] == "UNKNOWN")
ex, exo = detect_capability_degradation({"w": {"state": "OFFLINE", "reason": "502 bad gateway upstream"}}, {"w": {"state": "OFFLINE"}}, now_iso=N)
ck("A8: 502 upstream -> EXTERNAL_PROVIDER_OUTAGE, 0 candidate", ex == [] and exo[0]["classification"] == "EXTERNAL_PROVIDER_OUTAGE")
# re-attack killers: EXCEPTION TEXT alone (no structured classification) never becomes a self-code candidate
for cid, reason, expect in [("k", "KeyError: 'OPENAI_API_KEY'", "CREDENTIAL_BLOCKER"),        # credential-as-exception
                            ("d", "InternalError: current transaction is aborted", "EXTERNAL_PROVIDER_OUTAGE"),  # DB failover
                            ("g", "Internal error encountered.", "UNKNOWN"),                   # provider 500 body, no code
                            ("a", "AttributeError: 'NoneType' object has no attribute 'encode'", "UNKNOWN")]:
    c, o = detect_capability_degradation({cid: {"state": "FAILED", "reason": reason}}, {cid: {"state": "FAILED"}}, now_iso=N)
    ck(f"A7/A8: exception text '{reason[:28]}...' -> {expect}, 0 self-code candidate", c == [] and o and o[0]["classification"] == expect)
# only a TRUSTED structured classification blames KAI code
tc, to = detect_capability_degradation({"z": {"state": "FAILED", "classification": "LOCAL_RUNTIME_DEFECT", "reason": "anything"}}, {"z": {"state": "FAILED"}}, now_iso=N)
ck("LOCAL_RUNTIME_DEFECT requires trusted structured classification -> 1 candidate", len(tc) == 1)

n = len(res); ok = sum(res)
print(f"\nSIGNAL EXPANSION CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
sys.exit(0 if ok == n else 1)
