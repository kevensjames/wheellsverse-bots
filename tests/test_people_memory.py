"""
tests/test_people_memory.py — unit tests for core/people_memory.py

The module persists to a module-level DATA_FILE path. Each test patches that
path to a fresh temp file and constructs a standalone PeopleMemory() instance
(not the process-wide singleton) so state never leaks between tests.
"""
from datetime import datetime, timedelta, timezone

import pytest

from core import people_memory
from core.people_memory import (
    COLD_LEAD_DAYS,
    MAX_MESSAGES_PER_PERSON,
    VIP_INTERACTION_THRESHOLD,
    PeopleMemory,
    PersonRecord,
)


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setattr(people_memory, "DATA_FILE", tmp_path / "people_memory.json")
    return PeopleMemory()


# ── PersonRecord scoring ──────────────────────────────────────────────────────

def test_engagement_score_combines_signals():
    p = PersonRecord("twitter:1", "twitter")
    p.interaction_count = 2          # +10
    p.sentiment_score = 0.5          # +10
    p.affiliate_clicks = ["amazon"]  # +10
    p.converted = True               # +50
    p.purchase_stage = "warm"        # +10
    assert p.engagement_score == pytest.approx(90.0)


def test_is_vip_by_interaction_count_or_stage():
    p = PersonRecord("x:1", "x")
    assert p.is_vip is False
    p.interaction_count = VIP_INTERACTION_THRESHOLD
    assert p.is_vip is True
    p2 = PersonRecord("x:2", "x")
    p2.purchase_stage = "vip"
    assert p2.is_vip is True


def test_is_cold_based_on_last_seen():
    fresh = PersonRecord("x:1", "x")
    assert fresh.is_cold is False
    old = PersonRecord("x:2", "x")
    old.last_seen = (
        datetime.now(timezone.utc) - timedelta(days=COLD_LEAD_DAYS + 1)
    ).isoformat()
    assert old.is_cold is True


def test_is_cold_handles_bad_timestamp():
    p = PersonRecord("x:1", "x")
    p.last_seen = "not-a-date"
    assert p.is_cold is True


def test_top_interest():
    p = PersonRecord("x:1", "x")
    assert p.top_interest == "general"
    p.topics_mentioned = {"crypto": 3, "ai": 1}
    assert p.top_interest == "crypto"


def test_to_dict_from_dict_roundtrip():
    p = PersonRecord("twitter:7", "twitter", handle="bob")
    p.name = "Bob"
    p.tags = ["vip"]
    p.interaction_count = 4
    p.topics_mentioned = {"crypto": 2}
    p.intents = ["buy"]
    restored = PersonRecord.from_dict(p.to_dict())
    assert restored.uid == "twitter:7"
    assert restored.handle == "bob"
    assert restored.name == "Bob"
    assert restored.tags == ["vip"]
    assert restored.interaction_count == 4
    assert restored.topics_mentioned == {"crypto": 2}


# ── get_or_create ─────────────────────────────────────────────────────────────

def test_uid_is_lowercased(mem):
    assert mem._uid("Twitter", "ABC") == "twitter:ABC"


def test_get_or_create_is_idempotent_and_backfills_handle(mem):
    p1 = mem.get_or_create("twitter", "1")
    p2 = mem.get_or_create("twitter", "1", handle="alice")
    assert p1 is p2
    assert p2.handle == "alice"


# ── remember ──────────────────────────────────────────────────────────────────

def test_remember_records_message_and_increments_inbound(mem):
    p = mem.remember("twitter", "1", "hello", direction="inbound",
                     intent="greeting", topic="crypto", sentiment_delta=0.3)
    assert p.interaction_count == 1
    assert len(p.messages) == 1
    assert p.messages[0]["text"] == "hello"
    assert p.intents == ["greeting"]
    assert p.topics_mentioned == {"crypto": 1}
    assert p.sentiment_score == pytest.approx(0.3)


def test_remember_outbound_does_not_increment_interactions(mem):
    p = mem.remember("twitter", "1", "hi there", direction="outbound")
    assert p.interaction_count == 0


def test_remember_caps_message_length(mem):
    p = mem.remember("twitter", "1", "x" * 1000)
    assert len(p.messages[0]["text"]) == 500


def test_remember_caps_message_history(mem):
    for i in range(MAX_MESSAGES_PER_PERSON + 20):
        mem.remember("twitter", "1", f"msg {i}")
    p = mem.get_or_create("twitter", "1")
    assert len(p.messages) == MAX_MESSAGES_PER_PERSON


def test_sentiment_is_clamped(mem):
    for _ in range(10):
        mem.remember("twitter", "1", "great", sentiment_delta=0.5)
    assert mem.get_or_create("twitter", "1").sentiment_score == 1.0
    for _ in range(20):
        mem.remember("twitter", "1", "awful", sentiment_delta=-0.5)
    assert mem.get_or_create("twitter", "1").sentiment_score == -1.0


def test_intents_capped_at_20(mem):
    for i in range(30):
        mem.remember("twitter", "1", "x", intent=f"intent{i}")
    assert len(mem.get_or_create("twitter", "1").intents) == 20


