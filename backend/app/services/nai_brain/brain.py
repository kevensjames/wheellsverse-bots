"""NAI brain: orchestrates router + tools + memory + conversation persistence."""
from __future__ import annotations

import logging
import uuid
from typing import Iterator

from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models.conversation import Conversation, Message
from app.services.nai_brain.memory_injection import build_memory_preamble
from app.services.nai_brain.system_prompt import build_system_prompt
from app.services.router.router import Router
from app.services.tools.base import ToolContext
from app.services.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

HISTORY_WINDOW = 20
TITLE_PREVIEW_CHARS = 60


def _eq_analyze_and_record(user_message: str) -> str:
    """Per-message companion hook: detect mood (persist a non-neutral sample) and
    bump the relationship interaction counter. Returns the tone-adaptation
    preamble for the system prompt. Fully fail-open: any error (or scopes off)
    yields '' so the chat path is never affected.

    SINGLE-OPERATOR ONLY: these sidecars persist to global untenanted SQLite with
    no user_id, so they must not run multi-user (see companion_mode.py). In the
    default multi-user mode this returns '' immediately — no per-user PII is
    written to an admin-readable store, and account deletion stays complete."""
    from app.services.companion_mode import single_operator_mode
    if not single_operator_mode():
        return ""
    # Relationship: count this turn toward the shared-history bond (fail-open).
    try:
        from app.services.governance import is_scope_enabled
        if is_scope_enabled("relationship"):
            from app.services.relationship import storage as rel_storage
            rel_storage.record_interaction()
    except Exception:
        pass
    try:
        from app.services.eq.injection import analyze
        mood, confidence, preamble = analyze(user_message)
        if mood != "neutral":
            try:
                from app.services.eq import storage as eq_storage
                eq_storage.record_mood(mood, confidence, user_message)
            except Exception:  # persistence is best-effort
                pass
        return preamble
    except Exception:
        return ""


