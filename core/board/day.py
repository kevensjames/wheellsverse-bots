"""The board's day view and the morning message (replica/architecture.md, API:
GET /api/board/day).

board_day (SQL) computes one New York calendar day in one round trip: the
Toodle opt-ins, the SiteBoost replies, revenue with every sale, Meta spend,
the stop rule's verdict, and each source's state. This module only shapes it.
Each number is {value, connected, state, source, note}, plus its own fields:

  * board_day fails, or `sources` comes back empty (the migration never ran):
    "database not connected" for every number, value null. Never 0.
  * the source's connector is not configured on this server (its own check,
    with its plain reason), or the source's state is not_connected: connected
    false, value null.
  * final: the source synced past the end of that day, in its own time zone;
    partial otherwise, and the note says how far it got. A day that no sync
    has reached yet has no value (null), not 0.

A real 0 stays 0. Amounts are USD cents. Buyers arrive masked from SQL.

  optins   Toodle opt-ins (Kit): value, by_channel, target 3 a day
  replies  SiteBoost replies (Instantly): distinct prospects that day; value_7d
           over that day and the 6 before it, null while any of those 7 days
           is before measured_from; auto_replies_ignored (automatic replies
           and bounces); target 1 a week
  revenue  Stripe, and manual entries (the 'manual' source) once there are
           any: net, gross, refunds, disputes and fees, every sale listed,
           split by source. Attributed revenue is the net with a known
           channel, split by channel (by_channel; the rest is
           'unattributed'): each sale's channel comes from its tracked /go
           link (attribution click_id), its checkout's utm_source
           (checkout_utm), or the buyer's earlier opt-in or reply, matched on
           email (lead_email); a refund or dispute takes its sale's. The
           morning message reads 'attributed $29.99 (meta)'. Its state is
           Stripe's
  spend    Meta: Toodle spend and link clicks on the ad account's own day
           (day_tz), and all campaigns' spend. Spend that has no US dollar
           amount yet leaves the total null, never a smaller number. While
           BOARD_TOODLE_META_CAMPAIGN_IDS names no campaign, no spend is
           Toodle's: the Toodle numbers are not connected, never $0.00. While
           it is not the list the last complete Meta sync labelled the stored
           spend with (its job_runs detail), they have no number yet: the next
           Meta sync relabels every stored day
  cpl      the stop rule (board_cpl), its verdict passed through from SQL. It
           needs Meta, Kit and the Toodle campaigns, and Kit's opt-ins counted
           from the first spend day to the end of the last one; until Kit has
           read that far, no verdict yet. While any spend has no US dollar
           amount (check_currency), the spend and the CPLs are null: SQL sums
           only the converted days. A no_spend verdict carries the last Meta
           sync's warning about listed campaigns it saw no spend for, by id
"""
from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple, Optional
from zoneinfo import ZoneInfo

from core.board import ledger
from core.board.connectors import instantly_sync, kit_sync, meta_sync, stripe_sync
from core.board.ledger import BoardDBError

log = logging.getLogger("board.day")

NY = ZoneInfo("America/New_York")
TZ_NAME = "America/New_York"
SOURCES = (("stripe", "Stripe"), ("kit", "Kit"), ("instantly", "Instantly"), ("meta_ads", "Meta"))
# How the morning message names a source's money line (another source shows its id).
SOURCE_NAMES = {"stripe": "Stripe", "manual": "Manual entries", "kdp": "KDP (estimate)"}
OPTIN_TARGET = 3              # Toodle opt-ins a day (marketing/GLOBAL_PLAN.md:196)
REPLY_TARGET_PER_WEEK = 1     # SiteBoost replies a week (marketing/GLOBAL_PLAN.md:197)
CPL_LOOKBACK_DAYS = 30        # board_cpl looks this far back for spend days
VERDICTS = ("no_spend", "check_currency", "collecting", "check_tags", "stop", "ok")
TOODLE_CAMPAIGNS_ENV = "BOARD_TOODLE_META_CAMPAIGN_IDS"     # read by meta_sync.toodle_campaigns()
TOODLE_CHANGED = "Toodle campaigns changed: waiting for the next Meta sync"
TOODLE_UNCHECKED = "Toodle campaigns not checked: database not connected"
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONEY_FIELDS = ("net_usd_cents", "gross_usd_cents", "refunds_usd_cents", "disputes_usd_cents",
                 "attributed_usd_cents", "fees_usd_cents", "unknown_fee_rows", "unconverted_rows",
                 "has_estimates", "by_source", "by_channel")
