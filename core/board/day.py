"""The board's day view and the morning message (replica/architecture.md, API:
GET /api/board/day).

board_day (SQL) computes one New York calendar day in one round trip: totals,
every sale, and each source's state. This module only shapes it. Each number is
{value, connected, state, source, note}:

  * board_day fails, or `sources` comes back empty (the migration never ran):
    "database not connected", value null. Never $0.
  * the source's key is not configured, or is a Stripe test-mode key, or its
    state is not_connected: connected false, value null.
  * final: the source synced past the end of that day; partial otherwise, and
    the note says how far it got.

A real 0 stays 0. Amounts are USD cents. Buyers arrive masked from SQL.

The board shows revenue from Stripe so far; the other numbers join it source by
source.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from core.board import ledger
from core.board.connectors import stripe_sync
from core.board.ledger import BoardDBError

log = logging.getLogger("board.day")

NY = ZoneInfo("America/New_York")
TZ_NAME = "America/New_York"
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONEY_FIELDS = ("net_usd_cents", "gross_usd_cents", "refunds_usd_cents", "disputes_usd_cents",
                 "attributed_usd_cents", "fees_usd_cents", "unknown_fee_rows", "unconverted_rows",
                 "has_estimates", "by_source", "by_channel")
_KIND_WORDS = (("sale", "sale", "sales"), ("refund", "refund", "refunds"),
               ("dispute", "dispute", "disputes"), ("dispute_reversal", "dispute won", "disputes won"),
               ("adjustment", "adjustment", "adjustments"))


# ─── days ───────────────────────────────────────────────────────────────────

def yesterday_ny(now: Optional[datetime] = None) -> date:
    """Yesterday in New York (only when the database cannot say it)."""
    return (now or datetime.now(timezone.utc)).astimezone(NY).date() - timedelta(days=1)


def parse_day(value: str) -> date:
    """A calendar day written YYYY-MM-DD; ValueError otherwise."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        raise ValueError("a day is YYYY-MM-DD")
    return date.fromisoformat(value)


def day_label(d: date) -> str:
    """'Sun 1 Nov', in English whatever the container's locale."""
    return f"{_WEEKDAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]}"


def hours_note(hours: Optional[int]) -> str:
    if hours == 25:
        return "a 25-hour day: clocks went back"
    if hours == 23:
        return "a 23-hour day: clocks went forward"
    return ""


def _ny_clock(value) -> Optional[str]:
    """'23:07 on Sun 1 Nov' in New York, from a timestamptz."""
    ts = ledger.parse_ts(value)
    if ts is None:
        return None
    local = ts.astimezone(NY)
    return f"{local:%H:%M} on {day_label(local.date())}"


# ─── the view ───────────────────────────────────────────────────────────────

def _stripe_pill(day: date, raw_sources: list) -> dict:
    """The Stripe source: its state for this day, decided in SQL, plus whether
    its key is configured here."""
    row = next((s for s in raw_sources if isinstance(s, dict) and s.get("id") == "stripe"), None)
    key = stripe_sync.read_key()
    pill = {"id": "stripe", "name": "Stripe", "state": "not_connected", "connected": False,
            "synced_through": None, "last_ok_at": None, "last_error": None, "note": ""}
    notes = []
    if row is None:
        pill["note"] = "no stripe row in public.sources"
        return pill
    pill.update({k: row.get(k) for k in ("synced_through", "last_ok_at", "last_error")})
    state = row.get("state") or "not_connected"
    measured_from = row.get("measured_from")
    if key is None:
        notes.append("Stripe key not set: STRIPE_READ_KEY (or STRIPE_SECRET_KEY)")
        state = "not_connected"
    elif stripe_sync.is_test_key(key[0]):
        notes.append(f"{key[1]} is a test-mode key: test payments are not revenue, so nothing is read")
        state = "not_connected"
    elif state == "not_connected":
        if not measured_from:
            notes.append("no Stripe sync has completed yet")
        elif day.isoformat() < str(measured_from):
            notes.append(f"not measured before {measured_from}")
        else:
            notes.append("the stripe source is disabled")
    elif state == "partial":
        clock = _ny_clock(row.get("synced_through"))
        notes.append(f"synced to {clock} (New York)" if clock else "not synced past the end of this day yet")
    if key is not None and key[1] == "STRIPE_SECRET_KEY" and not stripe_sync.is_test_key(key[0]):
        notes.append("read with STRIPE_SECRET_KEY; a restricted read-only STRIPE_READ_KEY is safer")
    if row.get("last_error"):
        # An ok run stores its warning in the same write as last_ok_at, so the
        # two timestamps are equal; a failed run's error never shares them.
        ok_at, error_at = ledger.parse_ts(row.get("last_ok_at")), ledger.parse_ts(row.get("last_error_at"))
        warned = ok_at is not None and ok_at == error_at
        notes.append(f"last sync: {row['last_error']}" if warned else f"last sync failed: {row['last_error']}")
    pill.update(state=state, connected=state in ("final", "partial"), note=" · ".join(notes))
    return pill


