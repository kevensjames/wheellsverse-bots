"""The old money numbers, read from the board's ledger by New York day.

GET /api/money/summary, /api/money/stripe and /api/money/record, the
/api/revenue/* routes (core/revenue.py RevenueEngine) and the scoreboard's
revenue cards (core/scoreboard.py) keep their JSON, but their numbers now
come from here, not from the old JSON files (the payment log and the revenue
store under data/, which every deploy wiped).

Totals come from SQL. board_revenue_daily gives one row per New York day,
source and channel, read completely (core.board.ledger.read_days). Python
only adds those whole day rows; it never adds up ledger rows. Counts come
from the database (PostgREST's exact count). Top earners come from board_day.

The rules:

  * Days are New York calendar days. Today (T) is the New York date of
    _clock(), which tests freeze. Week: T-6 to T (7 days). Month: T-29 to T
    (30 days). All time: since Stripe's measured_from.
  * Money is integer US cents in here. Dollars (cents / 100) appear only at
    the edge, for the old JSON. Net is sales minus refunds and disputes,
    before fees.
  * A number that is not measured is None, never 0. The database unreadable:
    every number is None. A figure that includes Stripe is None unless Stripe
    is connected on this server (its key set and not a test key, its source
    enabled, a sync completed), measured from the figure's first day, and
    synced into its last day (today): a sync that stopped would otherwise
    show today as $0. A figure with a row that has no US dollar amount yet is
    None, never a smaller number. Manual-only figures are numbers whenever
    the database answers. Stripe is the one API money source in Phase 1: a
    store added later needs its own check here.
  * Money never includes an estimate: provisional KDP royalties (is_estimate)
    are left out of every figure here. The board shows them, labelled.
  * Buyers leave masked: the first character, ***, then the domain.

Manual entries (record_manual) are ledger rows of the 'manual' source. A
positive amount is a sale and a negative one an adjustment, in USD, with an
unknown fee, dated when they are entered. The key is 'manual:<uuid>', or
'manual:idem:<sha256 of the Idempotency-Key>' when the caller sends one: the
same key again is answered from the stored row and never written twice.
"""
from __future__ import annotations

import hashlib
import logging
import math
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional
from zoneinfo import ZoneInfo

from core.board import day as board_day
from core.board import ledger
from core.board.connectors import stripe_sync
from core.board.ledger import BoardDBError

log = logging.getLogger("board.money")

NY = ZoneInfo("America/New_York")
TZ_NAME = "America/New_York"
MANUAL = ledger.MANUAL_SOURCE
WEEK_DAYS, MONTH_DAYS = 7, 30
MAX_DAYS = 3660                      # /api/money/stripe?days= reads at most this far back
MAX_DOLLARS = Decimal("1000000")     # one manual entry
SOURCE_LONGEST, NOTE_LONGEST = 64, 500
RECENT_STRIPE, STRIPE_PAYMENTS, RECENT_CHARGES = 5, 50, 10
NOTE = "New York days. Net of refunds and disputes, before fees. Estimates are left out."
CARD_NOTE = "New York days; net of refunds and disputes; Stripe and manual entries"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _now() -> datetime:
    return datetime.now(timezone.utc)


_clock = _now                        # tests freeze it


def today() -> date:
    """Today in New York (T)."""
    return _clock().astimezone(NY).date()


def day_text(d: date) -> str:
    """'1 Jan 2026'."""
    return f"{d.day} {_MONTHS[d.month - 1]} {d.year}"


def dollars(cents: Optional[int]) -> Optional[float]:
    """US cents as dollars for the old JSON (2999 -> 29.99); None stays None."""
    return None if cents is None else cents / 100


def mask(email) -> str:
    """'b***@example.com', as board_day masks a buyer; '' when there is none."""
    if not isinstance(email, str) or not email:
        return ""
    at = email.find("@")
    return email[0] + "***" + email[at:] if at > 0 else "***"


def stripe_configured() -> bool:
    """A Stripe key is set on this server and it is not a test-mode key."""
    key = stripe_sync.read_key()
    return key is not None and not stripe_sync.is_test_key(key[0])


