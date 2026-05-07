"""Phase G.1: tests for the policy evolver.

Coverage targets each of the seven hard invariants from the spec, plus
the per-test bullets:

  * Empty store → effective == static (cold-start neutrality).
  * History below ``min_history`` → effective == static (per-tool
    cold start).
  * Tool with evidence ≥ min_history and success rate below threshold
    → tool dropped from dynamic allowlist; static unchanged.
  * Tool with regression rate above threshold → dropped.
  * Capability dropped only when ALL its tools are dropped (not "any").
  * Re-allow only after ``stability_window`` of improvement (boundary:
    window-1 = restricted; window = re-allowed).
  * Restriction-only invariant: a tool NOT in ``static.allowed_tools``
    is never added to effective.
  * ``enabled=False`` → effective == static regardless of history.
  * ``explain()`` produces ``PolicyAdjustment`` records with correct
    evidence counts.
  * Static is never mutated (frozen + same identity preserved on
    no-restriction paths).
  * Telemetry: ``policy_dynamic_restriction`` event per restriction.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from infra.brain.policy import (
    BrainPolicy,
    CAPABILITY_NETWORK,
    CAPABILITY_READ_ONLY,
    CAPABILITY_SHELL,
    NARAI_POLICY,
)
from infra.brain.learning.policy_evolver import (
    EVENT_POLICY_DYNAMIC_RESOLVED,
    EVENT_POLICY_DYNAMIC_RESTRICTION,
    EvolutionConfig,
    PolicyAdjustment,
    PolicyEvolver,
)
from infra.brain.learning.repair_outcome_memory import (
    RepairOutcome,
    RepairOutcomeStore,
    STATE_APPLIED,
    STATE_MERGED,
    STATE_REGRESSED,
    STATE_REVERTED,
)
from infra.brain.tools.registry import Tool, ToolRegistry


# ── Helpers ─────────────────────────────────────────────────────────────


def _outcome(
    *,
    sig: str = "sig",
    patch: str,
    state: str = STATE_APPLIED,
    touched_tools: tuple[str, ...] = (),
    applied_at: str = "2026-05-06T00:00:00+00:00",
) -> RepairOutcome:
    return RepairOutcome(
        failure_signature=sig,
        patch_hash=patch,
        applied_at=applied_at,
        outcome_state=state,
        outcome_observed_at=applied_at,
        touched_tools=touched_tools,
    )


def _make_store(tmp_path: Path, outcomes: list[RepairOutcome]) -> RepairOutcomeStore:
    store = RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")
    for o in outcomes:
        store.record_outcome(o)
    return store


def _custom_static_policy(
    *,
    allowed_tools: tuple[str, ...] | None = ("alpha", "beta"),
    allowed_capabilities: frozenset[str] | None = frozenset({
        CAPABILITY_READ_ONLY, CAPABILITY_NETWORK,
    }),
) -> BrainPolicy:
    return BrainPolicy(
        mode="test",
        tone="test",
        system_prompt="test",
        memory_enabled=False,
        rag_enabled=False,
        tools_enabled=True,
        allowed_tools=allowed_tools,
        allowed_capabilities=allowed_capabilities,
    )


def _enabled_config(**overrides) -> EvolutionConfig:
    return dataclasses.replace(
        EvolutionConfig(enabled=True, min_history=5, stability_window=10),
        **overrides,
    )


def _bulk_outcomes(
    *,
    tool: str,
    n: int,
    state: str,
    sig: str = "sig_bulk",
    start_date: str = "2026-05-06T00:00:00+00:00",
) -> list[RepairOutcome]:
    """Helper: produce ``n`` outcomes for a single tool, all in
    ``state``, with distinct patch_hashes."""
    return [
        _outcome(
            sig=f"{sig}_{i}",
            patch=f"{tool}_p{i}",
            state=state,
            touched_tools=(tool,),
            applied_at=f"2026-05-06T00:{i:02d}:00+00:00",
        )
        for i in range(n)
    ]


# ── 1. Cold-start neutrality ───────────────────────────────────────────


def test_empty_store_returns_static_unchanged(tmp_path):
    store = _make_store(tmp_path, [])
    static = _custom_static_policy()
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(),
    )
    assert out is static  # identity preserved on no-op path


def test_history_below_min_history_returns_static(tmp_path):
    static = _custom_static_policy()
    # Below the cold-start threshold even though stats are bad.
    outcomes = _bulk_outcomes(tool="alpha", n=4, state=STATE_REVERTED)
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(min_history=5),
    )
    assert out is static


def test_history_below_min_history_per_tool_does_not_punish_other_tools(tmp_path):
    """A flood of bad outcomes for tool A doesn't trigger restrictions
    on tool B which has zero evidence."""
    static = _custom_static_policy(allowed_tools=("alpha", "beta"))
    outcomes = _bulk_outcomes(tool="alpha", n=20, state=STATE_REVERTED)
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(min_history=5),
    )
    # alpha drops; beta stays.
    assert "beta" in out.allowed_tools
    assert "alpha" not in out.allowed_tools


# ── 2. Decision rule: success_rate ──────────────────────────────────────


def test_low_success_rate_drops_tool(tmp_path):
    static = _custom_static_policy(allowed_tools=("alpha", "beta"))
    # 10 reverted (terminal, success=0%) + 0 merged → success_rate = 0.0
    outcomes = _bulk_outcomes(tool="alpha", n=10, state=STATE_REVERTED)
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(
            min_history=5, restrict_below_success_rate=0.40,
        ),
    )
    assert out.allowed_tools == ("beta",)


def test_high_success_rate_keeps_tool(tmp_path):
    static = _custom_static_policy(allowed_tools=("alpha", "beta"))
    outcomes = _bulk_outcomes(tool="alpha", n=10, state=STATE_MERGED)
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(min_history=5),
    )
    assert out is static  # nothing to restrict


# ── 3. Decision rule: regression_rate ──────────────────────────────────


def test_high_regression_rate_drops_tool(tmp_path):
    static = _custom_static_policy(allowed_tools=("alpha", "beta"))
    # 5 merged, 5 regressed → regression_rate = 0.5 (above 0.20 threshold).
    # Success rate = 5/10 = 0.5 (above 0.40 threshold) — so the
    # *only* signal driving the restriction is regression, which is
    # what this test isolates.
    outcomes = (
        _bulk_outcomes(tool="alpha", n=5, state=STATE_MERGED, sig="m")
        + _bulk_outcomes(tool="alpha", n=5, state=STATE_REGRESSED, sig="r")
    )
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(
            min_history=5,
            restrict_below_success_rate=0.30,  # success path stays clean
            restrict_above_regression_rate=0.20,
        ),
    )
    assert "alpha" not in out.allowed_tools


def test_explain_records_regression_reason(tmp_path):
    static = _custom_static_policy(allowed_tools=("alpha",))
    outcomes = (
        _bulk_outcomes(tool="alpha", n=5, state=STATE_MERGED, sig="m")
        + _bulk_outcomes(tool="alpha", n=5, state=STATE_REGRESSED, sig="r")
    )
    store = _make_store(tmp_path, outcomes)
    adjustments = PolicyEvolver().explain(
        static, store, config=_enabled_config(
            min_history=5,
            restrict_below_success_rate=0.30,  # not the trigger
            restrict_above_regression_rate=0.20,
        ),
    )
    assert len(adjustments) == 1
    adj = adjustments[0]
    assert adj.kind == "tool" and adj.name == "alpha"
    assert adj.reason == "high_regression_rate"
    assert adj.evidence_count == 10
    assert adj.regression_rate == pytest.approx(0.5)


# ── 4. Capability decisions ─────────────────────────────────────────────


def _registry_with_caps(**tool_caps: tuple[str, ...]) -> ToolRegistry:
    """Build a tool registry from ``name=(cap, cap, ...)`` kwargs."""
    async def _run(_):
        return {}
    reg = ToolRegistry()
    for name, caps in tool_caps.items():
        reg.register(Tool(
            name=name, description="test", run=_run,
            capabilities=frozenset(caps),
        ))
    return reg


def test_capability_dropped_when_all_tools_with_it_dropped(tmp_path):
    """``alpha`` and ``beta`` both declare CAPABILITY_NETWORK. Both
    get restricted by low success rate. Therefore NETWORK should be
    dropped from allowed_capabilities."""
    static = _custom_static_policy(
        allowed_tools=("alpha", "beta"),
        allowed_capabilities=frozenset({
            CAPABILITY_READ_ONLY, CAPABILITY_NETWORK,
        }),
    )
    outcomes = (
        _bulk_outcomes(tool="alpha", n=10, state=STATE_REVERTED, sig="a")
        + _bulk_outcomes(tool="beta", n=10, state=STATE_REVERTED, sig="b")
    )
    store = _make_store(tmp_path, outcomes)
    registry = _registry_with_caps(
        alpha=(CAPABILITY_READ_ONLY, CAPABILITY_NETWORK),
        beta=(CAPABILITY_READ_ONLY, CAPABILITY_NETWORK),
    )
    out = PolicyEvolver().compute_dynamic_policy(
        static, store,
        config=_enabled_config(min_history=5),
        tool_registry=registry,
    )
    # Both tools dropped; both capabilities (READ_ONLY + NETWORK) shared
    # by both → both capabilities dropped.
    assert out.allowed_tools == ()
    assert out.allowed_capabilities == frozenset()


def test_capability_kept_when_some_tools_with_it_pass(tmp_path):
    """If at least one tool with capability NETWORK has good stats,
    NETWORK stays."""
    static = _custom_static_policy(
        allowed_tools=("alpha", "beta"),
        allowed_capabilities=frozenset({
            CAPABILITY_READ_ONLY, CAPABILITY_NETWORK,
        }),
    )
    outcomes = (
        _bulk_outcomes(tool="alpha", n=10, state=STATE_REVERTED, sig="a")
        + _bulk_outcomes(tool="beta", n=10, state=STATE_MERGED, sig="b")
    )
    store = _make_store(tmp_path, outcomes)
    registry = _registry_with_caps(
        alpha=(CAPABILITY_NETWORK,),
        beta=(CAPABILITY_NETWORK, CAPABILITY_READ_ONLY),
    )
    out = PolicyEvolver().compute_dynamic_policy(
        static, store,
        config=_enabled_config(min_history=5),
        tool_registry=registry,
    )
    assert "alpha" not in out.allowed_tools
    assert "beta" in out.allowed_tools
    # NETWORK has a healthy member (beta) → stays.
    assert CAPABILITY_NETWORK in out.allowed_capabilities


def test_capability_decisions_skipped_without_registry(tmp_path):
    """No registry → only tool-level decisions fire; capabilities
    untouched."""
    static = _custom_static_policy()
    outcomes = _bulk_outcomes(tool="alpha", n=10, state=STATE_REVERTED)
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store,
        config=_enabled_config(min_history=5),
        # tool_registry not passed
    )
    assert "alpha" not in out.allowed_tools
    assert out.allowed_capabilities == static.allowed_capabilities


# ── 5. Stability window — boundary tests ───────────────────────────────


def test_stability_window_minus_one_keeps_restricted(tmp_path):
    """20 reverted (lifetime bad) + 9 merged (recent good but window=10).
    Recent doesn't satisfy the window → tool stays restricted."""
    static = _custom_static_policy(allowed_tools=("alpha",))
    outcomes = (
        _bulk_outcomes(tool="alpha", n=20, state=STATE_REVERTED, sig="r",
                       start_date="2026-05-01T00:00:00+00:00")
        + _bulk_outcomes(tool="alpha", n=9, state=STATE_MERGED, sig="m",
                         start_date="2026-05-06T00:00:00+00:00")
    )
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(
            min_history=5, stability_window=10,
        ),
    )
    assert "alpha" not in out.allowed_tools