def _unavailable(day: date, note: str) -> dict:
    return {"day": day.isoformat(), "label": day_label(day), "tz": TZ_NAME, "hours_in_day": None,
            "starts_at": None, "ends_at": None, "database": "not_connected",
            "numbers": {"revenue": {"value": None, "connected": False, "state": "not_connected",
                                    "source": "stripe", "note": note, "counts": {},
                                    **{k: None for k in _MONEY_FIELDS}}},
            "products": [], "sales": [],
            "sources": [{"id": "stripe", "name": "Stripe", "state": "not_connected", "connected": False,
                         "synced_through": None, "last_ok_at": None, "last_error": None, "note": note}]}


def day_view(day: Optional[date] = None) -> dict:
    """One owner day for the board and the morning message. `day` None means
    yesterday in New York, decided in SQL."""
    try:
        raw = ledger.board_day(day)
    except BoardDBError as e:
        log.warning("board day: %s", e)
        return _unavailable(day or yesterday_ny(), "database not connected")
    try:
        the_day = parse_day(str(raw.get("day")))
    except ValueError:
        log.warning("board day: board_day returned no day")
        return _unavailable(day or yesterday_ny(), "database not connected")
    sources = raw.get("sources") if isinstance(raw.get("sources"), list) else []
    if not sources:
        return _unavailable(the_day, "database not connected: the board migration has not run")

    pill = _stripe_pill(the_day, sources)
    revenue, fees = raw.get("revenue") or {}, raw.get("fees") or {}
    sales = [s for s in raw.get("sales") or [] if isinstance(s, dict)] if pill["connected"] else []
    number = {"value": None, "connected": pill["connected"], "state": pill["state"],
              "source": "stripe", "note": pill["note"], "counts": {},
              **{k: None for k in _MONEY_FIELDS}}
    if pill["connected"]:
        number.update({k: revenue.get(k) for k in ("net_usd_cents", "gross_usd_cents", "refunds_usd_cents",
                                                   "disputes_usd_cents", "attributed_usd_cents",
                                                   "unconverted_rows", "has_estimates")})
        number.update(value=revenue.get("net_usd_cents"), fees_usd_cents=fees.get("fees_usd_cents"),
                      unknown_fee_rows=fees.get("unknown_fee_rows"),
                      by_source=raw.get("by_source") or {}, by_channel=raw.get("by_channel") or {},
                      counts={kind: n for kind, _, _ in _KIND_WORDS
                              if (n := sum(1 for s in sales if s.get("kind") == kind))})
        extra = []
        if number["unconverted_rows"]:
            n = number["unconverted_rows"]
            extra.append(f"{n} row{'s have' if n != 1 else ' has'} no USD amount, left out of the totals")
        if number["unknown_fee_rows"]:
            n = number["unknown_fee_rows"]
            extra.append(f"fees unknown on {n} row{'s' if n != 1 else ''}")
        number["note"] = " · ".join(n for n in [pill["note"], *extra] if n)
    return {"day": the_day.isoformat(), "label": day_label(the_day), "tz": raw.get("tz") or TZ_NAME,
            "hours_in_day": raw.get("hours_in_day"), "starts_at": raw.get("starts_at"),
            "ends_at": raw.get("ends_at"), "database": "connected",
            "numbers": {"revenue": number},
            "products": (raw.get("products") or []) if pill["connected"] else [],
            "sales": sales, "sources": [pill]}


# ─── the morning message ────────────────────────────────────────────────────

def money(cents: Optional[int]) -> str:
    """$1,234.56 from integer cents; -$19.99 when negative."""
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(int(cents)), 100)
    return f"{sign}${whole:,}.{part:02d}"


def _counts_words(counts: dict) -> str:
    words = [f"{counts[kind]} {one if counts[kind] == 1 else many}"
             for kind, one, many in _KIND_WORDS if counts.get(kind)]
    return ", ".join(words) or "no sales"


def summary_line(view: dict) -> str:
    """The revenue line of the morning message, in plain text."""
    rev = view["numbers"]["revenue"]
    if not rev["connected"]:
        return f"Revenue: not connected ({rev['note']})" if rev.get("note") else "Revenue: not connected"
    line = f"Revenue: {money(rev['net_usd_cents'])} net"
    if rev["state"] == "partial":
        line += " so far"
    line += f" · fees {money(rev['fees_usd_cents'])}"
    if rev["state"] == "partial":
        line += " (partial)"
    return line


def render_report(view: dict) -> str:
    """The morning message as Telegram HTML; every value is escaped."""
    e = html.escape
    head = f"<b>{e(view['label'])}</b> (New York"
    if hours_note(view.get("hours_in_day")):
        head += f"; {e(hours_note(view['hours_in_day']))}"
    lines = [head + ")", e(summary_line(view))]
    rev = view["numbers"]["revenue"]
    if rev["connected"]:
        stripe_net = (rev.get("by_source") or {}).get("stripe", 0)
        lines.append(f"  Stripe {e(money(stripe_net))}: {e(_counts_words(rev.get('counts') or {}))}")
        if rev.get("note"):
            lines.append(f"  {e(rev['note'])}")
    states = ", ".join(f"{s['name']} {s['state'].replace('_', ' ')}" for s in view["sources"])
    lines.append(f"Sources: {e(states)}")
    return "\n".join(lines)
