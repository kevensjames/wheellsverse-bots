"""Memory layer tests.

Requires a live Postgres at TEST_DATABASE_URL with pgvector available.
The shared conftest provides `db_session` and `free_user` (which we use here
because the existing User fixture covers the FK shape we need).
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

# These exercise the real embedding path (app/services/memory/embeddings.py
# raises RuntimeError("OPENAI_API_KEY not set")), so they need a live key. Skip
# rather than fail when one isn't configured — an unrunnable test is not a
# regression, and 7 permanent reds train people to ignore the suite.
pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="needs a live OPENAI_API_KEY (real embedding calls)",
)

from app.services.memory.retrieval import format_for_prompt, search_memories
from app.services.memory.store import (
    MemoryStoreError,
    add_memories_bulk,
    add_memory,
    count_memories,
    delete_memory,
    get_memory,
)


def test_add_memory_persists(db_session, free_user):
    m = add_memory(
        db_session,
        user_id=free_user.id,
        content="User lives in Taunton, MA",
        memory_type="fact",
    )
    db_session.commit()

    fetched = get_memory(db_session, m.id)
    assert fetched is not None
    assert fetched.content == "User lives in Taunton, MA"
    assert fetched.memory_type == "fact"
    assert len(fetched.embedding) == 1536


def test_add_memory_rejects_invalid_type(db_session, free_user):
    with pytest.raises(MemoryStoreError):
        add_memory(db_session, user_id=free_user.id, content="x", memory_type="wrong")


def test_add_memory_rejects_empty_content(db_session, free_user):
    with pytest.raises(MemoryStoreError):
        add_memory(db_session, user_id=free_user.id, content="   ", memory_type="note")


def test_bulk_insert(db_session, free_user):
    add_memories_bulk(
        db_session,
        user_id=free_user.id,
        items=[
            ("Loves espresso", "preference"),
            ("Met with investor on Tuesday", "event"),
            ("Building WheellsVerse", "fact"),
        ],
    )
    db_session.commit()
    assert count_memories(db_session, free_user.id) == 3


def test_delete_memory(db_session, free_user):
    m = add_memory(db_session, user_id=free_user.id, content="temp", memory_type="note")
    db_session.commit()
    assert delete_memory(db_session, m.id) is True
    db_session.commit()
    assert get_memory(db_session, m.id) is None


def test_delete_missing_returns_false(db_session, free_user):
    assert delete_memory(db_session, uuid.uuid4()) is False


def test_semantic_match(db_session, free_user):
    add_memories_bulk(
        db_session,
        user_id=free_user.id,
        items=[
            ("User has two cats named Luna and Mochi", "fact"),
            ("Favorite programming language is Python", "preference"),
            ("Lives in Taunton, Massachusetts", "fact"),
            ("Working on a stock trading SaaS called WheellsVerse", "fact"),
            ("Prefers direct, no-fluff communication", "preference"),
        ],
    )
    db_session.commit()

    results = search_memories(
        db_session, user_id=free_user.id, query="where does the user live"
    )
    assert results, "expected at least one result"
    assert any("Taunton" in r.content for r in results[:2])


def test_type_filter(db_session, free_user):
    add_memories_bulk(
        db_session,
        user_id=free_user.id,
        items=[
            ("Owns a cat", "fact"),
            ("Likes cats", "preference"),
        ],
    )
    db_session.commit()

    only_prefs = search_memories(
        db_session,
        user_id=free_user.id,
        query="cats",
        memory_type="preference",
    )
    assert only_prefs
    assert all(r.memory_type == "preference" for r in only_prefs)


def test_format_for_prompt_empty():
    assert format_for_prompt([]) == ""


def test_format_for_prompt_lists_memories(db_session, free_user):
    add_memory(
        db_session,
        user_id=free_user.id,
        content="Lives in Boston",
        memory_type="fact",
    )
    db_session.commit()
    results = search_memories(db_session, user_id=free_user.id, query="where lives")
    formatted = format_for_prompt(results)
    assert "Relevant memories" in formatted
    assert "Lives in Boston" in formatted


def test_search_bumps_last_used(db_session, free_user):
    add_memories_bulk(
        db_session,
        user_id=free_user.id,
        items=[("User likes espresso", "preference")],
    )
    db_session.commit()

    first = search_memories(db_session, user_id=free_user.id, query="coffee preferences")
    assert first
    first_ts = first[0].last_used_at
    db_session.commit()

    time.sleep(1)
    search_memories(db_session, user_id=free_user.id, query="coffee preferences")
    db_session.commit()

    db_session.expire_all()
    third = search_memories(
        db_session,
        user_id=free_user.id,
        query="coffee preferences",
        bump_last_used=False,
    )
    assert third[0].last_used_at > first_ts