def test_stability_window_exact_re_allows(tmp_path):
    """20 reverted (lifetime bad) + 10 merged (recent good = exactly
    one window) → recent dominates → tool re-allowed."""
    static = _custom_static_policy(allowed_tools=("alpha",))
    outcomes = (
        _bulk_outcomes(tool="alpha", n=20, state=STATE_REVERTED, sig="r")
        + _bulk_outcomes(tool="alpha", n=10, state=STATE_MERGED, sig="m")
    )
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(
            min_history=5, stability_window=10,
        ),
    )
    assert "alpha" in out.allowed_tools  # re-allowed via stability window


# ── 6. Restriction-only invariant ──────────────────────────────────────


def test_tool_not_in_static_never_appears_in_effective(tmp_path):
    """An outcome touches a tool that's NOT in ``static.allowed_tools``
    → that tool can never be ADDED to the effective allowlist."""
    static = _custom_static_policy(allowed_tools=("alpha",))
    # Outcomes touch "ghost", a tool absent from the static allowlist.
    outcomes = _bulk_outcomes(tool="ghost", n=20, state=STATE_MERGED)
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(min_history=5),
    )
    assert out.allowed_tools == ("alpha",)
    assert "ghost" not in (out.allowed_tools or ())


def test_unrestricted_static_stays_unrestricted(tmp_path):
    """When the static side has ``allowed_tools=None`` (unrestricted),
    the dynamic layer can't narrow it to a finite set without
    expanding the contract — so it leaves it as None and only acts
    on capabilities."""
    static = _custom_static_policy(allowed_tools=None)
    outcomes = _bulk_outcomes(tool="alpha", n=10, state=STATE_REVERTED)
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(min_history=5),
    )
    assert out.allowed_tools is None  # restriction-only invariant