# ─── is Stripe measured? ────────────────────────────────────────────────────

@dataclass(frozen=True)
class Coverage:
    database: bool                  # the board's tables answered
    stripe: bool                    # Stripe is connected on this server
    stripe_from: Optional[date]     # Stripe's measured_from: the first day it covers
    note: str                       # why not, in plain words; '' when both hold
    synced_through: Optional[datetime] = None   # Stripe's watermark: everything before it is in the ledger


_OFF = Coverage(False, False, None, "database not connected")


def coverage() -> Coverage:
    """Whether the database answers, and whether Stripe is connected here: its
    sources row enabled with a completed sync (measured_from), and its key
    configured (core.board.day.read_problem). Never raises."""
    try:
        row = ledger.source_row("stripe")
    except BoardDBError as e:
        log.warning("money: cannot read the stripe source (%s)", e)
        return _OFF
    if row is None:
        return Coverage(True, False, None, "no stripe row in public.sources")
    try:
        since = date.fromisoformat(str(row["measured_from"])) if row.get("measured_from") else None
    except ValueError:
        since = None
    synced = ledger.parse_ts(row.get("synced_through"))
    problem = board_day.read_problem("stripe")
    if problem:
        return Coverage(True, False, since, problem, synced)
    if not row.get("enabled"):
        return Coverage(True, False, since, "the stripe source is disabled", synced)
    if since is None:
        return Coverage(True, False, None, "no Stripe sync has completed yet", synced)
    return Coverage(True, True, since, "", synced)


def _synced_into(cov: Coverage, day: date) -> bool:
    """Whether Stripe's watermark is past the start of New York `day`, so the
    sync has read at least part of it (core.board.day's rule for a day)."""
    return cov.synced_through is not None and cov.synced_through > datetime.combine(day, time(0), tzinfo=NY)


def measured(cov: Coverage, first: Optional[date], last: date) -> bool:
    """Whether a figure that includes Stripe, over New York days `first` to
    `last`, is measured: Stripe connected here, measured from `first` or
    earlier, and synced into `last`."""
    return bool(cov.stripe and cov.stripe_from is not None and first is not None
                and cov.stripe_from <= first and _synced_into(cov, last))


def _clock_text(at: datetime) -> str:
    """'23:02 on Mon 2 Nov', New York time."""
    local = at.astimezone(NY)
    return f"{local:%H:%M} on {board_day.day_label(local.date())}"


def _behind(cov: Coverage) -> str:
    """Why a figure up to today is not measured while Stripe's sync lags."""
    if cov.synced_through is None:
        return "no Stripe sync has completed yet"
    return f"the Stripe sync has read only up to {_clock_text(cov.synced_through)} (New York)"


# ─── revenue by day, from board_revenue_daily ───────────────────────────────

@dataclass
class Totals:
    """One window's sums of whole board_revenue_daily rows, in US cents."""
    net: int = 0
    gross: int = 0
    refunds: int = 0
    disputes: int = 0
    sales: int = 0
    units: int = 0
    unconverted: int = 0
    by_source: dict = field(default_factory=dict)             # source_id -> net
    unconverted_by_source: dict = field(default_factory=dict)


class Revenue:
    """board_revenue_daily from `first` to `last`, read once, estimates left
    out. `everything`: no ledger row is earlier than `first`, so a window may
    start before it."""

    def __init__(self, groups: list[dict], first: date, last: date, everything: bool = False):
        self.groups, self.first, self.last, self.everything = groups, first, last, everything

    @classmethod
    def load(cls, first: date, last: date, *, source_id: Optional[str] = None,
             everything: bool = False) -> "Revenue":
        return cls(ledger.revenue_daily(first, last, source_id=source_id), first, last, everything)

    def window(self, first: date, last: date, sources=None) -> Totals:
        """The sums over New York days `first` to `last`, of `sources` (ids) or of every source."""
        if last > self.last or (first < self.first and not self.everything):
            raise ValueError("that window was not read")
        t = Totals()
        for g in self.groups:
            if not first <= g["local_day"] <= last or (sources is not None and g["source_id"] not in sources):
                continue
            t.net += g["net_usd_cents"]
            t.gross += g["gross_usd_cents"]
            t.refunds += g["refunds_usd_cents"]
            t.disputes += g["disputes_usd_cents"]
            t.sales += g["sales"]
            t.units += g["units"]
            t.unconverted += g["unconverted_rows"]
            sid = g["source_id"]
            t.by_source[sid] = t.by_source.get(sid, 0) + g["net_usd_cents"]
            t.unconverted_by_source[sid] = t.unconverted_by_source.get(sid, 0) + g["unconverted_rows"]
        return t

    def days_with_money(self, first: date, last: date) -> list[date]:
        """The days from `first` to `last` with a sale or any money."""
        return sorted({g["local_day"] for g in self.groups
                       if first <= g["local_day"] <= last and (g["sales"] or g["net_usd_cents"])})


