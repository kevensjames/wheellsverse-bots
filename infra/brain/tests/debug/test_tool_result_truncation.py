"""Issue #5: ``format_tool_result`` truncation safety in
:mod:`infra.brain.tools.agent_loop`.

Pre-fix: 8000-byte cap silently appended ``" …[truncated]"`` to the
end of the rendered body. Easy for the planner LLM to miss; no
telemetry signal at all.

Post-fix:
  * The truncation event ``tool_result_truncated`` fires through the
    active :class:`TelemetryCollector` with ``(tool, original_size,
    truncated_size, iteration)``.
  * A clear inline marker is *prepended* to the body so the LLM sees
    the truncation BEFORE the (now-incomplete) data.
  * The 8000-byte cap is unchanged — protecting the context window
    is still load-bearing.

Four tests below lock all of that in.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from infra.brain.tools.agent_loop import format_tool_result


# ── Below the cap: no marker, no event ────────────────────────────────


def test_short_result_passes_through_without_marker():
    out = format_tool_result("ws", {"hits": 3})
    assert "TRUNCATED" not in out
    assert "[tool:ws OK]" in out


def test_short_result_does_not_emit_truncation_event():
    from infra.brain.telemetry.collector import _current_telemetry

    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        format_tool_result("ws", {"hits": 3})
    finally:
        _current_telemetry.reset(token)

    truncation_calls = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == "tool_result_truncated"
    ]
    assert truncation_calls == []


# ── Over the cap: visible marker + telemetry event ───────────────────


def test_oversized_result_prepends_visible_marker():
    """The marker must be at the START of the body so the LLM
    encounters it before the (now-truncated) payload. The previous
    suffix-only ``[truncated]`` was too easy to gloss over."""
    big_payload = {"data": "x" * 20000}
    out = format_tool_result("big_tool", big_payload)

    # Marker is present and contains the original size.
    assert "[TRUNCATED:" in out
    assert "original size" in out
    assert "kept first 8000 bytes" in out

    # Marker is BEFORE the data, not after.
    marker_idx = out.index("[TRUNCATED:")
    payload_first_x = out.index('xxxx')  # any run of payload chars
    assert marker_idx < payload_first_x


def test_oversized_result_emits_telemetry_event():
    from infra.brain.telemetry.collector import _current_telemetry

    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        format_tool_result(
            "big_tool",
            {"data": "y" * 20000},
            iteration=2,
        )
    finally:
        _current_telemetry.reset(token)

    truncation_calls = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == "tool_result_truncated"
    ]
    assert len(truncation_calls) == 1
    kw = truncation_calls[0].kwargs
    assert kw["tool"] == "big_tool"
    assert kw["truncated_size"] == 8000
    assert kw["original_size"] > 8000
    assert kw["iteration"] == 2


# ── Cap is unchanged (regression guard) ──────────────────────────────


def test_truncation_threshold_is_still_8000_bytes():
    """The cap must NOT have been raised by the fix. Audit Issue #5
    explicitly says: do not raise the limit, do not add a knob."""
    # Build a body that's exactly 8001 bytes when serialised, so we
    # hit the truncation branch on the first byte beyond the cap.
    payload = {"k": "z" * 8000}  # serialised body is well > 8000
    out = format_tool_result("probe", payload)
    assert "[TRUNCATED:" in out

    # And a body that's clearly under: no marker.
    small = {"k": "z" * 100}
    assert "[TRUNCATED:" not in format_tool_result("probe", small)


# ── No collector bound: silent no-op ─────────────────────────────────


def test_no_collector_bound_does_not_break_render():
    """The brain's telemetry pattern: when no collector is bound to
    the ContextVar, emit must be a silent no-op. Truncation rendering
    must still produce a usable string."""
    # No _current_telemetry.set() — collector is None.
    out = format_tool_result("big_tool", {"data": "q" * 20000})
    assert "[TRUNCATED:" in out
    assert "[tool:big_tool OK]" in out


# ── iteration=None is allowed and emits cleanly ──────────────────────


def test_iteration_optional_for_legacy_callers():
    """Existing callers that don't pass iteration must keep working;
    the telemetry event still fires with ``iteration=None``."""
    from infra.brain.telemetry.collector import _current_telemetry

    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        # No iteration kwarg — same shape as the existing _run_tool_loop
        # callers in interface.py.
        format_tool_result("big", {"data": "w" * 20000})
    finally:
        _current_telemetry.reset(token)

    truncation_calls = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == "tool_result_truncated"
    ]
    assert len(truncation_calls) == 1
    assert truncation_calls[0].kwargs["iteration"] is None
