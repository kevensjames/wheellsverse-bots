"""infra.brain.tools.registry — tool definitions + registry.

A ``Tool`` is a frozen, named, async callable with a description. Tools live
in a ``ToolRegistry`` which is the single source of truth for what's
available; ``ToolExecutor`` looks tools up there before running them.

A module-level :func:`default_registry` is the registry every
``BrainClient`` uses unless a caller explicitly passes its own (for tests
or per-request scopes).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


# A tool's run function takes a single dict of inputs and returns anything
# JSON-serializable (dict / list / scalar). Async-only, so the executor can
# always ``await`` without branching.
ToolRun = Callable[[dict], Awaitable[Any]]


@dataclass(frozen=True)
class Tool:
    """Immutable tool definition.

    Fields
    ------
    name:
        Stable identifier the policy authorizes against. Must match exactly
        what appears in ``BrainPolicy.allowed_tools`` for restricted modes.
    description:
        One-line human-readable description. Surfaces in tool catalogs and
        the LLM tool-use system prompt.
    run:
        Async callable: ``await run(input_dict)`` → result. Must not catch
        ``PermissionError`` — the executor raises that *before* run is
        invoked.
    schema:
        Optional JSON Schema (object type) describing the ``input`` dict
        ``run`` expects. When present, the tool is *planner-visible* — the
        :class:`BrainClient` tool-calling loop advertises it to the LLM.
        When ``None``, the tool is still executable via ``use_tool`` but the
        agent loop will not list it. This is the on/off switch for "expose
        to the LLM planner".
    capabilities:
        Frozen set of capability tokens (see
        :data:`infra.brain.policy.VALID_CAPABILITIES`) describing what
        side-effects the tool can have:
        ``read_only``, ``mutating``, ``network``, ``shell``, ``cost_bearing``.

        Default is an *empty set* — meaning "unspecified, opt-out of the
        capability gate". Tools that declare a non-empty set become
        subject to :meth:`infra.brain.policy.BrainPolicy.allows`'s
        capability check whenever the policy specifies
        ``allowed_capabilities``. New tools should declare capabilities
        explicitly so future policy tightening is automatic; existing
        tools keep working unchanged with the empty default.
    """

    name: str
    description: str
    run: ToolRun
    schema: Optional[dict] = None
    capabilities: frozenset[str] = field(default_factory=frozenset)


class ToolRegistry:
    """In-memory registry of available tools, keyed by name.

    Registration is one-shot per name — re-registering raises ``ValueError``
    so accidental shadowing is caught at import time rather than at first
    call. Use :meth:`replace` for explicit hot-swapping.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool. Raises ``ValueError`` if the name is taken."""
        if tool.name in self._tools:
            raise ValueError(
                f"Tool already registered: {tool.name!r}. Use replace() to overwrite."
            )
        self._tools[tool.name] = tool

    def replace(self, tool: Tool) -> Optional[Tool]:
        """Force-overwrite. Returns the previous tool if any."""
        prev = self._tools.get(tool.name)
        self._tools[tool.name] = tool
        return prev

    def unregister(self, name: str) -> Optional[Tool]:
        """Remove a tool. Returns the removed tool, or ``None`` if absent."""
        return self._tools.pop(name, None)

    def get(self, name: str) -> Tool:
        """Look up a tool by name. Raises ``KeyError`` if not registered."""
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"No such tool: {name!r}")

    # The user spec asks for ``list()`` — we honour the name even though it
    # shadows the builtin inside method bodies; we never use ``list()`` here.
    def list(self) -> list[str]:
        """Return the registered tool names, sorted."""
        return sorted(self._tools)

    def all(self) -> list[Tool]:
        """Return every registered :class:`Tool` (sorted by name)."""
        return [self._tools[n] for n in sorted(self._tools)]

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


# ── Module-level default registry ────────────────────────────────────────────
#
# A single shared registry that BrainClient uses by default. Tools registered
# here are visible to every BrainClient. Tests and per-request scopes can
# bypass this by passing their own ToolRegistry to BrainClient.

_default_registry: ToolRegistry = ToolRegistry()


def default_registry() -> ToolRegistry:
    """Return the process-wide default registry."""
    return _default_registry


def register(tool: Tool) -> None:
    """Convenience: register a tool in the default registry."""
    _default_registry.register(tool)


__all__ = [
    "Tool",
    "ToolRun",
    "ToolRegistry",
    "default_registry",
    "register",
]