_KIND_WORDS = (("sale", "sale", "sales"), ("refund", "refund", "refunds"),
               ("dispute", "dispute", "disputes"), ("dispute_reversal", "dispute won", "disputes won"),
               ("adjustment", "adjustment", "adjustments"))
_CPL_FIELDS = ("first_day", "last_day", "spend_days", "spend_usd_cents", "unconverted_spend_rows",
               "meta_optins", "toodle_optins", "cpl_meta_usd_cents", "cpl_all_usd_cents")


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


def _date(value) -> Optional[date]:
    try:
        return parse_day(str(value)) if value else None
    except ValueError:
        return None


def _zone(name) -> ZoneInfo:
    """A source's own day zone (sources.day_tz); New York when it is unusable."""
    try:
        return ZoneInfo(str(name)) if name else NY
    except (KeyError, ValueError, OSError):        # ZoneInfoNotFoundError is a KeyError
        return NY


def _count(value) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _counts(value) -> dict:
    """{name: n} with the largest first, then by name."""
    if not isinstance(value, dict):
        return {}
    pairs = [(str(k), v) for k, v in value.items() if _count(v) is not None]
    return dict(sorted(pairs, key=lambda kv: (-kv[1], kv[0])))


def _join(*notes: str) -> str:
    return " · ".join(n for n in notes if n)


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


# ─── the sources ────────────────────────────────────────────────────────────

def _how_read(source_id: str) -> tuple[Optional[str], list[str]]:
    """(why `source_id` cannot be read on this server, or None; notes on how
    it is read). Each connector's own check, so the note names the setting to
    fix and never a key's value."""
    if source_id == "stripe":
        key = stripe_sync.read_key()
        if key is None:
            return "Stripe key not set: STRIPE_READ_KEY (or STRIPE_SECRET_KEY)", []
        if stripe_sync.is_test_key(key[0]):
            return f"{key[1]} is a test-mode key: test payments are not revenue, so nothing is read", []
        if key[1] == "STRIPE_SECRET_KEY":
            return None, ["read with STRIPE_SECRET_KEY; a restricted read-only STRIPE_READ_KEY is safer"]
        return None, []
    if source_id == "kit":
        return kit_sync.configured(), []
    if source_id == "instantly":
        return instantly_sync.configured(), []
    if source_id == "meta_ads":
        reason = meta_sync.configured()
        token = meta_sync.read_token() if reason is None else None
        if token is not None and token[1] == "META_ACCESS_TOKEN":
            return None, ["read with META_ACCESS_TOKEN; a read-only META_INSIGHTS_TOKEN is safer"]
        return reason, []
    return f"no connector for {source_id}", []


def read_problem(source_id: str) -> Optional[str]:
    """Why `source_id` (stripe, kit, instantly or meta_ads) cannot be read on
    this server, in a few plain words that name the setting to fix; None when
    its connector is configured. It reads settings only: no call goes out."""
    return _how_read(source_id)[0]


def _synced_into(pill: dict, day: date) -> bool:
    """Whether the source's watermark is past the start of `day` in its own
    zone, so a sync has read at least part of that day."""
    synced = ledger.parse_ts(pill.get("synced_through"))
    return synced is not None and synced > datetime.combine(day, time(0), tzinfo=_zone(pill.get("day_tz")))


def _synced_past(pill: dict, day: date) -> bool:
    """Whether the source's watermark has reached the end of `day` in its own
    zone (board_source_state's test for final), so all of that day is read."""
    synced = ledger.parse_ts(pill.get("synced_through"))
    return synced is not None and synced >= datetime.combine(day + timedelta(days=1), time(0),
                                                             tzinfo=_zone(pill.get("day_tz")))


class _Toodle(NamedTuple):
    """What the board can tell of the Toodle labels on the stored Meta spend."""
    unset: Optional[str] = None       # the list names no campaign: the Toodle numbers are not connected
    waiting: Optional[str] = None     # the labels may not follow the list yet: no number yet, and why
    waiting_text: str = ""            # the stop rule's verdict text while waiting
    unseen: Optional[str] = None      # the last Meta sync's warning on listed campaigns with no spend


