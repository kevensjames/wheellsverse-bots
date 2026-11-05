"""
Briefing assembler tests.

Each section assembler is tested in two modes:
  1. Happy path — patched data source returns realistic data, assertions
     on the returned string format
  2. Sad path — patched data source raises any Exception, assertion that
     the section returns its '—' fallback string and never propagates
     (the cron must never crash on a missing data source).

The revenue and KPI sections read the daily numbers board by New York day
(core.board.day.day_view, core.click_tracker.clicks_on); their tests patch
those two, and tests/test_briefing_board_lines.py runs them on the board's
fake database.

assemble_briefing is tested as a smoke flow — every section runs without
raising. The full text isn't asserted line-by-line because the data is
live (yfinance, the board), but the structural invariants are:
  - 9+ lines (header + 6 sections + footer)
  - Each emoji marker appears exactly once
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Pre-import the submodules so unittest.mock.patch can resolve their
# dotted paths. Without this, `patch("narai.core.trading.paper.PaperBroker")`
# fails with AttributeError on `narai.core.trading` (the submodule isn't
# loaded until something imports it).
import narai.core.trading.paper  # noqa: F401

from narai.integrations import briefing


# ── _revenue_section ─────────────────────────────────────────────────────────

def _view(net=1000, attributed=2999, by_channel=None, fees=317, state="final", counts=None,
          connected=True, note=""):
    """A day view as core.board.day.day_view gives it: only its revenue number."""
    revenue = {"value": net, "net_usd_cents": net, "attributed_usd_cents": attributed, "fees_usd_cents": fees,
               "by_channel": {"meta": 2999, "unattributed": -1999} if by_channel is None else by_channel,
               "counts": {"sale": 1, "refund": 1} if counts is None else counts,
               "state": state, "connected": connected, "note": note}
    return {"numbers": {"revenue": revenue}}


def test_revenue_section_is_yesterdays_board_line_by_new_york_day():
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)       # 07:00 on Mon 2 Nov in New York
    with patch("core.board.day.day_view", return_value=_view()) as day_view:
        out = briefing._revenue_section(now)
    assert out == "💰 Revenue: $10.00 net · attributed $29.99 (meta) · fees $3.17"
    day_view.assert_called_once_with(date(2026, 11, 1))


def test_revenue_section_late_evening_utc_is_still_the_new_york_day():
    now = datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc)       # 23:30 on Sun 1 Nov in New York
    with patch("core.board.day.day_view", return_value=_view()) as day_view:
        briefing._revenue_section(now)
    day_view.assert_called_once_with(date(2026, 10, 31))


def test_revenue_section_not_connected_is_never_zero():
    view = _view(net=None, connected=False, note="database not connected")
    with patch("core.board.day.day_view", return_value=view):
        out = briefing._revenue_section(datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
    assert out == "💰 Revenue: not connected (database not connected)" and "$0" not in out


def test_revenue_section_is_escaped_for_telegram():
    view = _view(net=None, connected=False, note="last sync failed: <b>boom</b> & co")
    with patch("core.board.day.day_view", return_value=view):
        out = briefing._revenue_section(datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
    assert "&lt;b&gt;boom&lt;/b&gt; &amp; co" in out and "<b>" not in out


def test_revenue_section_falls_back_on_error():
    with patch("core.board.day.day_view", side_effect=RuntimeError("database gone")):
        out = briefing._revenue_section(datetime.now(timezone.utc))
    assert out == "💰 Revenue: —"


# ── _trading_section ─────────────────────────────────────────────────────────

def test_trading_section_no_positions_no_history():
    fake_broker = MagicMock()
    fake_broker.status.return_value = {
        "equity": 10000.0,
        "cash": 10000.0,
        "starting_equity": 10000.0,
        "open_positions": [],
        "total_return_pct": 0.0,
    }
    fake_broker.history.return_value = []
    with patch("narai.core.trading.paper.PaperBroker", return_value=fake_broker):
        out = briefing._trading_section()
    # Empty broker → headline only, no detail line
    assert "$10,000 equity" in out
    assert "0 open" in out
    assert "↳" not in out  # no detail line padding


def test_trading_section_renders_top_open_position():
    fake_broker = MagicMock()
    fake_broker.status.return_value = {
        "equity": 10250.0,
        "cash": 9000.0,
        "starting_equity": 10000.0,
        "open_positions": [
            {"symbol": "NVDA", "shares": 10, "entry": 120.0, "current": 125.0,
             "unrealized_pnl": 50.0},
            {"symbol": "AAPL", "shares": 5, "entry": 200.0, "current": 195.0,
             "unrealized_pnl": -25.0},
        ],
        "total_return_pct": 2.5,
    }
    with patch("narai.core.trading.paper.PaperBroker", return_value=fake_broker):
        out = briefing._trading_section()
    assert "↳ top open: NVDA" in out  # max-pnl wins
    assert "x10" in out
    assert "(+$50)" in out


def test_trading_section_falls_back_on_error():
    with patch(
        "narai.core.trading.paper.PaperBroker",
        side_effect=RuntimeError("ledger corrupt"),
    ):
        out = briefing._trading_section()
    assert out == "📈 Trading: —"


# ── _crypto_section ──────────────────────────────────────────────────────────

def test_crypto_section_falls_back_on_error():
    """Network/library error must produce '—', not a crash."""
    pytest.importorskip("yfinance")
    with patch("yfinance.Ticker", side_effect=RuntimeError("network down")):
        out = briefing._crypto_section()
    assert out == "🪙 Crypto: —"


def test_crypto_section_handles_missing_yfinance():
    """If yfinance import itself fails, section still returns '—'."""
    import sys
    saved = sys.modules.pop("yfinance", None)
    sys.modules["yfinance"] = None  # forces ImportError on `import yfinance`
    try:
        out = briefing._crypto_section()
        assert out == "🪙 Crypto: —"
    finally:
        if saved is not None:
            sys.modules["yfinance"] = saved
        else:
            sys.modules.pop("yfinance", None)


# ── _kpi_section ─────────────────────────────────────────────────────────────

def _by_day(values: dict):
    return lambda day: values[day]


def test_kpi_section_directional_arrows():
    """Yesterday > day-before should yield ▲; reverse yields ▼. New York days."""
    now = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
    yest, prev = date(2026, 5, 4), date(2026, 5, 3)
    views = {yest: _view(net=1000), prev: _view(net=1999)}
    with patch("core.click_tracker.clicks_on", side_effect=_by_day({yest: 3, prev: 1})), \
         patch("core.board.day.day_view", side_effect=_by_day(views)):
        out = briefing._kpi_section(now)
    assert out == "✅ KPIs (yesterday, New York): 3 clicks ▲ (prev 1) · $10.00 net revenue ▼ (prev $19.99)"


def test_kpi_section_equal_days_show_no_change():
    now = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
    with patch("core.click_tracker.clicks_on", return_value=0), \
         patch("core.board.day.day_view", return_value=_view(net=0, counts={})):
        out = briefing._kpi_section(now)
    assert out == "✅ KPIs (yesterday, New York): 0 clicks → (prev 0) · $0.00 net revenue → (prev $0.00)"


def test_kpi_section_an_unknown_number_is_a_dash_with_no_arrow():
    now = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
    yest, prev = date(2026, 5, 4), date(2026, 5, 3)
    views = {yest: _view(net=None, connected=False, note="database not connected"), prev: _view(net=500)}
    with patch("core.click_tracker.clicks_on", side_effect=_by_day({yest: None, prev: 2})), \
         patch("core.board.day.day_view", side_effect=_by_day(views)):
        out = briefing._kpi_section(now)
    assert out == "✅ KPIs (yesterday, New York): — clicks (prev 2) · — net revenue (prev $5.00)"
    assert "0 clicks" not in out and "$0" not in out


def test_kpi_section_counts_new_york_days_not_utc_ones():
    now = datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc)      # still Sun 1 Nov in New York
    with patch("core.click_tracker.clicks_on", return_value=1) as clicks_on, \
         patch("core.board.day.day_view", return_value=_view()):
        briefing._kpi_section(now)
    assert [c.args[0] for c in clicks_on.call_args_list] == [date(2026, 10, 31), date(2026, 10, 30)]


def test_kpi_section_falls_back_on_error():
    with patch("core.click_tracker.clicks_on", side_effect=RuntimeError("boom")):
        out = briefing._kpi_section(datetime.now(timezone.utc))
    assert out == "✅ KPIs: —"


# ── assemble_briefing ────────────────────────────────────────────────────────

def test_assemble_briefing_smoke():
    """End-to-end render with all live integrations. Assert structural
    invariants only — content is live data."""
    text = briefing.assemble_briefing()
    # Header + 6 sections + footer + 2 blank separators = at least 9 lines
    lines = text.split("\n")
    assert len(lines) >= 9
    # Each section emoji appears at least once (sections never disappear,
    # only fall back to '—').
    for emoji in ["🌅", "💰", "📈", "📅", "📨", "👥", "🪙", "✅"]:
        assert emoji in text, f"missing {emoji} section in briefing"
    # Footer prompt is always present.
    assert "Reply with a question" in text


def test_assemble_briefing_markdown_strips_html():
    """The markdown variant must strip <b>/<i> tags."""
    md = briefing.assemble_briefing_markdown()
    assert "<b>" not in md
    assert "</b>" not in md
    assert "<i>" not in md
    assert "</i>" not in md
    # But the content (e.g. 'Good morning') should still be there.
    assert "Good morning" in md


# ── log_briefing_to_memory ───────────────────────────────────────────────────

def test_log_briefing_to_memory_swallows_errors():
    """Memory log is a side effect — never blocks delivery. We don't
    care which backend it uses (the memory module changed twice already);
    we only care that an unhandled error never propagates."""
    # Force whatever backend log_briefing_to_memory imports to fail by
    # poisoning sys.modules entries it commonly touches. log_briefing_to_memory
    # imports infra.brain.interface inside its try block, so an ImportError
    # there is the same as a missing module — both must be swallowed.
    import sys
    saved = sys.modules.pop("infra.brain.interface", None)
    sys.modules["infra.brain.interface"] = None  # forces ImportError
    try:
        briefing.log_briefing_to_memory("test briefing text")  # must not raise
    finally:
        if saved is not None:
            sys.modules["infra.brain.interface"] = saved
        else:
            sys.modules.pop("infra.brain.interface", None)