@dataclass(frozen=True)
class _Snapshot:
    day: date                       # T
    cov: Coverage
    rev: Optional[Revenue]          # None: the database did not answer


def _snapshot(*, everything: bool = True) -> _Snapshot:
    """T, Stripe's coverage, and board_revenue_daily from the first ledger day
    (or just the last 30 days, without `everything`) to T."""
    t = today()
    cov = coverage()
    if not cov.database:
        return _Snapshot(t, cov, None)
    first = t - timedelta(days=MONTH_DAYS - 1)
    try:
        if everything:
            start = ledger.first_ledger_day()
            if start is not None and start < first:
                first = start
        rev = Revenue.load(first, t, everything=everything)
    except BoardDBError as e:
        log.warning("money: cannot read board_revenue_daily (%s)", e)
        return _Snapshot(t, _OFF, None)
    return _Snapshot(t, cov, rev)


def _net(snap: _Snapshot, first: Optional[date], last: date, sources=None, *, stripe: bool = True) -> Optional[int]:
    """Net cents over `first` to `last` (of `sources`, or every source); None
    when it is not measured. `stripe`: the figure includes Stripe."""
    if snap.rev is None or first is None or (stripe and not measured(snap.cov, first, last)):
        return None
    t = snap.rev.window(first, last, sources)
    return None if t.unconverted else t.net


def _why(snap: _Snapshot, first: Optional[date], *, stripe: bool = True) -> str:
    """Why _net gave None for a window ending today, in plain words."""
    if snap.rev is None:
        return snap.cov.note or "database not connected"
    if stripe and not snap.cov.stripe:
        return snap.cov.note
    if stripe and (first is None or snap.cov.stripe_from is None):
        return "no Stripe sync has completed yet"
    if stripe and first < snap.cov.stripe_from:
        return f"Stripe is measured only from {day_text(snap.cov.stripe_from)}"
    if stripe and not _synced_into(snap.cov, snap.day):
        return _behind(snap.cov)
    return "a row has no US dollar amount yet"


def _status(t: date, cov: Coverage, first: Optional[date] = None) -> dict:
    """The additive 'ledger' block: where the numbers come from and, when one
    is null, why."""
    if not cov.database:
        note = cov.note or "database not connected"
    elif not cov.stripe:
        note = f"Stripe is not measured here ({cov.note}). {NOTE}"
    elif first is not None and cov.stripe_from is not None and first < cov.stripe_from:
        note = f"Stripe is measured only from {day_text(cov.stripe_from)}. {NOTE}"
    elif not _synced_into(cov, t):
        note = f"Stripe is not measured today: {_behind(cov)}. {NOTE}"
    else:
        note = NOTE
    return {"connected": cov.database, "today": t.isoformat(), "tz": TZ_NAME,
            "measured_from": cov.stripe_from.isoformat() if cov.stripe_from else None,
            "stripe_synced_through": (cov.synced_through.astimezone(timezone.utc).isoformat()
                                      if cov.synced_through else None),
            "note": note}


# ─── rows in the old record shape ───────────────────────────────────────────