def _toodle(meta: dict) -> _Toodle:
    """Whether Toodle's part of the Meta spend can be told here (`meta` is
    Meta's pill). While BOARD_TOODLE_META_CAMPAIGN_IDS names no campaign
    (unset, or no item is a campaign id), the Meta sync labels no spend
    Toodle's, so the Toodle spend would read $0.00 and the stop rule "no
    spend" while ads run. That is a missing setting, not a 0. The stored
    labels follow the list the last complete Meta sync ran with (its detail's
    toodle_campaigns): a list set or changed since then reaches the stored
    days only at the next Meta run, so until then the Toodle numbers have no
    value, rather than the old list's, and with no run on record the same.
    Only asked once Meta itself is configured, so the note names one setting
    to fix at a time; the last run is read only while Meta is connected."""
    if meta_sync.configured() is not None:
        return _Toodle()
    listed = meta_sync.toodle_campaigns()[0]
    if not listed:
        return _Toodle(unset=f"Toodle campaigns not set: {TOODLE_CAMPAIGNS_ENV} names no campaign")
    if not meta["connected"]:
        return _Toodle()
    try:
        detail = ledger.last_ok_detail(meta_sync.JOB)
    except BoardDBError as e:
        log.warning("board day: cannot read the last Meta sync (%s)", e)
        return _Toodle(waiting=TOODLE_UNCHECKED, waiting_text="No verdict: database not connected.")
    used = detail.get("toodle_campaigns") if isinstance(detail, dict) else None
    if not (isinstance(used, list) and all(isinstance(c, str) for c in used)) or frozenset(used) != listed:
        return _Toodle(waiting=TOODLE_CHANGED, waiting_text="No verdict until the next Meta sync.")
    return _Toodle(unseen=_unseen(detail, listed))


def _unseen(detail: dict, listed: frozenset) -> Optional[str]:
    """The last complete Meta sync's warning about the listed campaigns it saw
    no spend for (a mistyped id, another account's campaign, or one paused
    long ago), worded as the run worded it: ids only, never a name. None
    when it saw spend for every one."""
    unseen, days = detail.get("toodle_campaigns_unseen"), detail.get("days")
    since = _date(days.get("since")) if isinstance(days, dict) else None
    ids = [c for c in unseen if isinstance(c, str) and c in listed] if isinstance(unseen, list) else []
    return meta_sync.unseen_warning(ids, since) if ids and since is not None else None


def _pill(source_id: str, name: str, day: date, raw_sources: list) -> tuple[dict, bool]:
    """One source's pill for `day`, and whether its number for that day is
    measured (final, or partial with a sync that reached into the day). The
    state is decided in SQL (board_source_state); it is also not_connected
    when the connector is not configured here."""
    row = next((s for s in raw_sources if isinstance(s, dict) and s.get("id") == source_id), None)
    pill = {"id": source_id, "name": name, "state": "not_connected", "connected": False, "day_tz": TZ_NAME,
            "measured_from": None, "synced_through": None, "last_ok_at": None, "last_error": None, "note": ""}
    if row is None:
        pill["note"] = f"no {source_id} row in public.sources"
        return pill, False
    pill.update({k: row.get(k) for k in ("measured_from", "synced_through", "last_ok_at", "last_error")})
    pill["day_tz"] = row.get("day_tz") or TZ_NAME
    reason, how = _how_read(source_id)
    state = row.get("state") or "not_connected"
    measured_from = row.get("measured_from")
    reached = _synced_into(pill, day)
    notes = []
    if reason is not None:
        notes.append(reason)
        state = "not_connected"
    elif state == "not_connected":
        if not measured_from:
            notes.append(f"no {name} sync has completed yet")
        elif day.isoformat() < str(measured_from):
            notes.append(f"not measured before {measured_from}")
        else:
            notes.append(f"the {source_id} source is disabled")
    elif state == "partial":
        clock = _ny_clock(row.get("synced_through"))
        if not reached:
            notes.append(f"not synced into this day yet: synced to {clock} (New York)" if clock
                         else "not synced into this day yet")
        else:
            notes.append(f"synced to {clock} (New York)" if clock else "not synced past the end of this day yet")
    if reason is None:
        notes.extend(how)
        if source_id == "meta_ads" and pill["day_tz"] != TZ_NAME:
            notes.append(f"Meta counts days in the ad account's time zone ({pill['day_tz']}), not New York time")
    if row.get("last_error"):
        # An ok run stores its warning in the same write as last_ok_at, so the
        # two timestamps are equal; a failed run's error never shares them.
        ok_at, error_at = ledger.parse_ts(row.get("last_ok_at")), ledger.parse_ts(row.get("last_error_at"))
        warned = ok_at is not None and ok_at == error_at
        notes.append(f"last sync: {row['last_error']}" if warned else f"last sync failed: {row['last_error']}")
    pill.update(state=state, connected=state in ("final", "partial"), note=_join(*notes))
    return pill, state == "final" or (state == "partial" and reached)