class Brain:
    def __init__(
        self,
        session: Session,
        router: Router,
        registry: ToolRegistry,
    ):
        self.session = session
        self.router = router
        self.registry = registry

    # --- Conversation management -----------------------------------------

    def get_or_create_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID | None
    ) -> Conversation:
        if conversation_id is not None:
            conv = (
                self.session.query(Conversation)
                .filter(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
                .first()
            )
            if conv is None:
                raise ValueError(f"conversation {conversation_id} not found for user")
            return conv

        conv = Conversation(user_id=user_id)
        self.session.add(conv)
        self.session.flush()
        return conv

    def list_conversations(
        self, user_id: uuid.UUID, limit: int = 50
    ) -> list[Conversation]:
        return (
            self.session.query(Conversation)
            .filter(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .all()
        )

    def get_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation | None:
        return (
            self.session.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
            .first()
        )

    # --- History building ------------------------------------------------

    def _recent_history(self, conversation_id: uuid.UUID) -> list[dict]:
        msgs = (
            self.session.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY_WINDOW)
            .all()
        )
        msgs.reverse()
        # Skip tool/system rows when re-feeding to the model — they re-emerge
        # naturally from the tool loop if tools are enabled this turn.
        return [
            {"role": m.role, "content": m.content}
            for m in msgs
            if m.role in ("user", "assistant")
        ]

    # --- Persistence helpers ---------------------------------------------

    def _save_message(
        self,
        conversation: Conversation,
        role: str,
        content: str,
        *,
        adapter: str | None = None,
        model_used: str | None = None,
        cost_usd: float | None = None,
        tool_calls: list[dict] | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        tokens_used: int | None = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation.id,
            user_id=conversation.user_id,  # denormalized, NOT NULL on live table
            role=role,
            content=content,
            adapter=adapter,
            model_used=model_used,
            cost_usd=cost_usd,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tokens_used=tokens_used,
        )
        self.session.add(msg)
        conversation.message_count = (conversation.message_count or 0) + 1
        return msg

    def _maybe_set_title(self, conv: Conversation, first_user_message: str) -> None:
        # Live default is 'New Chat'; replace it on the first real turn.
        if conv.title and conv.title != "New Chat":
            return
        preview = first_user_message.strip().splitlines()[0][:TITLE_PREVIEW_CHARS]
        conv.title = preview or "New Chat"

    # --- Main entry points -----------------------------------------------

    def chat(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        user_message: str,
        use_tools: bool = False,
        prefer_local: bool = False,
        max_tokens: int = 1024,
        persona_prompt: str = "",
        allow_writes: bool = False,
    ) -> tuple[Conversation, Message, float]:
        """Non-streaming chat. Returns (conversation, assistant_message, total_cost).

        ``persona_prompt`` is an optional expert-agent preset prompt
        (SWE / Marketing / Legal Researcher / etc.). Empty = no preset,
        chat uses the bare KAI baseline.
        """
        conv = self.get_or_create_conversation(user_id, conversation_id)
        history = self._recent_history(conv.id)
        history.append({"role": "user", "content": user_message})

        self._save_message(conv, "user", user_message)
        self._maybe_set_title(conv, user_message)

        memory_preamble = build_memory_preamble(
            self.session, user_id, user_message, k=3
        )
        eq_preamble = _eq_analyze_and_record(user_message)
        system = build_system_prompt(
            memory_preamble, persona_prompt=persona_prompt, eq_preamble=eq_preamble
        )

        if use_tools:
            ctx = ToolContext(user_id=user_id, session=self.session, allow_writes=allow_writes)
            result = self.router.chat(
                user_id=user_id,
                messages=history,
                tool_registry=self.registry,
                tool_context=ctx,
                system=system,
                max_tokens=max_tokens,
                prefer_local=prefer_local,
            )
        else:
            result = self.router.complete(
                user_id=user_id,
                messages=history,
                system=system,
                max_tokens=max_tokens,
                prefer_local=prefer_local,
            )

        assistant_msg = self._save_message(
            conv,
            "assistant",
            result.content,
            adapter=result.adapter,
            model_used=result.model,
            cost_usd=result.cost_usd,
            tokens_used=result.input_tokens + result.output_tokens,
        )

        conv.updated_at = func.now()
        self.session.commit()
        self.session.refresh(assistant_msg)
        self.session.refresh(conv)

        return conv, assistant_msg, float(result.cost_usd)

    def stream(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        user_message: str,
        prefer_local: bool = False,
        max_tokens: int = 1024,
    ) -> Iterator[dict]:
        """Streaming chat. Yields SSE-ready dicts.

        Event shapes:
          {"type": "meta",  "conversation_id": "...", "user_message_id": "..."}
          {"type": "delta", "content": "..."}
          {"type": "done",  "assistant_message_id": "..."}
          {"type": "error", "error": "..."}
        """
        conv = self.get_or_create_conversation(user_id, conversation_id)
        history = self._recent_history(conv.id)
        history.append({"role": "user", "content": user_message})

        user_msg = self._save_message(conv, "user", user_message)
        self._maybe_set_title(conv, user_message)
        self.session.commit()
        self.session.refresh(user_msg)
        self.session.refresh(conv)

        yield {
            "type": "meta",
            "conversation_id": str(conv.id),
            "user_message_id": str(user_msg.id),
        }

        memory_preamble = build_memory_preamble(
            self.session, user_id, user_message, k=3
        )
        eq_preamble = _eq_analyze_and_record(user_message)
        system = build_system_prompt(memory_preamble, eq_preamble=eq_preamble)

        collected: list[str] = []
        try:
            for delta in self.router.stream(
                user_id=user_id,
                messages=history,
                system=system,
                max_tokens=max_tokens,
                prefer_local=prefer_local,
            ):
                collected.append(delta)
                yield {"type": "delta", "content": delta}
        except Exception as e:
            logger.exception("stream failure")
            yield {"type": "error", "error": str(e)}
            return

        full_content = "".join(collected)
        # adapter/model not surfaced by router.stream() — Phase B refinement.
        assistant_msg = self._save_message(conv, "assistant", full_content)
        conv.updated_at = func.now()
        self.session.commit()
        self.session.refresh(assistant_msg)

        yield {
            "type": "done",
            "assistant_message_id": str(assistant_msg.id),
        }