def legacy_record(row: dict, *, manual: bool = False) -> dict:
    """A ledger row in the shape of an old payment-log record: ts (New York,
    with its offset), type (the ledger kind, or manual_<source> for a manual
    entry), amount (signed dollars), currency, email (masked), product and
    event_id (the row's key)."""
    at = ledger.parse_ts(row.get("occurred_at"))
    ts = at.astimezone(NY).isoformat() if at else str(row.get("occurred_on") or row.get("local_day") or "")
    kind = str(row.get("kind") or "")
    if manual:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        src = raw.get("source")
        kind = f"manual_{src}" if isinstance(src, str) and src else "manual"
    cents = row.get("amount_usd_cents")
    return {"ts": ts, "type": kind,
            "amount": dollars(cents) if isinstance(cents, int) and not isinstance(cents, bool) else None,
            "currency": "usd", "email": mask(row.get("customer_email")), "product": row.get("product") or "",
            "event_id": str(row.get("external_id") or "")}


def _recent_stripe(snap: _Snapshot, limit: int) -> list[dict]:
    if snap.rev is None:
        return []
    try:
        rows, _ = ledger.money_rows("stripe", None, snap.day, limit=limit)
    except BoardDBError as e:
        log.warning("money: cannot read the newest Stripe rows (%s)", e)
        return []
    return [legacy_record(r) for r in rows]


def top_products(rev: Revenue, first: date, last: date, limit: int) -> list[tuple[str, int]]:
    """[(product, net cents)], the best first: board_day's products (SQL) for
    each day from `first` to `last` that has money, merged by product name.
    Estimates are left out, and so is a product whose net over the window is
    not above 0 (a refund of an older sale earns nothing). [] when a day
    cannot be read."""
    merged: dict[str, int] = {}
    try:
        for d in rev.days_with_money(first, last):
            for p in ledger.board_day(d).get("products") or []:
                if not isinstance(p, dict) or p.get("estimate"):
                    continue
                cents = p.get("net_usd_cents")
                if isinstance(cents, bool) or not isinstance(cents, int):
                    continue
                name = str(p.get("product") or "(no product name)")
                merged[name] = merged.get(name, 0) + cents
    except BoardDBError as e:
        log.warning("money: cannot read the products (%s)", e)
        return []
    earners = [(name, cents) for name, cents in merged.items() if cents > 0]
    return sorted(earners, key=lambda kv: (-kv[1], kv[0]))[:limit]


# ─── manual entries ─────────────────────────────────────────────────────────

