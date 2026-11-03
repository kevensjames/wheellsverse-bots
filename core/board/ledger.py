"""Money rows, lead events and ad spend for the daily numbers board, and the
board's calls into Supabase.

Every write goes through the tables and SQL functions of
narai/migrations/0002_daily_numbers_board.sql (replica/schema.sql): over
PostgREST, with the service-role key (RLS is on with no policies, so no other
key can read these tables), one short HTTP call each, the way
core/board/auth.py reads owner_sessions. No supabase-py client.

  LedgerRow    one money movement (ledger_entries), written by board_ingest_ledger
  LeadRow      one Toodle opt-in or SiteBoost reply (lead_events), by board_ingest_leads
  AdSpendRow   one campaign's spend on one ad-account day (ad_spend_daily), a PostgREST upsert
  clicks       one /go redirect (public.clicks), never with an IP address: insert_click
               (live), import_clicks (the old JSON log), clicks_by_id and click_channel
               (the Stripe sync's click attribution), and the readers behind
               core/click_tracker.py

Totals come from SQL: board_day computes one New York calendar day in one
round trip, and board_revenue_daily one row per day, source and channel.
Python adds only whole board_revenue_daily rows, read completely (read_days:
the API answers at most MAX_ROWS rows to one read, so a long window is read
in parts, and a single day it cannot read whole raises), and counts come from
PostgREST's exact count. Ledger rows are never summed here. A list that must
be whole (every click) is read page by page until an empty page (read_all).

Amounts are integer minor units of their currency (cents for USD). A NULL USD
amount or fee means "unknown", never 0. to_minor_units turns a decimal string
into minor units with the SQL's own exponent table.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Any, NamedTuple, Optional
from uuid import UUID

import httpx

from core.board.auth import _usable_url

log = logging.getLogger("board.ledger")

# Tests put an httpx.MockTransport here; None means the real network.
_transport: Optional[httpx.BaseTransport] = None
_TIMEOUT = 20.0          # seconds, each call
_INGEST_CHUNK = 500      # rows per board_ingest_ledger or board_ingest_leads call
_SPEND_CHUNK = 500       # rows per ad_spend_daily upsert
_IDS_CHUNK = 100         # external ids per lookup
_INT_MAX = 2 ** 31 - 1   # Postgres int
_BIGINT_MAX = 2 ** 63 - 1

KINDS = frozenset({"sale", "refund", "dispute", "dispute_reversal", "fee", "adjustment"})
LEAD_KINDS = frozenset({"optin", "reply"})


class BoardDBError(Exception):
    """The board's tables could not be read or written: Supabase unset,
    unreachable, or the call refused (a missing migration, a bad money field)."""


class TooManyRows(BoardDBError):
    """read_all stopped at its cap (READ_ALL_MOST): the database answered,
    but there are more rows than one whole read takes."""


# ─── the connector contract: one money movement ─────────────────────────────

@dataclass(frozen=True)
class LedgerRow:
    """One row of public.ledger_entries, as board_ingest_ledger takes it.
    external_id is the source's id for the money movement (Stripe: the balance
    transaction, txn_...), never the id of an event that announced it."""
    external_id: str
    kind: str
    amount_minor: int
    currency: str
    occurred_at: Optional[datetime] = None
    occurred_on: Optional[date] = None
    amount_usd_cents: Optional[int] = None
    fx_source: Optional[str] = None
    fee_usd_cents: Optional[int] = None
    product: Optional[str] = None
    quantity: Optional[int] = None
    customer_email: Optional[str] = None
    channel: Optional[str] = None
    attribution: str = "none"
    click_id: Optional[UUID] = None
    order_ref: Optional[str] = None
    via_platform: Optional[str] = None
    raw: dict = field(default_factory=dict)

    def __post_init__(self):
        # Money fields are checked again by the SQL; these catch a connector bug early.
        for name in ("amount_minor", "amount_usd_cents", "fee_usd_cents"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise TypeError(f"{name} must be integer minor units, not {type(value).__name__}")
        if self.kind not in KINDS:
            raise ValueError(f"unknown ledger kind {self.kind!r}")
        if (self.occurred_at is None) == (self.occurred_on is None):
            raise ValueError("a ledger row has exactly one of occurred_at and occurred_on")
        if self.occurred_at is not None and self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must carry a time zone")

    def as_json(self) -> dict:
        """The row as one element of board_ingest_ledger's p_rows (unset fields left out)."""
        out: dict[str, Any] = {"external_id": self.external_id, "kind": self.kind,
                               "amount_minor": self.amount_minor, "currency": self.currency,
                               "attribution": self.attribution, "raw": self.raw}
        if self.occurred_at is not None:
            out["occurred_at"] = self.occurred_at.astimezone(timezone.utc).isoformat()
        if self.occurred_on is not None:
            out["occurred_on"] = self.occurred_on.isoformat()
        if self.click_id is not None:
            out["click_id"] = str(self.click_id)
        for name in ("amount_usd_cents", "fx_source", "fee_usd_cents", "product", "quantity",
                     "customer_email", "channel", "order_ref", "via_platform"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        return out


# ─── amounts: decimal strings to integer minor units ────────────────────────

# ISO 4217 minor-unit exponents: the same table as board_currency_exponent in
# the SQL (a test compares the two). Every other currency has 2.
_EXPONENTS = {**dict.fromkeys(("BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF",
                               "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF"), 0),
              **dict.fromkeys(("BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"), 3),
              **dict.fromkeys(("CLF", "UYW"), 4)}
_CURRENCY_RE = re.compile(r"[A-Z]{3}")
_DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]{1,18}(?:\.[0-9]{0,12})?|\.[0-9]{1,12})")


def _currency(code) -> str:
    """An ISO 4217 code, trimmed and upper-cased."""
    if not isinstance(code, str):
        raise TypeError("a currency is a 3-letter ISO code")
    code = code.strip().upper()
    if not _CURRENCY_RE.fullmatch(code):
        raise ValueError("a currency is a 3-letter ISO code")
    return code


