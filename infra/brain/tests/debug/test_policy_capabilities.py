"""Tests for the Phase B Capability taxonomy on :mod:`infra.brain.policy`.

Lives under ``tests/debug/`` so the local conftest no-ops the parent
``_isolate_chroma`` fixture (the policy/registry/tools-executor modules
imported here do not touch ChromaDB / litellm — see
``tests/debug/conftest.py``).

Coverage:

  * Capability constants are stable strings + present in
    :data:`VALID_CAPABILITIES`.
  * Default ``Tool.capabilities`` is an empty frozenset (opt-out).
  * :meth:`BrainPolicy.allows_tool` is name-only (back-compat).
  * :meth:`BrainPolicy.allows` enforces both name + capability gates.
  * Tools with empty capabilities pass through the capability gate
    (opt-in for both sides).
  * Predefined ``NARAI_POLICY`` / ``NAI_POLICY`` reflect the audit
    Critical-Issue-#1 hardening.
"""
from __future__ import annotations

import pytest

from infra.brain.policy import (
    CAPABILITY_COST_BEARING,
    CAPABILITY_MUTATING,
    CAPABILITY_NETWORK,
    CAPABILITY_READ_ONLY,
    CAPABILITY_SHELL,
    BrainPolicy,
    NAI_POLICY,
    NARAI_POLICY,
    SAFE_CAPABILITIES,
    SAFE_TOOLS,
    VALID_CAPABILITIES,
)
from infra.brain.tools.registry import Tool


# ── Helpers ────────────────────────────────────────────────────────────────


async def _noop_run(input):
    return {}


def _tool(name: str, *, capabilities=None, schema=None) -> Tool:
    return Tool(
        name=name,
        description="x",
        run=_noop_run,
        schema=schema,
        capabilities=frozenset(capabilities) if capabilities else frozenset(),
    )


def _policy(
    *,
    allowed_tools=None,
    allowed_capabilities=None,
    tools_enabled: bool = True,
) -> BrainPolicy:
    return BrainPolicy(
        mode="t",
        tone="t",
        system_prompt="t",
        memory_enabled=False,
        rag_enabled=False,
        tools_enabled=tools_enabled,
        allowed_tools=allowed_tools,
        allowed_capabilities=allowed_capabilities,
    )


# ── Capability vocabulary ──────────────────────────────────────────────────


def test_capability_constants_are_stable_strings():
    for c in (
        CAPABILITY_READ_ONLY, CAPABILITY_MUTATING, CAPABILITY_NETWORK,
        CAPABILITY_SHELL, CAPABILITY_COST_BEARING,
    ):
        assert isinstance(c, str)
        assert c in VALID_CAPABILITIES


def test_valid_capabilities_size():
    assert len(VALID_CAPABILITIES) == 5


def test_safe_capabilities_subset_of_valid():
    assert SAFE_CAPABILITIES <= VALID_CAPABILITIES
    # The "safe" baseline is read_only + network — the conservative read path.
    assert SAFE_CAPABILITIES == frozenset({CAPABILITY_READ_ONLY, CAPABILITY_NETWORK})


# ── Tool.capabilities default ──────────────────────────────────────────────


def test_tool_default_capabilities_is_empty():
    tool = Tool(name="x", description="d", run=_noop_run)
    assert tool.capabilities == frozenset()


def test_tool_capabilities_field_is_frozen_set():
    tool = _tool("x", capabilities=[CAPABILITY_READ_ONLY])
    assert isinstance(tool.capabilities, frozenset)
    with pytest.raises(AttributeError):
        tool.capabilities = frozenset()  # frozen dataclass


# ── allows_tool: name-only check (backwards-compat) ────────────────────────


def test_allows_tool_disabled_master_switch():
    p = _policy(tools_enabled=False, allowed_tools=("foo",))
    assert p.allows_tool("foo") is False


def test_allows_tool_unrestricted_when_allowed_tools_is_none():
    p = _policy(allowed_tools=None)
    assert p.allows_tool("anything") is True


def test_allows_tool_restricted_to_allowlist():
    p = _policy(allowed_tools=("foo", "bar"))
    assert p.allows_tool("foo") is True
    assert p.allows_tool("bar") is True
    assert p.allows_tool("baz") is False


