"""MCP integration tests.

We don't spin up a real MCP server in unit tests — that would require
npx/uvx in the test environment and a deterministic server. Instead we
mock the SDK functions at the seam (_discover_tools, _call_tool) and
test the dispatcher logic, adapter behavior, and registry integration.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import MagicMock

import pytest

from app.services import mcp_tools
from app.services.mcp_tools import MCPServerSpec, MCPTool
from app.services.tools.base import ToolContext, ToolError


# ─── config parsing ──────────────────────────────────────────────────


def _write_cfg(tmp_path, data):
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps(data))
    return p


def test_parse_config_minimal(tmp_path):
    cfg = _write_cfg(tmp_path, {
        "mcpServers": {
            "fs": {"command": "npx", "args": ["-y", "@m/fs", "/data"]},
        }
    })
    specs = mcp_tools._parse_config(cfg)
    assert len(specs) == 1
    assert specs[0].label == "fs"
    assert specs[0].command == "npx"
    assert specs[0].args == ["-y", "@m/fs", "/data"]
    assert specs[0].env is None


def test_parse_config_with_env_and_cwd(tmp_path):
    cfg = _write_cfg(tmp_path, {
        "mcpServers": {
            "pg": {
                "command": "uvx",
                "args": ["mcp-server-postgres"],
                "env": {"DATABASE_URL": "postgres://..."},
                "cwd": "/tmp",
            },
        }
    })
    specs = mcp_tools._parse_config(cfg)
    assert specs[0].env == {"DATABASE_URL": "postgres://..."}
    assert specs[0].cwd == "/tmp"


def test_parse_config_skips_entries_without_command(tmp_path):
    cfg = _write_cfg(tmp_path, {
        "mcpServers": {
            "good": {"command": "npx", "args": []},
            "bad":  {"args": ["forgot-the-command"]},   # no `command`
        }
    })
    specs = mcp_tools._parse_config(cfg)
    assert len(specs) == 1
    assert specs[0].label == "good"


def test_parse_config_missing_mcpServers_block(tmp_path):
    cfg = _write_cfg(tmp_path, {"otherKey": "junk"})
    specs = mcp_tools._parse_config(cfg)
    assert specs == []


def test_resolve_config_path_env_var(tmp_path, monkeypatch):
    cfg = _write_cfg(tmp_path, {"mcpServers": {}})
    monkeypatch.setenv("KAI_MCP_CONFIG_PATH", str(cfg))
    assert mcp_tools._resolve_config_path() == cfg


def test_resolve_config_path_env_var_missing_file_returns_none(monkeypatch):
    monkeypatch.setenv("KAI_MCP_CONFIG_PATH", "/tmp/does-not-exist.json")
    # The env var IS set, but the file is missing — should log + return None,
    # never raise.
    assert mcp_tools._resolve_config_path() is None


# ─── adapter behavior ────────────────────────────────────────────────


def _make_tool(monkeypatch, spec_label="fs", upstream_name="read_file",
               returned_text="hello from MCP"):
    """Build an MCPTool with the SDK call mocked."""
    spec = MCPServerSpec(label=spec_label, command="echo", args=["mocked"])
    meta = {
        "name": upstream_name,
        "description": "read a file's contents",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    }

    async def fake_call(_spec, _name, _args):
        return returned_text

    monkeypatch.setattr(mcp_tools, "_call_tool", fake_call)
    return MCPTool(spec, meta)


def test_mcp_tool_name_is_namespaced(monkeypatch):
    tool = _make_tool(monkeypatch)
    # mcp_<label>__<upstream-name> — guarantees no collision with native tools
    assert tool.name == "mcp_fs__read_file"


def test_mcp_tool_description_mentions_server(monkeypatch):
    tool = _make_tool(monkeypatch)
    assert "via MCP server 'fs'" in tool.description


def test_mcp_tool_execute_returns_text(monkeypatch):
    tool = _make_tool(monkeypatch, returned_text="file contents here")
    ctx = ToolContext(user_id=uuid.uuid4(), session=MagicMock())
    out = tool.execute(ctx, path="/some/file.txt")
    assert out["server"] == "fs"
    assert out["tool"] == "read_file"
    assert out["text"] == "file contents here"
    assert out["truncated"] is False


def test_mcp_tool_execute_truncates_large_output(monkeypatch):
    huge = "x" * (mcp_tools.MAX_RESULT_CHARS + 5000)
    tool = _make_tool(monkeypatch, returned_text=huge)
    ctx = ToolContext(user_id=uuid.uuid4(), session=MagicMock())
    out = tool.execute(ctx, path="/big.txt")
    assert len(out["text"]) == mcp_tools.MAX_RESULT_CHARS
    assert out["truncated"] is True


def test_mcp_tool_execute_wraps_exceptions_as_tool_error(monkeypatch):
    async def fake_call_fails(_s, _n, _a):
        raise RuntimeError("upstream MCP exploded")
    monkeypatch.setattr(mcp_tools, "_call_tool", fake_call_fails)
    spec = MCPServerSpec(label="fs", command="echo", args=[])
    tool = MCPTool(spec, {"name": "x", "description": "", "inputSchema": {}})
    ctx = ToolContext(user_id=uuid.uuid4(), session=MagicMock())
    with pytest.raises(ToolError, match="MCP tool .* failed"):
        tool.execute(ctx)


def test_mcp_tool_timeout_raises_tool_error(monkeypatch):
    """Slow MCP servers must not hang the chat loop — TimeoutError is
    wrapped into a ToolError so the LLM gets a recoverable failure."""
    async def fake_call_hangs(_s, _n, _a):
        await asyncio.sleep(60)
        return "never reached"
    monkeypatch.setattr(mcp_tools, "_call_tool", fake_call_hangs)
    monkeypatch.setattr(mcp_tools, "DEFAULT_TIMEOUT_SECONDS", 0.05)
    spec = MCPServerSpec(label="slow", command="echo", args=[])
    tool = MCPTool(spec, {"name": "x", "description": "", "inputSchema": {}})
    ctx = ToolContext(user_id=uuid.uuid4(), session=MagicMock())
    with pytest.raises(ToolError, match="timed out"):
        tool.execute(ctx)


# ─── loader fallthrough ─────────────────────────────────────────────


def test_load_mcp_tools_returns_empty_when_no_config(monkeypatch):
    """No env var, no convention file → returns [] silently."""
    monkeypatch.delenv("KAI_MCP_CONFIG_PATH", raising=False)
    monkeypatch.setattr(mcp_tools, "_resolve_config_path", lambda: None)
    assert mcp_tools.load_mcp_tools() == []


def test_load_mcp_tools_returns_empty_on_broken_json(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not valid json")
    monkeypatch.setattr(mcp_tools, "_resolve_config_path", lambda: bad)
    # Should log + return [] — never raise the JSONDecodeError up.
    assert mcp_tools.load_mcp_tools() == []


def test_load_mcp_tools_skips_servers_that_fail_discovery(tmp_path, monkeypatch):
    """A broken MCP entry should NOT prevent other entries from loading."""
    cfg = _write_cfg(tmp_path, {
        "mcpServers": {
            "good": {"command": "echo", "args": []},
            "broken": {"command": "echo", "args": []},
        }
    })
    monkeypatch.setattr(mcp_tools, "_resolve_config_path", lambda: cfg)

    async def discovery(spec):
        if spec.label == "broken":
            raise RuntimeError("subprocess died")
        return [{"name": "t1", "description": "", "inputSchema": {}}]

    monkeypatch.setattr(mcp_tools, "_discover_tools", discovery)
    tools = mcp_tools.load_mcp_tools()
    assert len(tools) == 1
    assert tools[0].name == "mcp_good__t1"