# ── stage advancement ─────────────────────────────────────────────────────────

def test_affiliate_click_advances_to_hot(mem):
    mem.remember("twitter", "1", "hi")
    mem.record_affiliate_click("twitter", "1", "amazon")
    assert mem.get_or_create("twitter", "1").purchase_stage == "hot"


def test_mark_converted_sets_customer(mem):
    mem.remember("twitter", "1", "hi")
    mem.mark_converted("twitter", "1")
    p = mem.get_or_create("twitter", "1")
    assert p.converted is True
    assert p.purchase_stage == "customer"


def test_customer_becomes_vip_at_threshold(mem):
    mem.remember("twitter", "1", "hi")
    mem.mark_converted("twitter", "1")
    for _ in range(VIP_INTERACTION_THRESHOLD - 1):
        mem.remember("twitter", "1", "hi")
    assert mem.get_or_create("twitter", "1").purchase_stage == "vip"


# ── tags / notes ──────────────────────────────────────────────────────────────

def test_add_tag_deduplicates(mem):
    mem.add_tag("twitter", "1", "vip")
    mem.add_tag("twitter", "1", "vip")
    assert mem.get_or_create("twitter", "1").tags == ["vip"]


def test_set_note(mem):
    mem.set_note("twitter", "1", "knows me from launch")
    assert mem.get_or_create("twitter", "1").notes == "knows me from launch"


# ── relationship prompt ───────────────────────────────────────────────────────

def test_relationship_prompt_for_new_person(mem):
    prompt = mem.get_relationship_prompt("twitter", "unknown")
    assert "new person" in prompt.lower()


def test_relationship_prompt_includes_context(mem):
    mem.remember("twitter", "1", "I love crypto", intent="interest",
                 topic="crypto", handle="alice", sentiment_delta=0.5)
    prompt = mem.get_relationship_prompt("twitter", "1")
    assert "alice" in prompt
    assert "crypto" in prompt
    assert "Interactions: 1" in prompt


# ── segment queries ───────────────────────────────────────────────────────────

def _seed(mem):
    mem.remember("twitter", "vip", "hi", handle="vip")
    for _ in range(VIP_INTERACTION_THRESHOLD):
        mem.remember("twitter", "vip", "hi")
    mem.remember("instagram", "cust", "hi")
    mem.mark_converted("instagram", "cust")
    mem.add_tag("twitter", "vip", "founder")
    mem.remember("twitter", "warm", "hi", topic="ai")


def test_get_all_sorted_by_engagement_and_platform_filter(mem):
    _seed(mem)
    all_people = mem.get_all()
    scores = [p["engagement_score"] for p in all_people]
    assert scores == sorted(scores, reverse=True)
    tw = mem.get_all(platform="twitter")
    assert all(p["platform"] == "twitter" for p in tw)


def test_get_vip_and_customer_lists(mem):
    _seed(mem)
    assert any(p["uid"] == "twitter:vip" for p in mem.get_vip_list())
    assert any(p["uid"] == "instagram:cust" for p in mem.get_customers())


def test_get_by_tag_and_topic(mem):
    _seed(mem)
    assert [p["uid"] for p in mem.get_by_tag("founder")] == ["twitter:vip"]
    assert [p["uid"] for p in mem.get_by_topic("ai")] == ["twitter:warm"]


def test_search_matches_handle(mem):
    mem.remember("twitter", "1", "hi", handle="alice_wonder")
    assert mem.search("wonder")
    assert mem.search("nomatch") == []


def test_get_person_returns_none_when_missing(mem):
    assert mem.get_person("twitter", "ghost") is None


def test_summary_counts(mem):
    _seed(mem)
    s = mem.summary()
    assert s["total_people"] == 3
    assert s["customers"] == 1
    assert s["vip"] >= 1
    assert "by_platform" in s and s["by_platform"]["twitter"] == 2


# ── persistence ───────────────────────────────────────────────────────────────

def test_state_persists_across_instances(tmp_path, monkeypatch):
    path = tmp_path / "people_memory.json"
    monkeypatch.setattr(people_memory, "DATA_FILE", path)
    m1 = PeopleMemory()
    m1.remember("twitter", "1", "hello", handle="alice")
    assert path.exists()
    m2 = PeopleMemory()
    assert m2.get_person("twitter", "1")["handle"] == "alice"


def test_load_survives_corrupt_file(tmp_path, monkeypatch):
    path = tmp_path / "people_memory.json"
    path.write_text("{ not valid json")
    monkeypatch.setattr(people_memory, "DATA_FILE", path)
    m = PeopleMemory()  # should not raise
    assert m.get_all() == []


# ── module-level convenience wrappers ─────────────────────────────────────────

def test_module_level_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(people_memory, "DATA_FILE", tmp_path / "pm.json")
    monkeypatch.setattr(PeopleMemory, "_instance", None)
    people_memory.remember("twitter", "1", "hey", handle="alice")
    assert "alice" in people_memory.get_context("twitter", "1")
