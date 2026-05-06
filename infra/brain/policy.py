"""infra.brain.policy — formal behavior contract for each brain mode.

Every behavior decision the brain makes (tone, memory recall, RAG injection,
tool authorization) reads from a single :class:`BrainPolicy` object.
``BrainClient`` resolves a mode string to a frozen policy at construction
time and never inspects the mode string again — every gate, prompt, and
authorization check goes through the policy.

Adding a new mode is a one-place change: register a new ``BrainPolicy`` in
:data:`_REGISTRY` below.

Phase B (2026-05-05) introduced two new authorization mechanisms:

  * **Capability taxonomy** — every :class:`Tool` may declare a non-empty
    ``capabilities`` set (read_only / mutating / network / shell /
    cost_bearing). When a policy specifies ``allowed_capabilities``,
    :meth:`BrainPolicy.allows` enforces the capability subset rule
    *in addition to* the name allowlist. Capabilities are opt-in — tools
    that don't declare any pass the capability gate (still subject to
    the name allowlist).
  * **NARAI is no longer unrestricted.** ``NARAI_POLICY.allowed_tools``
    is now an explicit tuple — adding a new tool requires editing this
    file. See audit Critical Issue #1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    # Type-only import to avoid a cycle (registry imports … nothing
    # that loops back, but using TYPE_CHECKING keeps policy.py loadable
    # without importing the tools layer at module import time).
    from .tools.registry import Tool


# ── Capability taxonomy ─────────────────────────────────────────────────────
#
# Stable strings, plain consts (mirroring the rest of the brain — no Enum so
# external sinks don't take a Python dependency). Capabilities describe
# *what a tool can do*, not *who runs it*.

CAPABILITY_READ_ONLY:    str = "read_only"
"""Tool only reads — no writes, no side effects, no external mutations."""

CAPABILITY_MUTATING:     str = "mutating"
"""Tool writes to local state (files, DB, in-memory caches)."""

CAPABILITY_NETWORK:      str = "network"
"""Tool makes outbound network calls (HTTP, gRPC, DNS, …)."""

CAPABILITY_SHELL:        str = "shell"
"""Tool executes a shell command or spawns a subprocess."""

CAPABILITY_COST_BEARING: str = "cost_bearing"
"""Tool incurs a billable cost (paid API, LLM call, metered service)."""

VALID_CAPABILITIES: frozenset[str] = frozenset({
    CAPABILITY_READ_ONLY, CAPABILITY_MUTATING, CAPABILITY_NETWORK,
    CAPABILITY_SHELL, CAPABILITY_COST_BEARING,
})


# ── Tool-access scope ────────────────────────────────────────────────────────

#: Tools considered safe for the consumer surface: read-only, side-effect-free.
SAFE_TOOLS: tuple[str, ...] = (
    "web_search",
    "read_file",
    "recall_memory",
    "query_rag",
)

#: Default capability set the predefined policies allow. Conservative on
#: purpose — adding a category here is a deliberate, reviewable diff.
SAFE_CAPABILITIES: frozenset[str] = frozenset({
    CAPABILITY_READ_ONLY, CAPABILITY_NETWORK,
})


# ── Policy ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BrainPolicy:
    """Frozen behavior contract for a single brain mode.

    Fields
    ------
    mode:
        Stable identifier (``"nai"`` | ``"narai"``). Used for telemetry and
        registry lookup; never branched on inside :class:`BrainClient`.
    tone:
        Short human-readable descriptor of the persona's tone — surfaces in
        logs and observability. Not the LLM prompt itself.
    system_prompt:
        Default system prompt prepended to LLM calls when the caller does
        not pass an explicit ``system=`` override.
    memory_enabled:
        When True, ``BrainClient.chat`` automatically recalls memory context
        and injects it into the system prompt.
    rag_enabled:
        When True, ``BrainClient.chat`` automatically queries RAG and
        injects the matching context.
    tools_enabled:
        Master switch for the tools layer. When False, no tool may run
        regardless of :attr:`allowed_tools` or :attr:`allowed_capabilities`.
    allowed_tools:
        ``None`` ⇒ unrestricted by NAME (capability gate may still apply).
        Tuple ⇒ explicit whitelist of tool names. Empty tuple ⇒ no tools.
    allowed_capabilities:
        ``None`` ⇒ capability gate is OFF — :meth:`allows` only checks
        the name allowlist. Set ⇒ a tool's declared capabilities must be
        a subset of this set. Tools whose capabilities set is empty pass
        the capability gate (it is opt-in for both sides — see
        :class:`infra.brain.tools.registry.Tool`).

    Authorization is layered:

      * :meth:`allows_tool` — name-only check, fast, used for back-compat
        and for hot paths where the :class:`Tool` object is not yet known.
      * :meth:`allows` — full check (name AND capabilities), used by
        :class:`infra.brain.tools.executor.ToolExecutor` AFTER the
        registry lookup, and by :meth:`BrainClient.available_tools` /
        the agent-loop tool catalog.
    """

    mode: str
    tone: str
    system_prompt: str
    memory_enabled: bool
    rag_enabled: bool
    tools_enabled: bool
    allowed_tools: Optional[tuple[str, ...]] = None
    allowed_capabilities: Optional[frozenset[str]] = None

    # ── Name-level check (existing API, backwards-compat) ────────────────

    def allows_tool(self, tool_name: str) -> bool:
        """Whether the given tool *name* is on the policy's whitelist.

        Does NOT perform a capability check — for that, prefer
        :meth:`allows`. Kept as the back-compat fast path so callers that
        don't yet hold a :class:`Tool` object work unchanged.
        """
        if not self.tools_enabled:
            return False
        if self.allowed_tools is None:
            return True
        return tool_name in self.allowed_tools

    # ── Full check (name + capabilities) ────────────────────────────────

    def allows(self, tool: "Tool") -> bool:
        """Whether the given :class:`Tool` is authorized end-to-end.

        Decision order:

          1. ``tools_enabled`` master switch.
          2. Name allowlist (same as :meth:`allows_tool`).
          3. Capability gate — if ``allowed_capabilities`` is set, the
             tool's declared capabilities (when non-empty) must be a
             subset. Tools with an empty capabilities set pass through
             (opt-in for both sides).

        Returns False on any denial. Never raises.
        """
        if not self.tools_enabled:
            return False
        if not self.allows_tool(tool.name):
            return False
        if self.allowed_capabilities is not None and tool.capabilities:
            return tool.capabilities <= self.allowed_capabilities
        return True


# ── Predefined policies ──────────────────────────────────────────────────────


NAI_POLICY: BrainPolicy = BrainPolicy(
    mode="nai",
    tone="emotional, friendly, human",
    system_prompt=(
        "You are NAI, a warm, supportive AI companion. "
        "Be concise and conversational. Avoid jargon. "
        "Lean toward emotional intelligence over technical depth."
    ),
    memory_enabled=True,
    rag_enabled=True,
    tools_enabled=True,
    allowed_tools=SAFE_TOOLS,
    allowed_capabilities=SAFE_CAPABILITIES,
)


# Phase B audit hardening (Critical Issue #1):
# Was: ``allowed_tools=None`` (unrestricted — every registered tool
# auto-authorized for NarAI). A teammate adding ``register(Tool("delete_X", ...))``
# would silently grant NarAI that capability.
#
# Now: explicit allowlist. New tools require a one-line edit here, which
# surfaces as a reviewable diff against ``policy.py``.
NARAI_POLICY: BrainPolicy = BrainPolicy(
    mode="narai",
    tone="technical, execution-focused",
    system_prompt=(
        "You are NarAI, a sharp, capable developer and automation AI. "
        "Be direct, use clear formatting, and push back when the user is "
        "wrong — respectfully. Prioritize correctness and speed."
    ),
    memory_enabled=True,
    rag_enabled=True,
    tools_enabled=True,
    allowed_tools=("web_search",),  # was None — see comment above
    allowed_capabilities=SAFE_CAPABILITIES,
)


# ── Registry ─────────────────────────────────────────────────────────────────


_REGISTRY: dict[str, BrainPolicy] = {
    NAI_POLICY.mode: NAI_POLICY,
    NARAI_POLICY.mode: NARAI_POLICY,
}


def get_policy(mode: str) -> BrainPolicy:
    """Resolve a mode identifier to its frozen :class:`BrainPolicy`."""
    try:
        return _REGISTRY[mode]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown brain mode: {mode!r} (expected one of: {known})"
        )


def available_modes() -> tuple[str, ...]:
    """Return the registered mode identifiers."""
    return tuple(sorted(_REGISTRY))


__all__ = [
    "BrainPolicy",
    "NAI_POLICY",
    "NARAI_POLICY",
    "SAFE_TOOLS",
    "SAFE_CAPABILITIES",
    # Capability vocabulary
    "CAPABILITY_READ_ONLY", "CAPABILITY_MUTATING", "CAPABILITY_NETWORK",
    "CAPABILITY_SHELL", "CAPABILITY_COST_BEARING",
    "VALID_CAPABILITIES",
    "get_policy",
    "available_modes",
]