def currency_exponent(currency: str) -> int:
    """Digits after the decimal point in `currency`: 2 for USD, 0 for JPY, 3 for KWD."""
    return _EXPONENTS.get(_currency(currency), 2)


def to_minor_units(amount, currency: str) -> int:
    """A decimal amount in major units ("25.10", Decimal("25.10") or 25) as an
    integer amount of the currency's minor unit (2510 cents). Exact arithmetic:
    a float is refused, and so is an amount with more decimal places than the
    currency has. It is never rounded."""
    if isinstance(amount, (bool, float)):
        raise TypeError("an amount is a decimal string, a Decimal or an int, never a float")
    if isinstance(amount, int):
        value = Decimal(amount)
    elif isinstance(amount, Decimal):
        value = amount
    elif isinstance(amount, str):
        text = amount.strip()
        if not _DECIMAL_RE.fullmatch(text):
            raise ValueError("an amount is a plain decimal number, such as 25.10")
        value = Decimal(text)
    else:
        raise TypeError("an amount is a decimal string, a Decimal or an int")
    if not value.is_finite() or (value and not -12 <= value.adjusted() <= 18):
        raise ValueError("the amount is not a usable sum of money")
    minor = Fraction(value) * 10 ** currency_exponent(currency)
    if minor.denominator != 1:
        raise ValueError(f"the amount has more decimal places than {_currency(currency)} has")
    return int(minor)


# ─── shared checks for the lead and spend rows ──────────────────────────────

_FUNNEL_RE = re.compile(r"[A-Za-z0-9_]{1,32}")


def _no_nul(value):
    """`value` with NUL removed from every string in it. Postgres text and
    jsonb refuse NUL, so one stray NUL in a label would fail the whole batch,
    and a label must never block a sync."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {_no_nul(k): _no_nul(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_no_nul(v) for v in value]
    return value


def _key(value, name: str, longest: int) -> None:
    """A row's key: 1 to `longest` characters (a check in the SQL)."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not 1 <= len(value) <= longest or "\x00" in value:
        raise ValueError(f"{name} must be 1 to {longest} characters")


def _label(value, name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} must be a string or None")


def _funnel(value) -> Optional[str]:
    """A funnel as the SQL stores it ('toodle'): trimmed, lower-cased, empty as
    None. Its column has a check and no fallback, so a funnel with any other
    character would fail the whole batch; it is refused here instead."""
    _label(value, "funnel")
    trimmed = value.strip(" ") if value is not None else ""
    if not trimmed:
        return None
    if not _FUNNEL_RE.fullmatch(trimmed):
        raise ValueError("a funnel is letters, digits or _, at most 32")
    return trimmed.lower()


# ─── lead events: Toodle opt-ins (Kit) and SiteBoost replies (Instantly) ────

@dataclass(frozen=True)
class LeadRow:
    """One row of public.lead_events, as board_ingest_leads reads it.

    Kit: external_id '<funnel>:sub:<subscriber id>' ('toodle:sub:123'), kind
    'optin', occurred_at the first Toodle tag time. Instantly: the email id,
    kind 'reply', occurred_at the time Instantly stored the email.

    What would fail the SQL, and so the whole batch, is refused here: a kind
    other than optin or reply, a time without a zone, an external_id that is
    empty or longer than 255 characters, an auto-reply that is not a reply, a
    funnel with characters other than letters, digits and _. Labels are kept as
    given, because the SQL normalises them: a malformed email is dropped, a
    missing channel is 'unknown' and a malformed one 'other', tags are
    lower-cased."""
    external_id: str
    kind: str
    occurred_at: datetime
    email: Optional[str] = None
    funnel: Optional[str] = None
    channel: Optional[str] = None
    campaign_ref: Optional[str] = None
    tags: tuple = ()
    is_auto_reply: bool = False
    raw: dict = field(default_factory=dict)

    def __post_init__(self):
        _key(self.external_id, "external_id", 255)
        if not isinstance(self.kind, str) or self.kind not in LEAD_KINDS:
            raise ValueError("a lead's kind is optin or reply")
        if not isinstance(self.occurred_at, datetime):
            raise TypeError("occurred_at must be a datetime")
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must carry a time zone")
        if not isinstance(self.is_auto_reply, bool):
            raise TypeError("is_auto_reply must be True or False")
        if self.is_auto_reply and self.kind != "reply":
            raise ValueError("only a reply can be an auto-reply")
        _funnel(self.funnel)
        for name in ("email", "channel", "campaign_ref"):
            _label(getattr(self, name), name)
        if not isinstance(self.tags, (list, tuple)) or not all(isinstance(t, str) for t in self.tags):
            raise TypeError("tags must be a list of strings")
        object.__setattr__(self, "tags", tuple(self.tags))
        if not isinstance(self.raw, dict):
            raise TypeError("raw must be a dict")

    def as_json(self) -> dict:
        """The row as one element of board_ingest_leads's p_rows: exactly the
        columns it reads, occurred_at in UTC."""
        return {"external_id": self.external_id, "kind": self.kind,
                "occurred_at": self.occurred_at.astimezone(timezone.utc).isoformat(),
                "email": _no_nul(self.email), "funnel": self.funnel, "channel": _no_nul(self.channel),
                "campaign_ref": _no_nul(self.campaign_ref), "tags": _no_nul(list(self.tags)),
                "is_auto_reply": self.is_auto_reply, "raw": _no_nul(self.raw)}


# ─── ad spend: Meta Insights, one row per campaign per ad-account day ───────

