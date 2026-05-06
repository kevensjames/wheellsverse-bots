"""Unit tests for the telemetry layer.

Covers:
  * Event dataclass shape + ``Event.make`` clock stamping
  * Counters: global, per-user, per-mode, snapshot
  * Histogram: percentiles, sliding window, empty-state
  * TelemetryCollector: enabled/disabled paths, record / emit /
    record_latency / flush / get_stats / clear
  * ContextVar plumbing: ``activate()`` scopes the collector and resets
    cleanly under both success and exception paths
"""
from __future__ import annotations

import pytest

from infra.brain.telemetry import (
    Counters,
    Event,
    Histogram,
    HistogramRegistry,
    TelemetryCollector,
    get_current_telemetry,
)


# ── Event ────────────────────────────────────────────────────────────────────


def test_event_make_stamps_clock():
    e = Event.make(user_id="u", mode="narai", event_type="t", metadata={"k": 1})
    assert e.user_id == "u"
    assert e.mode == "narai"
    assert e.event_type == "t"
    assert e.metadata == {"k": 1}
    assert e.timestamp > 0


def test_event_to_dict_coerces_unrepresentable_metadata():
    class Custom:
        def __repr__(self):
            return "<Custom!>"

    e = Event.make(
        user_id="u", mode="narai", event_type="t",
        metadata={"obj": Custom(), "list": [1, 2], "nested": {"a": 1}},
    )
    out = e.to_dict()
    assert out["metadata"]["obj"] == "<Custom!>"
    assert out["metadata"]["list"] == [1, 2]
    assert out["metadata"]["nested"] == {"a": 1}


def test_event_metadata_defaults_to_empty():
    e = Event(timestamp=1.0, user_id="u", mode="m", event_type="t")
    assert dict(e.metadata) == {}


# ── Counters ─────────────────────────────────────────────────────────────────


def test_counters_global_user_mode():
    c = Counters()
    c.incr("a")
    c.incr("a", user="u1", mode="narai")
    c.incr("b", user="u2", mode="nai", by=3)
    snap = c.snapshot()
    assert snap["events"] == {"a": 2, "b": 3}
    assert snap["by_user"] == {"u1": {"a": 1}, "u2": {"b": 3}}
    assert snap["by_mode"] == {"narai": {"a": 1}, "nai": {"b": 3}}


def test_counters_get_returns_zero_for_missing():
    c = Counters()
    assert c.get("nope") == 0


def test_counters_clear_resets_everything():
    c = Counters()
    c.incr("x", user="u", mode="narai")
    c.clear()
    snap = c.snapshot()
    assert snap == {"events": {}, "by_user": {}, "by_mode": {}}


# ── Histogram ───────────────────────────────────────────────────────────────


def test_histogram_empty_returns_zeroes():
    h = Histogram()
    s = h.stats()
    assert s["count"] == 0
    assert s["min"] == s["max"] == s["mean"] == 0.0


def test_histogram_basic_percentiles():
    h = Histogram()
    for v in range(1, 101):
        h.record(v)
    s = h.stats()
    assert s["count"] == 100
    assert s["min"] == 1.0
    assert s["max"] == 100.0
    assert s["mean"] == pytest.approx(50.5)
    # nearest-rank percentile is deterministic
    assert s["p50"] == 50.0 or s["p50"] == 51.0
    assert s["p95"] >= 95.0
    assert s["p99"] >= 99.0


def test_histogram_sliding_window_drops_old_samples():
    h = Histogram(max_samples=3)
    for v in [1, 2, 3, 4, 5]:
        h.record(v)
    s = h.stats()
    # Only the last 3 samples are retained.
    assert s["count"] == 3
    assert s["min"] == 3.0
    assert s["max"] == 5.0


def test_histogram_invalid_max_samples():
    with pytest.raises(ValueError):
        Histogram(max_samples=0)


def test_histogram_registry_lazy_creation():
    reg = HistogramRegistry()
    reg.record("a", 1.0)
    reg.record("b", 2.0)
    snap = reg.snapshot()
    assert set(snap.keys()) == {"a", "b"}
    assert snap["a"]["count"] == 1


# ── TelemetryCollector — recording ──────────────────────────────────────────