# ── 7. Kill switch ─────────────────────────────────────────────────────


def test_disabled_config_returns_static_regardless_of_history(tmp_path):
    static = _custom_static_policy(allowed_tools=("alpha",))
    # Worst-possible evidence; should still be a no-op.
    outcomes = _bulk_outcomes(tool="alpha", n=100, state=STATE_REVERTED)
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=EvolutionConfig(enabled=False, min_history=5),
    )
    assert out is static
    assert PolicyEvolver().explain(
        static, store, config=EvolutionConfig(enabled=False, min_history=5),
    ) == []


def test_default_config_is_disabled():
    """The Phase G spec says: "default off". Verify."""
    cfg = EvolutionConfig()
    assert cfg.enabled is False


# ── 8. explain() correctness ───────────────────────────────────────────


def test_explain_returns_adjustments_with_correct_evidence(tmp_path):
    static = _custom_static_policy(allowed_tools=("alpha", "beta"))
    outcomes = (
        _bulk_outcomes(tool="alpha", n=10, state=STATE_REVERTED, sig="a")
        # beta has good stats — should not be restricted.
        + _bulk_outcomes(tool="beta", n=10, state=STATE_MERGED, sig="b")
    )
    store = _make_store(tmp_path, outcomes)
    adjustments = PolicyEvolver().explain(
        static, store, config=_enabled_config(min_history=5),
    )
    assert len(adjustments) == 1
    adj = adjustments[0]
    assert adj.kind == "tool"
    assert adj.name == "alpha"
    assert adj.evidence_count == 10
    assert adj.success_rate == pytest.approx(0.0)
    assert adj.reason == "low_success_rate"


