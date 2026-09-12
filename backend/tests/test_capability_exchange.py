"""Capability Exchange — inert Stage 1 tests.

The load-bearing invariant is the honesty one: with no adapters bound, NOTHING
is executable and execute() refuses. The rest guard manifest validation,
CONSEQUENTIAL governance, and scope-gated lifecycle (via a dummy adapter that
would only ever be bound in a later, separately-approved stage).
"""
from __future__ import annotations

import pytest

from app.services.capability_exchange import (
    ANGULAR_CAPABILITIES,
    CapabilityError,
    CapabilityManifest,
    CapabilityRegistry,
    ExecutionMode,
    Lifecycle,
    RiskClass,
    default_registry,
    scope_env_var,
)


def _read_cap(cid="test.thing.v1", scope="test.thing"):
    return CapabilityManifest(
        capability_id=cid, risk_class=RiskClass.READ,
        execution_mode=ExecutionMode.OBSERVE, provider="x", scope=scope,
    )


# ─── manifest validation ────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["Frontend.Scaffold.v1", "no_dots_v1", "a.b", "a.b.v", "a.b.1"])
def test_manifest_rejects_bad_id(bad):
    with pytest.raises(ValueError):
        _read_cap(cid=bad)


def test_manifest_accepts_versioned_dotted_id():
    assert _read_cap(cid="kai.frontend.scaffold.v1").capability_id == "kai.frontend.scaffold.v1"


def test_consequential_requires_full_governance():
    # missing approval_policy + rollback_target
    with pytest.raises(ValueError):
        CapabilityManifest(
            capability_id="x.publish.v1", risk_class=RiskClass.CONSEQUENTIAL,
            execution_mode=ExecutionMode.APPROVE_EXECUTE, provider="p", scope="x.publish",
        )
    # wrong execution mode for a consequential capability
    with pytest.raises(ValueError):
        CapabilityManifest(
            capability_id="x.publish.v1", risk_class=RiskClass.CONSEQUENTIAL,
            execution_mode=ExecutionMode.DRAFT, provider="p", scope="x.publish",
            approval_policy="named", rollback_target="prev",
        )
    # fully-governed consequential capability is accepted
    ok = CapabilityManifest(
        capability_id="x.publish.v1", risk_class=RiskClass.CONSEQUENTIAL,
        execution_mode=ExecutionMode.APPROVE_EXECUTE, provider="p", scope="x.publish",
        approval_policy="named approval + fresh bound single-use approval",
        rollback_target="prev build",
    )
    assert ok.rollback_target == "prev build"


def test_scope_env_var_matches_governance_normalization():
    assert scope_env_var("frontend.scaffold") == "KAI_SCOPE_FRONTEND_SCAFFOLD"


# ─── registry ─────────────────────────────────────────────────────────────


def test_register_get_list_and_duplicate():
    r = CapabilityRegistry()
    r.register(_read_cap())
    assert r.ids() == ["test.thing.v1"]
    assert r.get("test.thing.v1").provider == "x"
    with pytest.raises(CapabilityError):
        r.register(_read_cap())  # duplicate id
    with pytest.raises(KeyError):
        r.get("nope.v1")


def test_bind_adapter_to_unknown_refused():
    r = CapabilityRegistry()
    with pytest.raises(KeyError):
        r.bind_adapter("ghost.thing.v1", lambda: None)


# ─── the load-bearing honesty invariant ────────────────────────────────────


def test_stage1_default_registry_is_fully_inert(monkeypatch):
    # Even if an operator turns every Angular scope ON, nothing runs: no adapters.
    for m in ANGULAR_CAPABILITIES:
        monkeypatch.setenv(scope_env_var(m.scope), "1")
    r = default_registry()
    assert r.summary()["adapters_bound"] == 0
    assert len(r.ids()) == len(ANGULAR_CAPABILITIES)
    for cid in r.ids():
        assert r.lifecycle(cid) is Lifecycle.INERT
        assert r.is_executable(cid) is False
        with pytest.raises(CapabilityError, match="INERT"):
            r.execute(cid)


# ─── lifecycle (adapter would only be bound in a later approved stage) ──────


def test_lifecycle_scope_gates_a_bound_adapter(monkeypatch):
    r = CapabilityRegistry()
    r.register(_read_cap(cid="demo.run.v1", scope="demo.run"))
    calls = []
    r.bind_adapter("demo.run.v1", lambda **kw: calls.append(kw) or "ran")

    # scope OFF → DISABLED, execute refuses, adapter never called
    monkeypatch.delenv("KAI_SCOPE_DEMO_RUN", raising=False)
    assert r.lifecycle("demo.run.v1") is Lifecycle.DISABLED
    with pytest.raises(CapabilityError, match="DISABLED"):
        r.execute("demo.run.v1")
    assert calls == []

    # scope ON → ENABLED, execute delegates to the adapter
    monkeypatch.setenv("KAI_SCOPE_DEMO_RUN", "1")
    assert r.lifecycle("demo.run.v1") is Lifecycle.ENABLED
    assert r.is_executable("demo.run.v1") is True
    assert r.execute("demo.run.v1", who="test") == "ran"
    assert calls == [{"who": "test"}]


def test_summary_shape():
    r = default_registry()
    s = r.summary()
    assert s["total"] == len(ANGULAR_CAPABILITIES)
    assert s["adapters_bound"] == 0
    assert s["by_status"] == {"INERT": sorted(m.capability_id for m in ANGULAR_CAPABILITIES)}
