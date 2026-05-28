"""Main router. Chooses an adapter based on intent + spend state."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Iterator

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

    def select(
        self,
        intent: Intent,
        user_id: uuid.UUID,
        prefer_local: bool = False,
    ) -> Adapter:
        if prefer_local:
            logger.info("routing to ollama (prefer_local)")
            return self._get("ollama", reason="prefer_local")

        if self.spend.over_daily_cap(user_id):
            logger.warning("user %s over daily cap — routing to ollama", user_id)
            return self._get("ollama", reason="over_daily_cap")

        if intent == Intent.CODE:
            return self._get("anthropic", reason="intent=code")
        if intent == Intent.REALTIME:
            return self._get("perplexity", reason="intent=realtime")
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
            self.spend.log_call(
                user_id=user_id,
                adapter=adapter.name,
                model=adapter.model,
                success=False,
                error_message=str(e),
            )
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
                self.spend.log_call(
                    user_id=user_id,
                    adapter=adapter.name,
                    model=adapter.model,
                    success=False,
                    error_message=str(e),
                )
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