@dataclass(frozen=True, kw_only=True)
class AdSpendRow:
    """One row of public.ad_spend_daily: one campaign's spend on one day of the
    ad account's own calendar (sources.day_tz), in the account's currency.
    Keyword arguments only.

    spend_minor is integer minor units: to_minor_units(spend, currency), never
    a float. A USD row is its own USD (fx_source 'identity'). A row in any
    other currency goes in with no USD, and board_fill_fx (fill_fx) gives it
    USD from the ECB rate on or before its day. The funnel is stored trimmed
    and lower-cased; currency upper-cased."""
    campaign_id: str
    campaign_name: Optional[str] = None
    funnel: Optional[str] = None
    day: date
    currency: str
    spend_minor: int
    impressions: int = 0
    link_clicks: int = 0
    platform_leads: Optional[int] = None

    def __post_init__(self):
        _key(self.campaign_id, "campaign_id", 64)
        _label(self.campaign_name, "campaign_name")
        object.__setattr__(self, "funnel", _funnel(self.funnel))
        if not isinstance(self.day, date) or isinstance(self.day, datetime):
            raise TypeError("day must be a date (the ad account's own day), not a datetime")
        object.__setattr__(self, "currency", _currency(self.currency))
        for name, top in (("spend_minor", _BIGINT_MAX), ("impressions", _BIGINT_MAX),
                          ("link_clicks", _BIGINT_MAX), ("platform_leads", _INT_MAX)):
            value = getattr(self, name)
            if value is None and name == "platform_leads":
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer" + (" of minor units" if name == "spend_minor" else ""))
            if not 0 <= value <= top:
                raise ValueError(f"{name} must be from 0 to {top}")

    def as_json(self) -> dict:
        """The row's columns for the upsert. Every row carries the same keys,
        nulls included: PostgREST takes a bulk upsert's columns from them, and
        a re-pulled day replaces every one of them. So a non-USD day's old
        conversion is cleared, and board_fill_fx makes it again from the new
        amount."""
        usd = self.currency == "USD"
        return {"campaign_id": self.campaign_id, "campaign_name": _no_nul(self.campaign_name),
                "funnel": self.funnel, "day": self.day.isoformat(), "currency": self.currency,
                "spend_minor": self.spend_minor, "spend_usd_cents": self.spend_minor if usd else None,
                "fx_source": "identity" if usd else None, "fx_rate": None,
                "impressions": self.impressions, "link_clicks": self.link_clicks,
                "platform_leads": self.platform_leads}


# ─── PostgREST with the service-role key ────────────────────────────────────

@dataclass(frozen=True)
class DBSettings:
    url: str
    service_key: str


def db_settings() -> Optional[DBSettings]:
    """SUPABASE_URL and SUPABASE_SERVICE_KEY, read at call time; None while
    either is unset or unusable."""
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key or not _usable_url(url) or not (key.isascii() and key.isprintable()):
        return None
    return DBSettings(url=url, service_key=key)


def _pg_error(r: httpx.Response) -> str:
    """PostgREST's error code and message. Never its `details`, which can quote
    a failing row (buyer emails)."""
    try:
        body = r.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    code = str(body.get("code") or "")[:12]
    message = " ".join(str(body.get("message") or "").split())[:200]
    return f" ({code}: {message})" if (code or message) else ""


def _call(method: str, path: str, *, params=None, json=None, prefer: Optional[str] = None,
          timeout: Optional[float] = None) -> httpx.Response:
    """One PostgREST call with the service key. `timeout` in seconds (default
    _TIMEOUT). Raises BoardDBError, whose message never holds a key or a row."""
    cfg = db_settings()
    if cfg is None:
        raise BoardDBError("SUPABASE_URL or SUPABASE_SERVICE_KEY is not set")
    headers = {"apikey": cfg.service_key, "Authorization": f"Bearer {cfg.service_key}",
               "Accept": "application/json"}
    if json is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    try:
        with httpx.Client(transport=_transport, timeout=_TIMEOUT if timeout is None else timeout) as client:
            r = client.request(method, f"{cfg.url}/rest/v1/{path}", params=params, json=json,
                               headers=headers)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        raise BoardDBError(f"{path}: {type(e).__name__}") from None
    if r.status_code >= 300:
        raise BoardDBError(f"{path}: HTTP {r.status_code}{_pg_error(r)}")
    return r


def _json(r: httpx.Response):
    if not r.content:
        return None
    try:
        return r.json()
    except ValueError:
        raise BoardDBError(f"{r.request.url.path}: not JSON") from None


def rpc(name: str, params: dict):
    """Call one board SQL function (POST /rest/v1/rpc/<name>)."""
    return _json(_call("POST", f"rpc/{name}", json=params))


