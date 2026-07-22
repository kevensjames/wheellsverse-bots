"""MCP (Model Context Protocol) client integration for KAI.

Lets KAI consume external MCP servers (filesystem, git, postgres,
community-built servers) and expose their tools to the chat loop
alongside our native tools.

Architecture:
- Config file uses the same shape as Claude Desktop's
  `claude_desktop_config.json` so operators can paste-in known configs:

      {
        "mcpServers": {
          "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
          }
        }
      }

- At daemon startup, `load_mcp_tools()` reads the config (if any),
  spawns each MCP server briefly to discover its tool catalog, then
  wraps each discovered tool in an `MCPTool` adapter that fits KAI's
  existing sync Tool protocol.

- On invocation, the adapter spawns the server again, runs the tool,
  and tears down. Per-call subprocess startup costs ~1-3s for `npx`
  servers — acceptable for v1 since tool work itself is the dominant
  latency. v2 can pool persistent sessions.

Tier gate:
- MCP servers can do real things (write files, push commits). Inherit
  the chat endpoint's paid-tier gate — same pattern as Composio.

Config discovery order:
  1. Env var KAI_MCP_CONFIG_PATH (explicit path)
  2. Repo-root mcp_config.json (convention)
  3. None — MCP tools simply not registered, daemon runs normally.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Per-call timeout. MCP servers can hang on bad inputs; we want a hard
# ceiling rather than blocking the chat loop indefinitely.
DEFAULT_TIMEOUT_SECONDS = 30.0

# Max chars returned to the LLM. Some MCP servers can emit huge results
# (e.g. filesystem list of /); we truncate before injection to protect
# the context window.
MAX_RESULT_CHARS = 8_000


@dataclass(slots=True)
class MCPServerSpec:
    """Parsed entry from the config file."""
    label: str  # operator-given name ("filesystem")
    command: str
    args: list[str]
    env: dict[str, str] | None = None
    cwd: str | None = None


def _resolve_config_path() -> Path | None:
    """Find an MCP config to load. Returns None when no config is configured."""
    env_path = os.environ.get("KAI_MCP_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        logger.warning("KAI_MCP_CONFIG_PATH=%s but file not found", env_path)
        return None
    # Convention fallback — repo-root mcp_config.json
    candidate = Path(__file__).resolve().parents[3] / "mcp_config.json"
    if candidate.exists():
        return candidate
    return None


def _parse_config(path: Path) -> list[MCPServerSpec]:
    raw = json.loads(path.read_text())
    servers_block = raw.get("mcpServers") or {}
    specs: list[MCPServerSpec] = []
    for label, cfg in servers_block.items():
        if not isinstance(cfg, dict):
            logger.warning("mcp config: skipping %s (not an object)", label)
            continue
        cmd = cfg.get("command")
        if not cmd:
            logger.warning("mcp config: skipping %s (no command)", label)
            continue
        specs.append(
            MCPServerSpec(
                label=label,
                command=cmd,
                args=list(cfg.get("args") or []),
                env=cfg.get("env") or None,
                cwd=cfg.get("cwd") or None,
            )
        )
    return specs


async def _discover_tools(spec: MCPServerSpec) -> list[dict[str, Any]]:
    """Spawn the server, list its tools, tear down. Returns the tool catalog."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=spec.command,
        args=spec.args,
        env=spec.env,
        cwd=spec.cwd,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema or {"type": "object", "properties": {}},
                }
                for t in result.tools
            ]


async def _call_tool(spec: MCPServerSpec, tool_name: str, args: dict[str, Any]) -> str:
    """Spawn the server, call one tool, tear down. Returns concatenated text content."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=spec.command,
        args=spec.args,
        env=spec.env,
        cwd=spec.cwd,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=args)
            parts: list[str] = []
            for c in result.content or []:
                # MCP content types: text, image, embedded resource.
                # We only flatten text for the LLM context window.
                text = getattr(c, "text", None)
                if text:
                    parts.append(text)
            return "\n\n".join(parts)


class MCPTool:
    """Adapter: makes an MCP-discovered tool look like a KAI sync Tool.

    Each MCP tool is exposed with the namespaced name
    ``mcp_<server-label>__<tool-name>`` so it can't collide with native
    KAI tools (web_fetch, memory, etc.).
    """

    # MCP servers can expose file/git writes and we can't reliably tell read
    # from write per tool, so treat ALL MCP tools as side-effecting (default
    # deny in the LLM loop unless the operator authorizes writes).
    writes = True

    def __init__(self, spec: MCPServerSpec, tool_meta: dict[str, Any]):
        self._spec = spec
        self._upstream_name = tool_meta["name"]
        self.name = f"mcp_{spec.label}__{tool_meta['name']}"
        self.description = (
            f"[via MCP server '{spec.label}'] " + (tool_meta.get("description") or "")
        )
        self.parameters = tool_meta.get("inputSchema") or {
            "type": "object", "properties": {}
        }

    def execute(self, ctx, **kwargs) -> dict[str, Any]:
        """Bridge sync KAI tool execution to the SDK's async API.

        Each call runs a fresh asyncio.run because the chat loop is sync
        and we don't want to thread an event-loop through every tool's
        signature. The wait_for cap prevents a runaway MCP server from
        blocking the chat indefinitely.
        """
        async def _run():
            return await asyncio.wait_for(
                _call_tool(self._spec, self._upstream_name, kwargs),
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
        try:
            text = asyncio.run(_run())
        except asyncio.TimeoutError:
            from app.services.tools.base import ToolError
            raise ToolError(
                f"MCP tool '{self.name}' timed out after "
                f"{DEFAULT_TIMEOUT_SECONDS}s"
            )
        except Exception as e:
            from app.services.tools.base import ToolError
            raise ToolError(f"MCP tool '{self.name}' failed: {e}") from e

        truncated = False
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS]
            truncated = True
        return {
            "server": self._spec.label,
            "tool": self._upstream_name,
            "text": text,
            "chars": len(text),
            "truncated": truncated,
        }


def load_mcp_tools() -> list[MCPTool]:
    """Return adapter-wrapped MCP tools, or [] when no config is present.

    Connection failures are logged and skipped (per-server) so a broken
    MCP entry doesn't take down the whole tool registry.
    """
    cfg_path = _resolve_config_path()
    if cfg_path is None:
        logger.info("mcp: no config found (set KAI_MCP_CONFIG_PATH to enable)")
        return []

    try:
        specs = _parse_config(cfg_path)
    except json.JSONDecodeError as e:
        logger.error("mcp config %s is not valid JSON: %s", cfg_path, e)
        return []
    except Exception as e:
        logger.error("mcp config %s could not be read: %s", cfg_path, e)
        return []

    tools: list[MCPTool] = []
    for spec in specs:
        try:
            catalog = asyncio.run(
                asyncio.wait_for(_discover_tools(spec), timeout=15.0)
            )
        except Exception as e:
            logger.warning(
                "mcp: skipping server '%s' — discovery failed: %s",
                spec.label, e,
            )
            continue
        for meta in catalog:
            tools.append(MCPTool(spec, meta))
        logger.info(
            "mcp: loaded %d tools from server '%s'", len(catalog), spec.label,
        )
    return tools
