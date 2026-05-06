"""Phase G.2: tests for ``BrainClient(dynamic_policy=...)`` integration.

The harness lives under ``tests/debug/`` so the local conftest no-ops
the parent ``_isolate_chroma`` autouse fixture (none of these tests
touch Chroma; they exercise the BrainClient init path).

Coverage targets the spec bullets directly:

  * ``dynamic_policy=False`` → ``client.policy is client.static_policy``
    (or equal, since the evolver no-ops to identity on cold start).
  * ``dynamic_policy=True`` resolves once at init; mutating the store
    AFTER init does NOT change ``client.policy``.
  * Env var ``BRAIN_POLICY_DYNAMIC`` honored when constructor arg is
    None (truthy: ``on/true/1/yes``, case-insensitive).
  * Default (no arg, no env) → dynamic OFF.
  * ``client.outcome_store`` is None when dynamic is off; populated
    when on.
  * ``client.static_policy`` always reflects unmutated base.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from infra.brain.interface import BrainClient
from infra.brain.policy import (
    BrainPolicy,
    CAPABILITY_NETWORK,
    CAPABILITY_READ_ONLY,
    NARAI_POLICY,
)
from infra.brain.learning.policy_evolver import EvolutionConfig
from infra.brain.learning.repair_outcome_memory import (
    RepairOutcome,
    RepairOutcomeStore,
    STATE_REVERTED,
)
from infra.brain.tools.registry import ToolRegistry


# ── Helpers ─────────────────────────────────────────────────────────────


def _custom_static() -> BrainPolicy:
    """A neutered policy isolated from the production NarAI / NAI
    constants so test mutations never leak."""
    return BrainPolicy(
        mode="test",
        tone="test",
        system_prompt="test",
        memory_enabled=False,
        rag_enabled=False,
        tools_enabled=True,
        allowed_tools=("alpha", "beta"),
        allowed_capabilities=frozenset({CAPABILITY_READ_ONLY, CAPABILITY_NETWORK}),
    )


def _seed_bad_history(store: RepairOutcomeStore, *, tool: str, n: int = 30):
    """Seed ``n`` reverted outcomes touching ``tool`` so the evolver
    has unambiguous evidence to restrict it."""
    for i in range(n):
        store.record_outcome(RepairOutcome(
            failure_signature=f"sig_{i}",
            patch_hash=f"{tool}_p{i}",
            applied_at=f"2026-05-06T00:{i:02d}:00+00:00",
            outcome_state=STATE_REVERTED,
            outcome_observed_at=f"2026-05-06T00:{i:02d}:00+00:00",
            touched_tools=(tool,),
        ))


def _make_client(
    *,
    dynamic_policy=None,
    outcome_store=None,
    policy=None,
    tool_registry=None,
    evolution_config=None,
):
    """Construct a BrainClient with the test defaults that don't drag
    in the chroma-touching surface."""
    return BrainClient(
        user_id="t",
        policy=policy if policy is not None else _custom_static(),
        tool_registry=tool_registry if tool_registry is not None else ToolRegistry(),
        telemetry_enabled=False,
        dynamic_policy=dynamic_policy,
        outcome_store=outcome_store,
        evolution_config=evolution_config,
    )


# ── Default behavior ────────────────────────────────────────────────────


def test_default_no_arg_no_env_disables_dynamic(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    client = _make_client()
    assert client.policy is client.static_policy
    assert client.outcome_store is None


def test_dynamic_false_disables_regardless_of_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_POLICY_DYNAMIC", "true")  # env says on
    client = _make_client(dynamic_policy=False)         # arg overrides
    assert client.policy is client.static_policy
    assert client.outcome_store is None


# ── Env-var parsing ─────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["on", "ON", "true", "TRUE", "1", "yes", "YES"])
def test_env_var_truthy_values_enable(tmp_path, monkeypatch, value):
    monkeypatch.setenv("BRAIN_POLICY_DYNAMIC", value)
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    client = _make_client(outcome_store=store)
    # Dynamic enabled → outcome_store attached, policy resolved.
    assert client.outcome_store is store


@pytest.mark.parametrize("value", ["off", "false", "0", "no", "garbage", ""])
def test_env_var_falsy_values_disable(tmp_path, monkeypatch, value):
    monkeypatch.setenv("BRAIN_POLICY_DYNAMIC", value)
    client = _make_client()
    assert client.policy is client.static_policy
    assert client.outcome_store is None


def test_env_var_unset_treated_as_off(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    client = _make_client()
    assert client.outcome_store is None


# ── Dynamic-on behavior ─────────────────────────────────────────────────


def test_dynamic_on_with_empty_store_returns_static(tmp_path, monkeypatch):
    """Cold-start invariant at the BrainClient seam: empty store →
    effective == static."""
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    client = _make_client(dynamic_policy=True, outcome_store=store)
    # Identity preserved when nothing to restrict.
    assert client.policy is client.static_policy
    assert client.outcome_store is store


def test_dynamic_on_with_bad_history_restricts(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    _seed_bad_history(store, tool="alpha", n=30)

    client = _make_client(
        dynamic_policy=True,
        outcome_store=store,
        evolution_config=EvolutionConfig(enabled=True, min_history=5),
    )

    # Static unchanged; effective dropped alpha.
    assert "alpha" in client.static_policy.allowed_tools
    assert "alpha" not in client.policy.allowed_tools
    assert "beta" in client.policy.allowed_tools


def test_dynamic_on_resolves_once_post_init_changes_ignored(tmp_path, monkeypatch):
    """The Phase G spec: 'mutating the store post-init does NOT change
    client.policy'. Verifies single-resolution-at-init."""
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    client = _make_client(
        dynamic_policy=True,
        outcome_store=store,
        evolution_config=EvolutionConfig(enabled=True, min_history=5),
    )
    # Empty store at init → effective == static.
    assert client.policy is client.static_policy

    # Mutate store post-init with bad history.
    _seed_bad_history(store, tool="alpha", n=30)

    # client.policy MUST NOT change. Single-resolution contract.
    assert client.policy is client.static_policy
    assert "alpha" in client.policy.allowed_tools