def _ts(value: datetime) -> str:
    """A timestamptz for PostgREST, in UTC with a Z (no '+' to escape in a URL)."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now() -> str:
    return _ts(datetime.now(timezone.utc))


def parse_ts(value) -> Optional[datetime]:
    """A timestamptz from PostgREST JSON, as an aware datetime; None when absent."""
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


# ─── job runs: every sync and report send starts with a claim ───────────────

def claim_run(job: str, run_key: str, trigger: str = "schedule",
              source_id: Optional[str] = None) -> Optional[str]:
    """board_claim_run: the job_runs id to work under, or None when there is
    nothing to do now (that key finished already, or another run of the job is
    in progress). A failed run with the same key is claimed again."""
    result = rpc("board_claim_run", {"p_job": job, "p_run_key": run_key,
                                     "p_trigger_kind": trigger, "p_source_id": source_id})
    return str(result) if result else None


def finish_run(run_id: str, status: str, *, rows_written: int = 0, detail: Optional[dict] = None,
               error: Optional[str] = None, window_start: Optional[datetime] = None,
               window_end: Optional[datetime] = None, covered_until: Optional[datetime] = None) -> None:
    """Close a claimed run: ok, failed or skipped."""
    body: dict[str, Any] = {"status": status, "finished_at": _now(), "rows_written": max(0, int(rows_written)),
                            "detail": detail or {}, "error": (error or None) and error[:500]}
    for name, value in (("window_start", window_start), ("window_end", window_end),
                        ("covered_until", covered_until)):
        if value is not None:
            body[name] = _ts(value)
    _call("PATCH", "job_runs", params={"id": f"eq.{run_id}"}, json=body, prefer="return=minimal")


def last_ok_detail(job: str) -> Optional[dict]:
    """The detail of `job`'s last complete run (status ok, the one that
    finished last), or None when it has none. A connector records there what
    a run read (Kit: its tag set), so the next run can tell a setting changed."""
    rows = _json(_call("GET", "job_runs", params={
        "select": "detail", "job": f"eq.{job}", "status": "eq.ok",
        "order": "finished_at.desc.nullslast", "limit": "1"}))
    if isinstance(rows, list) and rows and isinstance(rows[0], dict) and isinstance(rows[0].get("detail"), dict):
        return rows[0]["detail"]
    return None


# ─── sources: state, watermark, measured_from ───────────────────────────────

def source_row(source_id: str) -> Optional[dict]:
    rows = _json(_call("GET", "sources", params={
        "select": "id,enabled,measured_from,synced_through,day_tz,currency,account_ref,"
                  "last_ok_at,last_error,last_error_at",
        "id": f"eq.{source_id}", "limit": "1"}))
    return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None


def mark_source_ok(source_id: str, synced_through: datetime, measured_from: Optional[date] = None,
                   warning: Optional[str] = None) -> None:
    """After a complete run: set measured_from if it was never set (the first
    run's backfill start), then move the watermark forward (never back), then
    set last_ok_at and replace last_error with the run's warning, or clear it.
    In that order, so a failure half-way never leaves a watermark without
    measured_from. A warning shares last_ok_at's timestamp, which is how the
    board tells it from a failed run's error."""
    if measured_from is not None:
        _call("PATCH", "sources", params={"id": f"eq.{source_id}", "measured_from": "is.null"},
              json={"measured_from": measured_from.isoformat()}, prefer="return=minimal")
    mark = _ts(synced_through)
    # ':' and '.' are reserved inside a PostgREST logic tree: the value is quoted.
    _call("PATCH", "sources",
          params={"id": f"eq.{source_id}", "or": f'(synced_through.is.null,synced_through.lt."{mark}")'},
          json={"synced_through": mark}, prefer="return=minimal")
    now = _now()
    _call("PATCH", "sources", params={"id": f"eq.{source_id}"},
          json={"last_ok_at": now, "last_error": warning[:300] if warning else None,
                "last_error_at": now if warning else None}, prefer="return=minimal")


def mark_source_error(source_id: str, message: str) -> None:
    _call("PATCH", "sources", params={"id": f"eq.{source_id}"},
          json={"last_error": message[:300], "last_error_at": _now()}, prefer="return=minimal")


SOURCE_FIELDS = ("day_tz", "currency", "account_ref")
_DAY_TZ_RE = re.compile(r"[A-Za-z_]+(?:/[A-Za-z0-9_+-]+)*")    # sources.day_tz's check


def update_source(source_id: str, **fields) -> None:
    """Record what a connector read about its account on its sources row, and
    nothing else: day_tz (the zone of the account's own days, such as Meta's
    timezone_name), currency (an ISO code, or None) and account_ref (an account
    id such as act_123, never a secret, or None). The database refuses a zone it
    does not know (BoardDBError)."""
    unknown = sorted(set(fields) - set(SOURCE_FIELDS))
    if unknown:
        raise TypeError(f"update_source writes only {', '.join(SOURCE_FIELDS)}, not {', '.join(unknown)}")
    body: dict[str, Any] = {}
    if "day_tz" in fields:
        tz = fields["day_tz"]
        if not isinstance(tz, str) or not _DAY_TZ_RE.fullmatch(tz):
            raise ValueError("day_tz must be a time zone name, such as America/New_York")
        body["day_tz"] = tz
    if "currency" in fields:
        body["currency"] = None if fields["currency"] is None else _currency(fields["currency"])
    if "account_ref" in fields:
        ref = fields["account_ref"]
        _label(ref, "account_ref")
        body["account_ref"] = (_no_nul(ref).strip() or None) if ref is not None else None
    if body:
        _call("PATCH", "sources", params={"id": f"eq.{source_id}"}, json=body, prefer="return=minimal")


# ─── ledger ─────────────────────────────────────────────────────────────────

def existing_ids(source_id: str, external_ids: list[str]) -> set[str]:
    """Which of these movements the ledger has already (so a sync fetches a
    sale's labels once). Ids are Stripe ids: letters, digits and _."""
    found: set[str] = set()
    ids = sorted({i for i in external_ids if i and i.replace("_", "").isalnum()})
    for start in range(0, len(ids), _IDS_CHUNK):
        chunk = ids[start:start + _IDS_CHUNK]
        rows = _json(_call("GET", "ledger_entries", params={
            "select": "external_id", "source_id": f"eq.{source_id}",
            "external_id": f"in.({','.join(chunk)})"}))
        found.update(str(r.get("external_id")) for r in rows or [] if isinstance(r, dict))
    return found


def ingest_ledger(source_id: str, run_id: Optional[str], rows: list[LedgerRow]) -> dict:
    """board_ingest_ledger, in chunks. Inserts new movements; one already there
    keeps its money and may only gain labels. A bad money field fails its chunk
    loudly (BoardDBError). Returns the summed counts."""
    total = {"received": 0, "inserted": 0, "relabelled": 0, "money_mismatches": 0}
    for start in range(0, len(rows), _INGEST_CHUNK):
        chunk = [r.as_json() for r in rows[start:start + _INGEST_CHUNK]]
        result = rpc("board_ingest_ledger", {"p_source_id": source_id, "p_job_run_id": run_id,
                                             "p_rows": chunk})
        row = result[0] if isinstance(result, list) and result else result
        if not isinstance(row, dict):
            raise BoardDBError("board_ingest_ledger: unexpected answer")
        for k in total:
            total[k] += int(row.get(k) or 0)
    return total


# ─── lead events ────────────────────────────────────────────────────────────

def _chunks_by_key(rows: list, key, size: int):
    """Chunks of at most `size` rows, where rows sharing a key are never split
    (a key with more rows than `size` gets a chunk of its own)."""
    groups: dict = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    chunk: list = []
    for group in groups.values():
        if chunk and len(chunk) + len(group) > size:
            yield chunk
            chunk = []
        chunk.extend(group)
    if chunk:
        yield chunk


def ingest_leads(source_id: str, run_id: Optional[str], rows: list[LeadRow]) -> dict:
    """board_ingest_leads, in chunks of at most _INGEST_CHUNK rows. A key seen
    before keeps its earliest time, gains a known channel where its own is
    'unknown', and gains tags (the union); its email, funnel and campaign are
    filled only where missing, and once an auto-reply, always one.

    Within one call the SQL keeps one row per external_id, the earliest, whole:
    the labels of a later row with the same key are dropped, not merged. So
    merge rows per key before calling (the Kit sync merges per subscriber).
    Rows that share a key always go in the same call, so the outcome never
    depends on where a chunk ends. Returns the summed received, inserted and
    relabelled (relabelled: keys that were there already)."""
    total = {"received": 0, "inserted": 0, "relabelled": 0}
    for chunk in _chunks_by_key(list(rows), lambda r: r.external_id, _INGEST_CHUNK):
        result = rpc("board_ingest_leads", {"p_source_id": source_id, "p_job_run_id": run_id,
                                            "p_rows": [r.as_json() for r in chunk]})
        row = result[0] if isinstance(result, list) and result else result
        if not isinstance(row, dict):
            raise BoardDBError("board_ingest_leads: unexpected answer")
        for k in total:
            total[k] += int(row.get(k) or 0)
    return total


# ─── ad spend and FX ────────────────────────────────────────────────────────

def upsert_ad_spend(source_id: str, run_id: Optional[str], rows: list[AdSpendRow]) -> int:
    """Write daily ad spend: a PostgREST upsert on ad_spend_daily's key
    (source_id, campaign_id, day), in chunks. Meta revises recent days, so the
    last pull wins: every column of a re-pulled day is replaced, pulled_at and
    job_run_id included, and a non-USD day loses its old USD until fill_fx()
    converts it again (call it after). The same campaign and day twice in one
    call is refused before anything is sent (ValueError): Postgres would fail
    the whole statement. Returns the number of rows written."""
    rows = list(rows)
    seen: set = set()
    for r in rows:
        if (r.campaign_id, r.day) in seen:
            raise ValueError(f"campaign {r.campaign_id} on {r.day.isoformat()} appears twice in one upsert")
        seen.add((r.campaign_id, r.day))
    pulled_at = _now()
    for start in range(0, len(rows), _SPEND_CHUNK):
        body = [{**r.as_json(), "source_id": source_id, "job_run_id": run_id, "pulled_at": pulled_at}
                for r in rows[start:start + _SPEND_CHUNK]]
        _call("POST", "ad_spend_daily", params={"on_conflict": "source_id,campaign_id,day"}, json=body,
              prefer="resolution=merge-duplicates,return=minimal")
    return len(rows)


_CAMPAIGN_ID_RE = re.compile(r"[0-9]{1,64}")


def label_spend_funnel(source_id: str, funnel: str, campaign_ids) -> None:
    """Make every stored spend row of `source_id` follow the current campaign
    list, not only the days a run pulls again: `funnel` on each row whose
    campaign is listed, none on each row labelled `funnel` whose campaign is
    not (with no campaign listed, no row keeps it). Two PostgREST PATCHes,
    campaign_id=in.(...) and campaign_id=not.in.(...), each touching only the
    rows whose label is wrong. Only the label changes, never the money.
    Campaign ids are Meta's, digits only; anything else raises ValueError."""
    label = _funnel(funnel)
    if label is None:
        raise ValueError("a funnel to label the spend with is needed")
    ids = {c.strip() if isinstance(c, str) else c for c in campaign_ids}
    if not all(isinstance(c, str) and _CAMPAIGN_ID_RE.fullmatch(c) for c in ids):
        raise ValueError("a campaign id to label is digits only")
    listed = ",".join(sorted(ids, key=lambda c: (len(c), c)))
    if ids:
        _call("PATCH", "ad_spend_daily", params={"source_id": f"eq.{source_id}", "campaign_id": f"in.({listed})",
                                                 "or": f"(funnel.is.null,funnel.neq.{label})"},
              json={"funnel": label}, prefer="return=minimal")
    cleared = {"source_id": f"eq.{source_id}", "funnel": f"eq.{label}"}
    if ids:
        cleared["campaign_id"] = f"not.in.({listed})"
    _call("PATCH", "ad_spend_daily", params=cleared, json={"funnel": None}, prefer="return=minimal")


def fill_fx() -> int:
    """board_fill_fx: USD for the ledger and spend rows still without it, from
    the ECB rate on or before their day (at most 6 days back). Stripe rows are
    never converted. Returns how many rows it converted."""
    result = rpc("board_fill_fx", {})
    if isinstance(result, bool) or not isinstance(result, int):
        raise BoardDBError("board_fill_fx: unexpected answer")
    return result


# ─── webhook events: each provider event runs once ──────────────────────────

def claim_webhook(source_id: str, event_id: str, event_type: str, livemode: Optional[bool]) -> str:
    """board_claim_webhook: 'run', 'busy' or 'done'."""
    result = rpc("board_claim_webhook", {"p_source_id": source_id, "p_event_id": event_id,
                                         "p_event_type": event_type, "p_livemode": livemode})
    if result not in ("run", "busy", "done"):
        raise BoardDBError(f"board_claim_webhook: unexpected answer {str(result)[:20]!r}")
    return result


def finish_webhook(source_id: str, event_id: str, ok: bool, error: Optional[str] = None) -> None:
    """Mark a claimed event processed, or failed (it runs again on Stripe's retry)."""
    body = ({"status": "processed", "processed_at": _now(), "error": None} if ok
            else {"status": "failed", "error": (error or "failed")[:500]})
    _call("PATCH", "webhook_events",
          params={"source_id": f"eq.{source_id}", "event_id": f"eq.{event_id}"},
          json=body, prefer="return=minimal")


# ─── the day view ───────────────────────────────────────────────────────────

CPL_DAYS_DEFAULT = 5          # BOARD_CPL_DAYS
CPL_STOP_CENTS_DEFAULT = 500  # BOARD_CPL_STOP_CENTS
_cpl_warned: set = set()      # (variable, value) pairs warned about already: one warning each


class CplSettings(NamedTuple):
    days: int          # spend days the stop rule waits for
    stop_cents: int    # stop when the cost per Meta opt-in is above this


def _setting(name: str, default: int, top: int, what: str) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    if re.fullmatch(r"[0-9]{1,10}", raw) and 1 <= int(raw) <= top:
        return int(raw)
    if (name, raw) not in _cpl_warned:
        _cpl_warned.add((name, raw))
        log.warning("%s must be %s; using %s", name, what, default)
    return default


def cpl_settings() -> CplSettings:
    """The stop rule (marketing/GLOBAL_PLAN.md:128: stop if CPL is above $5
    after 5 days of spend): BOARD_CPL_DAYS, whole spend days from 1 to 30 (the
    SQL looks back 30 days), default 5; BOARD_CPL_STOP_CENTS, whole cents above
    0, default 500. A value that is not valid falls back to the default, with
    one log warning."""
    return CplSettings(
        days=_setting("BOARD_CPL_DAYS", CPL_DAYS_DEFAULT, 30, "a whole number of days from 1 to 30"),
        stop_cents=_setting("BOARD_CPL_STOP_CENTS", CPL_STOP_CENTS_DEFAULT, _INT_MAX,
                            "a whole number of cents above 0"))


def board_day(day: Optional[date]) -> dict:
    """board_day: one owner day as JSON. day None = yesterday in New York,
    decided in SQL, not by this container's clock. The stop rule's settings
    (cpl_settings) go with every call."""
    cpl = cpl_settings()
    result = rpc("board_day", {"p_day": day.isoformat() if day else None,
                               "p_cpl_days": cpl.days, "p_cpl_stop_cents": cpl.stop_cents})
    if not isinstance(result, dict):
        raise BoardDBError("board_day: unexpected answer")
    return result


# ─── reads for the legacy money routes (core/board/money.py) ────────────────

MAX_ROWS = 1000      # Supabase's API answers at most this many rows to one read (its db-max-rows)
READ_ALL_MOST = 200_000   # rows read_all reads before it gives up
MONEY_KINDS = ("sale", "refund", "dispute", "dispute_reversal", "adjustment")   # fees are their own number
MANUAL_SOURCE = "manual"
REVENUE_FIELDS = ("sales", "units", "gross_usd_cents", "refunds_usd_cents", "disputes_usd_cents",
                  "net_usd_cents", "fees_usd_cents", "unconverted_rows")
_RANGE_RE = re.compile(r"(?:[0-9]+-[0-9]+|\*)/([0-9]+)")
_WHOLE_RE = re.compile(r"-?[0-9]{1,19}")


def _rows(r: httpx.Response) -> list[dict]:
    rows = _json(r)
    if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
        raise BoardDBError(f"{r.request.url.path}: unexpected answer")
    return rows


def _total(r: httpx.Response) -> Optional[int]:
    """The exact row count PostgREST puts in Content-Range ('0-9/42', '*/0')
    when asked with Prefer: count=exact; None when the answer has none."""
    m = _RANGE_RE.fullmatch(r.headers.get("content-range", "").strip())
    return int(m.group(1)) if m else None


def _params(params) -> list[tuple[str, str]]:
    """Query parameters as (name, value) pairs, so a column can be filtered twice."""
    return list(params.items()) if isinstance(params, dict) else list(params or ())


def read_days(path: str, select: str, first: date, last: date, *, params=None, order: str) -> list[dict]:
    """Every row of `path` (a table or view with a local_day column) whose
    local_day is from `first` to `last`, read completely. One read answers at
    most MAX_ROWS rows (or fewer, if the server is set lower), so each read
    also asks for the exact count: a window that comes back short is split in
    two and each half read again, and a single day that still comes back short
    raises BoardDBError. A read is whole when it holds every row the database
    counted; without a count, only when it is under MAX_ROWS. A total made
    from these rows is never a smaller number. `params` adds filters ((name,
    value) pairs or a dict)."""
    if last < first:
        return []
    query = [("select", select), ("local_day", f"gte.{first.isoformat()}"),
             ("local_day", f"lte.{last.isoformat()}"), *_params(params), ("order", order)]
    r = _call("GET", path, params=query, prefer="count=exact")
    rows, total = _rows(r), _total(r)
    if len(rows) >= total if total is not None else len(rows) < MAX_ROWS:
        return rows
    if first == last:
        raise BoardDBError(f"{path}: {first.isoformat()} has more rows than one read returns")
    middle = first + timedelta(days=(last - first).days // 2)
    return (read_days(path, select, first, middle, params=params, order=order)
            + read_days(path, select, middle + timedelta(days=1), last, params=params, order=order))


def read_all(path: str, select: str, *, params=None, order: str, most: Optional[int] = None) -> list[dict]:
    """Every row of `path` that matches `params`, in `order`, read a page at a
    time: limit MAX_ROWS, offset the rows read so far. It stops only at an
    empty page, never at a short one, because a server set to answer fewer
    rows than asked would otherwise end the read early. `order` must end in a
    unique column (id), so paging never reads a row twice or skips one. More
    than `most` rows (READ_ALL_MOST) raises TooManyRows (a BoardDBError: the
    database answered) instead of reading without end."""
    most = READ_ALL_MOST if most is None else most
    rows: list[dict] = []
    while True:
        page = _rows(_call("GET", path, params=[("select", select), *_params(params), ("order", order),
                                                ("limit", str(MAX_ROWS)), ("offset", str(len(rows)))]))
        if not page:
            return rows
        rows.extend(page)
        if len(rows) > most:
            raise TooManyRows(f"{path}: more than {most:,} rows to read")


def _whole(value, where: str) -> int:
    """A whole number from PostgREST JSON (a count or a sum of cents)."""
    if isinstance(value, bool):
        raise BoardDBError(f"{where}: unexpected answer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and _WHOLE_RE.fullmatch(value.strip()):
        return int(value.strip())
    raise BoardDBError(f"{where}: unexpected answer")


def revenue_daily(first: date, last: date, *, source_id: Optional[str] = None) -> list[dict]:
    """board_revenue_daily from `first` to `last`: one row per New York day,
    source and channel, with sales, units, gross, refunds, disputes, net and
    fees in US cents (ints) and the rows that have no USD amount yet. Groups
    that hold an estimate (provisional KDP royalties) are left out: money
    never includes an estimate. local_day comes back as a date."""
    params = [("has_estimates", "is.false")]
    if source_id is not None:
        params.append(("source_id", f"eq.{source_id}"))
    rows = read_days("board_revenue_daily", "local_day,source_id,channel," + ",".join(REVENUE_FIELDS),
                     first, last, params=params, order="local_day.asc,source_id.asc,channel.asc")
    out = []
    for r in rows:
        try:
            day = date.fromisoformat(str(r.get("local_day")))
        except ValueError:
            raise BoardDBError("board_revenue_daily: unexpected answer") from None
        item = {"local_day": day, "source_id": str(r.get("source_id") or ""), "channel": r.get("channel")}
        for name in REVENUE_FIELDS:
            item[name] = _whole(r.get(name), "board_revenue_daily")
        out.append(item)
    return out


def first_ledger_day() -> Optional[date]:
    """The earliest New York day with a ledger row; None when the ledger is empty."""
    rows = _rows(_call("GET", "ledger_entries", params={"select": "local_day", "order": "local_day.asc",
                                                         "limit": "1"}))
    if not rows or not rows[0].get("local_day"):
        return None
    try:
        return date.fromisoformat(str(rows[0]["local_day"]))
    except ValueError:
        raise BoardDBError("ledger_entries: unexpected answer") from None


def count(path: str, params=None, *, select: str = "external_id") -> int:
    """How many rows of `path` match `params`, counted by the database
    (Prefer: count=exact; PostgREST answers it in Content-Range), never by
    reading the rows: one read stops at MAX_ROWS."""
    r = _call("GET", path, params=[("select", select), *_params(params), ("limit", "1")], prefer="count=exact")
    total = _total(r)
    if total is None:
        raise BoardDBError(f"{path}: no row count in the answer")
    return total


def _kinds(kinds) -> str:
    kinds = tuple(kinds)
    if not kinds or not set(kinds) <= KINDS:
        raise ValueError("kinds must be ledger kinds")
    return f"in.({','.join(kinds)})"


def money_rows(source_id: str, first: Optional[date] = None, last: Optional[date] = None, *,
               kinds=MONEY_KINDS, limit: int = 50) -> tuple[list[dict], int]:
    """(the newest `limit` money rows of `source_id` from board_ledger, the
    exact count of all of them), on New York days `first` to `last` (either
    end open when None). Estimates are left out. Each row: external_id, kind,
    occurred_at, occurred_on, local_day, amount_usd_cents, product,
    customer_email (whole: mask it before it leaves the server) and order_ref.
    A refund or dispute carries its sale's product and buyer (board_ledger)."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    limit = min(limit, MAX_ROWS)
    params = [("select","external_id,kind,occurred_at,occurred_on,local_day,amount_usd_cents,product,"
                         "customer_email,order_ref"),
              ("source_id", f"eq.{source_id}"), ("kind", _kinds(kinds)), ("is_estimate", "is.false")]
    if first is not None:
        params.append(("local_day", f"gte.{first.isoformat()}"))
    if last is not None:
        params.append(("local_day", f"lte.{last.isoformat()}"))
    params += [("order", "occurred_at.desc.nullslast,local_day.desc,external_id.desc"), ("limit", str(limit))]
    r = _call("GET", "board_ledger", params=params, prefer="count=exact")
    rows, total = _rows(r), _total(r)
    if total is None:
        raise BoardDBError("board_ledger: no row count in the answer")
    return rows, total


def find_row(source_id: str, external_id: str) -> Optional[dict]:
    """One ledger row by its key, or None: external_id, kind, amount_minor,
    currency, amount_usd_cents, occurred_at, product and raw."""
    rows = _rows(_call("GET", "ledger_entries", params={
        "select": "external_id,kind,amount_minor,currency,amount_usd_cents,occurred_at,product,raw",
        "source_id": f"eq.{source_id}", "external_id": f"eq.{external_id}", "limit": "1"}))
    return rows[0] if rows else None


def sources_rows() -> list[dict]:
    """Every row of public.sources (state, watermark, measured_from), by id."""
    return _rows(_call("GET", "sources", params={
        "select": "id,kind,method,enabled,measured_from,synced_through,day_tz,last_ok_at,last_error,last_error_at",
        "order": "id.asc"}))


def manual_row(external_id: str, amount_cents: int, occurred_at: datetime, *,
               product: Optional[str] = None, raw: Optional[dict] = None) -> LedgerRow:
    """One manual entry as a ledger row of the 'manual' source: US cents the
    owner entered, a sale when positive and an adjustment when negative (never
    0), in USD (board_ingest_ledger makes it its own USD amount: 'identity'),
    with an unknown fee (NULL: the owner did not say), dated `occurred_at`.
    Text loses any NUL, which Postgres refuses."""
    _key(external_id, "external_id", 255)
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise TypeError("a manual amount is integer US cents")
    if amount_cents == 0:
        raise ValueError("a manual amount is not 0")
    if abs(amount_cents) > _BIGINT_MAX:
        raise ValueError("a manual amount must fit in a bigint of cents")
    _label(product, "product")
    return LedgerRow(external_id=external_id, kind="sale" if amount_cents > 0 else "adjustment",
                     amount_minor=amount_cents, currency="USD", occurred_at=occurred_at,
                     product=(_no_nul(product).strip() or None) if product is not None else None,
                     raw=_no_nul(dict(raw or {})))


# ─── clicks: /go redirects (public.clicks; no visitor IP address is stored) ──

CLICK_TIMEOUT = 3.0       # seconds for a live click's insert: a hung database holds a worker briefly
_CLICKS_CHUNK = 500
LIVE_CLICK_COLUMNS = ("id", "partner", "clicked_at", "referrer_host", "destination", "utm")
IMPORT_CLICK_COLUMNS = ("partner", "clicked_at", "referrer_host", "destination", "utm", "import_key")
CLICK_FIELDS = "id,partner,clicked_at,referrer_host,destination,utm"
_CHANNEL_RE = re.compile(r"[a-z0-9_]{1,32}")    # ledger_entries.channel's check


def insert_click(row: dict) -> None:
    """Store one live /go click: exactly LIVE_CLICK_COLUMNS of `row` (id, the
    click id a Payment Link carries as client_reference_id; partner; clicked_at,
    a timestamptz string; referrer_host, the referring host only; destination;
    utm, an object), with Prefer: return=minimal and a short timeout
    (CLICK_TIMEOUT), because a click is best effort. Anything else in `row` is
    never sent: local_day is generated by the database, and the table has no
    column for an IP address. Raises BoardDBError."""
    _call("POST", "clicks", json={c: _no_nul(row.get(c)) for c in LIVE_CLICK_COLUMNS},
          prefer="return=minimal", timeout=CLICK_TIMEOUT)


def import_clicks(rows: list[dict]) -> int:
    """Insert old clicks (scripts/board_import_json.py) into public.clicks, in
    chunks of 500; returns how many were new. Each row sends exactly
    IMPORT_CLICK_COLUMNS (the id is the database's default), the same keys in
    every object, as PostgREST requires of a bulk insert. A row whose
    import_key is there already is left as it is (ON CONFLICT (import_key) DO
    NOTHING), so an import can run again. No visitor IP address is ever
    stored: the table has no column for one."""
    new = 0
    for start in range(0, len(rows), _CLICKS_CHUNK):
        chunk = [{c: _no_nul(r.get(c)) for c in IMPORT_CLICK_COLUMNS} for r in rows[start:start + _CLICKS_CHUNK]]
        r = _call("POST", "clicks", params={"on_conflict": "import_key", "select": "id"}, json=chunk,
                  prefer="resolution=ignore-duplicates,return=representation")
        new += len(_rows(r))
    return new


def click_uuid(value) -> Optional[str]:
    """A click id as canonical lower-case uuid text; None when `value` is not a uuid."""
    if isinstance(value, UUID):
        return str(value)
    try:
        return str(UUID(str(value).strip())) if value else None
    except ValueError:
        return None


def clicks_by_id(ids) -> dict[str, dict]:
    """The stored clicks among `ids` (uuids, or uuid text in any case; anything
    else is left out), as {id: {id, partner, utm}} with the id as canonical
    lower-case text. In chunks of _IDS_CHUNK, each read whole (read_all), so
    a server that answers fewer rows than a chunk holds still finds every
    click. Raises BoardDBError."""
    wanted = sorted({u for u in (click_uuid(i) for i in ids) if u})
    found: dict[str, dict] = {}
    for start in range(0, len(wanted), _IDS_CHUNK):
        chunk = wanted[start:start + _IDS_CHUNK]
        for r in read_all("clicks", "id,partner,utm", params={"id": f"in.({','.join(chunk)})"}, order="id.asc"):
            cid = click_uuid(r.get("id"))
            if cid:
                found[cid] = {"id": cid, "partner": r.get("partner"),
                              "utm": r.get("utm") if isinstance(r.get("utm"), dict) else {}}
    return found


def click_channel(click: Optional[dict]) -> Optional[str]:
    """The channel a stored click gives the sale it led to: the visitor's own
    utm_source on the /go link, else the /go key itself ('insider'). Trimmed,
    lower-cased and '-' read as '_', it must be 1 to 32 of a-z, 0-9 and _
    (the ledger's channel check), and never 'unattributed', the board's word
    for no channel. None when neither is usable."""
    if not isinstance(click, dict):
        return None
    utm = click.get("utm") if isinstance(click.get("utm"), dict) else {}
    for value in (utm.get("utm_source"), click.get("partner")):
        if isinstance(value, str):
            channel = value.strip().lower().replace("-", "_")
            if _CHANNEL_RE.fullmatch(channel) and channel != "unattributed":
                return channel
    return None


def read_clicks(select: str = CLICK_FIELDS) -> list[dict]:
    """Every stored click, the oldest first (clicked_at, then id), read whole
    however many there are (read_all)."""
    return read_all("clicks", select, order="clicked_at.asc,id.asc")


def newest_clicks(limit: int, select: str = CLICK_FIELDS) -> list[dict]:
    """The `limit` newest stored clicks (at most MAX_ROWS), the newest first:
    fewer only when there are fewer, never because a server answers fewer
    rows to one read (it reads on from where the last page ended)."""
    limit = max(1, min(int(limit), MAX_ROWS))
    rows: list[dict] = []
    while len(rows) < limit:
        page = _rows(_call("GET", "clicks", params=[("select", select), ("order", "clicked_at.desc,id.desc"),
                                                    ("limit", str(limit - len(rows))), ("offset", str(len(rows)))]))
        if not page:
            break
        rows.extend(page)
    return rows[:limit]


def count_clicks(first: Optional[date] = None, last: Optional[date] = None) -> int:
    """How many clicks were made on New York days `first` to `last` (local_day;
    either end open when None), counted by the database."""
    params = []
    if first is not None:
        params.append(("local_day", f"gte.{first.isoformat()}"))
    if last is not None:
        params.append(("local_day", f"lte.{last.isoformat()}"))
    return count("clicks", params, select="id")


def click_sales() -> list[dict]:
    """Every sale in the ledger with a stored click id (board_ingest_ledger
    keeps a click id only when it names a stored click): source_id,
    external_id, click_id and amount_usd_cents, read whole. Estimates are
    left out."""
    return read_all("ledger_entries", "source_id,external_id,click_id,amount_usd_cents",
                    params=[("kind", "eq.sale"), ("click_id", "not.is.null"), ("is_estimate", "is.false")],
                    order="id.asc")