def _off_pill(source_id: str, name: str, note: str) -> dict:
    return {"id": source_id, "name": name, "state": "not_connected", "connected": False, "day_tz": None,
            "measured_from": None, "synced_through": None, "last_ok_at": None, "last_error": None, "note": note}


# ─── the numbers ────────────────────────────────────────────────────────────

def _number(pill: dict, source: str, **fields) -> dict:
    """A number's common fields: value null until it is filled in."""
    return {"value": None, "connected": pill["connected"], "state": pill["state"], "source": source,
            "note": pill["note"], **fields}


def _block(raw: dict, name: str) -> dict:
    value = raw.get(name)
    return value if isinstance(value, dict) else {}


def _optins(raw: dict, pill: dict, measured: bool) -> dict:
    """Toodle opt-ins (Kit): the New York day's count and its split by channel."""
    n = _number(pill, "kit", by_channel=None, target=OPTIN_TARGET)
    if measured:
        block = _block(raw, "optins")
        n.update(value=_count(block.get("total")), by_channel=_counts(block.get("by_channel")))
    return n


def _replies(raw: dict, pill: dict, measured: bool, day: date) -> dict:
    """SiteBoost replies (Instantly): distinct prospects who replied, automatic
    replies and bounces left out. The 7-day count is null while any of its 7
    days is before measured_from: a count over fewer days is not a week's."""
    n = _number(pill, "instantly", value_7d=None, auto_replies_ignored=None,
                target_per_week=REPLY_TARGET_PER_WEEK)
    if measured:
        block = _block(raw, "replies")
        n.update(value=_count(block.get("people")), value_7d=_count(block.get("people_7d")),
                 auto_replies_ignored=_count(block.get("auto_replies")))
        first = _date(pill["measured_from"])
        if first is not None and day - timedelta(days=6) < first:
            n["value_7d"] = None
            n["note"] = _join(n["note"], f"no 7-day count: replies are counted only from {first.isoformat()}")
    return n


def _kind_counts(sales: list) -> dict:
    return {kind: n for kind, _, _ in _KIND_WORDS if (n := sum(1 for s in sales if s.get("kind") == kind))}


def _revenue(raw: dict, pill: dict, measured: bool) -> tuple[dict, list]:
    """Revenue and the day's sales list. The state is Stripe's; the money is
    every source's (Stripe, and manual entries once there are any): `source`
    names them, by_source splits the net, counts_by_source the rows. counts
    covers every source's rows, as before."""
    revenue, fees = _block(raw, "revenue"), _block(raw, "fees")
    sales = [s for s in raw.get("sales") or [] if isinstance(s, dict)] if measured else []
    number = _number(pill, "stripe", counts={}, counts_by_source={}, **{k: None for k in _MONEY_FIELDS})
    if measured:
        by_source = raw.get("by_source") or {}
        number.update({k: revenue.get(k) for k in ("net_usd_cents", "gross_usd_cents", "refunds_usd_cents",
                                                   "disputes_usd_cents", "attributed_usd_cents",
                                                   "unconverted_rows", "has_estimates")})
        number.update(value=revenue.get("net_usd_cents"), fees_usd_cents=fees.get("fees_usd_cents"),
                      unknown_fee_rows=fees.get("unknown_fee_rows"),
                      by_source=by_source, by_channel=raw.get("by_channel") or {},
                      counts=_kind_counts(sales),
                      counts_by_source={str(src): _kind_counts([s for s in sales if s.get("source") == src])
                                        for src in sorted({s.get("source") for s in sales if s.get("source")})},
                      source=", ".join(["stripe"] + sorted(str(s) for s in by_source if s != "stripe")))
        extra = []
        if number["unconverted_rows"]:
            n = number["unconverted_rows"]
            extra.append(f"{n} row{'s have' if n != 1 else ' has'} no USD amount, left out of the totals")
        if number["unknown_fee_rows"]:
            n = number["unknown_fee_rows"]
            extra.append(f"fees unknown on {n} row{'s' if n != 1 else ''}")
        number["note"] = _join(pill["note"], *extra)
    return number, sales


