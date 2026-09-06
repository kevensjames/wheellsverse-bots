"""Tests for DEPLOYMENT_STATUS (Part A, §7-13). SHA comparison uses REAL git ancestry over the monorepo.
Run: python3 backend/app/services/holding/test_deployment_status.py"""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.deployment_status import (  # noqa: E402
    make_deployment_provider, resolve_deployment, compare_shas, DeployDenied,
    MATCH, DEPLOYMENT_BEHIND, UNCOMPARABLE)

_ROOT = str(Path(__file__).resolve().parents[4])   # monorepo root
# Two commits that exist in the object store, used ONLY for the pure compare_shas() ancestry check.
_HEAD = "ca791234d6fffb5f04115e43e249259778d36402"
_OLD = "b82b873e36a49faaff01dc9be6114642f7fc5ead"   # an ancestor of _HEAD


def _ancestor_of_live_head(n: int = 5) -> str:
    """A REAL ancestor of whatever this checkout's HEAD is.

    The stale-discrimination check below resolves through the live repository head, not through _HEAD, so
    a hardcoded "old" commit only works while the checkout descends from it. _OLD does not: it is an
    ancestor of feat/kai-cyber-operations but NOT of production, so on a production-based branch the
    comparison is honestly UNCOMPARABLE and the check failed for a reason that had nothing to do with the
    code under test. Ask git for an ancestor instead of pinning one to a branch."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", _ROOT, "rev-parse", f"HEAD~{n}"],
                           capture_output=True, text=True, timeout=15)
        sha = r.stdout.strip()
        return sha if r.returncode == 0 and len(sha) == 40 else ""
    except Exception:
        return ""


_LIVE_ANCESTOR = _ancestor_of_live_head()

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _ents():
    return [SimpleNamespace(entity_id="kai", repository="wheellsverse-bots"),
            SimpleNamespace(entity_id="sol", repository="wheellsverse-sol")]


def _factory(sources):
    return make_deployment_provider(sources=sources, entities=_ents())


def _src(**kw):
    base = {"provider": "LOCAL", "company_id": "kai", "deployed_sha": _HEAD, "deployment_id": "d1",
            "status": "SUCCESS", "environment": "production", "local_root": _ROOT}
    base.update(kw)
    return {"kai": base}


def t_sha_comparison_real_ancestry():
    """§7: real git ancestry — deployed==source→MATCH; deployed is ancestor of source→BEHIND."""
    assert compare_shas(_ROOT, _HEAD, _HEAD) == MATCH
    assert compare_shas(_ROOT, _HEAD, _OLD) == DEPLOYMENT_BEHIND    # source HEAD ahead of deployed OLD
    assert compare_shas(_ROOT, _HEAD, "0" * 40) == UNCOMPARABLE     # unknown commit, not guessed
    assert compare_shas(_ROOT, "", _HEAD) == UNCOMPARABLE
    # injection defense: a non-hex / flag-like sha is never passed to git → UNCOMPARABLE
    for bad in ("--all", "-n1", "HEAD; rm -rf /", "main", "$(whoami)"):
        assert compare_shas(_ROOT, _HEAD, bad) == UNCOMPARABLE, bad


def t_deployment_stale_discrimination():
    """§41 critical acceptance: source ahead of deployed → DEPLOYMENT_BEHIND (NOT a code-fix signal)."""
    assert _LIVE_ANCESTOR, ("cannot resolve an ancestor of this checkout's HEAD (shallow clone or no git) "
                            "— reported, never passed silently")
    ev = _factory(_src(deployed_sha=_LIVE_ANCESTOR))({"company_id": "kai", "service_id": "kai"})
    assert ev["sha_comparison"] == DEPLOYMENT_BEHIND and ev["deployed_sha"] == _LIVE_ANCESTOR


def t_match_when_current():
    from app.services.holding.repo_inspect import LocalGitProvider
    live_head = LocalGitProvider(_ROOT).repository_status()["commit_sha"]   # deployed == current source
    ev = _factory(_src(deployed_sha=live_head))({"company_id": "kai", "service_id": "kai"})
    assert ev["sha_comparison"] == MATCH


def t_evidence_whitelist_no_secrets():
    """§6/§9: only whitelisted read-only fields; no env vars / tokens / raw provider blob."""
    ev = _factory(_src())({"company_id": "kai", "service_id": "kai"})
    for k in ("provider", "service_id", "deployed_sha", "sha_comparison", "deployment_status"):
        assert k in ev, k
    # a source that (hypothetically) carried secrets must not surface them
    ev2 = _factory({"kai": {"provider": "LOCAL", "company_id": "kai", "deployed_sha": _HEAD,
                            "local_root": _ROOT, "environment": "production", "status": "SUCCESS",
                            "AIKIDO_TOKEN": "sk-secret", "DATABASE_URL": "postgres://u:p@h"}})(
        {"company_id": "kai", "service_id": "kai"})
    assert "AIKIDO_TOKEN" not in ev2 and "DATABASE_URL" not in ev2 and "sk-secret" not in str(ev2)


def t_short_sha_matches_full():
    """Recheck finding: a short deployed SHA of the SAME commit as source → MATCH, not false-BEHIND."""
    from app.services.holding.repo_inspect import LocalGitProvider
    full = LocalGitProvider(_ROOT).repository_status()["commit_sha"]
    ev = _factory(_src(deployed_sha=full[:7]))({"company_id": "kai", "service_id": "kai"})
    assert ev["sha_comparison"] == MATCH


def t_cross_company_service_denied():
    """Recheck finding: a service bound to company A cannot be read under company B."""
    sources = {"svc1": {"provider": "LOCAL", "company_id": "kai", "deployed_sha": _HEAD,
                        "local_root": _ROOT, "environment": "production", "status": "SUCCESS"}}
    prov = make_deployment_provider(sources=sources, entities=_ents())
    try:
        prov({"company_id": "sol", "service_id": "svc1"}); assert False, "cross-company must be denied"
    except DeployDenied:
        pass


def t_unknown_and_unconfigured_block():
    prov = _factory(_src())
    try:
        prov({"company_id": "ghost", "service_id": "ghost"}); assert False
    except DeployDenied:
        pass
    # a configured service for a different company/service that is not registered → block
    try:
        prov({"company_id": "sol", "service_id": "sol"}); assert False
    except DeployDenied:
        pass


def t_mutation_and_forged_ops_denied():
    """§3/§12: only read operations exist; anything else is denied."""
    prov = _factory(_src())
    for bad in ("REDEPLOY", "RESTART", "ROLLBACK", "SCALE", "SET_VARIABLE", "DELETE_SERVICE", "rm -rf"):
        try:
            prov({"company_id": "kai", "service_id": "kai", "operation": bad}); assert False, bad
        except DeployDenied:
            pass


def t_uncertified_provider_never_substituted():
    """§1: a Railway/other provider with no certified adapter → BLOCKED, never swapped for LOCAL."""
    prov = _factory({"kai": {"provider": "RAILWAY", "deployed_sha": _HEAD, "local_root": _ROOT}})
    try:
        prov({"company_id": "kai", "service_id": "kai"}); assert False
    except DeployDenied:
        pass


def t_resolve_provider_unavailable_when_unconfigured():
    ident = resolve_deployment("kai", "kai", entities=_ents(), sources={})
    assert ident.provider == "UNAVAILABLE"


def t_railway_adapter_runtime_pending_without_client():
    """Part D: RAILWAY provider with no read client wired → RUNTIME_PENDING (fail closed)."""
    from app.services.holding.deployment_status import make_deployment_provider
    sources = {"appb": {"provider": "RAILWAY", "company_id": "kai", "environment": "production"}}
    prov = make_deployment_provider(sources=sources, entities=_ents(), railway_api=None)
    try:
        prov({"company_id": "kai", "service_id": "appb"}); assert False
    except DeployDenied:
        pass


def t_railway_adapter_read_only_with_client():
    """Part D: with an injected READ client → real whitelisted evidence, no secrets, no mutation method."""
    from app.services.holding.deployment_status import make_deployment_provider, RailwayDeploymentReadAdapter
    def fake_api(service_id, environment):
        return {"deployment_id": "dep_abc", "status": "SUCCESS", "sha": _HEAD, "created_at": "2026-09-02",
                "RAILWAY_TOKEN": "sk-should-not-leak", "env": {"DATABASE_URL": "postgres://u:p@h"}}
    sources = {"appb": {"provider": "RAILWAY", "company_id": "kai", "environment": "production",
                        "local_root": _ROOT}}
    prov = make_deployment_provider(sources=sources, entities=_ents(), railway_api=fake_api)
    ev = prov({"company_id": "kai", "service_id": "appb"})
    assert ev["provider"] == "RAILWAY" and ev["deployment_status"] == "SUCCESS" and ev["deployed_sha"] == _HEAD
    assert "RAILWAY_TOKEN" not in ev and "DATABASE_URL" not in str(ev) and "sk-should-not-leak" not in str(ev)
    # no mutation method exists on the adapter (§20)
    for banned in ("deploy", "redeploy", "restart", "rollback", "scale", "set_variable", "delete"):
        assert not hasattr(RailwayDeploymentReadAdapter, banned), banned


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
