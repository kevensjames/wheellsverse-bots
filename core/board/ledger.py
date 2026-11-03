"""Money rows for the daily numbers board, and the board's calls into Supabase.

Every write goes through the tables and SQL functions of
narai/migrations/0002_daily_numbers_board.sql (replica/schema.sql): over
PostgREST, with the service-role key (RLS is on with no policies, so no other
key can read these tables), one short HTTP call each, the way
core/board/auth.py reads owner_sessions. No supabase-py client.

Totals are never summed here. board_day computes them in SQL, by New York
calendar day, in one round trip.

Amounts are integer minor units of their currency (cents for USD). A NULL USD
amount or fee means "unknown", never 0.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID

import httpx

from core.board.auth import _usable_url

log = logging.getLogger("board.ledger")

# Tests put an httpx.MockTransport here; None means the real network.
_transport: Optional[httpx.BaseTransport] = None
_TIMEOUT = 20.0          # seconds, each call
_INGEST_CHUNK = 500      # rows per board_ingest_ledger call
_IDS_CHUNK = 100         # external ids per lookup

KINDS = frozenset({"sale", "refund", "dispute", "dispute_reversal", "fee", "adjustment"})


class BoardDBError(Exception):
    """The board's tables could not be read or written: Supabase unset,
    unreachable, or the call refused (a missing migration, a bad money field)."""


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


def _call(method: str, path: str, *, params=None, json=None, prefer: Optional[str] = None) -> httpx.Response:
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
        with httpx.Client(transport=_transport, timeout=_TIMEOUT) as client:
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


# ─── sources: state, watermark, measured_from ───────────────────────────────

def source_row(source_id: str) -> Optional[dict]:
    rows = _json(_call("GET", "sources", params={
        "select": "id,enabled,measured_from,synced_through,day_tz,last_ok_at,last_error,last_error_at",
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

def board_day(day: Optional[date]) -> dict:
    """board_day: one owner day as JSON. day None = yesterday in New York,
    decided in SQL, not by this container's clock."""
    result = rpc("board_day", {"p_day": day.isoformat() if day else None})
    if not isinstance(result, dict):
        raise BoardDBError("board_day: unexpected answer")
    return result
