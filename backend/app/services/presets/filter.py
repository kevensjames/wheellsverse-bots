"""Tool-registry filter — applies a preset's whitelist to a ToolRegistry.

Returns a NEW registry containing only tools whose name matches one of
the whitelist patterns. Original registry is untouched so other concurrent
requests aren't affected.

Pattern matching uses fnmatch (shell-style wildcards). The most useful
case: `mcp_filesystem__*` matches every filesystem MCP tool the operator
configured, without us needing to know their names ahead of time.
"""
from __future__ import annotations

import fnmatch
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.presets.registry import PresetSpec
    from app.services.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def filter_registry(registry: "ToolRegistry", preset: "PresetSpec") -> "ToolRegistry":
    """Return a copy of `registry` containing only tools allowed by `preset`.

    Empty whitelist → empty registry (preset is text-only).
    No registry → returns it unchanged (caller might pass None for testing).
    """
    if registry is None:
        return registry
    if not preset.tool_whitelist:
        # Empty whitelist = text-only preset (no tools at all)
        from app.services.tools.registry import ToolRegistry
        return ToolRegistry()

    from app.services.tools.registry import ToolRegistry
    filtered = ToolRegistry()
    kept: list[str] = []
    skipped: list[str] = []
    for tool in _iter_tools(registry):
        if any(fnmatch.fnmatch(tool.name, pat) for pat in preset.tool_whitelist):
            filtered.register(tool)
            kept.append(tool.name)
        else:
            skipped.append(tool.name)
    logger.info(
        "preset[%s] tool filter: kept=%d skipped=%d "
        "(kept=%s)", preset.id, len(kept), len(skipped), kept,
    )
    return filtered


def _iter_tools(registry: "ToolRegistry"):
    """Yield Tool instances from the registry. Tolerates a couple of
    common registry shapes — different versions of ToolRegistry have
    used `.tools`, `._tools`, or implemented __iter__."""
    if hasattr(registry, "all_tools") and callable(registry.all_tools):
        yield from registry.all_tools()
        return
    if hasattr(registry, "tools"):
        attr = registry.tools
        # `.tools` might be a dict {name: tool} or a list
        if isinstance(attr, dict):
            yield from attr.values()
            return
        yield from attr
        return
    if hasattr(registry, "_tools"):
        attr = registry._tools
        if isinstance(attr, dict):
            yield from attr.values()
            return
        yield from attr
        return
    # Fallback: try iterating directly
    try:
        yield from registry
    except TypeError:
        logger.warning("preset filter: registry shape not recognized — returning empty")
        return