def test_explain_empty_when_no_history(tmp_path):
    static = _custom_static_policy()
    store = _make_store(tmp_path, [])
    assert PolicyEvolver().explain(
        static, store, config=_enabled_config(),
    ) == []


# ── 9. Static-policy non-mutation invariant ────────────────────────────


def test_static_policy_is_never_mutated(tmp_path):
    """Frozen-dataclass plus identity check: after a restrictive
    compute, the static reference must be unchanged."""
    static = _custom_static_policy(allowed_tools=("alpha", "beta"))
    snapshot_tools = static.allowed_tools
    snapshot_caps = static.allowed_capabilities

    outcomes = _bulk_outcomes(tool="alpha", n=10, state=STATE_REVERTED)
    store = _make_store(tmp_path, outcomes)
    PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(min_history=5),
    )

    assert static.allowed_tools == snapshot_tools
    assert static.allowed_capabilities == snapshot_caps


def test_returned_policy_is_a_new_instance_when_restricted(tmp_path):
    static = _custom_static_policy(allowed_tools=("alpha", "beta"))
    outcomes = _bulk_outcomes(tool="alpha", n=10, state=STATE_REVERTED)
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(min_history=5),
    )
    assert out is not static
    assert isinstance(out, BrainPolicy)
    assert out.mode == static.mode  # other fields preserved


