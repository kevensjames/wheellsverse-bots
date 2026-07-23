"""
tests/test_content_calendar.py — unit tests for core/content_calendar.py

Each test isolates the module-level QUEUE_FILE / CALENDAR_FILE paths to a
temp directory and uses a standalone ContentCalendar() instance so no state
leaks between tests. Network publishing paths are never exercised.
"""
from datetime import datetime, timedelta, timezone

import pytest

from core import content_calendar
from core.content_calendar import (
    OPTIMAL_TIMES,
    WEEKLY_THEMES,
    ContentCalendar,
    QueueItem,
    _platform_format,
)


@pytest.fixture
def cal(tmp_path, monkeypatch):
    monkeypatch.setattr(content_calendar, "QUEUE_FILE", tmp_path / "queue.json")
    monkeypatch.setattr(content_calendar, "CALENDAR_FILE", tmp_path / "calendar.json")
    return ContentCalendar()


# ── QueueItem ─────────────────────────────────────────────────────────────────

def test_queue_item_defaults_and_autogenerates_id():
    item = QueueItem("twitter", "post", "crypto", "2030-01-01T08:00:00+00:00")
    assert item.id and len(item.id) == 8
    assert item.status == "pending"
    assert item.account == "main"
    assert item.result == {}


def test_queue_item_roundtrip():
    item = QueueItem("instagram", "tips", "ai", "2030-01-01T09:00:00+00:00",
                     content="hello", status="published", account="shop")
    item.published_at = "2030-01-01T09:05:00+00:00"
    item.result = {"ok": True}
    restored = QueueItem.from_dict(item.to_dict())
    assert restored.id == item.id
    assert restored.platform == "instagram"
    assert restored.account == "shop"
    assert restored.status == "published"
    assert restored.result == {"ok": True}


def test_queue_item_from_dict_legacy_without_account():
    d = {
        "platform": "twitter", "content_type": "post", "topic": "x",
        "scheduled_time": "2030-01-01T08:00:00+00:00", "id": "abc123",
    }
    item = QueueItem.from_dict(d)
    assert item.account == "main"


# ── add / remove / query ──────────────────────────────────────────────────────

def test_add_defaults_schedule_to_tomorrow_optimal_time(cal):
    item = cal.add("twitter", "crypto")
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    assert item.scheduled_time.startswith(tomorrow)
    assert OPTIMAL_TIMES["twitter"][0] in item.scheduled_time
    assert cal.get_pending() == [item]


def test_add_unknown_platform_falls_back_to_default_time(cal):
    item = cal.add("myspace", "topic")
    assert "10:00" in item.scheduled_time


def test_remove(cal):
    item = cal.add("twitter", "crypto")
    assert cal.remove(item.id) is True
    assert cal.get_pending() == []
    assert cal.remove("does-not-exist") is False


def test_get_pending_filtered_and_sorted(cal):
    cal.add("twitter", "later", scheduled_time="2030-01-02T08:00:00+00:00")
    cal.add("twitter", "earlier", scheduled_time="2030-01-01T08:00:00+00:00")
    cal.add("instagram", "ig", scheduled_time="2030-01-01T08:00:00+00:00")
    tw = cal.get_pending(platform="twitter")
    assert [i.topic for i in tw] == ["earlier", "later"]
    assert len(cal.get_pending()) == 3


def test_get_due_returns_only_past_pending(cal):
    cal.add("twitter", "past", scheduled_time="2000-01-01T08:00:00+00:00")
    cal.add("twitter", "future", scheduled_time="2999-01-01T08:00:00+00:00")
    due = cal.get_due()
    assert [i.topic for i in due] == ["past"]


def test_get_due_ignores_non_pending(cal):
    item = cal.add("twitter", "past", scheduled_time="2000-01-01T08:00:00+00:00")
    cal.mark_published(item.id)
    assert cal.get_due() == []


# ── mark published / failed ───────────────────────────────────────────────────