def _spend(raw: dict, pill: dict, measured: bool, toodle: _Toodle = _Toodle()) -> dict:
    """Meta spend on the ad account's own day. While any of the day's spend
    has no US dollar amount, the totals are null: summing only the converted
    rows would show less than was spent. With toodle.unset (no Toodle
    campaign listed) the Toodle numbers are not connected; with
    toodle.waiting (the stored labels may not follow the list yet) they have
    no number yet. All campaigns' spend is still shown."""
    n = _number(pill, "meta_ads", toodle_usd_cents=None, all_usd_cents=None, toodle_link_clicks=None,
                impressions=None, unconverted_rows=None, day_tz=pill["day_tz"])
    if measured:
        block = _block(raw, "spend")
        unconverted = _count(block.get("unconverted_rows")) or 0
        n.update(toodle_link_clicks=_count(block.get("toodle_link_clicks")),
                 impressions=_count(block.get("impressions")), unconverted_rows=unconverted)
        if unconverted:
            n["note"] = _join(n["note"], f"{_plural(unconverted, 'spend row has', 'spend rows have')} no US dollar "
                                         "amount yet (no exchange rate), so the spend is not shown")
        else:
            cents = _count(block.get("toodle_usd_cents"))
            n.update(value=cents, toodle_usd_cents=cents, all_usd_cents=_count(block.get("all_usd_cents")))
    if toodle.unset:
        n.update(value=None, toodle_usd_cents=None, toodle_link_clicks=None, connected=False,
                 state="not_connected", note=_join(toodle.unset, n["note"]))
    elif toodle.waiting:                        # only while Meta is connected: connected, not final
        n.update(value=None, toodle_usd_cents=None, toodle_link_clicks=None, state="partial",
                 note=_join(toodle.waiting, n["note"]))
    return n


def _cpl(raw: dict, meta: dict, kit: dict, toodle: _Toodle = _Toodle()) -> dict:
    """The stop rule: the verdict from SQL when Meta and Kit are both connected,
    the Toodle campaigns are set, and Kit has counted the opt-ins from the
    first spend day in the window to the end of the last; null otherwise, with
    the reason. Until Kit has read to the end of the last spend day, or while
    the stored Toodle labels may not follow the list (toodle.waiting), it is
    connected but has no verdict yet (partial): opt-ins still to come would
    lower the cost per opt-in, and the spend is the old list's. value is the
    cost per Meta opt-in, null while any spend has no US dollar amount
    (check_currency). A no_spend verdict stays a verdict, with the last Meta
    sync's warning on listed campaigns it saw no spend for (toodle.unseen): a
    mistyped id reads like a paused campaign, whose 0 is real."""
    settings = ledger.cpl_settings()
    n = {"value": None, "connected": False, "state": "not_connected", "source": "meta_ads, kit", "note": "",
         "verdict": None, "verdict_text": "", **dict.fromkeys(_CPL_FIELDS),
         "spend_days_needed": settings.days, "stop_above_cents": settings.stop_cents}
    block = _block(raw, "cpl")
    missing = [p["name"] for p in (meta, kit) if not p["connected"]]
    first, last, kit_from = _date(block.get("first_day")), _date(block.get("last_day")), _date(kit["measured_from"])
    text = None
    if missing:
        n["note"] = f"needs {' and '.join(missing)}"
    elif toodle.unset:
        n["note"], text = toodle.unset, "No verdict until the Toodle campaigns are set."
    elif toodle.waiting:
        n.update(connected=True, state="partial", note=toodle.waiting)
        text = toodle.waiting_text
    elif block.get("verdict") not in VERDICTS:
        n["note"] = "the database gave no verdict"
    elif first is not None and kit_from is not None and first < kit_from:
        n["note"] = f"Kit counts opt-ins only from {kit_from.isoformat()}, but the spend days start on {first.isoformat()}"
    elif last is not None and not _synced_past(kit, last):
        n.update(connected=True, state="partial", note=f"waiting for Kit to finish {day_label(last)}")
        text = f"No verdict until Kit has counted every opt-in of {day_label(last)}."
    else:
        final = meta["state"] == "final" and kit["state"] == "final"
        n.update({k: block.get(k) for k in _CPL_FIELDS}, value=block.get("cpl_meta_usd_cents"),
                 verdict=block["verdict"], connected=True, state="final" if final else "partial",
                 stop_above_cents=_count(block.get("stop_above_cents")) or settings.stop_cents)
        if block["verdict"] == "check_currency" or _count(block.get("unconverted_spend_rows")):
            # board_cpl sums only the days that have US dollars: never show that as the spend or a CPL
            n.update(value=None, spend_usd_cents=None, cpl_meta_usd_cents=None, cpl_all_usd_cents=None)
        if not final:
            n["note"] = "partial: Meta and Kit have not both synced past the end of this day"
        if block["verdict"] == "no_spend" and toodle.unseen:
            n["note"] = _join(n["note"], toodle.unseen)
    n["verdict_text"] = text or verdict_text(n)
    return n