def test_outcome_store_default_constructed_when_dynamic_on_and_arg_omitted(
    tmp_path, monkeypatch,
):
    """When dynamic_policy=True and no outcome_store is supplied, the
    BrainClient builds one at the canonical default path."""
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    # Move CWD so the default path doesn't smear test state into the repo.
    monkeypatch.chdir(tmp_path)
    client = _make_client(dynamic_policy=True)
    assert client.outcome_store is not None
    assert client.policy is client.static_policy  # cold-start neutrality


# ── Static vs effective separation ──────────────────────────────────────


def test_static_policy_always_reflects_base(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    _seed_bad_history(store, tool="alpha", n=30)

    static_input = _custom_static()
    client = _make_client(
        policy=static_input,
        dynamic_policy=True,
        outcome_store=store,
        evolution_config=EvolutionConfig(enabled=True, min_history=5),
    )

    # static_policy must be the input we provided, byte-equal.
    assert client.static_policy == static_input
    # And distinct from the (now restricted) effective policy.
    assert client.policy != client.static_policy


def test_static_policy_attribute_is_set_on_dynamic_off(tmp_path, monkeypatch):
    """Even when dynamic is off, ``client.static_policy`` must be a
    valid BrainPolicy reference (not None / missing)."""
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    client = _make_client(dynamic_policy=False)
    assert isinstance(client.static_policy, BrainPolicy)
    assert client.static_policy is client.policy


# ── Config interaction ─────────────────────────────────────────────────


def test_explicit_disabled_evolution_config_short_circuits(
    tmp_path, monkeypatch,
):
    """Caller passes ``dynamic_policy=True`` but a config with
    ``enabled=False``: the evolver must honor the config-level kill
    switch even though the BrainClient-level switch is on."""
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    _seed_bad_history(store, tool="alpha", n=30)

    client = _make_client(
        dynamic_policy=True,
        outcome_store=store,
        evolution_config=EvolutionConfig(enabled=False, min_history=5),
    )

    # Effective == static even though dynamic_policy=True, because
    # the supplied config says off.
    assert client.policy is client.static_policy


# ── Backwards compatibility ────────────────────────────────────────────


def test_existing_callers_with_no_dynamic_kwarg_unchanged(tmp_path, monkeypatch):
    """Pre-Phase-G call sites pass no dynamic_policy / outcome_store
    kwargs. They must keep getting the static policy unchanged."""
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    static = _custom_static()
    client = BrainClient(
        user_id="legacy",
        policy=static,
        tool_registry=ToolRegistry(),
        telemetry_enabled=False,
    )
    assert client.policy is static
    assert client.static_policy is static
    assert client.outcome_store is None


def test_narai_default_policy_unchanged_at_brain_client_seam(tmp_path, monkeypatch):
    """The production NARAI_POLICY constant is read but not mutated
    when dynamic is on with empty history."""
    monkeypatch.delenv("BRAIN_POLICY_DYNAMIC", raising=False)
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    client = BrainClient(
        user_id="t",
        mode="narai",
        tool_registry=ToolRegistry(),
        telemetry_enabled=False,
        dynamic_policy=True,
        outcome_store=store,
        evolution_config=EvolutionConfig(enabled=True, min_history=5),
    )
    assert client.static_policy is NARAI_POLICY
    assert client.policy is NARAI_POLICY  # cold-start identity preserved
