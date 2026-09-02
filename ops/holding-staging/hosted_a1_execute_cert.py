"""Hosted A1 (COMPUTE_ONLY) certification for RUN_INTERNAL_TEST — pure/python3, real subprocess.

The first A1 autonomy rung: KAI verifies work itself under the real runtime. A1 = internal computation
(run a certified test suite); it does NOT modify source. This certifies the whole chain end to end:
authoritative condition (deployment change) -> plan emits RUN_INTERNAL_TEST -> deterministic resolver
-> holding.internal_test -> server-owned suite -> REAL execution -> normalized evidence -> COMPLETE,
plus every A1 safety property. Run on the staging box:

    railway run --service kai-staging-appb python3 ops/holding-staging/hosted_a1_execute_cert.py
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))

from app.services.holding.autonomous_work import (  # noqa: E402
    run_cycle, HoldingAutonomousWorkEngine, EXECUTED, OWNER_QUEUED, BLOCKED_CAPABILITY)
from app.services.holding.holding_cycle import build_live_engine  # noqa: E402
from app.services.holding.manual_cycle import run_manual_cycle, InMemoryCycleStore  # noqa: E402
from app.services.holding.task_resolver import (  # noqa: E402
    TaskCapabilityResolver, make_engine_resolver, build_holding_executor, _MAPPINGS)
from app.services.holding.plan import PlanTask, AutonomyClass, Assignee  # noqa: E402
from app.services.holding.internal_test import (  # noqa: E402
    make_internal_test_provider, resolve_suite, TestDenied, SuiteDef, _BACKEND)
from app.services.capability.manifest import ActionClass  # noqa: E402

res = []
def ck(n, ok, d=""):
    res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def snap(dep="sha-abc"):
    return {"companies": [{"company_id": "sol", "status": "OK", "active_incidents": [],
            "owner_actions_required": [], "deployments": [dep]}],
            "shared_resources": {"workers_online": 1, "capabilities_available": 7},
            "autonomy_overall": "AUTONOMOUS_READ_ONLY"}


# server-owned cert suites (registered here, NEVER client-supplied) exercising failure/limits/output
CERT_SUITES = {
    "cert_fail":    SuiteDef("cert_fail", ("python3", "-c", "print('1 failed'); import sys; sys.exit(1)"), _BACKEND),
    "cert_timeout": SuiteDef("cert_timeout", ("python3", "-c", "import time; time.sleep(5)"), _BACKEND, timeout=1),
    "cert_secret":  SuiteDef("cert_secret", ("python3", "-c", "print('leak sk-abcdefghijklmnop1234 password=hunter2')"), _BACKEND),
    "cert_huge":    SuiteDef("cert_huge", ("python3", "-c", "print('x'*200000)"), _BACKEND),
    "cert_company": SuiteDef("cert_company", ("python3", "-c", "pass"), _BACKEND, company_id="other-co"),
    "cert_disabled":SuiteDef("cert_disabled", ("python3", "-c", "pass"), _BACKEND, enabled=False),
}
cert_prov = make_internal_test_provider(suites=CERT_SUITES)   # REAL subprocess runner over cert suites


def counting_engine(*, global_autonomy=True):
    """Engine whose internal-test runtime counts real invocations (deterministic, no subprocess)."""
    calls = {"n": 0}
    def run_fn(cmd, **kw):
        calls["n"] += 1
        r = type("R", (), {})(); r.returncode = 0; r.stdout = "1 passed"; r.stderr = ""; return r
    ex = build_holding_executor(providers={"holding.internal_test": make_internal_test_provider(run_fn=run_fn)})
    eng = HoldingAutonomousWorkEngine(execute=ex, resolver=make_engine_resolver(TaskCapabilityResolver()),
                                      global_autonomy=global_autonomy)
    return eng, calls


print("A1 HOSTED CERT — RUN_INTERNAL_TEST (COMPUTE_ONLY)")

try:
    from app.config import settings
    B1 = bool(getattr(settings, "KAI_CAPABILITY_EXECUTION_ENABLED", False))
    B2 = bool(getattr(settings, "HOLDING_AUTONOMY_ENABLED", False))
except Exception:
    B1 = B2 = None
print(f"  brake#1 KAI_CAPABILITY_EXECUTION_ENABLED = {B1} ; brake#2 HOLDING_AUTONOMY_ENABLED = {B2}")

print("STEP 1 — A1 EXECUTE CHAIN: a deploy change -> plan emits RUN_INTERNAL_TEST -> real suite -> COMPLETE")
ck("both brakes lifted (required to certify A1 execute)", B1 is True and B2 is True,
   "live config permits A1 execution" if (B1 and B2) else f"brake#1={B1} brake#2={B2} — run on the staging box")
eng = build_live_engine()   # real deployed brakes + real subprocess runtime
r1 = run_cycle(snap("sha-abc"), snap("sha-def"), engine=eng, cycle_id="a1", now="t")
ck("material change -> exactly one A1 action executed", r1["auto_executed"] == 1 and r1["owner_queued"] == 0,
   f"executed={r1['auto_executed']}")
w = (r1["results"] or [{}])[0]
ck("outcome EXECUTED + COMPLETE via holding.internal_test/run_suite",
   w.get("outcome") == EXECUTED and w.get("task_status") == "COMPLETE"
   and w.get("capability_id") == "holding.internal_test" and w.get("operation") == "run_suite")
ck("executed task is A1 (COMPUTE_ONLY, not a write)", w.get("autonomy") == int(AutonomyClass.A1_INTERNAL_SAFE))
# real evidence with all §17 fields
ev = build_holding_executor()("holding.internal_test", "run_suite",
                              {"suite_id": "holding_self_model", "company_id": "sol"}, mission_id="m").evidence
need = ("suite", "execution", "test_result", "commit_sha", "tests_discovered", "passed", "failed",
        "skipped", "exit_status", "duration_s")
ck("evidence carries all required fields", all(k in ev for k in need), str([k for k in need if k not in ev]))
ck("real execution: COMPLETED + PASSED + real counts", ev["execution"] == "COMPLETED"
   and ev["test_result"] == "PASSED" and ev["passed"] >= 1 and ev["exit_status"] == 0)
ck("real commit SHA in evidence (not UNAVAILABLE placeholder)", len(str(ev.get("commit_sha", ""))) >= 7
   and ev["commit_sha"] != "UNAVAILABLE")

print("STEP 2 — TEST FAILURE IS NOT ENGINE FAILURE (§32): a failing suite -> COMPLETED / FAILED, not CAPABILITY_FAILURE")
fail_ev = cert_prov({"suite_id": "cert_fail", "company_id": "sol"})
ck("failing suite -> execution COMPLETED, test_result FAILED", fail_ev["execution"] == "COMPLETED"
   and fail_ev["test_result"] == "FAILED" and fail_ev["exit_status"] != 0)
# fed to the engine's executor, a FAILED test is still a verified EXECUTED capability (evidence present, status OK)
fex = build_holding_executor(providers={"holding.internal_test": cert_prov})
fr = fex("holding.internal_test", "run_suite", {"suite_id": "cert_fail"}, mission_id="m")
ck("engine sees a FAILED test as OK+evidence (EXECUTED, not a capability failure)",
   fr.status == "OK" and bool(fr.evidence))

print("STEP 2b — TIMEOUT IS NOT A VERIFIED COMPLETION (§22, adversarial F1): a suite that did not complete")
# a suite TIMEOUT carries honest evidence but omits the pass/fail result -> the engine must NOT mark it
# EXECUTED/COMPLETE/verified (a deployment-verify that never finished is not a green check).
timeout_prov = lambda a: {"suite": a.get("suite_id"), "execution": "TIMEOUT", "test_result": "UNAVAILABLE",
                          "exit_status": None, "duration_s": 1.0}
teng = HoldingAutonomousWorkEngine(
    execute=build_holding_executor(providers={"holding.internal_test": timeout_prov}),
    resolver=make_engine_resolver(TaskCapabilityResolver()), global_autonomy=True)
tr = teng.run_task(PlanTask(task_id="to", company_id="sol", goal="g", reason="r", source_key="to",
     task_type="RUN_INTERNAL_TEST", autonomy=int(AutonomyClass.A1_INTERNAL_SAFE)))
ck("a timed-out suite is NOT verified/COMPLETE (evidence-required-for-COMPLETE holds)",
   tr.outcome != EXECUTED and tr.verified is False and tr.task_status != "COMPLETE", f"{tr.outcome}/{tr.verified}")

print("STEP 3 — NO ARBITRARY SHELL (§19): only a server-owned suite_id ever reaches execution")
rct = TaskCapabilityResolver().resolve(PlanTask(task_id="d", company_id="sol", goal="g", reason="r",
      source_key="d", task_type="RUN_INTERNAL_TEST", autonomy=int(AutonomyClass.A1_INTERNAL_SAFE)))
ck("resolver hands ONLY {suite_id, company_id} — no command/shell/cwd/env/args",
   rct is not None and set(rct.arguments) == {"suite_id", "company_id"}, str(rct.arguments if rct else None))
for bad in ("command", "shell", "cwd", "env", "args", "argv", "entrypoint"):
    try:
        cert_prov({"suite_id": "cert_fail", bad: "rm -rf /"}); ck(f"forbidden key '{bad}' denied", False)
    except TestDenied:
        ck(f"forbidden key '{bad}' denied before execution", True)
for evil in ("../../etc/passwd", "a; rm -rf /", "$(whoami)", "holding_self_model && cat /etc/passwd"):
    try:
        resolve_suite(evil); ck(f"suite_id '{evil[:16]}' denied", False)
    except TestDenied:
        ck(f"suite_id traversal/shell '{evil[:16]}' denied", True)
try:
    resolve_suite("cert_disabled", suites=CERT_SUITES); ck("disabled suite denied", False)
except TestDenied:
    ck("disabled suite denied", True)
try:
    resolve_suite("cert_company", company_id="sol", suites=CERT_SUITES); ck("cross-company suite denied", False)
except TestDenied:
    ck("cross-company suite denied", True)
# unknown suite -> the executor fails CLOSED to CAPABILITY_UNAVAILABLE (runner failure, not a silent pass)
ue = build_holding_executor(providers={"holding.internal_test": cert_prov})("holding.internal_test",
     "run_suite", {"suite_id": "does_not_exist"}, mission_id="m")
ck("unknown suite -> CAPABILITY_UNAVAILABLE (fail closed)", ue.status == "CAPABILITY_UNAVAILABLE")

print("STEP 4 — IDEMPOTENCY (§20): same task+suite+SHA under replay -> no duplicate execution")
eng_c, calls = counting_engine()
store = InMemoryCycleStore()
run_manual_cycle(store, eng_c, lambda: snap("sha-abc"), now="t1")                       # baseline
run_manual_cycle(store, eng_c, lambda: snap("sha-def"), now="t2", idempotency_key="K")  # deploy change -> 1 run
run_manual_cycle(store, eng_c, lambda: snap("sha-def"), now="t3", idempotency_key="K")  # replay -> no run
ck("idempotent replay ran the suite exactly once", calls["n"] == 1, f"runs={calls['n']}")

print("STEP 5 — BRAKES (§21): autonomy off -> no A1 auto-run; capability off -> blocked")
eng_off, calls_off = counting_engine(global_autonomy=False)
r_off = run_cycle(snap("sha-abc"), snap("sha-def"), engine=eng_off, cycle_id="b2", now="t")
ck("autonomy OFF -> A1 task not executed, subprocess NOT invoked", r_off["auto_executed"] == 0 and calls_off["n"] == 0)
eng_nocap = build_live_engine(autonomy_on=True, execution_on=False)
r_nocap = run_cycle(snap("sha-abc"), snap("sha-def"), engine=eng_nocap, cycle_id="b1", now="t")
ck("capability execution OFF -> blocked, 0 executed", r_nocap["auto_executed"] == 0 and r_nocap["blocked"] >= 1)

print("STEP 6 — RESOURCE LIMITS (§22): timeout + output ceiling enforced by the server-owned runner")
to = cert_prov({"suite_id": "cert_timeout"})
ck("a suite over its timeout -> execution TIMEOUT (bounded, not hung)", to["execution"] == "TIMEOUT")
huge = cert_prov({"suite_id": "cert_huge"})
ck("huge output is bounded (output_ref <= 2000 chars)", len(str(huge.get("output_ref", ""))) <= 2000,
   f"len={len(str(huge.get('output_ref','')))}")

print("STEP 7 — MALICIOUS OUTPUT (§23): secret-like output is redacted before it leaves the runtime")
sec = cert_prov({"suite_id": "cert_secret"})
blob = str(sec)
ck("token-like + password in test output are REDACTED", "sk-abcdefghijklmnop1234" not in blob
   and "hunter2" not in blob and "[REDACTED]" in blob)

print("STEP 8 — OWNER FILTERING (§24): a successful A1 verification creates 0 owner work")
ck("successful A1 cycle -> owner_queued 0 (KAI verified it, owner not asked to)", r1["owner_queued"] == 0)

print("STEP 9 — QUIET LOOP (§25): after the A1 test, an unchanged cycle does 0 work")
eng_q, calls_q = counting_engine()
run_cycle(snap("sha-abc"), snap("sha-def"), engine=eng_q, cycle_id="q1", now="t")   # 1 run
q2 = run_cycle(snap("sha-def"), snap("sha-def"), engine=eng_q, cycle_id="q2", now="t")  # identical -> 0
ck("quiet follow-up: 0 executed, no duplicate test run", q2["auto_executed"] == 0 and calls_q["n"] == 1)

print("STEP 10 — CLASS: RUN_INTERNAL_TEST is READ_ONLY (COMPUTE_ONLY) — no write/source-modification path")
ck("mapping action_class is READ_ONLY", _MAPPINGS["RUN_INTERNAL_TEST"].action_class == ActionClass.READ_ONLY)

n = len(res); ok = sum(res)
print(f"\nA1 HOSTED CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
sys.exit(0 if ok == n else 1)
