"""Stripe to the board's ledger: one row per balance transaction.

Stripe money comes only from balance transactions (GET /v1/balance_transactions):
one per money movement, with the amount and the fee that settled in the account
(USD), and the buyer's own amount and currency on the expanded source. A row's
key is the balance transaction id (txn_...), so a re-run, a backfill and the
hourly sync all land on the same row; order_ref is the charge, so a refund or a
dispute finds its sale. The webhook never writes money: it only starts this sync.

  charge, payment                     sale
  refund, payment_refund              refund (negative)
  adjustment for a dispute            dispute (negative) or dispute_reversal (positive)
  stripe_fee, stripe_fx_fee, tax_fee  fee (negative)
  refund_failure                      adjustment
  payouts, transfers, top-ups, reserves, Climate    skipped: not revenue; a fee they
                                      carry (an Instant Payout's) is kept as a fee row
                                      with no amount
  any other type                      skipped, named in the run's detail and in the
                                      source's last_error (the board's note), so a new
                                      type shows up instead of quietly changing revenue

Fees keep Stripe's sign: a refunded fee, or the fee returned with a won dispute, is
negative. Net revenue is before fees. USD comes from Stripe's own balance
transaction; an account that settles in another currency leaves USD unknown
(NULL) and the run counts those rows.

A run reads balance transactions created from the watermark minus 48 hours up to
its own start (the first run backfills from BOARD_BACKFILL_FROM, midnight in New
York), writes them with board_ingest_ledger, and on success moves the watermark
to its start minus 5 minutes. Each run is claimed in job_runs first, so two never
overlap. Test mode never reaches the ledger: a test-mode key (sk_test_, rk_test_)
is refused before any claim or read, and an object marked livemode false is
skipped.

Each new sale is labelled once, from its charge and Checkout Session: product,
quantity, buyer email, the connected platform that created it (application), the
checkout's utm_source as its channel, and client_reference_id as a click id (the
SQL keeps it only when it names a stored click). A /go click hands its id to a
Stripe Payment Link, so a sale whose click id names a stored click is credited
to that click: its channel is the click's (the visitor's utm_source on the /go
link, else the /go key) and its attribution 'click_id'. The click wins over the
checkout's utm_source, and over the buyer's earlier lead (board_ledger matches a
lead by email only for a sale with no stored channel). A refund or dispute
takes its sale's channel. Labels never block money: a failed label fetch or
click lookup is counted and the sale is written without it. The run's warning
names those sales (the board's note and the morning message show it), and its
detail lists them ('unlabelled'), so the next runs label them again while they
are still in the read window; a second failure keeps what was stored.

mrr() reads the active subscriptions for the scoreboard's MRR card
(RevenueEngine.live_mrr in core/revenue.py): a read, nothing is written.

Keys: STRIPE_READ_KEY (a restricted read-only key), else STRIPE_SECRET_KEY.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter
from dataclasses import replace
from datetime import date, datetime, time as dtime, timedelta, timezone
from fractions import Fraction
from typing import Iterator, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx

from core.board import ledger
from core.board.ledger import BoardDBError, LedgerRow

log = logging.getLogger("board.stripe_sync")

SOURCE_ID = "stripe"
JOB = "stripe_sync"
API = "https://api.stripe.com"
NY = ZoneInfo("America/New_York")
OVERLAP = timedelta(hours=48)       # each run re-reads this much before the watermark
LAG = timedelta(minutes=5)          # the watermark trails the run's start by this much
DEFAULT_BACKFILL = date(2026, 1, 1)
UNLABELLED_MOST = 500               # sales a run names in its detail, to be labelled again

# Tests put an httpx.MockTransport here; None means the real network.
_transport: Optional[httpx.BaseTransport] = None
_sleep = time.sleep
_TIMEOUT = 20.0
_RETRIES = 3
# The MRR card is read while a page waits: one short try and one retry, so a
# Stripe outage costs the page seconds, not a minute and a half.
_LIVE_TIMEOUT = 10.0
_LIVE_RETRIES = 1

SALE_TYPES = frozenset({"charge", "payment"})
REFUND_TYPES = frozenset({"refund", "payment_refund"})
FEE_TYPES = frozenset({"stripe_fee", "stripe_fx_fee", "tax_fee"})
ADJUSTMENT_TYPES = frozenset({"refund_failure"})
NOT_REVENUE = frozenset({
    "payout", "payout_cancel", "payout_failure", "payout_minimum_balance_hold",
    "payout_minimum_balance_release", "transfer", "transfer_cancel", "transfer_failure",
    "transfer_refund", "topup", "topup_reversal", "reserve_transaction", "reserved_funds",
    "payment_network_reserve_hold", "payment_network_reserve_release", "contribution",
    "climate_order_purchase", "climate_order_refund"})

_KEY_RE = re.compile(r"^(sk|rk)_(live|test)_[A-Za-z0-9]{8,}$")


class StripeError(Exception):
    """Stripe refused or failed a call. The message names the status and the
    error type, never the key."""


# ─── configuration ──────────────────────────────────────────────────────────

def read_key() -> Optional[tuple[str, str]]:
    """(key, the variable it came from): STRIPE_READ_KEY, else STRIPE_SECRET_KEY.
    None when neither holds a Stripe key (a placeholder does not count)."""
    for name in ("STRIPE_READ_KEY", "STRIPE_SECRET_KEY"):
        key = os.getenv(name, "").strip()
        if _KEY_RE.match(key):
            return key, name
    return None


def is_test_key(key: str) -> bool:
    """sk_test_ or rk_test_: test payments, never revenue. The sync refuses it."""
    return key.split("_")[1:2] == ["test"]


def backfill_from() -> date:
    """BOARD_BACKFILL_FROM (YYYY-MM-DD): the first owner day the first run covers."""
    raw = os.getenv("BOARD_BACKFILL_FROM", "").strip()
    if not raw:
        return DEFAULT_BACKFILL
    try:
        return date.fromisoformat(raw)
    except ValueError:
        log.warning("BOARD_BACKFILL_FROM is not YYYY-MM-DD; backfilling from %s", DEFAULT_BACKFILL)
        return DEFAULT_BACKFILL


def backfill_start() -> datetime:
    """Midnight in New York on BOARD_BACKFILL_FROM, as a UTC instant."""
    return datetime.combine(backfill_from(), dtime(0), tzinfo=NY).astimezone(timezone.utc)


# ─── Stripe's API (read only) ───────────────────────────────────────────────

def _error_type(r: httpx.Response) -> str:
    """Stripe's error type and code. Never its message, which can quote the key's tail."""
    try:
        err = (r.json() or {}).get("error") or {}
    except (ValueError, AttributeError):
        return ""
    parts = [re.sub(r"[^a-z_]", "", str(err.get(k) or ""))[:40] for k in ("type", "code")]
    parts = [p for p in parts if p]
    return f" ({'/'.join(parts)})" if parts else ""


def _retry_after(r: httpx.Response, attempt: int) -> float:
    try:
        return min(max(float(r.headers.get("retry-after", "")), 0.5), 30.0)
    except ValueError:
        return float(2 ** attempt)


class _Stripe:
    def __init__(self, key: str, *, timeout: Optional[float] = None, retries: Optional[int] = None):
        self._retries = _RETRIES if retries is None else retries
        self._client = httpx.Client(transport=_transport, timeout=_TIMEOUT if timeout is None else timeout,
                                    base_url=API, headers={"Authorization": f"Bearer {key}"})

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, params: list) -> dict:
        for attempt in range(self._retries + 1):
            try:
                r = self._client.get(path, params=params)
            except httpx.HTTPError as e:
                if attempt == self._retries:
                    raise StripeError(f"Stripe unreachable ({type(e).__name__}) on {path}") from None
                _sleep(float(2 ** attempt))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self._retries:
                    raise StripeError(f"Stripe HTTP {r.status_code}{_error_type(r)} on {path}")
                _sleep(_retry_after(r, attempt))
                continue
            if r.status_code != 200:
                raise StripeError(f"Stripe HTTP {r.status_code}{_error_type(r)} on {path}")
            try:
                body = r.json()
            except ValueError:
                body = None
            if not isinstance(body, dict):
                raise StripeError(f"Stripe answered {path} without a JSON object")
            return body
        raise StripeError(f"Stripe failed on {path}")   # not reached

    def balance_transactions(self, since: datetime, until: datetime) -> Iterator[dict]:
        """Every balance transaction created in [since, until), each with its
        source (charge, refund, dispute) expanded. Stripe pages newest first."""
        params = [("limit", "100"), ("created[gte]", str(int(since.timestamp()))),
                  ("created[lt]", str(int(until.timestamp()))), ("expand[]", "data.source")]
        after = None
        while True:
            page = self.get("/v1/balance_transactions",
                            params + ([("starting_after", after)] if after else []))
            data = [bt for bt in page.get("data") or [] if isinstance(bt, dict)]
            yield from data
            after = data[-1].get("id") if data else None
            if not page.get("has_more") or not after:
                return

    def checkout_session(self, payment_intent: str) -> Optional[dict]:
        page = self.get("/v1/checkout/sessions", [("payment_intent", payment_intent), ("limit", "1"),
                                                  ("expand[]", "data.line_items")])
        data = page.get("data") or []
        return data[0] if data and isinstance(data[0], dict) else None

    def active_subscriptions(self) -> Iterator[dict]:
        """Every active subscription, its items and their prices included."""
        after = None
        while True:
            page = self.get("/v1/subscriptions", [("status", "active"), ("limit", "100")]
                            + ([("starting_after", after)] if after else []))
            data = [s for s in page.get("data") or [] if isinstance(s, dict)]
            yield from data
            after = data[-1].get("id") if data else None
            if not page.get("has_more") or not after:
                return


_MONTHS_PER = {"month": Fraction(1), "year": Fraction(1, 12), "week": Fraction(52, 12), "day": Fraction(365, 12)}


def mrr(key: str) -> tuple[Optional[int], int, Optional[str]]:
    """(monthly recurring revenue in US cents, active subscriptions, a
    problem): every active subscription's items, each price per month
    (a yearly price is a twelfth; quantity and interval_count count), summed
    exactly and rounded to the cent once. The MRR is None, with the problem
    named, when a price is not a plain USD amount (tiered, metered, or in
    another currency) or a subscription's items do not all come in one read:
    a smaller number would be wrong. A page waits on this read, so each call
    gets one short retry (_LIVE_TIMEOUT, _LIVE_RETRIES). Raises StripeError."""
    client = _Stripe(key, timeout=_LIVE_TIMEOUT, retries=_LIVE_RETRIES)
    total, count, problem = Fraction(0), 0, None
    try:
        for sub in client.active_subscriptions():
            count += 1
            items = sub.get("items") if isinstance(sub.get("items"), dict) else {}
            if items.get("has_more"):
                problem = problem or "a subscription has more items than one read returns"
            for item in items.get("data") or []:
                price = item.get("price") if isinstance(item, dict) else None
                recurring = price.get("recurring") if isinstance(price, dict) else None
                amount, interval = (price or {}).get("unit_amount"), (recurring or {}).get("interval")
                every = (recurring or {}).get("interval_count") or 1
                quantity = item.get("quantity") if isinstance(item.get("quantity"), int) else 1
                if str((price or {}).get("currency") or "").lower() != "usd":
                    problem = problem or "a subscription is priced in another currency than USD"
                elif isinstance(amount, bool) or not isinstance(amount, int) or interval not in _MONTHS_PER \
                        or isinstance(every, bool) or not isinstance(every, int) or every < 1 \
                        or (recurring or {}).get("usage_type") == "metered":
                    problem = problem or "a subscription has a price that is not a plain amount"
                else:
                    total += Fraction(amount * quantity) * _MONTHS_PER[interval] / every
    finally:
        client.close()
    if problem:
        return None, count, problem
    whole, rest = divmod(total.numerator, total.denominator)
    return whole + (1 if 2 * rest >= total.denominator else 0), count, None


# ─── mapping: one balance transaction to one ledger row ─────────────────────

def _id(value) -> Optional[str]:
    """An id, whether Stripe sent it as a string or as an expanded object."""
    if isinstance(value, dict):
        value = value.get("id")
    return value if isinstance(value, str) and value else None


def _source(bt: dict) -> dict:
    src = bt.get("source")
    return src if isinstance(src, dict) else {}


def _int(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{what} is not an integer amount")
    return value


def _is_dispute(bt: dict) -> bool:
    if bt.get("reporting_category") in ("dispute", "dispute_reversal"):
        return True
    if _source(bt).get("object") == "dispute":
        return True
    return (_id(bt.get("source")) or "").startswith(("du_", "dp_"))


def classify(bt: dict) -> tuple[Optional[str], Optional[tuple[str, str]]]:
    """(ledger kind, None) for a money movement, else (None, (why, name)):
    ('not_revenue', type) or ('unmapped', a name for the run's detail)."""
    btype = str(bt.get("type") or "")
    amount = bt.get("amount")
    if btype in SALE_TYPES:
        return "sale", None
    if btype in REFUND_TYPES:
        return "refund", None
    if btype == "adjustment":
        if _is_dispute(bt):
            amount = _int(amount, f"balance transaction {bt.get('id')}")
            return ("dispute" if amount < 0 else "dispute_reversal"), None
        return None, ("unmapped", "adjustment (not a dispute)")
    if btype in FEE_TYPES:
        amount = _int(amount, f"balance transaction {bt.get('id')}")
        if amount <= 0:
            return "fee", None
        return None, ("unmapped", f"{btype} (a credit)")   # named, not guessed
    if btype in ADJUSTMENT_TYPES:
        return "adjustment", None
    if btype in NOT_REVENUE:
        return None, ("not_revenue", btype)
    return None, ("unmapped", btype or "(no type)")


def to_row(bt: dict, kind: str) -> LedgerRow:
    """The money of one balance transaction. Raises ValueError on a malformed
    money field: the run fails loudly instead of guessing."""
    txn = bt.get("id")
    if not isinstance(txn, str) or not txn:
        raise ValueError("a balance transaction has no id")
    what = f"balance transaction {txn}"
    amount = _int(bt.get("amount"), what)              # settled, signed, account currency
    created = _int(bt.get("created"), f"{what} created")
    settled = str(bt.get("currency") or "").upper()
    if not re.fullmatch(r"[A-Z]{3}", settled):
        raise ValueError(f"{what} has no currency")
    src = _source(bt)
    # The buyer's own amount and currency, when they differ from what settled.
    src_amount = src.get("amount")
    if src.get("object") == "charge" and isinstance(src.get("amount_captured"), int) and src["amount_captured"] > 0:
        src_amount = src["amount_captured"]
    src_currency = str(src.get("currency") or "").upper()
    if (re.fullmatch(r"[A-Z]{3}", src_currency) and src_currency != settled
            and isinstance(src_amount, int) and not isinstance(src_amount, bool)):
        minor, currency = (-abs(src_amount) if amount < 0 else abs(src_amount)), src_currency
    else:
        minor, currency = amount, settled
    usd = amount if settled == "USD" else None
    if kind == "sale":
        order_ref = _id(bt.get("source"))
    elif kind == "fee":
        order_ref = None
    else:
        order_ref = _id(src.get("charge"))
    fee = bt.get("fee")
    raw = {"type": bt.get("type"), "reporting_category": bt.get("reporting_category"),
           "source": _id(bt.get("source")), "status": bt.get("status"),
           "settled_amount": amount, "settled_currency": settled}
    if bt.get("exchange_rate") is not None:
        raw["exchange_rate"] = bt.get("exchange_rate")
    return LedgerRow(
        external_id=txn, kind=kind, amount_minor=minor, currency=currency,
        occurred_at=datetime.fromtimestamp(created, timezone.utc),
        amount_usd_cents=usd, fx_source="stripe" if usd is not None else None,
        fee_usd_cents=_int(fee, f"{what} fee") if (usd is not None and fee is not None) else None,
        order_ref=order_ref, raw=raw)


def fee_row(bt: dict) -> LedgerRow:
    """The fee of a balance transaction whose amount is not revenue (an Instant
    Payout's fee sits on its payout): a fee row with no amount and Stripe's fee,
    with Stripe's sign, so the board's fees match Stripe's export."""
    row = to_row(bt, "fee")
    return replace(row, amount_minor=0, amount_usd_cents=None if row.amount_usd_cents is None else 0)


def _uuid(value) -> Optional[UUID]:
    try:
        return UUID(str(value).strip()) if value else None
    except ValueError:
        return None


def sale_labels(charge: dict, session: Optional[dict]) -> dict:
    """Labels for a sale from its charge and Checkout Session (either may be
    empty): product, quantity, customer_email, channel and attribution (the
    checkout's utm_source), click_id, via_platform."""
    s = session or {}
    items = [i for i in ((s.get("line_items") or {}).get("data") or []) if isinstance(i, dict)]
    names = [str(i.get("description") or "").strip() for i in items]
    names = [n for n in names if n]
    if names:
        product = names[0] + (f" and {len(names) - 1} more" if len(names) > 1 else "")
    else:
        product = str(charge.get("description") or "").strip() or None
    quantity = sum(i["quantity"] for i in items
                   if isinstance(i.get("quantity"), int) and not isinstance(i.get("quantity"), bool))
    email = ((s.get("customer_details") or {}).get("email")
             or (charge.get("billing_details") or {}).get("email") or charge.get("receipt_email"))
    meta = {**(charge.get("metadata") or {}), **(s.get("metadata") or {})}
    utm = str(meta.get("utm_source") or "").strip().lower() or None
    return {"product": product[:200] if product else None, "quantity": quantity or None,
            "customer_email": str(email).strip() if email else None,
            "channel": utm, "attribution": "checkout_utm" if utm else "none",
            "click_id": _uuid(s.get("client_reference_id")),
            "via_platform": _id(charge.get("application"))}


def collect(key: str, since: datetime, until: datetime) -> tuple[list[LedgerRow], dict]:
    """Read and map every balance transaction created in [since, until).
    Returns the rows and the counts for the run's detail."""
    api = _Stripe(key)
    try:
        rows: list[LedgerRow] = []
        sales: list[tuple[int, dict]] = []      # (index in rows, its charge)
        not_revenue, unmapped, fees_kept = Counter(), Counter(), Counter()
        listed = test_mode = 0
        for bt in api.balance_transactions(since, until):
            listed += 1
            src = _source(bt)
            if src.get("livemode") is False:     # test mode: never revenue
                test_mode += 1
                continue
            kind, skip = classify(bt)
            if kind is None:
                (not_revenue if skip[0] == "not_revenue" else unmapped)[skip[1]] += 1
                if skip[0] == "not_revenue" and bt.get("fee"):
                    rows.append(fee_row(bt))
                    fees_kept[skip[1]] += 1
                continue
            if kind == "sale":
                sales.append((len(rows), src))
            rows.append(to_row(bt, kind))
        # Label each sale once: the ones the ledger has already keep their labels,
        # except those a recent run could not label, which are tried again.
        existing = ledger.existing_ids(SOURCE_ID, [rows[i].external_id for i, _ in sales]) if sales else set()
        retry = _unlabelled_before() & existing if existing else set()
        unlabelled: set[str] = set()
        labelled = []
        for i, charge in sales:
            external_id = rows[i].external_id
            if external_id in existing and external_id not in retry:
                continue
            session = None
            payment_intent = _id(charge.get("payment_intent"))
            if payment_intent:
                try:
                    session = api.checkout_session(payment_intent)
                except StripeError as e:
                    unlabelled.add(external_id)
                    log.info("stripe sync: no labels for %s (%s)", external_id, e)
                    if external_id in retry:
                        continue            # failed again: the labels stored the first time stay as they are
            rows[i] = replace(rows[i], **sale_labels(charge, session))
            labelled.append(i)
        click_attributed, unchecked = _click_attribution(rows, labelled)
        unlabelled |= unchecked
        return rows, {"listed": listed, "not_revenue": dict(not_revenue), "fees_kept": dict(fees_kept),
                      "unmapped_types": dict(unmapped), "skipped_test_mode": test_mode,
                      "non_usd_settlement": sum(1 for r in rows if r.amount_usd_cents is None),
                      "label_errors": len(unlabelled), "click_attributed": click_attributed,
                      "unlabelled": sorted(unlabelled)[:UNLABELLED_MOST]}
    finally:
        api.close()


def _unlabelled_before() -> set[str]:
    """The sales the last complete run could not label (its detail's
    'unlabelled'), so this run labels them again while they are still in its
    read window (the 48 h overlap). Best effort: none when it cannot be read."""
    try:
        detail = ledger.last_ok_detail(JOB) or {}
    except BoardDBError as e:
        log.info("stripe sync: the last run's unlabelled sales cannot be read (%s)", e)
        return set()
    ids = detail.get("unlabelled")
    return {i for i in ids if isinstance(i, str)} if isinstance(ids, list) else set()


def _click_attribution(rows: list[LedgerRow], labelled: list[int]) -> tuple[int, set[str]]:
    """Credit each newly labelled sale whose click id names a stored click to
    that click: channel = the click's channel (its utm_source, else its /go
    key; ledger.click_channel) and attribution 'click_id'. The click wins over
    a checkout UTM, and over the buyer's earlier lead, which board_ledger uses
    only for a sale with no stored channel. One lookup for all of them. A
    lookup that fails leaves every other label as it was and is counted, never
    failing the run: labels never block money. Returns (sales credited to a
    click, the external ids of the sales whose click could not be checked)."""
    with_click = [i for i in labelled if rows[i].click_id is not None]
    if not with_click:
        return 0, set()
    try:
        clicks = ledger.clicks_by_id(rows[i].click_id for i in with_click)
    except BoardDBError as e:
        log.info("stripe sync: the clicks of %d sales could not be checked (%s)", len(with_click), e)
        return 0, {rows[i].external_id for i in with_click}
    credited = 0
    for i in with_click:
        channel = ledger.click_channel(clicks.get(ledger.click_uuid(rows[i].click_id) or ""))
        if channel:
            rows[i] = replace(rows[i], channel=channel, attribution="click_id")
            credited += 1
    return credited, set()


# ─── one run ────────────────────────────────────────────────────────────────

def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _warning(mismatches: int, unmapped: dict, unlabelled: int = 0) -> Optional[str]:
    """What an ok run must still tell the owner (the run's error and the
    source's last_error, so the board's note and the morning message show it).
    The money warnings come first: last_error keeps 300 characters."""
    parts = []
    if mismatches:
        parts.append(f"{mismatches} balance transaction{'s disagree' if mismatches != 1 else ' disagrees'} "
                     "with the ledger; the amounts written first are kept")
    if unmapped:
        n = sum(unmapped.values())
        parts.append(f"skipped {n} balance transaction{'s' if n != 1 else ''} of a type the board does not "
                     f"map ({', '.join(sorted(unmapped))}): totals may differ from Stripe")
    if unlabelled:
        parts.append(f"{unlabelled} sale{'s' if unlabelled != 1 else ''} could not be labelled (Stripe's Checkout "
                     "Session or the click could not be read): product and channel may be missing, so attributed "
                     "revenue may be low")
    return "; ".join(parts) or None


def run(trigger: str = "schedule", days: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    """One sync run, claimed in job_runs. `days` widens the window to at least
    the last N days (it never narrows it, so no gap opens behind the watermark).
    Returns the run's fields (status ok, failed, busy or skipped); never raises."""
    started = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out: dict = {"id": None, "job": JOB, "source_id": SOURCE_ID, "trigger_kind": trigger,
                 "status": None, "started_at": started.isoformat(), "finished_at": None,
                 "window_start": None, "window_end": None, "covered_until": None,
                 "rows_written": 0, "detail": {}, "error": None}
    found = read_key()
    if found is None:
        out.update(status="skipped", error="no Stripe key: set STRIPE_READ_KEY (or STRIPE_SECRET_KEY)")
        return out
    key, key_name = found
    if is_test_key(key):
        # Before any claim or read: no test payment, watermark or measured_from
        # reaches the ledger, which a live key would inherit later.
        out.update(status="skipped", error=f"{key_name} is a test-mode key: test payments are not revenue, "
                                           "so nothing is read; set a live read key (rk_live_...)")
        return out
    out["run_key"] = started.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    try:
        run_id = ledger.claim_run(JOB, out["run_key"], trigger, SOURCE_ID)
    except BoardDBError as e:
        log.warning("stripe sync: cannot claim a run (%s)", e)
        out.update(status="failed", error=f"database: {e}")
        return out
    if run_id is None:
        out.update(status="busy", error="another Stripe sync is running")
        return out
    out["id"] = run_id
    detail: dict = {"key": key_name}
    out["detail"] = detail
    since = until = None
    try:
        src = ledger.source_row(SOURCE_ID)
        if src is None:
            raise BoardDBError("no 'stripe' row in public.sources: apply migration 0002")
        if src.get("enabled") is False:
            ledger.finish_run(run_id, "skipped", detail=detail, error="the stripe source is disabled")
            out.update(status="skipped", error="the stripe source is disabled",
                       finished_at=datetime.now(timezone.utc).isoformat())
            return out
        watermark = ledger.parse_ts(src.get("synced_through"))
        first = watermark is None
        since = backfill_start() if first else watermark - OVERLAP
        if days:
            since = min(since, started - timedelta(days=days))
        until = started
        rows, counts = collect(key, since, until)
        detail.update(counts)
        result = (ledger.ingest_ledger(SOURCE_ID, run_id, rows) if rows
                  else {"received": 0, "inserted": 0, "relabelled": 0, "money_mismatches": 0})
        detail.update(result)
        covered = started - LAG
        error = _warning(result["money_mismatches"], counts["unmapped_types"], counts["label_errors"])
        ledger.finish_run(run_id, "ok", rows_written=result["inserted"], detail=detail, error=error,
                          window_start=since, window_end=until, covered_until=covered)
        ledger.mark_source_ok(SOURCE_ID, covered, backfill_from() if first else None, warning=error)
        out.update(status="ok", rows_written=result["inserted"], error=error,
                   window_start=_iso(since), window_end=_iso(until), covered_until=_iso(covered),
                   finished_at=datetime.now(timezone.utc).isoformat())
        log.info("stripe sync ok: %s new of %s rows (%s)", result["inserted"], result["received"], trigger)
    except Exception as e:  # noqa: BLE001 — a failed run is recorded, never left running
        if isinstance(e, (StripeError, BoardDBError, ValueError)):
            message = str(e)[:300]
        else:
            message = f"unexpected {type(e).__name__}"
            log.exception("stripe sync failed")
        log.warning("stripe sync failed: %s", message)
        for step in (lambda: ledger.finish_run(run_id, "failed", detail=detail, error=message,
                                               window_start=since, window_end=until),
                     lambda: ledger.mark_source_error(SOURCE_ID, message)):
            try:
                step()
            except BoardDBError as db_error:
                log.warning("stripe sync: could not record the failure (%s)", db_error)
        out.update(status="failed", error=message, window_start=_iso(since), window_end=_iso(until),
                   finished_at=datetime.now(timezone.utc).isoformat())
    return out