def test_collector_emit_records_event_and_increments_counter():
    t = TelemetryCollector(user_id="alice", mode="nai")
    t.emit("chat_start", message_len=5)
    stats = t.get_stats()
    assert stats["enabled"] is True
    assert stats["events"]["chat_start"] == 1
    assert stats["by_user"]["alice"]["chat_start"] == 1
    assert stats["by_mode"]["nai"]["chat_start"] == 1
    assert stats["buffer_size"] == 1


def test_collector_record_latency_into_named_histogram():
    t = TelemetryCollector(user_id="u", mode="m")
    t.record_latency("chat", 12.5)
    t.record_latency("chat", 22.5)
    t.record_latency("tool:web_search", 5.0)
    lat = t.get_stats()["latencies_ms"]
    assert lat["chat"]["count"] == 2
    assert lat["chat"]["mean"] == pytest.approx(17.5)
    assert lat["tool:web_search"]["count"] == 1


def test_collector_flush_drains_buffer_but_keeps_counters():
    t = TelemetryCollector(user_id="u", mode="m")
    t.emit("chat_start")
    t.emit("chat_end")
    flushed = t.flush()
    assert [e["event_type"] for e in flushed] == ["chat_start", "chat_end"]
    # Buffer is empty, but counters survive
    stats = t.get_stats()
    assert stats["buffer_size"] == 0
    assert stats["events"] == {"chat_start": 1, "chat_end": 1}


def test_collector_clear_resets_all():
    t = TelemetryCollector(user_id="u", mode="m")
    t.emit("x")
    t.record_latency("a", 1.0)
    t.clear()
    stats = t.get_stats()
    assert stats["events"] == {}
    assert stats["latencies_ms"] == {}
    assert stats["buffer_size"] == 0


def test_collector_disabled_short_circuits_everything():
    t = TelemetryCollector(user_id="u", mode="m", enabled=False)
    t.emit("x")
    t.record_latency("a", 1.0)
    flushed = t.flush()
    stats = t.get_stats()
    assert flushed == []
    assert stats["events"] == {}
    assert stats["latencies_ms"] == {}


def test_collector_set_enabled_can_toggle():
    t = TelemetryCollector(user_id="u", mode="m", enabled=False)
    t.emit("x")  # ignored
    t.set_enabled(True)
    t.emit("y")
    assert t.get_stats()["events"] == {"y": 1}


def test_collector_emit_explicit_user_mode_overrides_bound_values():
    t = TelemetryCollector(user_id="default", mode="narai")
    t.emit("x", user_id="other_user", mode="nai")
    stats = t.get_stats()
    # The Event was attributed to the explicit user/mode
    assert stats["by_user"]["other_user"]["x"] == 1
    assert stats["by_mode"]["nai"]["x"] == 1


# ── TelemetryCollector — ContextVar plumbing ────────────────────────────────


def test_get_current_telemetry_is_none_outside_activate():
    # Outside any with-block, the var is None.
    assert get_current_telemetry() is None


def test_activate_binds_collector_inside_block():
    t = TelemetryCollector(user_id="u", mode="m")
    assert get_current_telemetry() is None
    with t.activate():
        assert get_current_telemetry() is t
    assert get_current_telemetry() is None


def test_activate_resets_even_when_block_raises():
    t = TelemetryCollector(user_id="u", mode="m")
    with pytest.raises(RuntimeError, match="boom"):
        with t.activate():
            assert get_current_telemetry() is t
            raise RuntimeError("boom")
    assert get_current_telemetry() is None


def test_activate_nested_returns_to_outer():
    outer = TelemetryCollector(user_id="o", mode="m")
    inner = TelemetryCollector(user_id="i", mode="m")
    with outer.activate():
        assert get_current_telemetry() is outer
        with inner.activate():
            assert get_current_telemetry() is inner
        assert get_current_telemetry() is outer
    assert get_current_telemetry() is None


# ── Logger bridge wiring ────────────────────────────────────────────────────


def test_logger_bridge_emits_structured_record(caplog):
    """Every recorded event also fires on the ``infra.brain.telemetry`` logger.

    Operators can plumb that channel into JSON log shippers without taking a
    Python dependency on the brain — so the bridge is part of the contract.
    """
    import logging
    t = TelemetryCollector(user_id="u", mode="m")
    with caplog.at_level(logging.INFO, logger="infra.brain.telemetry"):
        t.emit("chat_start", message_len=4)
    assert any(r.message == "chat_start" for r in caplog.records)
