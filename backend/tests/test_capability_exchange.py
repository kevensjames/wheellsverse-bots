"""Capability Exchange — catalog-only tests (Phase 1).

Corrected from an earlier version that tested bind_adapter/execute/scope-gated
lifecycle. The registry is now a CATALOG: it cannot execute and has no surface
to bind/run a capability. Load-bearing negative control: the execution surface
does not exist (allowlist of public methods), so no in-process caller can
activate a capability. Manifest validation + the CONSEQUENTIAL construction
invariant remain (declarative, not execution).
"""
from __future__ import annotations

import pytest

import app.services.capability_exchange as cx_module
from app.services.capability_exchange import (
    ANGULAR_CAPABILITIES,
    CapabilityError,
    CapabilityManifest,
    CapabilityRegistry,
    ExecutionMode,
    RiskClass,
    default_registry,
    scope_env_var,
)


def _read_cap(cid="test.thing.v1", scope="test.thing"):
    return CapabilityManifest(
        capability_id=cid, risk_class=RiskClass.READ,
        execution_mode=ExecutionMode.OBSERVE, provider="x", scope=scope,
    )


# ─── manifest validation (declarative, construction-time) ──────────────────


@pytest.mark.parametrize("bad", ["Frontend.Scaffold.v1", "no_dots_v1", "a.b", "a.b.v", "a.b.1"])
def test_manifest_rejects_bad_id(bad):
    with pytest.raises(ValueError):
        _read_cap(cid=bad)


def test_manifest_accepts_versioned_dotted_id():
    assert _read_cap(cid="kai.frontend.scaffold.v1").capability_id == "kai.frontend.scaffold.v1"


def test_consequential_requires_full_governance():
    with pytest.raises(ValueError, match="approve_execute"):
        CapabilityManifest(
            capability_id="x.publish.v1", risk_class=RiskClass.CONSEQUENTIAL,
            execution_mode=ExecutionMode.DRAFT, provider="p", scope="x.publish",
            approval_policy="named", rollback_target="prev",
        )
    with pytest.raises(ValueError, match="approval_policy"):
        CapabilityManifest(
            capability_id="x.publish.v1", risk_class=RiskClass.CONSEQUENTIAL,
            execution_mode=ExecutionMode.APPROVE_EXECUTE, provider="p", scope="x.publish",
        )
    # approval_policy present, rollback_target missing — the only input that reaches
    # the rollback guard (negative control for that requirement).
    with pytest.raises(ValueError, match="rollback_target"):
        CapabilityManifest(
            capability_id="x.publish.v1", risk_class=RiskClass.CONSEQUENTIAL,
            execution_mode=ExecutionMode.APPROVE_EXECUTE, provider="p", scope="x.publish",
            approval_policy="named",
        )
    ok = CapabilityManifest(
        capability_id="x.publish.v1", risk_class=RiskClass.CONSEQUENTIAL,
        execution_mode=ExecutionMode.APPROVE_EXECUTE, provider="p", scope="x.publish",
        approval_policy="named approval + fresh bound single-use approval",
        rollback_target="prev build",
    )
    assert ok.rollback_target == "prev build"


def test_scope_env_var_is_pure_formatter():
    # Formats the env name only — the catalog never reads it.
    assert scope_env_var("frontend.scaffold") == "KAI_SCOPE_FRONTEND_SCAFFOLD"


# ─── catalog behavior ───────────────────────────────────────────────────────


def test_register_get_list_and_duplicate():
    r = CapabilityRegistry()
    r.register(_read_cap())
    assert r.ids() == ["test.thing.v1"]
    assert r.get("test.thing.v1").provider == "x"
    with pytest.raises(CapabilityError):
        r.register(_read_cap())  # duplicate id
    with pytest.raises(KeyError):
        r.get("nope.v1")


def test_for_risk_filter():
    r = default_registry()
    consequential = [m.capability_id for m in r.for_risk(RiskClass.CONSEQUENTIAL)]
    assert consequential == ["kai.frontend.publish.v1"]


def test_summary_catalog_shape():
    r = default_registry()
    s = r.summary()
    assert s["total"] == len(ANGULAR_CAPABILITIES)
    assert s["execution_supported"] is False
    assert sum(s["by_risk"].values()) == len(ANGULAR_CAPABILITIES)
    assert sum(s["by_mode"].values()) == len(ANGULAR_CAPABILITIES)


# ─── load-bearing negative control: no execution surface exists ─────────────


def test_no_execution_surface_exists():
    """Catalog-only by construction: no method/type through which any caller
    (in-process included) could bind or run a capability, and no scope/flag
    evaluation. Fails the moment an execution path is reintroduced."""
    r = CapabilityRegistry()
    assert CapabilityRegistry.execution_supported is False
    for forbidden in ("bind_adapter", "execute", "lifecycle", "is_executable", "_adapters"):
        assert not hasattr(r, forbidden), f"{forbidden!r} must not exist on the catalog"
    for forbidden in ("Adapter", "Lifecycle", "_exact_scope_enabled", "_is_env_truthy", "is_scope_enabled"):
        assert not hasattr(cx_module, forbidden), f"{forbidden!r} must not be in the module"
    # Allowlist teeth: the ONLY public methods are the catalog methods (catches a
    # re-introduced execution path under ANY new name).
    public_methods = {n for n in dir(r) if not n.startswith("_") and callable(getattr(r, n))}
    assert public_methods == {"register", "get", "ids", "for_risk", "summary"}, public_methods
    # default catalog is honest about it too
    assert default_registry().summary()["execution_supported"] is False
