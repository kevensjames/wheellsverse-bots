"""Unit tests for the low-level ``ToolExecutor`` permission gate.

Distinct from ``test_executor_agent.py``: that one tests the *agent*-level
executor (which walks plans). This one tests the *tool*-level executor
(which gates a single ``tool.run`` call).
"""
from __future__ import annotations

import pytest

from infra.brain.interface import (
    BrainClient,
    BrainPolicy,
    Tool,
    ToolNotFoundError,
    ToolPermissionError,
    ToolRegistry,
)
from infra.brain.tools.executor import ToolExecutor


def _tool_ok(name: str = "ok_tool"):
    async def _run(input):
        return {"echoed": input}
    return Tool(
        name=name, description="x", run=_run,
        schema={"type": "object", "properties": {}, "required": []},
    )


def _tool_raise():
    async def _run(input):
        raise RuntimeError("broken")
    return Tool(
        name="broken", description="x", run=_run,
        schema={"type": "object", "properties": {}, "required": []},
    )


def _permissive_policy(mode: str = "test_permissive") -> BrainPolicy:
    """Construct an unrestricted policy for tests that exercise the
    *executor mechanics* rather than the policy gate.

    Phase B made the predefined NARAI policy a true allowlist; tests that
    previously leaned on NarAI's unrestricted behavior switch to this
    helper so they keep testing what they were meant to test.
    """
    return BrainPolicy(
        mode=mode,
        tone="test",
        system_prompt="test",
        memory_enabled=False,
        rag_enabled=False,
        tools_enabled=True,
        allowed_tools=None,             # unrestricted by name
        allowed_capabilities=None,      # capability gate off
    )


# ── Permission gate ─────────────────────────────────────────────────────────


async def test_tool_executor_denies_unauthorized():
    reg = ToolRegistry()
    reg.register(_tool_ok("shell_exec"))
    nai = BrainClient(user_id="alice", mode="nai", tool_registry=reg)

    with pytest.raises(ToolPermissionError) as exc:
        await nai.use_tool("shell_exec", {})
    # Subclass of stdlib PermissionError so existing handlers catch it
    assert isinstance(exc.value, PermissionError)
    assert "nai" in str(exc.value)
    assert "shell_exec" in str(exc.value)

    # Telemetry recorded the denial
    events = [e["event_type"] for e in nai.telemetry.flush()]
    assert "tool_denied" in events
    # tool_start must NOT fire — denied calls never reach run()
    assert "tool_start" not in events


async def test_tool_executor_allows_safe_tool_under_nai_policy():
    """SAFE_TOOLS includes ``web_search`` — NAI policy authorizes it."""
    reg = ToolRegistry()
    reg.register(_tool_ok("web_search"))
    nai = BrainClient(user_id="alice", mode="nai", tool_registry=reg)
    out = await nai.use_tool("web_search", {"x": 1})
    assert out == {"echoed": {"x": 1}}


async def test_tool_executor_unrestricted_under_permissive_policy():
    """A custom policy with ``allowed_tools=None`` allows every tool.

    Pre-Phase-B this test used NarAI directly; NarAI is now a true allowlist
    so we exercise the unrestricted path via an explicit custom policy.
    """
    reg = ToolRegistry()
    reg.register(_tool_ok("anything_goes"))
    client = BrainClient(
        user_id="owner", policy=_permissive_policy(), tool_registry=reg,
    )
    out = await client.use_tool("anything_goes", {})
    assert out["echoed"] == {}


# ── Existence gate ──────────────────────────────────────────────────────────


async def test_tool_executor_raises_not_found():
    # Permissive policy: name check passes, registry lookup raises.
    client = BrainClient(
        user_id="owner", policy=_permissive_policy(),
        tool_registry=ToolRegistry(),
    )
    with pytest.raises(ToolNotFoundError) as exc:
        await client.use_tool("does_not_exist", {})
    # Subclass of stdlib KeyError
    assert isinstance(exc.value, KeyError)

    events = [e["event_type"] for e in client.telemetry.flush()]
    assert "tool_not_found" in events


# ── Tool exception propagates verbatim ──────────────────────────────────────


async def test_tool_executor_propagates_tool_exception():
    reg = ToolRegistry()
    reg.register(_tool_raise())
    client = BrainClient(
        user_id="owner", policy=_permissive_policy(), tool_registry=reg,
    )

    with pytest.raises(RuntimeError, match="broken"):
        await client.use_tool("broken", {})

    events = [e["event_type"] for e in client.telemetry.flush()]
    # Both start and error fire — start happens before the run call
    assert "tool_start" in events
    assert "tool_error" in events


# ── Latency telemetry ───────────────────────────────────────────────────────


async def test_tool_executor_records_per_tool_latency():
    reg = ToolRegistry()
    reg.register(_tool_ok("metered"))
    client = BrainClient(
        user_id="owner", policy=_permissive_policy(), tool_registry=reg,
    )
    await client.use_tool("metered", {})
    await client.use_tool("metered", {})
    lat = client.telemetry.get_stats()["latencies_ms"]
    assert "tool:metered" in lat
    assert lat["tool:metered"]["count"] == 2


# ── allows_tool / available_tools ──────────────────────────────────────────


def test_allows_tool_uses_policy_directly():
    nai = BrainClient(user_id="alice", mode="nai", tool_registry=ToolRegistry())
    assert nai.allows_tool("web_search") is True       # SAFE_TOOLS
    assert nai.allows_tool("shell_exec") is False      # not in SAFE_TOOLS

    # Phase B audit hardening (Critical Issue #1): NarAI is no longer
    # unrestricted. The default allowlist contains exactly the names
    # listed in NARAI_POLICY.allowed_tools.
    narai = BrainClient(user_id="owner", mode="narai", tool_registry=ToolRegistry())
    assert narai.allows_tool("web_search") is True     # in NARAI allowlist
    assert narai.allows_tool("anything") is False      # NOT in allowlist


def test_available_tools_intersects_registry_and_policy():
    reg = ToolRegistry()
    reg.register(_tool_ok("web_search"))   # in SAFE_TOOLS
    reg.register(_tool_ok("shell_exec"))   # NOT in SAFE_TOOLS

    nai = BrainClient(user_id="alice", mode="nai", tool_registry=reg)
    narai = BrainClient(user_id="owner", mode="narai", tool_registry=reg)

    # NAI: only the SAFE_TOOLS-listed name appears
    assert "web_search" in nai.available_tools()
    assert "shell_exec" not in nai.available_tools()
    # Phase B: NarAI's allowlist is now ("web_search",); shell_exec
    # is no longer auto-authorized by virtue of unrestricted policy.
    assert set(narai.available_tools()) == {"web_search"}
    assert "shell_exec" not in narai.available_tools()


# ── Telemetry-disabled path is a no-op ─────────────────────────────────────


async def test_tool_executor_no_telemetry_when_disabled():
    reg = ToolRegistry()
    reg.register(_tool_ok())
    c = BrainClient(
        user_id="silent",
        policy=_permissive_policy("test_silent"),
        tool_registry=reg, telemetry_enabled=False,
    )
    await c.use_tool("ok_tool", {})
    assert c.telemetry.flush() == []
    assert c.telemetry.get_stats()["events"] == {}