# ── allows: full check (name + capabilities) ──────────────────────────────


def test_allows_blocks_when_name_not_allowed():
    p = _policy(allowed_tools=("foo",))
    blocked = _tool("bar", capabilities=[CAPABILITY_READ_ONLY])
    assert p.allows(blocked) is False


def test_allows_when_name_passes_and_no_capability_gate():
    """When ``allowed_capabilities`` is ``None``, capability set is ignored."""
    p = _policy(allowed_tools=("dangerous",), allowed_capabilities=None)
    tool = _tool("dangerous", capabilities=[CAPABILITY_SHELL, CAPABILITY_MUTATING])
    assert p.allows(tool) is True


def test_allows_when_capability_subset_matches():
    p = _policy(
        allowed_tools=("web_search",),
        allowed_capabilities=frozenset({CAPABILITY_READ_ONLY, CAPABILITY_NETWORK}),
    )
    tool = _tool("web_search", capabilities=[CAPABILITY_READ_ONLY, CAPABILITY_NETWORK])
    assert p.allows(tool) is True


def test_allows_blocks_when_capability_set_exceeds_allowed():
    """Tool declares a capability the policy doesn't include → deny."""
    p = _policy(
        allowed_tools=("foo",),
        allowed_capabilities=frozenset({CAPABILITY_READ_ONLY}),
    )
    tool = _tool("foo", capabilities=[CAPABILITY_READ_ONLY, CAPABILITY_SHELL])
    assert p.allows(tool) is False


def test_allows_passes_through_when_tool_has_empty_capabilities():
    """Empty tool.capabilities → opt-out of the capability gate.

    This preserves backwards-compat with tools that never declared
    capabilities. The name allowlist is still enforced.
    """
    p = _policy(
        allowed_tools=("foo",),
        allowed_capabilities=frozenset({CAPABILITY_READ_ONLY}),
    )
    tool = _tool("foo")  # empty capabilities
    assert p.allows(tool) is True


def test_allows_blocks_when_tools_disabled():
    p = _policy(
        tools_enabled=False,
        allowed_tools=("foo",),
        allowed_capabilities=frozenset({CAPABILITY_READ_ONLY}),
    )
    tool = _tool("foo", capabilities=[CAPABILITY_READ_ONLY])
    assert p.allows(tool) is False


# ── Predefined policies after Phase B ──────────────────────────────────────


def test_narai_policy_is_no_longer_unrestricted():
    """Audit Critical Issue #1 closure assertion."""
    assert NARAI_POLICY.allowed_tools is not None
    assert "web_search" in NARAI_POLICY.allowed_tools
    # Negative: random names are NOT auto-authorized.
    assert NARAI_POLICY.allows_tool("delete_everything") is False
    assert NARAI_POLICY.allows_tool("shell_exec") is False


def test_narai_policy_capability_set_is_safe():
    assert NARAI_POLICY.allowed_capabilities == SAFE_CAPABILITIES
    # Mutating / shell / cost-bearing are NOT allowed by default.
    assert CAPABILITY_MUTATING not in NARAI_POLICY.allowed_capabilities
    assert CAPABILITY_SHELL not in NARAI_POLICY.allowed_capabilities
    assert CAPABILITY_COST_BEARING not in NARAI_POLICY.allowed_capabilities


def test_nai_policy_unchanged_name_allowlist():
    assert NAI_POLICY.allowed_tools == SAFE_TOOLS


def test_nai_policy_capability_set_now_set():
    """NAI was already restricted by name; Phase B adds capability gate too."""
    assert NAI_POLICY.allowed_capabilities == SAFE_CAPABILITIES


# ── Capability-aware denial via the predefined NarAI policy ────────────────


def test_narai_blocks_shell_capability_even_for_listed_name():
    """Hypothetical: someone replaces ``web_search`` with a tool that
    declares ``shell`` capabilities. NarAI's capability gate must reject it."""
    sneaky = _tool(
        "web_search",
        capabilities=[CAPABILITY_READ_ONLY, CAPABILITY_SHELL],
    )
    # Name passes (web_search in allowlist). Capability gate denies.
    assert NARAI_POLICY.allows_tool("web_search") is True
    assert NARAI_POLICY.allows(sneaky) is False