def verdict_text(cpl: dict) -> str:
    """The stop rule's verdict in plain words, for the CPL card."""
    if not cpl.get("connected"):
        return "No verdict until Meta spend and Kit opt-ins are both connected."
    verdict = cpl.get("verdict")
    days, need = cpl.get("spend_days") or 0, cpl.get("spend_days_needed")
    stop, spent = money(cpl.get("stop_above_cents")), money(cpl.get("spend_usd_cents"))
    meta, toodle = cpl.get("meta_optins") or 0, cpl.get("toodle_optins") or 0
    if verdict == "no_spend":
        return f"No Toodle ad spend in the last {CPL_LOOKBACK_DAYS} days."
    if verdict == "check_currency":
        rows = cpl.get("unconverted_spend_rows") or 0
        return (f"Check the currency: {_plural(rows, 'spend row has', 'spend rows have')} no US dollar amount "
                "yet, so the cost per opt-in cannot be worked out.")
    if verdict == "collecting" and need is not None and days < need:
        return f"Collecting: {days} of {need} spend days so far."
    if verdict == "collecting":
        return f"Collecting: {spent} spent over the last {days} spend days and no opt-in yet. It stops above {stop}."
    if verdict == "check_tags":
        return (f"Check the tags: {_plural(toodle, 'Toodle opt-in', 'Toodle opt-ins')} came in over the last "
                f"{days} spend days, but none is tagged meta. Fix the tags before stopping.")
    if verdict == "stop" and meta:
        return (f"STOP: {money(cpl.get('cpl_meta_usd_cents'))} per Meta opt-in over the last {days} spend days, "
                f"above {stop}.")
    if verdict == "stop":
        return f"STOP: {spent} spent over the last {days} spend days and no Meta opt-in."
    if verdict == "ok":
        return (f"OK: {money(cpl.get('cpl_meta_usd_cents'))} per Meta opt-in over the last {days} spend days, "
                f"at or below {stop}.")
    return "No verdict."


# ─── the view ───────────────────────────────────────────────────────────────

def _unavailable(day: date, note: str) -> dict:
    """Every number null and every source not connected: the database cannot say."""
    off = {sid: _off_pill(sid, name, note) for sid, name in SOURCES}
    revenue, _ = _revenue({}, off["stripe"], False)
    cpl = _cpl({}, off["meta_ads"], off["kit"])
    cpl.update(note=note, verdict_text=f"No verdict: {note}.")
    return {"day": day.isoformat(), "label": day_label(day), "tz": TZ_NAME, "hours_in_day": None,
            "starts_at": None, "ends_at": None, "database": "not_connected",
            "numbers": {"optins": _optins({}, off["kit"], False),
                        "replies": _replies({}, off["instantly"], False, day),
                        "revenue": revenue, "spend": _spend({}, off["meta_ads"], False), "cpl": cpl},
            "products": [], "sales": [], "sources": [off[sid] for sid, _ in SOURCES]}


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

    pills, measured = {}, {}
    for source_id, name in SOURCES:
        pills[source_id], measured[source_id] = _pill(source_id, name, the_day, sources)
    revenue, sales = _revenue(raw, pills["stripe"], measured["stripe"])
    toodle = _toodle(pills["meta_ads"])
    return {"day": the_day.isoformat(), "label": day_label(the_day), "tz": raw.get("tz") or TZ_NAME,
            "hours_in_day": raw.get("hours_in_day"), "starts_at": raw.get("starts_at"),
            "ends_at": raw.get("ends_at"), "database": "connected",
            "numbers": {"optins": _optins(raw, pills["kit"], measured["kit"]),
                        "replies": _replies(raw, pills["instantly"], measured["instantly"], the_day),
                        "revenue": revenue,
                        "spend": _spend(raw, pills["meta_ads"], measured["meta_ads"], toodle),
                        "cpl": _cpl(raw, pills["meta_ads"], pills["kit"], toodle)},
            "products": (raw.get("products") or []) if measured["stripe"] else [],
            "sales": sales, "sources": [pills[sid] for sid, _ in SOURCES]}


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