class NotRecorded(Exception):
    """A manual entry that was not written: `status` (422 refused, 409 the
    Idempotency-Key was used for another amount, 503 the database is not
    connected) and a plain-English `message` for the caller."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


_AMOUNT_HELP = "The amount must be a number of dollars, such as 25.00."
DB_DOWN = "Not recorded: the database is not connected."
STRIPE_REFUSED = "Stripe money comes from the Stripe sync."
# The routes' answer (503) to a manual entry while API_KEY is not set on the
# server and no owner session sent it (core/api.py _manual_entry_denial).
# Nothing was written: the dashboard and NarAI show it and do not ask again.
NO_API_KEY = "Not recorded: API_KEY is not set on the server."


def _cents(amount) -> int:
    """An amount in dollars as whole US cents. A float is read as written
    (repr), never rounded: more than 2 decimal places is refused."""
    if isinstance(amount, bool):
        raise NotRecorded(422, _AMOUNT_HELP)
    try:
        if isinstance(amount, float):
            value = Decimal(repr(amount))
        elif isinstance(amount, (int, Decimal)):
            value = Decimal(amount)
        elif isinstance(amount, str):
            value = Decimal(amount.strip())
        else:
            raise NotRecorded(422, _AMOUNT_HELP)
    except InvalidOperation:
        raise NotRecorded(422, _AMOUNT_HELP) from None
    if not value.is_finite():
        raise NotRecorded(422, _AMOUNT_HELP)
    if value == 0:
        raise NotRecorded(422, "The amount cannot be 0.")
    if abs(value) > MAX_DOLLARS:
        raise NotRecorded(422, "The amount is too large. One entry can record at most $1,000,000.00.")
    try:
        return ledger.to_minor_units(value, "USD")
    except ValueError:
        raise NotRecorded(422, "The amount can have at most 2 decimal places (whole cents).") from None


def one_line(text: str) -> str:
    """`text` on one line, as the plain-text report and every list show it:
    line breaks, tabs and other control characters become spaces, format
    characters (such as a right-to-left override) are dropped, and each run of
    spaces is one space."""
    return " ".join("".join(" " if unicodedata.category(ch) == "Cc" else ch
                            for ch in text if unicodedata.category(ch) != "Cf").split())


def _text(value, what: str, longest: int) -> str:
    if value is None:
        return ""
    text = one_line(value if isinstance(value, str) else str(value))
    if len(text) > longest:
        raise NotRecorded(422, f"The {what} is too long. Keep it to {longest} characters or fewer.")
    return text


def _scalars(metadata) -> dict:
    """The plain values of `metadata` (text, numbers, true or false), never
    one under a key that names an email."""
    out: dict = {}
    if not isinstance(metadata, dict):
        return out
    for k, v in list(metadata.items())[:20]:
        if not isinstance(k, str) or "email" in k.lower():
            continue
        if isinstance(v, float) and not math.isfinite(v):
            continue
        if v is None or isinstance(v, (bool, int, float)):
            out[k[:64]] = v
        elif isinstance(v, str):
            out[k[:64]] = v.replace("\x00", "")[:NOTE_LONGEST]
    return out


def idempotency_id(key: str) -> str:
    """The ledger key for an Idempotency-Key: 'manual:idem:' and the first 48
    hex digits of its SHA-256 (the key itself is never stored)."""
    if not isinstance(key, str) or not 1 <= len(key) <= 255 or not (key.isascii() and key.isprintable()):
        raise NotRecorded(422, "The Idempotency-Key header must be 1 to 255 printable ASCII characters.")
    return "manual:idem:" + hashlib.sha256(key.encode("ascii")).hexdigest()[:48]


def _answer(found: dict, cents: int, external_id: str) -> dict:
    """The answer for a key that is in the ledger already: the same amount is
    the same entry, sent again; another amount is a conflict."""
    if found.get("amount_minor") != cents or str(found.get("currency") or "").strip() != "USD":
        raise NotRecorded(409, "This Idempotency-Key was used before for another amount. "
                               "Nothing new was recorded.")
    return {"id": external_id, "amount": dollars(cents), "cents": cents, "replayed": True}


def record_manual(source, amount, *, note=None, label=None, entered_via: str,
                  idempotency_key: Optional[str] = None, metadata=None) -> dict:
    """Write one manual entry: a ledger row of the 'manual' source, dated now.
    Its product reads '<source>: <label or note>' (or '<source>'), the source
    and the note or label each kept on one line (one_line); raw keeps
    where it was entered, the source, the note or label, and the plain values
    of `metadata` (never one under an email key). Returns {id, amount (dollars),
    cents, replayed}. Raises NotRecorded: 422 for an amount of 0, not a
    number, with more than 2 decimal places or above $1,000,000, a source
    that is empty, longer than 64 characters or 'stripe', a note or label
    longer than 500; 409 for an Idempotency-Key used before with another
    amount; 503 when the database is not connected (nothing is written)."""
    src = _text(source, "source", SOURCE_LONGEST)
    if not src:
        raise NotRecorded(422, "Say where the money came from, such as kdp_royalty.")
    if src.lower() == "stripe":
        raise NotRecorded(422, STRIPE_REFUSED)
    words = _text(label if label is not None else note, "label" if label is not None else "note", NOTE_LONGEST)
    cents = _cents(amount)
    external_id = idempotency_id(idempotency_key) if idempotency_key is not None else f"manual:{uuid.uuid4()}"
    raw: dict = {"entered_via": entered_via, "source": src}
    if label is not None:
        raw["label"] = words
    else:
        raw["note"] = words
    extra = _scalars(metadata)
    if extra:
        raw["metadata"] = extra
    row = ledger.manual_row(external_id, cents, _clock(), product=f"{src}: {words}" if words else src, raw=raw)
    try:
        if idempotency_key is not None:
            found = ledger.find_row(MANUAL, external_id)
            if found is not None:
                return _answer(found, cents, external_id)
        written = ledger.ingest_ledger(MANUAL, None, [row])
        if written.get("inserted") != 1:          # the same key arrived twice at once
            found = ledger.find_row(MANUAL, external_id)
            if found is None:
                raise BoardDBError("ledger_entries: the entry is not there after writing it")
            return _answer(found, cents, external_id)
    except BoardDBError as e:
        log.warning("money: a manual entry was not recorded (%s)", e)
        raise NotRecorded(503, DB_DOWN) from None
    return {"id": external_id, "amount": dollars(cents), "cents": cents, "replayed": False}


def manual_records(days: int = MONTH_DAYS) -> dict:
    """GET /api/money/record: the manual entries of the last `days` New York
    days (T-29 to T for 30), newest first, in the old record shape."""
    t = today()
    first = t - timedelta(days=max(1, days) - 1)
    try:
        rows = ledger.read_days("ledger_entries", "external_id,kind,occurred_at,occurred_on,local_day,"
                                "amount_usd_cents,product,raw", first, t,
                                params=[("source_id", f"eq.{MANUAL}")], order="occurred_at.desc.nullslast")
    except BoardDBError as e:
        log.warning("money: cannot read the manual entries (%s)", e)
        return {"records": [], "error": "database not connected"}
    far = datetime.min.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda r: (ledger.parse_ts(r.get("occurred_at")) or far, str(r.get("external_id"))), reverse=True)
    return {"records": [legacy_record(r, manual=True) for r in rows]}


# ─── the numbers of each old route ──────────────────────────────────────────

def _by_source(snap: _Snapshot, first: date, last: date) -> dict:
    """{source_id: net cents} over `first` to `last`: stripe (None unless
    measured) and manual always, then any other source that has money."""
    if snap.rev is None:
        return {"stripe": None, "manual": None}
    t = snap.rev.window(first, last)
    out = {"stripe": _net(snap, first, last, {"stripe"}),
           "manual": None if t.unconverted_by_source.get(MANUAL) else t.by_source.get(MANUAL, 0)}
    for sid in sorted(t.by_source):
        if sid not in out:
            out[sid] = None if t.unconverted_by_source.get(sid) else t.by_source[sid]
    return out


def _money_rows_count(snap: _Snapshot) -> Optional[int]:
    if snap.rev is None:
        return None
    try:
        return ledger.count("ledger_entries", [("kind", f"in.({','.join(ledger.MONEY_KINDS)})"),
                                               ("is_estimate", "is.false")])
    except BoardDBError as e:
        log.warning("money: cannot count the ledger rows (%s)", e)
        return None


def summary_cents(top: int = 3) -> dict:
    """The numbers behind summary() and the daily report, in US cents, each
    None when not measured, with `why` for each one that is None."""
    snap = _snapshot()
    t, since = snap.day, snap.cov.stripe_from
    windows = {"today": t, "week": t - timedelta(days=WEEK_DAYS - 1),
               "month": t - timedelta(days=MONTH_DAYS - 1), "all_time": since}
    out: dict = {"day": t, "measured_from": since, "database": snap.rev is not None, "why": {}}
    for name, first in windows.items():
        out[name] = _net(snap, first, t)
        if out[name] is None:
            out["why"][name] = _why(snap, first)
    month0 = windows["month"]
    out["by_source_30d"] = _by_source(snap, month0, t)
    # Only over a measured 30 days: a partial window would rank partial sums as "30 days".
    out["top_earners_30d"] = top_products(snap.rev, month0, t, top) if out["month"] is not None else []
    out["total_records"] = _money_rows_count(snap)
    out["note"] = _status(t, snap.cov, month0)["note"]
    return out


def summary(top: int = 3) -> dict:
    """RevenueEngine.summary(): {today, week, month, all_time} in dollars, all
    sources, each None unless measured; by_source_30d {source: dollars};
    top_earners_30d [{label, amount}]; total_records (money rows in the
    ledger, estimates left out); stripe_configured. Additive: day, tz,
    measured_from, note."""
    s = summary_cents(top)
    return {"today": dollars(s["today"]), "week": dollars(s["week"]), "month": dollars(s["month"]),
            "all_time": dollars(s["all_time"]),
            "by_source_30d": {k: dollars(v) for k, v in s["by_source_30d"].items()},
            "top_earners_30d": [{"label": name, "amount": dollars(cents)} for name, cents in s["top_earners_30d"]],
            "total_records": s["total_records"], "stripe_configured": stripe_configured(),
            "day": s["day"].isoformat(), "tz": TZ_NAME,
            "measured_from": s["measured_from"].isoformat() if s["measured_from"] else None, "note": s["note"]}


def month_total() -> Optional[float]:
    """Net dollars of the last 30 New York days, all sources; None unless measured."""
    snap = _snapshot(everything=False)
    return dollars(_net(snap, snap.day - timedelta(days=MONTH_DAYS - 1), snap.day))


def money_summary_numbers() -> dict:
    """GET /api/money/summary's money: stripe {today, week, total, recent},
    manual {today, week, total}, ledger {connected, today, tz, measured_from,
    stripe_synced_through, note} and total_revenue_today (every source,
    Stripe measured), in dollars."""
    snap = _snapshot()
    t, since = snap.day, snap.cov.stripe_from
    week0 = t - timedelta(days=WEEK_DAYS - 1)
    first_read = snap.rev.first if snap.rev is not None else None
    stripe = {"today": dollars(_net(snap, t, t, {"stripe"})), "week": dollars(_net(snap, week0, t, {"stripe"})),
              "total": dollars(_net(snap, since, t, {"stripe"})), "recent": _recent_stripe(snap, RECENT_STRIPE)}
    manual = {"today": dollars(_net(snap, t, t, {MANUAL}, stripe=False)),
              "week": dollars(_net(snap, week0, t, {MANUAL}, stripe=False)),
              "total": dollars(_net(snap, first_read, t, {MANUAL}, stripe=False))}
    return {"stripe": stripe, "manual": manual, "ledger": _status(t, snap.cov, week0),
            "total_revenue_today": dollars(_net(snap, t, t))}


def stripe_payload(days: int = 30) -> dict:
    """GET /api/money/stripe: New York days T-days to T (the old cutoff).
    total and by_type (sale, refund, dispute with its reversals netted,
    adjustment; signed dollars) from board_revenue_daily; count, the exact
    number of Stripe money rows in the window; payments, the 50 newest, in
    the old record shape. total, count and by_type are null or empty unless
    Stripe is measured over the whole window."""
    days = max(0, min(int(days), MAX_DAYS))
    t = today()
    first = t - timedelta(days=days)
    cov = coverage()
    out = {"total": None, "count": None, "by_type": {}, "payments": [], "ledger": _status(t, cov, first)}
    if not cov.database:
        return out
    try:
        rev = Revenue.load(first, t, source_id="stripe")
        rows, n = ledger.money_rows("stripe", first, t, limit=STRIPE_PAYMENTS)
    except BoardDBError as e:
        log.warning("money: cannot read the Stripe rows (%s)", e)
        out["ledger"] = _status(t, _OFF, first)
        return out
    out["payments"] = [legacy_record(r) for r in rows]
    if measured(cov, first, t):
        out["count"] = n
        w = rev.window(first, t)
        if not w.unconverted:
            out["total"] = dollars(w.net)
            by_type = {"sale": w.gross, "refund": -w.refunds, "dispute": -w.disputes,
                       "adjustment": w.net - w.gross + w.refunds + w.disputes}
            out["by_type"] = {k: dollars(v) for k, v in by_type.items() if v}
    return out


def stripe_window(days: int = 30) -> dict:
    """RevenueEngine.pull_stripe's ledger part, over New York days
    T-(days-1) to T: total_revenue (net dollars), charge_count (sales) and
    recent_charges (the 10 newest sales: id, amount, description,
    customer_email masked, ts). The totals are None unless Stripe is measured
    over the whole window."""
    days = max(1, min(int(days), MAX_DAYS))
    t = today()
    first = t - timedelta(days=days - 1)
    cov = coverage()
    out = {"total_revenue": None, "charge_count": None, "recent_charges": []}
    if not cov.database:
        return out
    try:
        rev = Revenue.load(first, t, source_id="stripe")
        rows, _ = ledger.money_rows("stripe", first, t, kinds=("sale",), limit=RECENT_CHARGES)
    except BoardDBError as e:
        log.warning("money: cannot read the Stripe rows (%s)", e)
        return out
    for r in rows:
        old = legacy_record(r)
        out["recent_charges"].append({"id": r.get("order_ref") or r.get("external_id"), "amount": old["amount"],
                                      "description": old["product"], "customer_email": old["email"],
                                      "ts": old["ts"]})
    if measured(cov, first, t):
        w = rev.window(first, t)
        out["charge_count"] = w.sales
        out["total_revenue"] = None if w.unconverted else dollars(w.net)
    return out


def revenue_cards() -> dict:
    """The scoreboard's revenue cards: month (T-29 to T) and all time (since
    Stripe's measured_from), net dollars of every source, each None unless
    measured, with a note."""
    snap = _snapshot()
    t, since = snap.day, snap.cov.stripe_from
    month0 = t - timedelta(days=MONTH_DAYS - 1)
    month, all_time = _net(snap, month0, t), _net(snap, since, t)
    return {"month": dollars(month), "all_time": dollars(all_time),
            "month_note": CARD_NOTE if month is not None else f"not measured: {_why(snap, month0)}",
            "all_time_note": (f"since {day_text(since)}; {CARD_NOTE}" if all_time is not None
                              else f"not measured: {_why(snap, since)}")}


def clicks_7d() -> Optional[int]:
    """/go clicks over the last 7 New York days (T-6 to T), counted in SQL by
    core.click_tracker; None when the clicks table cannot be read."""
    from core.click_tracker import clicks_between
    t = today()
    return clicks_between(t - timedelta(days=WEEK_DAYS - 1), t)


# ─── the daily report's text ────────────────────────────────────────────────

def _line_amount(s: dict, name: str) -> str:
    cents = s[name]
    return board_day.money(cents) if cents is not None else f"not measured ({s['why'].get(name) or 'unknown'})"


def goal_progress(current: Optional[float], target) -> dict:
    """{target, current, progress_pct} for the monthly revenue goal, in
    dollars; progress_pct is None when the month is not measured."""
    pct = None if current is None else round(min(100.0, current / max(float(target), 1.0) * 100), 1)
    return {"target": target, "current": current, "progress_pct": pct}


def report_text(s: dict, goal_target=None) -> str:
    """The revenue report in plain text (no markup, so nothing needs
    escaping), from summary_cents(); with the monthly goal's target in
    dollars, a goal line too."""
    since = s["measured_from"]
    lines = [f"NarAI revenue report: {board_day.day_label(s['day'])} (New York)",
             f"Today so far: {_line_amount(s, 'today')}",
             f"Last 7 days: {_line_amount(s, 'week')}",
             f"Last 30 days: {_line_amount(s, 'month')}",
             (f"All time since {day_text(since)}: {_line_amount(s, 'all_time')}" if since
              else f"All time: {_line_amount(s, 'all_time')}")]
    names = {"stripe": "Stripe", MANUAL: "Manual entries"}
    parts = [f"{names.get(k, k)} {board_day.money(v) if v is not None else 'not measured'}"
             for k, v in s["by_source_30d"].items()]
    if parts:
        lines.append("By source (30 days): " + " · ".join(parts))
    if s["top_earners_30d"]:            # a product name from anywhere (Stripe, an entry) stays on its line
        lines.append("Top earners (30 days): " + " · ".join(f"{one_line(str(name))} {board_day.money(cents)}"
                                                           for name, cents in s["top_earners_30d"]))
    if goal_target is not None:
        target = board_day.money(int(round(float(goal_target) * 100)))
        goal = goal_progress(dollars(s["month"]), goal_target)
        if goal["progress_pct"] is None:
            lines.append(f"Monthly goal: not measured yet (target {target})")
        else:
            lines.append(f"Monthly goal: {board_day.money(s['month'])} of {target} ({goal['progress_pct']}%)")
    lines.append(s["note"])
    return "\n".join(lines)