def test_mark_published(cal):
    item = cal.add("twitter", "crypto")
    cal.mark_published(item.id, {"url": "http://x"})
    found = [i for i in cal._queue if i.id == item.id][0]
    assert found.status == "published"
    assert found.published_at
    assert found.result == {"url": "http://x"}


def test_mark_failed(cal):
    item = cal.add("twitter", "crypto")
    cal.mark_failed(item.id, "boom")
    found = [i for i in cal._queue if i.id == item.id][0]
    assert found.status == "failed"
    assert found.result == {"error": "boom"}


# ── generate_week ─────────────────────────────────────────────────────────────

def test_generate_week_default_platforms(cal):
    res = cal.generate_week(start_date="2030-01-07")  # Monday
    assert res["status"] == "generated"
    assert res["days"] == 7
    # 6 default platforms * 7 days
    assert res["items_queued"] == 42
    assert len(cal.get_pending()) == 42
    first_day = res["calendar"]["2030-01-07"]
    assert first_day["theme"] == WEEKLY_THEMES[0]["theme"]


def test_generate_week_is_idempotent(cal):
    cal.generate_week(platforms=["twitter"], start_date="2030-01-07")
    second = cal.generate_week(platforms=["twitter"], start_date="2030-01-07")
    assert second["items_queued"] == 0  # duplicates skipped
    assert len(cal.get_pending()) == 7


def test_generate_week_account_tuples(cal):
    res = cal.generate_week(
        platforms=[("instagram", "main"), ("instagram", "shop")],
        start_date="2030-01-07",
    )
    assert res["items_queued"] == 14
    day = res["calendar"]["2030-01-07"]["platforms"]
    assert "instagram" in day               # main → bare key
    assert "instagram@shop" in day          # non-main → qualified key


# ── summary ───────────────────────────────────────────────────────────────────

def test_summary_reflects_state(cal):
    a = cal.add("twitter", "a", scheduled_time="2000-01-01T08:00:00+00:00")
    b = cal.add("instagram", "b", scheduled_time="2999-01-01T08:00:00+00:00")
    cal.mark_published(a.id)
    s = cal.summary()
    assert s["total_queued"] == 2
    assert s["published"] == 1
    assert s["pending"] == 1
    assert s["pending_by_platform"] == {"instagram": 1}
    assert s["next_item"]["id"] == b.id


# ── persistence ───────────────────────────────────────────────────────────────

def test_queue_persists_across_instances(tmp_path, monkeypatch):
    monkeypatch.setattr(content_calendar, "QUEUE_FILE", tmp_path / "queue.json")
    monkeypatch.setattr(content_calendar, "CALENDAR_FILE", tmp_path / "calendar.json")
    c1 = ContentCalendar()
    item = c1.add("twitter", "crypto")
    c2 = ContentCalendar()
    assert [i.id for i in c2.get_pending()] == [item.id]


def test_load_survives_corrupt_queue(tmp_path, monkeypatch):
    qpath = tmp_path / "queue.json"
    qpath.write_text("not json")
    monkeypatch.setattr(content_calendar, "QUEUE_FILE", qpath)
    monkeypatch.setattr(content_calendar, "CALENDAR_FILE", tmp_path / "calendar.json")
    c = ContentCalendar()  # should not raise
    assert c.get_pending() == []


# ── helpers / module wrappers ─────────────────────────────────────────────────

def test_platform_format_mapping():
    assert _platform_format("twitter") == "twitter_thread"
    assert _platform_format("INSTAGRAM") == "instagram_caption"
    assert _platform_format("unknown") == "twitter_thread"


def test_module_wrappers(tmp_path, monkeypatch):
    monkeypatch.setattr(content_calendar, "QUEUE_FILE", tmp_path / "queue.json")
    monkeypatch.setattr(content_calendar, "CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr(ContentCalendar, "_instance", None)
    d = content_calendar.queue_post("twitter", "crypto", content="hi")
    assert d["platform"] == "twitter"
    assert content_calendar.get_summary()["total_queued"] == 1