def _no_value(label: str, n: dict) -> str:
    """The line of a number that has no value: not connected, or connected
    with no number yet; the note says why."""
    words = "not connected" if not n.get("connected") else "no number yet"
    return f"{label}: {words} ({n['note']})" if n.get("note") else f"{label}: {words}"


def _so_far(n: dict) -> str:
    return " so far" if n.get("state") == "partial" else ""


def attributed_channels(rev: dict) -> list[tuple[str, int]]:
    """[(channel, net cents)] of the day's attributed revenue: by_channel
    without 'unattributed' and without a channel that nets to 0, the largest
    first, then by name."""
    by_channel = rev.get("by_channel") if isinstance(rev.get("by_channel"), dict) else {}
    pairs = [(str(k), v) for k, v in by_channel.items()
             if k != "unattributed" and _count(v) is not None and v != 0]
    return sorted(pairs, key=lambda kv: (-kv[1], kv[0]))


def _attributed(rev: dict) -> str:
    """' · attributed $29.99 (meta)'; with several channels ' · attributed $49.98
    (meta $29.99, organic $19.99)'; with none ' · attributed $0.00'. Left out
    on a day with no money rows, so a real zero reads as before."""
    total = _count(rev.get("attributed_usd_cents"))
    if not rev.get("counts") or total is None:
        return ""
    pairs = attributed_channels(rev)
    if len(pairs) == 1:
        return f" · attributed {money(total)} ({pairs[0][0]})"
    if pairs:
        return f" · attributed {money(total)} ({', '.join(f'{name} {money(cents)}' for name, cents in pairs)})"
    return f" · attributed {money(total)}"


def summary_line(view: dict) -> str:
    """The revenue line of the morning message, in plain text: 'Revenue:
    $10.00 net · attributed $29.99 (meta) · fees $3.17'."""
    rev = view["numbers"]["revenue"]
    if rev["value"] is None:
        return _no_value("Revenue", rev)
    line = f"Revenue: {money(rev['net_usd_cents'])} net{_so_far(rev)}{_attributed(rev)}"
    line += f" · fees {money(rev['fees_usd_cents'])}"
    if rev["state"] == "partial":
        line += " (partial)"
    return line


def optins_line(n: dict) -> str:
    """'Toodle opt-ins: 2 · target 3 · meta 1, organic 1'"""
    if n["value"] is None:
        return _no_value("Toodle opt-ins", n)
    line = f"Toodle opt-ins: {n['value']}{_so_far(n)} · target {n['target']}"
    split = ", ".join(f"{channel} {count}" for channel, count in (n.get("by_channel") or {}).items())
    return f"{line} · {split}" if split else line


def replies_line(n: dict) -> str:
    """'SiteBoost replies: 1 · last 7 days: 2 (target 1 a week) · 1 automatic
    reply or bounce ignored' (the ignored count holds both)"""
    if n["value"] is None:
        return _no_value("SiteBoost replies", n)
    line = f"SiteBoost replies: {n['value']}{_so_far(n)}"
    if n.get("value_7d") is not None:
        line += f" · last 7 days: {n['value_7d']} (target {n['target_per_week']} a week)"
    if n.get("auto_replies_ignored"):
        line += (f" · {_plural(n['auto_replies_ignored'], 'automatic reply or bounce', 'automatic replies or bounces')}"
                 " ignored")
    return line


def spend_line(spend: dict, optins: dict) -> str:
    """'Meta: Toodle spend $5.02 · 9 link clicks → 2 opt-ins' (opt-ins: Kit's,
    on the New York day)."""
    if spend["value"] is None:
        return _no_value("Meta", spend)
    line = (f"Meta: Toodle spend {money(spend['toodle_usd_cents'])}{_so_far(spend)} · "
            f"{_plural(spend.get('toodle_link_clicks') or 0, 'link click', 'link clicks')}")
    if optins["value"] is not None:
        return f"{line} → {_plural(optins['value'], 'opt-in', 'opt-ins')}"
    return f"{line} → opt-ins {'not connected' if not optins.get('connected') else 'not counted yet'}"


