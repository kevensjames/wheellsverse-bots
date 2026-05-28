"""Brain integration tests.

Uses the existing db_session + free_user fixtures, with a scripted router and
an empty ToolRegistry so we don't hit any external API. Validates persistence,
conversation ownership, and SSE event shape.

Requires a reachable Postgres (TEST_DATABASE_URL) — the shared conftest
creates the schema from Base.metadata. Skipped when TEST_DATABASE_URL is unset
or unreachable.

Note: the existing free_user fixture inserts into the local ``users`` table.
In production, conversations/messages.user_id FKs to ``profiles.id``. For
these tests against a fresh local DB created by Base.metadata.create_all(),
the FK target ``profiles`` does not exist; conftest tweaks are an operator
follow-up. See decision log 0005.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterator

import pytest

from app.models.conversation import Conversation, Message
from app.services.nai_brain import Brain
from app.services.router.types import CompletionResult
from app.services.tools.registry import ToolRegistry


@dataclass
class ScriptedRouter:
    completion: CompletionResult

    def complete(self, **kwargs):
        return self.completion

    def chat(self, **kwargs):
        return self.completion

    def stream(self, **kwargs) -> Iterator[str]:
        for chunk in ["hel", "lo", " world"]:
            yield chunk


def _result(text: str = "hi") -> CompletionResult:
    return CompletionResult(
        content=text,
        adapter="openai",
        model="gpt-4o-mini",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.0001,
        latency_ms=50,
    )


def test_chat_creates_conversation_and_persists_both_messages(db_session, free_user):
    brain = Brain(
        session=db_session,
        router=ScriptedRouter(_result("hello there")),
        registry=ToolRegistry(),
    )
    conv, msg, cost = brain.chat(
        user_id=free_user.id,
        conversation_id=None,
        user_message="hi there",
    )
    assert conv.user_id == free_user.id
    assert conv.title == "hi there"
    assert msg.role == "assistant"
    assert msg.content == "hello there"
    assert msg.adapter == "openai"
    assert msg.model_used == "gpt-4o-mini"
    assert float(msg.cost_usd) == pytest.approx(0.0001)

    rows = (
        db_session.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
        .all()
    )
    assert [r.role for r in rows] == ["user", "assistant"]
    assert conv.message_count == 2


def test_chat_resumes_existing_conversation(db_session, free_user):
    brain = Brain(
        session=db_session,
        router=ScriptedRouter(_result("ok")),
        registry=ToolRegistry(),
    )
    conv, _, _ = brain.chat(
        user_id=free_user.id, conversation_id=None, user_message="first"
    )
    brain.chat(
        user_id=free_user.id, conversation_id=conv.id, user_message="second"
    )

    rows = (
        db_session.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
        .all()
    )
    assert len(rows) == 4
    assert [r.role for r in rows] == ["user", "assistant", "user", "assistant"]


def test_chat_rejects_foreign_conversation(db_session, free_user):
    # Path X: create a profile row directly for the "other" user. The
    # conversations.user_id FK targets profiles.id, so this is what the FK
    # needs to satisfy. profiles.id has no server_default in code (prod
    # supplies it via the auth.users.id trigger) — mint one explicitly.
    import uuid as _uuid
    from app.models.profile import Profile

    other_profile = Profile(
        id=_uuid.uuid4(), email="other@test.com", name="other", tier="free"
    )
    db_session.add(other_profile)
    db_session.commit()
    db_session.refresh(other_profile)

    other = Conversation(user_id=other_profile.id, title="other")
    db_session.add(other)
    db_session.commit()

    brain = Brain(
        session=db_session,
        router=ScriptedRouter(_result()),
        registry=ToolRegistry(),
    )
    with pytest.raises(ValueError, match="not found"):
        brain.chat(
            user_id=free_user.id,
            conversation_id=other.id,
            user_message="x",
        )


def test_stream_yields_meta_then_deltas_then_done(db_session, free_user):
    brain = Brain(
        session=db_session,
        router=ScriptedRouter(_result()),
        registry=ToolRegistry(),
    )
    events = list(
        brain.stream(
            user_id=free_user.id,
            conversation_id=None,
            user_message="stream me",
        )
    )
    types = [e["type"] for e in events]
    assert types[0] == "meta"
    assert "delta" in types
    assert types[-1] == "done"

    streamed = "".join(e["content"] for e in events if e["type"] == "delta")
    assert streamed == "hello world"

    # assistant row persisted with the full streamed content
    assistant_rows = (
        db_session.query(Message)
        .filter(Message.role == "assistant")
        .order_by(Message.created_at.desc())
        .all()
    )
    assert assistant_rows[0].content == "hello world"


def test_chat_uses_tool_loop_when_use_tools_true(db_session, free_user):
    """use_tools=True should hit router.chat (not router.complete)."""

    calls = {"complete": 0, "chat": 0}

    @dataclass
    class TrackingRouter:
        completion: CompletionResult

        def complete(self, **kwargs):
            calls["complete"] += 1
            return self.completion

        def chat(self, **kwargs):
            calls["chat"] += 1
            return self.completion

        def stream(self, **kwargs):
            yield ""

    brain = Brain(
        session=db_session,
        router=TrackingRouter(_result("done")),
        registry=ToolRegistry(),
    )
    brain.chat(
        user_id=free_user.id,
        conversation_id=None,
        user_message="use tools please",
        use_tools=True,
    )
    assert calls == {"complete": 0, "chat": 1}
