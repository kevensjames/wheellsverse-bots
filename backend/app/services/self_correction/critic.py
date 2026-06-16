"""Critic — judges KAI's draft response against the user's prompt.

Routes through the CHEAP adapter (Cloudflare Llama) by default because:
  - Critique is short-form classification, not generation — small models
    are fine for it
  - One self-correction loop = 1-2 critic calls; we want each to cost
    ~$0.0001 not ~$0.01
  - Falls back to OpenAI if Cloudflare is unavailable (the router already
    has this fallback wired)

The critic is instructed to return a JSON verdict. We parse with a
forgiving extractor so the LLM doesn't have to be perfect with quoting
— stripping markdown code fences if it wraps them, hunting for the
first {...} block if it adds prose.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


SEVERITIES = ("none", "minor", "major", "critical")
DEFAULT_CRITIC_MAX_TOKENS = 400
DEFAULT_CRITIC_TEMPERATURE = 0.2  # Critic should be consistent, not creative


@dataclass(slots=True)
class Verdict:
    """A critic's judgement on a draft response."""
    ok: bool                           # True if no major+ issues
    severity: str                      # none / minor / major / critical
    critique: str                      # 1-3 sentences explaining the verdict
    suggestions: list[str] = field(default_factory=list)  # actionable fixes
    raw: str = ""                      # the critic's full text reply (for audit)

    @property
    def needs_revision(self) -> bool:
        """True if the draft needs another pass through the reviser."""
        return not self.ok and self.severity in ("major", "critical")


_CRITIC_SYSTEM_PROMPT = (
    "You are a strict but fair critic of an AI assistant's draft response. "
    "You will be given the USER's original message and the ASSISTANT's "
    "draft reply. Judge the draft on three dimensions:\n"
    "  1. Did it actually answer what the user asked? (relevance)\n"
    "  2. Are factual claims accurate, or does it hallucinate?\n"
    "  3. If the draft promised to do something (call a tool, return a "
    "list, follow a format), did it follow through?\n"
    "\n"
    "Return ONLY a JSON object with this exact shape:\n"
    "{\n"
    '  "ok": true|false,\n'
    '  "severity": "none"|"minor"|"major"|"critical",\n'
    '  "critique": "1-3 sentences",\n'
    '  "suggestions": ["short", "concrete", "actionable"]\n'
    "}\n"
    "\n"
    "Severity guide:\n"
    "  none     — flawless\n"
    "  minor    — small phrasing / completeness nit; reply is still usable\n"
    "  major    — answer is wrong, off-topic, or fails a promise; needs revision\n"
    "  critical — hallucinated facts, broken format, dangerous advice\n"
    "\n"
    "ok=true only when severity is none or minor."
)


def critique(
    *,
    user_message: str,
    draft_response: str,
    router,  # type: app.services.router.router.Router
    prefer_local: bool = False,
    max_tokens: int = DEFAULT_CRITIC_MAX_TOKENS,
) -> tuple[Verdict, float]:
    """Run one critic pass. Returns (Verdict, cost_in_usd).

    `router` is the same Router instance the chat uses — we tap into its
    adapters directly so we don't re-pay the intent-classification cost.
    `prefer_local` forces routing through Ollama (matches admin_chat's
    flag, useful for offline / privacy-sensitive prompts).

    The critic prompt is short and structured, so we don't use the
    full chat loop — just one direct adapter call.
    """
    adapter = _pick_critic_adapter(router, prefer_local=prefer_local)
    msgs = [
        {
            "role": "user",
            "content": (
                f"USER MESSAGE:\n{user_message.strip()}\n\n"
                f"ASSISTANT DRAFT REPLY:\n{draft_response.strip()}\n\n"
                "Now return the JSON verdict."
            ),
        }
    ]
    result = _call_adapter_complete(
        adapter,
        msgs,
        max_tokens=max_tokens,
        temperature=DEFAULT_CRITIC_TEMPERATURE,
        system=_CRITIC_SYSTEM_PROMPT,
    )
    if result is None:
        # Fail-open: if the critic can't run, we don't block the reply.
        # The original draft becomes the final answer.
        return _open_pass_verdict(reason=f"critic adapter {adapter.name} unavailable"), 0.0

    text = (result.content or "").strip()
    cost = _result_cost(result)
    verdict = _parse_verdict(text)
    return verdict, cost


