"""Unit tests for the low-level ``ToolExecutor`` permission gate.

Distinct from ``test_executor_agent.py``: that one tests the *agent*-level
executor (which walks plans). This one tests the *tool*-level executor
(which gates a single ``tool.run`` call).
"""
from __future__ import annotations

import pytest

from infra.brain.interface import (
    BrainClient,
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


async def test_tool_executor_unrestricted_under_narai_policy():
    """NarAI policy has ``allowed_tools=None`` → all tools allowed."""
    reg = ToolRegistry()
    reg.register(_tool_ok("anything_goes"))
    narai = BrainClient(user_id="owner", mode="narai", tool_registry=reg)
    out = await narai.use_tool("anything_goes", {})
    assert out["echoed"] == {}


# ── Existence gate ──────────────────────────────────────────────────────────


async def test_tool_executor_raises_not_found():
    narai = BrainClient(user_id="owner", mode="narai", tool_registry=ToolRegistry())
    with pytest.raises(ToolNotFoundError) as exc:
        await narai.use_tool("does_not_exist", {})
    # Subclass of stdlib KeyError
    assert isinstance(exc.value, KeyError)

    events = [e["event_type"] for e in narai.telemetry.flush()]
    assert "tool_not_found" in events


# ── Tool exception propagates verbatim ──────────────────────────────────────


async def test_tool_executor_propagates_tool_exception():
    reg = ToolRegistry()
    reg.register(_tool_raise())
    narai = BrainClient(user_id="owner", mode="narai", tool_registry=reg)

    with pytest.raises(RuntimeError, match="broken"):
        await narai.use_tool("broken", {})

    events = [e["event_type"] for e in narai.telemetry.flush()]
    # Both start and error fire — start happens before the run call
    assert "tool_start" in events
    assert "tool_error" in events


# ── Latency telemetry ───────────────────────────────────────────────────────


async def test_tool_executor_records_per_tool_latency():
    reg = ToolRegistry()
    reg.register(_tool_ok("metered"))
    narai = BrainClient(user_id="owner", mode="narai", tool_registry=reg)
    await narai.use_tool("metered", {})
    await narai.use_tool("metered", {})
    lat = narai.telemetry.get_stats()["latencies_ms"]
    assert "tool:metered" in lat
    assert lat["tool:metered"]["count"] == 2


# ── allows_tool / available_tools ──────────────────────────────────────────


def test_allows_tool_uses_policy_directly():
    nai = BrainClient(user_id="alice", mode="nai", tool_registry=ToolRegistry())
    assert nai.allows_tool("web_search") is True       # SAFE_TOOLS
    assert nai.allows_tool("shell_exec") is False      # not in SAFE_TOOLS

    narai = BrainClient(user_id="owner", mode="narai", tool_registry=ToolRegistry())
    assert narai.allows_tool("anything") is True       # unrestricted


def test_available_tools_intersects_registry_and_policy():
    reg = ToolRegistry()
    reg.register(_tool_ok("web_search"))   # in SAFE_TOOLS
    reg.register(_tool_ok("shell_exec"))   # NOT in SAFE_TOOLS

    nai = BrainClient(user_id="alice", mode="nai", tool_registry=reg)
    narai = BrainClient(user_id="owner", mode="narai", tool_registry=reg)

    # NAI: only the SAFE_TOOLS-listed name appears
    assert "web_search" in nai.available_tools()
    assert "shell_exec" not in nai.available_tools()
    # NarAI: both appear (unrestricted)
    assert set(narai.available_tools()) == {"web_search", "shell_exec"}


# ── Telemetry-disabled path is a no-op ─────────────────────────────────────


async def test_tool_executor_no_telemetry_when_disabled():
    reg = ToolRegistry()
    reg.register(_tool_ok())
    c = BrainClient(
        user_id="silent", mode="narai",
        tool_registry=reg, telemetry_enabled=False,
    )
    await c.use_tool("ok_tool", {})
    assert c.telemetry.flush() == []
    assert c.telemetry.get_stats()["events"] == {}
