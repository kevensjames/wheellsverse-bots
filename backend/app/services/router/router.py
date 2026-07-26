"""Main router. Chooses an adapter based on intent + spend state."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Iterator

from app.services import alerts
from app.services.router.adapters.base import Adapter, calculate_cost
from app.services.router.intent import classify_intent
from app.services.router.spend_tracker import SpendTracker
from app.services.router.types import CompletionResult, Intent, to_message_dicts

if TYPE_CHECKING:
    from app.services.tools.base import ToolContext
    from app.services.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


REQUIRED_ADAPTERS = frozenset({"openai"})
TOOL_CAPABLE_ADAPTERS = frozenset({"openai", "anthropic"})
DEFAULT_MAX_TOOL_ITERS = 5

# Adapters that don't expose OpenAI-style tool_calls. If the chat loop
# needs tools, we must NOT route to these — the request would silently
# return text instead of a tool invocation, breaking the loop.
TOOL_INCAPABLE_ADAPTERS = frozenset({"cloudflare", "perplexity", "ollama"})


class SpendCapExceeded(Exception):
    """The user is over their spend cap and there is no free local adapter to
    absorb the request. Raised instead of silently routing to a paid provider —
    a cap that still bills is not a cap. Callers translate this to a friendly
    402 (non-streaming) or an SSE error event (streaming)."""

    def __init__(self, cap: str = "daily"):
        self.cap = cap
        super().__init__(
            f"You've reached your {cap} usage limit. It resets at the start of the "
            f"next {cap} period."
        )


class Router:
    def __init__(
        self,
        adapters: dict[str, Adapter],
        spend_tracker: SpendTracker,
    ):
        missing = REQUIRED_ADAPTERS - set(adapters.keys())
        if missing:
            raise ValueError(f"missing adapters: {missing}")
        self.adapters = adapters
        self.spend = spend_tracker

    def _get(self, preferred: str, *, reason: str) -> Adapter:
        """Return the preferred adapter, falling back to openai when it
        isn't configured. Lets the router survive in degraded deployments
        (e.g. Perplexity/Ollama unset) without crashing the chat endpoint."""
        if preferred in self.adapters:
            return self.adapters[preferred]
        logger.warning(
            "router: %s preferred (%s) not configured — falling back to openai",
            reason, preferred,
        )
        return self.adapters["openai"]

    def _runtime_fallback(self, failed: Adapter) -> Adapter | None:
        """When a LOCAL adapter (ollama) fails at runtime — a timeout, a
        connection refusal, a wedged model — return the cloud adapter to retry
        on, or None when there's no distinct fallback.

        This is the runtime complement to ``_get``: ``_get`` covers "Ollama
        isn't configured", this covers "Ollama is configured but unresponsive".
        Together they make prefer_local genuinely fail-soft — critical now that
        local is the operator's default, since a hung local model must never
        hang the chat; it should just be slower, then yield to cloud."""
        if (
            failed.name == "ollama"
            and "openai" in self.adapters
            and self.adapters["openai"] is not failed
        ):
            return self.adapters["openai"]
        return None

    def _next_tool_brain(self, tried: set[str]) -> Adapter | None:
        """Next configured TOOL-CAPABLE adapter not yet tried this turn — for
        failing a tool loop over to the other cloud brain (e.g. OpenAI 429 →
        Anthropic) so tool-calling survives one provider being down."""
        for name in ("anthropic", "openai"):
            if name not in tried and name in self.adapters:
                return self.adapters[name]
        return None

    def _log_failure_safe(self, *, user_id, adapter: Adapter, error: str) -> None:
        """Record an adapter failure, best-effort. Spend logging hits the DB,
        and a logging hiccup must NEVER defeat the runtime fallback or mask the
        original adapter error — so swallow logging errors here."""
        try:
            self.spend.log_call(
                user_id=user_id, adapter=adapter.name, model=adapter.model,
                success=False, error_message=error,
            )
        except Exception as log_err:  # pragma: no cover - defensive
            logger.warning("router: spend.log_call swallowed: %s", log_err)

    def select(
        self,
        intent: Intent,
        user_id: uuid.UUID,
        prefer_local: bool = False,
    ) -> Adapter:
        if prefer_local:
            logger.info("routing to ollama (prefer_local)")
            return self._get("ollama", reason="prefer_local")

        # Spend caps. Route an over-cap user to the free local model if one
        # exists; otherwise REFUSE — do not fall back to paid openai (which
        # _get would do), or the cap never actually stops spending. Both the
        # daily and monthly caps are enforced (monthly was previously unchecked).
        over_monthly = self.spend.over_monthly_cap(user_id)
        if self.spend.over_daily_cap(user_id) or over_monthly:
            which = "monthly" if over_monthly else "daily"
            if "ollama" in self.adapters:
                logger.warning("user %s over %s cap — routing to local ollama", user_id, which)
                return self.adapters["ollama"]
            logger.warning("user %s over %s cap, no local adapter — refusing", user_id, which)
            raise SpendCapExceeded(which)

        if intent == Intent.CODE:
            return self._get("anthropic", reason="intent=code")
        if intent == Intent.REALTIME:
            return self._get("perplexity", reason="intent=realtime")
        if intent == Intent.SIMPLE:
            return self._get("cloudflare", reason="intent=simple")
        return self.adapters["openai"]

    def complete(
        self,
        *,
        user_id: uuid.UUID,
        messages: list[dict],
        prefer_local: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> CompletionResult:
        msgs = to_message_dicts(messages)
        user_last = next(
            (m["content"] for m in reversed(msgs) if m["role"] == "user"), ""
        )
        intent = classify_intent(user_last)
        adapter = self.select(intent, user_id, prefer_local)

        logger.info(
            "routing: intent=%s adapter=%s model=%s",
            intent.value, adapter.name, adapter.model,
        )

        try:
            result = adapter.complete(
                msgs, max_tokens=max_tokens, temperature=temperature, system=system
            )
        except Exception as e:
            self._log_failure_safe(user_id=user_id, adapter=adapter, error=str(e))
            fb = self._runtime_fallback(adapter)
            if fb is None:
                # Cloud adapter hard-failed with no runtime fallback (the common
                # case — _runtime_fallback only rescues a failed local ollama).
                # Alert before re-raising, same as stream() and chat().
                alerts.provider_alert(provider=adapter.name, exc=e, active_fallback=None)
                raise
            logger.warning(
                "router: local adapter %s failed (%s) — retrying on %s",
                adapter.name, e, fb.name,
            )
            alerts.provider_alert(provider=adapter.name, exc=e, active_fallback=fb.name)
            adapter = fb
            try:
                result = adapter.complete(
                    msgs, max_tokens=max_tokens, temperature=temperature, system=system
                )
            except Exception as e2:
                self._log_failure_safe(user_id=user_id, adapter=adapter, error=str(e2))
                alerts.provider_alert(provider=adapter.name, exc=e2, active_fallback=None)
                raise

        self.spend.log_result(user_id, result)
        return result

    def stream(
        self,
        *,
        user_id: uuid.UUID,
        messages: list[dict],
        prefer_local: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
    ) -> Iterator[str]:
        """Streaming variant. Token counts are post-hoc estimated (chars/4)
        because not every provider returns usage cleanly during streaming.
        """
        msgs = to_message_dicts(messages)
        user_last = next(
            (m["content"] for m in reversed(msgs) if m["role"] == "user"), ""
        )
        intent = classify_intent(user_last)
        adapter = self.select(intent, user_id, prefer_local)

        logger.info(
            "streaming: intent=%s adapter=%s model=%s",
            intent.value, adapter.name, adapter.model,
        )

        start = time.time()
        collected: list[str] = []
        try:
            for delta in adapter.stream(
                msgs, max_tokens=max_tokens, temperature=temperature, system=system
            ):
                collected.append(delta)
                yield delta
        except Exception as e:
            self.spend.log_call(
                user_id=user_id,
                adapter=adapter.name,
                model=adapter.model,
                success=False,
                error_message=str(e),
            )
            alerts.provider_alert(provider=adapter.name, exc=e, active_fallback=None)
            raise

        total_text = "".join(collected)
        out_tokens = max(1, len(total_text) // 4)
        in_tokens = sum(len(m["content"]) // 4 for m in msgs)
        self.spend.log_call(
            user_id=user_id,
            adapter=adapter.name,
            model=adapter.model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=calculate_cost(adapter.model, in_tokens, out_tokens),
            latency_ms=int((time.time() - start) * 1000),
            success=True,
            metadata={"streamed": True, "estimated_tokens": True},
        )

    def chat(
        self,
        *,
        user_id: uuid.UUID,
        messages: list[dict],
        tool_registry: "ToolRegistry | None" = None,
        tool_context: "ToolContext | None" = None,
        prefer_local: bool = False,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        system: str | None = None,
        max_tool_iters: int = DEFAULT_MAX_TOOL_ITERS,
    ) -> CompletionResult:
        """Orchestrated chat with optional tool loop.

        Routes to the selected adapter (same rules as complete()). When the
        adapter supports tools (openai/anthropic) and a registry is provided,
        passes the schema and runs a tool loop up to ``max_tool_iters``. Each
        LLM turn logs to ``llm_call_log``. Returns the final CompletionResult
        (one with empty ``tool_calls``).
        """
        from app.services.tools.base import ToolLoopExceededError

        if tool_registry is not None and tool_context is None:
            raise ValueError("tool_context required when tool_registry is provided")

        msgs = to_message_dicts(list(messages))
        user_last = next(
            (m["content"] for m in reversed(msgs) if m["role"] == "user"), ""
        )
        intent = classify_intent(user_last)
        adapter = self.select(intent, user_id, prefer_local)

        # Guard: SIMPLE intent routes to cloudflare for cost savings, but
        # cloudflare silently drops tools=. If a tool registry was provided
        # AND the selected adapter is tool-incapable, swap to openai so the
        # tool loop can actually work. Cost penalty is acceptable because
        # the caller explicitly opted into tools.
        if (
            tool_registry is not None
            and adapter.name in TOOL_INCAPABLE_ADAPTERS
            and "openai" in self.adapters
        ):
            logger.info(
                "chat: tools requested but %s is tool-incapable — "
                "swapping to openai", adapter.name,
            )
            adapter = self.adapters["openai"]

        tool_capable = (
            adapter.name in TOOL_CAPABLE_ADAPTERS and tool_registry is not None
        )
        tool_schema: list[dict] | None = None
        if tool_capable:
            tool_schema = (
                tool_registry.openai_schema()
                if adapter.name == "openai"
                else tool_registry.anthropic_schema()
            )

        logger.info(
            "chat: intent=%s adapter=%s model=%s tools=%s",
            intent.value, adapter.name, adapter.model, tool_capable,
        )

        last_result: CompletionResult | None = None
        tried_brains: set[str] = {adapter.name}  # tool-capable adapters tried this turn
        for _ in range(max_tool_iters + 1):
            try:
                result = adapter.complete(
                    msgs,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    tools=tool_schema,
                )
            except Exception as e:
                self._log_failure_safe(user_id=user_id, adapter=adapter, error=str(e))
                # 1. FAIL OVER to another tool-capable brain — KEEP tools. The key
                #    resilience path: OpenAI 429 → retry this turn on Anthropic, so
                #    the tool layer keeps working when one cloud brain is down.
                alt = self._next_tool_brain(tried_brains) if tool_capable else None
                if alt is not None:
                    logger.warning(
                        "chat: tool-brain %s failed (%s) — failing over to %s",
                        adapter.name, e, alt.name,
                    )
                    alerts.provider_alert(provider=adapter.name, exc=e, active_fallback=alt.name)
                    tried_brains.add(alt.name)
                    adapter = alt
                    tool_schema = (
                        tool_registry.openai_schema()
                        if alt.name == "openai"
                        else tool_registry.anthropic_schema()
                    )
                    continue  # retry this turn on the new brain
                # 2. No tool-capable brain left → DEGRADE to a plain local answer
                #    (no tools) instead of erroring, so KAI stays responsive.
                local = self.adapters.get("ollama")
                if local is not None and local is not adapter:
                    logger.warning(
                        "chat: %s failed (%s) — degrading to a plain local "
                        "answer (no tools)", adapter.name, e,
                    )
                    alerts.provider_alert(provider=adapter.name, exc=e, active_fallback=local.name)
                    try:
                        result = local.complete(
                            msgs, max_tokens=max_tokens,
                            temperature=temperature, system=system,
                        )
                    except Exception as e2:
                        self._log_failure_safe(user_id=user_id, adapter=local, error=str(e2))
                        alerts.provider_alert(provider=local.name, exc=e2, active_fallback=None)
                        raise
                    self.spend.log_result(user_id, result)
                    return result
                alerts.provider_alert(provider=adapter.name, exc=e, active_fallback=None)
                raise

            self.spend.log_result(user_id, result)
            last_result = result

            if not result.tool_calls or not tool_capable:
                return result

            msgs.append(
                {
                    "role": "assistant",
                    "content": result.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in result.tool_calls
                    ],
                }
            )

            for tc in result.tool_calls:
                tool_result = tool_registry.execute(tc.name, tc.arguments, tool_context)
                tool_result.call_id = tc.id
                # Auto-record tool failures so the next chat with a similar
                # prompt can warn the user. Silent — never break the chat
                # loop if the failure log itself fails to write.
                if tool_result.is_error:
                    try:
                        from app.services.failure_memory import record_failure
                        err_blob = tool_result.output if isinstance(
                            tool_result.output, dict
                        ) else {"error": str(tool_result.output)}
                        record_failure(
                            prompt=user_last,
                            detail=str(err_blob.get("error", "")) or "tool returned error",
                            category="tool_error",
                            tool_name=tc.name,
                            user_id=str(user_id),
                            context={
                                "arguments": _safe_args(tc.arguments),
                                "adapter": adapter.name,
                                "model": adapter.model,
                            },
                        )
                    except Exception as fm_err:
                        logger.warning(
                            "failure_memory: record_failure swallowed: %s", fm_err,
                        )
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": tool_result.as_content(),
                    }
                )

        raise ToolLoopExceededError(
            f"Tool loop exceeded {max_tool_iters} iterations; "
            f"last response had "
            f"{len(last_result.tool_calls) if last_result else 0} tool calls"
        )


def _safe_args(arguments) -> dict:
    """Strip secrets + truncate long values before logging tool arguments
    to the failure log. Mirrors the redaction the governance audit log does,
    so this can't accidentally land an API key in a grep-able file."""
    SECRET_KEY_PATTERNS = (
        "password", "secret", "token", "api_key", "apikey", "auth",
        "x-admin-token", "cookie", "bearer",
    )
    if not isinstance(arguments, dict):
        return {"_raw": str(arguments)[:200]}
    out = {}
    for k, v in arguments.items():
        if any(p in str(k).lower() for p in SECRET_KEY_PATTERNS):
            out[k] = "<redacted>"
            continue
        s = str(v)
        out[k] = s if len(s) <= 300 else s[:300] + f"… ({len(s)} chars)"
    return out