# ── 10. Telemetry ──────────────────────────────────────────────────────


def test_restriction_emits_per_adjustment_telemetry(tmp_path):
    from infra.brain.telemetry.collector import _current_telemetry

    static = _custom_static_policy(allowed_tools=("alpha", "beta"))
    outcomes = (
        _bulk_outcomes(tool="alpha", n=10, state=STATE_REVERTED, sig="a")
        + _bulk_outcomes(tool="beta", n=10, state=STATE_REVERTED, sig="b")
    )
    store = _make_store(tmp_path, outcomes)

    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        PolicyEvolver().compute_dynamic_policy(
            static, store, config=_enabled_config(min_history=5),
        )
    finally:
        _current_telemetry.reset(token)

    restriction_calls = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == EVENT_POLICY_DYNAMIC_RESTRICTION
    ]
    assert len(restriction_calls) == 2  # one per tool dropped

    resolved_calls = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == EVENT_POLICY_DYNAMIC_RESOLVED
    ]
    assert len(resolved_calls) == 1
    assert resolved_calls[0].kwargs["tools_dropped"] == 2


def test_explain_does_not_emit_telemetry(tmp_path):
    """``explain()`` is read-only audit — must not call emit."""
    from infra.brain.telemetry.collector import _current_telemetry

    static = _custom_static_policy(allowed_tools=("alpha",))
    outcomes = _bulk_outcomes(tool="alpha", n=10, state=STATE_REVERTED)
    store = _make_store(tmp_path, outcomes)

    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        PolicyEvolver().explain(
            static, store, config=_enabled_config(min_history=5),
        )
    finally:
        _current_telemetry.reset(token)

    assert fake.emit.call_args_list == []


# ── 11. Outcomes without touched_tools contribute zero ────────────────


def test_outcomes_with_empty_touched_tools_are_ignored(tmp_path):
    """Phase D outcomes (which all have ``touched_tools=()``) must
    contribute zero to per-tool stats — backwards-compat invariant."""
    static = _custom_static_policy(allowed_tools=("alpha",))
    # 100 untagged outcomes — should not move any per-tool needle.
    outcomes = [
        _outcome(patch=f"p{i}", state=STATE_REVERTED, touched_tools=())
        for i in range(100)
    ]
    store = _make_store(tmp_path, outcomes)
    out = PolicyEvolver().compute_dynamic_policy(
        static, store, config=_enabled_config(min_history=5),
    )
    assert out is static  # nothing to attribute


# ── 12. Real-NarAI integration smoke ───────────────────────────────────


def test_narai_static_policy_unchanged_with_no_evidence(tmp_path):
    """Sanity: feed the production NARAI_POLICY through the evolver
    with empty history and confirm we get the same instance back."""
    store = _make_store(tmp_path, [])
    out = PolicyEvolver().compute_dynamic_policy(
        NARAI_POLICY, store, config=_enabled_config(min_history=5),
    )
    assert out is NARAI_POLICY
