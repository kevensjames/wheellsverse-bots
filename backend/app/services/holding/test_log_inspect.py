"""Tests for LOG_INSPECT (Part B, §16-25). Adversarial secret fixtures must yield 0 reproduction;
legit SHAs stay visible. Run: python3 backend/app/services/holding/test_log_inspect.py"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.log_inspect import (  # noqa: E402
    make_log_provider, LogDenied, build_request, MAX_LINES, LocalLogFileProvider, LogRequest)
from app.services.holding.task_resolver import REDACTED  # noqa: E402

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


_SHA = "a1b2c3d4e5f6071829304152637485960718293a"   # 40-hex, must stay visible
_SECRETS = [
    "ERROR loaded ghp_0123456789abcdefABCDEF0123456789abcd",
    "ERROR pat github_pat_11ABCDE0Yabcdefghij_KLMNOPqrstuvwxyz0123456789",
    "ERROR key sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJ",
    "ERROR svc sk-svcacct-abcdefghijklmnop0123456789",
    "ERROR slack xox" "b-1234567890-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx",
    "ERROR aws_secret_access_key=wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY",
    "ERROR auth Authorization: Bearer super.secret.jwt.token.value",
    "ERROR cookie Cookie: session=abcdef123456; other=1",
    "ERROR -----BEGIN PRIVATE KEY-----",
    "ERROR MIIEvQreallysecretkeymaterialhere",
    "ERROR -----END PRIVATE KEY-----",
    f"INFO deploy {_SHA} succeeded",
    "ERROR correlation-XYZ event failed hard",
    'ERROR auth ctx={"user":"bob","password":"Pa55w0rd-json-LEAK","client_secret":"cs_json_LEAK"}',
]


def _logfile():
    p = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False)
    p.write("\n".join(_SECRETS) + "\n")
    p.close()
    return p.name


def _factory(path=None):
    path = path or _logfile()
    return make_log_provider(sources={"kai": {"provider": "local-file", "path": path}})


def t_no_secret_reproduction():
    """§24: every known secret format is redacted; nothing leaks into evidence."""
    ev = _factory()({"service": "kai", "severity": "DEBUG", "bounded_limit": 100})
    blob = str(ev)
    for needle in ("ghp_0123456789", "github_pat_11", "sk-proj-abc", "sk-svcacct-abc", "xoxb-1234567890",
                   "wJalrXUtnFEMI", "super.secret.jwt", "session=abcdef123456", "MIIEvQreallysecret",
                   "Pa55w0rd-json-LEAK", "cs_json_LEAK"):     # JSON-formatted credentials (recheck finding)
        assert needle not in blob, f"LEAKED: {needle}"
    assert REDACTED in blob and ev["redaction_count"] >= 5


def t_sha_stays_visible():
    """§24: a legitimate 40-char SHA must NOT be redacted."""
    ev = _factory()({"service": "kai", "severity": "DEBUG", "bounded_limit": 100})
    assert any(_SHA in e for e in ev["excerpts"]), "SHA should remain visible"


def t_evidence_shape():
    ev = _factory()({"service": "kai", "severity": "DEBUG", "bounded_limit": 100})
    for k in ("service", "source", "time_range", "severity", "correlation_id",
              "matched_count", "redaction_count", "retrieved_at", "excerpts"):
        assert k in ev, k
    assert ev["source"] == "local-file" and ev["service"] == "kai"


def t_forbidden_fields_rejected():
    """§16: shell/command/grep/path never reach a provider."""
    prov = _factory()
    for bad in ({"service": "kai", "command": "cat /etc/passwd"}, {"service": "kai", "grep": "x"},
                {"service": "kai", "path": "/var/log"}, {"service": "kai", "shell": "sh"}):
        try:
            prov(bad); assert False, f"{bad} should be denied"
        except LogDenied:
            pass


def t_bounds_enforced():
    """§18: bounded_limit clamped to server max; a client cannot request more."""
    req = build_request({"service": "kai", "bounded_limit": 10 ** 9})
    assert req.bounded_limit == MAX_LINES
    ev = _factory()({"service": "kai", "severity": "DEBUG", "bounded_limit": 3})
    assert len(ev["excerpts"]) <= 3


def t_unknown_and_unconfigured_service_block():
    """§17: a service with no configured source → denied (never a guessed source)."""
    prov = _factory()
    try:
        prov({"service": "unmapped-service"}); assert False
    except LogDenied:
        pass
    try:
        prov({}); assert False   # no service_id
    except LogDenied:
        pass


def t_correlation_filter():
    ev = _factory()({"service": "kai", "severity": "DEBUG", "bounded_limit": 100, "correlation_id": "correlation-XYZ"})
    assert ev["matched_count"] == 1 and "correlation-XYZ" in ev["excerpts"][0]


def t_two_stage_redaction_at_source():
    """§19: the provider redacts at source — a raw secret is never returned even before evidence assembly."""
    path = _logfile()
    out = LocalLogFileProvider().read(path, LogRequest(service_id="kai", severity="DEBUG", bounded_limit=100))
    assert all("ghp_0123456789" not in e and "sk-proj-abc" not in e for e in out["excerpts"])


def t_engine_e2e_with_registered_source():
    """§23: LOG_INSPECT runs through the real engine executor when a source is server-registered."""
    from app.services.holding.log_inspect import register_log_source
    from app.services.holding.autonomous_work import HoldingAutonomousWorkEngine, EXECUTED
    from app.services.holding.task_resolver import (TaskCapabilityResolver, make_engine_resolver,
                                                    build_holding_executor)
    from app.services.holding.plan import PlanTask, AutonomyClass, Assignee
    from app.services.holding.task_resolver import HoldingTaskType
    register_log_source("kai", provider="local-file", path=_logfile())
    task = PlanTask("log:kai", "kai", "inspect logs", "degraded", "log:kai",
                    task_type=HoldingTaskType.LOG_INSPECT.value, autonomy=int(AutonomyClass.A0_OBSERVE),
                    assigned_to=Assignee.KAI.value)
    eng = HoldingAutonomousWorkEngine(execute=build_holding_executor(),
                                      resolver=make_engine_resolver(TaskCapabilityResolver()))
    r = eng.run_task(task)
    assert r.outcome == EXECUTED and r.verified and r.capability_id == "holding.logs"
    assert "ghp_0123456789" not in str(r.__dict__)     # no secret in the work result


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
