"""Main router. Chooses an adapter based on intent + spend state."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Iterator

from app.services.router.adapters.base import Adapter, calculate_cost
from app.services.router.intent import classify_intent
from app.services.router.spend_tracker import SpendTracker
from app.services.router.types import CompletionResult, Intent, to_message_dicts

logger = logging.getLogger(__name__)


REQUIRED_ADAPTERS = frozenset({"openai", "anthropic", "perplexity", "ollama"})


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

    def select(
        self,
        intent: Intent,
        user_id: uuid.UUID,
        prefer_local: bool = False,
    ) -> Adapter:
        if prefer_local:
            logger.info("routing to ollama (prefer_local)")
            return self.adapters["ollama"]

        if self.spend.over_daily_cap(user_id):
            logger.warning("user %s over daily cap — routing to ollama", user_id)
            return self.adapters["ollama"]

        if intent == Intent.CODE:
            return self.adapters["anthropic"]
        if intent == Intent.REALTIME:
            return self.adapters["perplexity"]
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
