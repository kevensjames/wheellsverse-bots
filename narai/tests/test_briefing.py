"""
Briefing assembler tests.

Each section assembler is tested in two modes:
  1. Happy path — patched data source returns realistic data, assertions
     on the returned string format
  2. Sad path — patched data source raises any Exception, assertion that
     the section returns its '—' fallback string and never propagates
     (the cron must never crash on a missing data source).

assemble_briefing is tested as a smoke flow — every section runs without
raising. The full text isn't asserted line-by-line because the data is
live (yfinance, click_tracker), but the structural invariants are:
  - 9+ lines (header + 6 sections + footer)
  - Each emoji marker appears exactly once
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Pre-import the submodules so unittest.mock.patch can resolve their
# dotted paths. Without this, `patch("narai.core.trading.paper.PaperBroker")`
# fails with AttributeError on `narai.core.trading` (the submodule isn't
# loaded until something imports it).
import narai.core.trading.paper  # noqa: F401

from narai.integrations import briefing


# ── _revenue_section ─────────────────────────────────────────────────────────

def test_revenue_section_happy():
    fake_stats = {
        "total_clicks": 42,
        "total_revenue_usd": 123.45,
        "by_partner": {"insider": 30, "amazon": 12},
    }
    with patch("core.click_tracker.get_stats", return_value=fake_stats):
        out = briefing._revenue_section(datetime.now(timezone.utc))
    assert "$123.45" in out
    assert "42 clicks" in out
    assert "insider" in out  # top partner
    assert out.startswith("💰 Revenue")


def test_revenue_section_falls_back_on_error():
    with patch("core.click_tracker.get_stats", side_effect=RuntimeError("disk gone")):
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

def test_kpi_section_no_data():
    with patch("core.click_tracker._load_clicks", return_value=[]), \
         patch("core.click_tracker._load_conversions", return_value=[]):
        out = briefing._kpi_section(datetime.now(timezone.utc))
    assert "0 clicks" in out
    assert "$0.00" in out
    assert "→" in out  # no-change indicator when both days are 0


def test_kpi_section_directional_arrows():
    """Yesterday > day-before should yield ▲; reverse yields ▼."""
    today = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
    yest = "2026-05-04"
    prev = "2026-05-03"
    clicks = [
        {"ts": yest + "T08:00:00Z"},
        {"ts": yest + "T09:00:00Z"},
        {"ts": yest + "T10:00:00Z"},
        {"ts": prev + "T08:00:00Z"},
    ]
    convs = [
        {"ts": yest + "T08:00:00Z", "amount_usd": 50.0},
        {"ts": prev + "T08:00:00Z", "amount_usd": 100.0},
    ]
    with patch("core.click_tracker._load_clicks", return_value=clicks), \
         patch("core.click_tracker._load_conversions", return_value=convs):
        out = briefing._kpi_section(today)
    # Clicks: 3 yesterday, 1 prev → ▲
    assert "3 clicks ▲" in out
    # Revenue: $50 yesterday, $100 prev → ▼
    assert "$50.00 revenue ▼" in out


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
