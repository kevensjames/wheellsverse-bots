"""infra.brain.policy — formal behavior contract for each brain mode.

Every behavior decision the brain makes (tone, memory recall, RAG injection,
tool authorization) reads from a single :class:`BrainPolicy` object.
``BrainClient`` resolves a mode string to a frozen policy at construction
time and never inspects the mode string again — every gate, prompt, and
authorization check goes through the policy.

Adding a new mode is a one-place change: register a new ``BrainPolicy`` in
:data:`_REGISTRY` below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── Tool-access scope ────────────────────────────────────────────────────────
#
# The tools layer doesn't ship yet — these names are the contract the future
# tool dispatcher will read from. Listing them here, frozen on the policy,
# means the gate is decided in *one* place before any executor is wired.

#: Tools considered safe for the consumer surface: read-only, side-effect-free.
SAFE_TOOLS: tuple[str, ...] = (
    "web_search",
    "read_file",
    "recall_memory",
    "query_rag",
)


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
        Master switch for the (forthcoming) tools layer. When False, no
        tool may run regardless of :attr:`allowed_tools`.
    allowed_tools:
        ``None`` ⇒ unrestricted (all tools allowed when ``tools_enabled``).
        Tuple ⇒ explicit whitelist of tool names. Empty tuple ⇒ no tools.

    Use :meth:`allows_tool` rather than reading ``allowed_tools`` directly —
    it composes ``tools_enabled`` and the whitelist into one decision.
    """

    mode: str
    tone: str
    system_prompt: str
    memory_enabled: bool
    rag_enabled: bool
    tools_enabled: bool
    allowed_tools: Optional[tuple[str, ...]] = None

    def allows_tool(self, tool_name: str) -> bool:
        """Single source of truth for tool authorization."""
        if not self.tools_enabled:
            return False
        if self.allowed_tools is None:
            return True
        return tool_name in self.allowed_tools


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
)


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
    allowed_tools=None,  # unrestricted
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
    "get_policy",
    "available_modes",
]