# ─── internals ──────────────────────────────────────────────────────


def _call_adapter_complete(adapter, msgs, *, max_tokens, temperature, system):
    """Call adapter.complete() with broad compat.

    Adapters have drift across the project (OpenAI/Anthropic/CF take a
    `tools` kwarg, Ollama does not). We try with `tools=None` first; on
    TypeError for the `tools` kwarg specifically, retry without it.
    Other errors → log + return None so the caller can fail-open.
    """
    try:
        return adapter.complete(
            msgs,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            tools=None,
        )
    except TypeError as e:
        if "tools" in str(e):
            try:
                return adapter.complete(
                    msgs,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                )
            except Exception as e2:
                logger.warning(
                    "self_correction: adapter %s retry failed: %s",
                    getattr(adapter, "name", "?"), e2,
                )
                return None
        logger.warning(
            "self_correction: adapter %s failed: %s",
            getattr(adapter, "name", "?"), e,
        )
        return None
    except Exception as e:
        logger.warning(
            "self_correction: adapter %s failed: %s",
            getattr(adapter, "name", "?"), e,
        )
        return None


def _pick_critic_adapter(router, *, prefer_local: bool):
    """Pick the cheap adapter for critic calls.

    Preference:
      1. prefer_local=True → ollama
      2. cloudflare (cheap Llama 3 — pennies per critic call)
      3. openai (fallback if cloudflare not configured)
      4. whatever's in router.adapters first
    """
    adapters = getattr(router, "adapters", {}) or {}
    if prefer_local and "ollama" in adapters:
        return adapters["ollama"]
    for name in ("cloudflare", "openai", "anthropic"):
        if name in adapters:
            return adapters[name]
    # Last resort: first adapter we can find
    for a in adapters.values():
        return a
    raise RuntimeError("self_correction: router has no adapters configured")


def _result_cost(result) -> float:
    """CompletionResult has cost on a few possible attrs depending on adapter."""
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def _open_pass_verdict(reason: str) -> Verdict:
    """When the critic itself fails, default to 'reply as-is'. Reasoning:
    a failed critic should never block a user's response."""
    return Verdict(
        ok=True,
        severity="none",
        critique=f"critic unavailable ({reason}); reply passed through",
        suggestions=[],
        raw="",
    )


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_verdict(text: str) -> Verdict:
    """Forgiving parser. Strips ```json fences, finds the first {...}
    block, falls back to fail-open if all else fails."""
    if not text:
        return _open_pass_verdict(reason="empty critic reply")

    # Strip code fences if the model wrapped them
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    blob = _extract_json_block(cleaned)
    if not blob:
        # Model returned prose instead of JSON. Treat as "OK with note"
        # rather than blocking — defensive.
        logger.warning("self_correction: critic returned non-JSON, fail-open")
        return Verdict(
            ok=True, severity="none",
            critique=f"critic returned non-JSON: {text[:120]}",
            suggestions=[], raw=text,
        )

    try:
        d = json.loads(blob)
    except json.JSONDecodeError as e:
        logger.warning("self_correction: critic JSON parse failed: %s", e)
        return Verdict(
            ok=True, severity="none",
            critique=f"critic JSON unparseable: {e}",
            suggestions=[], raw=text,
        )

    severity = str(d.get("severity") or "none").strip().lower()
    if severity not in SEVERITIES:
        severity = "none"

    return Verdict(
        ok=bool(d.get("ok", severity in ("none", "minor"))),
        severity=severity,
        critique=str(d.get("critique") or "").strip(),
        suggestions=[str(s).strip() for s in (d.get("suggestions") or []) if s],
        raw=text,
    )


def _extract_json_block(s: str) -> str:
    """Find the first balanced {...} block. We can't rely on a regex
    alone because the JSON might contain nested objects — walk the
    bracket count instead."""
    start = s.find("{")
    if start == -1:
        return ""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return ""