def cpl_line(cpl: dict) -> str:
    """'Stop rule: CPL $6.28 over the last 5 spend days (4 Meta opt-ins) → STOP (above $5.00)'"""
    if not cpl.get("connected"):
        return f"Stop rule: not connected ({cpl['note']})" if cpl.get("note") else "Stop rule: not connected"
    verdict = cpl["verdict"]
    if verdict is None:                         # connected, waiting for Kit to read the last spend day
        return f"Stop rule: no verdict yet ({cpl['note']})" if cpl.get("note") else "Stop rule: no verdict yet"
    days, need = cpl.get("spend_days") or 0, cpl.get("spend_days_needed")
    stop, spent = money(cpl.get("stop_above_cents")), money(cpl.get("spend_usd_cents"))
    meta, toodle = cpl.get("meta_optins") or 0, cpl.get("toodle_optins") or 0
    over = f"over the last {days} spend days"
    if verdict == "stop" and meta:
        line = (f"CPL {money(cpl.get('cpl_meta_usd_cents'))} {over} "
                f"({_plural(meta, 'Meta opt-in', 'Meta opt-ins')}) → STOP (above {stop})")
    elif verdict == "stop":
        line = f"{spent} spent {over} and no Meta opt-in → STOP (above {stop})"
    elif verdict == "ok":
        line = (f"CPL {money(cpl.get('cpl_meta_usd_cents'))} {over} "
                f"({_plural(meta, 'Meta opt-in', 'Meta opt-ins')}) → OK (at or below {stop})")
    elif verdict == "collecting" and need is not None and days < need:
        line = f"collecting, {days} of {need} spend days so far"
    elif verdict == "collecting":
        line = f"collecting, {spent} spent {over} and no opt-in yet (it stops above {stop})"
    elif verdict == "check_tags":
        line = (f"check the tags: {_plural(toodle, 'Toodle opt-in', 'Toodle opt-ins')} {over} "
                "and none tagged meta")
    elif verdict == "check_currency":
        rows = cpl.get("unconverted_spend_rows") or 0
        line = f"check the currency: {_plural(rows, 'spend row has', 'spend rows have')} no US dollar amount yet"
    elif verdict == "no_spend":
        line = f"no Toodle ad spend in the last {CPL_LOOKBACK_DAYS} days"
    else:
        line = "no verdict"
    return f"Stop rule: {line}{' (partial)' if cpl.get('state') == 'partial' else ''}"


def _escape(text: str) -> str:
    """Text for Telegram HTML: <, > and & escaped. The message puts no value in
    an attribute, so quotes stay as they are (Telegram reads them as text)."""
    return html.escape(text, quote=False)


def render_report(view: dict) -> str:
    """The morning message as Telegram HTML; every value is escaped. A number
    with a value carries its note on an indented line of its own; one without
    a value carries it in brackets."""
    e = _escape
    nums = view["numbers"]
    head = f"<b>{e(view['label'])}</b> (New York"
    if hours_note(view.get("hours_in_day")):
        head += f"; {e(hours_note(view['hours_in_day']))}"
    lines = [head + ")"]

    def add(line: str, number: dict, shown: bool) -> None:
        lines.append(e(line))
        if shown and number.get("note"):
            lines.append(f"  {e(number['note'])}")

    add(optins_line(nums["optins"]), nums["optins"], nums["optins"]["value"] is not None)
    add(replies_line(nums["replies"]), nums["replies"], nums["replies"]["value"] is not None)
    rev = nums["revenue"]
    lines.append(e(summary_line(view)))
    if rev["value"] is not None:
        by_source = rev.get("by_source") or {}
        per_source = rev.get("counts_by_source") or {}
        stripe_counts = per_source.get("stripe", {}) if "counts_by_source" in rev else rev.get("counts") or {}
        lines.append(f"  Stripe {e(money(by_source.get('stripe', 0)))}: {e(_counts_words(stripe_counts))}")
        for source_id in sorted(set(by_source) - {"stripe"}, key=lambda s: (SOURCE_NAMES.get(s, s), s)):
            name = SOURCE_NAMES.get(source_id, source_id)
            lines.append(f"  {e(name)} {e(money(by_source[source_id]))}: "
                         f"{e(_counts_words(per_source.get(source_id, {})))}")
        if rev.get("note"):
            lines.append(f"  {e(rev['note'])}")
    add(spend_line(nums["spend"], nums["optins"]), nums["spend"], nums["spend"]["value"] is not None)
    add(cpl_line(nums["cpl"]), nums["cpl"], nums["cpl"].get("verdict") is not None)
    states = " · ".join(f"{s['name']} {s['state'].replace('_', ' ')}" for s in view["sources"])
    lines.append(f"Sources: {e(states)}")
    return "\n".join(lines)
