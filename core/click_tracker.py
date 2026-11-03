#!/usr/bin/env python3
"""
core/click_tracker.py
─────────────────────────────────────────────────────────────────────────────
Product click tracking: the /go/{partner} redirector's keys and destinations,
and the click store behind it.

Destinations (affiliate_swap_2026_05_29): every partner key resolves to
DIGITAL_PRODUCT_URL with UTM tagging by partner key. The owned 'insider'
funnel is the only env-backed entry (AFFILIATE_INSIDER_URL).

A key is lower-cased and must then be 1 to 64 of a-z, 0-9, _ and -; any other
key is no key (the route answers 404).

Clicks live in the daily numbers board's database, in public.clicks
(narai/migrations/0002_daily_numbers_board.sql), through core.board.ledger:
one row per stored click with its id, the key, the time, the referring host
(never the path), the visitor's own utm_* tags from the /go link, and the
destination. No visitor IP address is stored anywhere. Storing is best effort:
a click that cannot be stored is logged and skipped, and the redirect never
waits for it. One client address gets at most 30 stored clicks a minute, and
everyone together 300 (counted in memory only); past that the link still
redirects, but nothing is stored.

The click id goes to a Stripe Payment Link (https://buy.stripe.com) as
client_reference_id, so the Stripe sync can credit the sale to the click.
Attribution lives in the ledger: no conversion log is kept here.

record_click, get_stats, _load_clicks and tracking_url keep their old
signatures and shapes for the callers outside the board.
─────────────────────────────────────────────────────────────────────────────
"""

import hashlib
import logging
import os
import re
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("click_tracker")

NY = ZoneInfo("America/New_York")

# ── Partner key → destination URL ────────────────────────────────────────────

# OLD: each known partner mapped to its own .env-backed network affiliate URL.
# NEW (affiliate_swap_2026_05_29): every partner key resolves to
# DIGITAL_PRODUCT_URL with UTM content = partner key. The owned 'insider'
# funnel still resolves to AFFILIATE_INSIDER_URL.

DIGITAL_PRODUCT_URL = "https://stan.store/Wheellsverse"


def _stan(partner: str, source: str = "click_tracker", medium: str = "redirect") -> str:
    """Build a UTM-tagged redirect URL to the owned digital product."""
    return (
        f"{DIGITAL_PRODUCT_URL}"
        f"?utm_source={source}"
        f"&utm_medium={medium}"
        f"&utm_campaign=affiliate_swap_2026_05_29"
        f"&utm_content={partner}"
    )


def _affiliate_urls() -> Dict[str, str]:
    """Return partner_key → destination URL map.

    Only the owned-funnel 'insider' key is env-backed. All other partner keys
    are resolved on demand via _resolve_destination().
    """
    base_app_url = os.getenv("APP_BASE_URL", "https://app.wheellsverse.com").rstrip("/")
    return {
        "insider": os.getenv("AFFILIATE_INSIDER_URL", f"{base_app_url}/insider"),
    }


def _resolve_destination(partner: str) -> str:
    """Resolve any partner key to its destination URL.

    'insider' → owned funnel. Anything else → DIGITAL_PRODUCT_URL with
    utm_content = partner key.
    """
    partner_key = partner.lower()
    urls = _affiliate_urls()
    if partner_key in urls:
        return urls[partner_key]
    return _stan(partner_key)


# ── One click ─────────────────────────────────────────────────────────────────

PARTNER_RE = re.compile(r"[a-z0-9_-]{1,64}")          # clicks.partner's check
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")
UTM_LONGEST = 100
HOST_LONGEST = 255                                    # clicks.referrer_host's check
DESTINATION_LONGEST = 2048                            # clicks.destination's check
PAYMENT_LINK_HOST = "buy.stripe.com"
TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"                   # the old click log's time, in UTC
RECENT = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


_clock = _now                                         # tests freeze it


def partner_key(partner) -> Optional[str]:
    """The key as stored: lower-cased, and only when it is then 1 to 64 of
    a-z, 0-9, _ and -. None for anything else."""
    if not isinstance(partner, str):
        return None
    key = partner.lower()
    return key if PARTNER_RE.fullmatch(key) else None


def referrer_host(referrer) -> Optional[str]:
    """The referring page's host, lower-case ASCII and at most 255 characters,
    never its path or query; None when there is none."""
    if not isinstance(referrer, str) or not referrer.strip():
        return None
    try:
        host = urlsplit(referrer.strip()).hostname
    except ValueError:
        return None
    if not host or not host.isascii() or not host.isprintable() or " " in host or len(host) > HOST_LONGEST:
        return None
    return host.lower()


def _first(query, key: str):
    """The first value of `key` in a query: Starlette's QueryParams, a dict,
    (name, value) pairs or a query string."""
    if query is None:
        return None
    if isinstance(query, str):
        return next((v for k, v in parse_qsl(query.lstrip("?"), keep_blank_values=True) if k == key), None)
    getlist = getattr(query, "getlist", None)
    if callable(getlist):
        values = getlist(key)
        return values[0] if values else None
    if isinstance(query, dict):
        value = query.get(key)
        return value[0] if isinstance(value, (list, tuple)) and value else value
    try:
        return next((v for k, v in query if k == key), None)
    except (TypeError, ValueError):
        return None


def utm_tags(query) -> Dict[str, str]:
    """The visitor's utm_source, utm_medium, utm_campaign, utm_content and
    utm_term from the /go link's query: the first value of each, with control
    characters removed, trimmed, at most 100 characters; empty ones left out."""
    out: Dict[str, str] = {}
    for key in UTM_KEYS:
        value = _first(query, key)
        if not isinstance(value, str):
            continue
        clean = "".join(ch for ch in value if ch.isprintable()).strip()[:UTM_LONGEST].strip()
        if clean:
            out[key] = clean
    return out


def with_click_id(url: str, click_id: str) -> str:
    """`url` with client_reference_id=<click_id> when it is a Stripe Payment
    Link (https and the host exactly buy.stripe.com), so the Checkout Session
    carries the click; its other parameters and fragment are kept, and any
    client_reference_id it had is replaced. Any other URL is returned as it is."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return url
    if parts.scheme.lower() != "https" or host != PAYMENT_LINK_HOST:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "client_reference_id"]
    query.append(("client_reference_id", click_id))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass(frozen=True)
class Click:
    """One /go click before it is stored. `destination` is where the key goes;
    `url` is where this visitor goes: the destination, plus the click id when
    it is a Stripe Payment Link."""
    id: str
    partner: str
    clicked_at: datetime
    referrer_host: Optional[str]
    utm: Dict[str, str]
    destination: str
    url: str

    def row(self) -> Dict:
        """The row of public.clicks: exactly id, partner, clicked_at,
        referrer_host, destination and utm."""
        return {"id": self.id, "partner": self.partner,
                "clicked_at": self.clicked_at.astimezone(timezone.utc).isoformat(),
                "referrer_host": self.referrer_host, "destination": self.destination, "utm": dict(self.utm)}


def new_click(partner: str, referrer: str = "", query=None) -> Optional[Click]:
    """A click on `partner` from the page `referrer` (the Referer header; only
    its host is kept) with the link's `query` (its utm_* tags are kept). None
    when the key is not a key (see partner_key) or has no destination."""
    key = partner_key(partner)
    if key is None:
        return None
    destination = _resolve_destination(key)
    if not isinstance(destination, str) or not destination.strip():
        return None
    click_id = str(uuid.uuid4())
    # A destination the table cannot hold is never stored, so it gets no click id.
    url = with_click_id(destination, click_id) if len(destination) <= DESTINATION_LONGEST else destination
    return Click(id=click_id, partner=key, clicked_at=_clock(), referrer_host=referrer_host(referrer),
                 utm=utm_tags(query), destination=destination, url=url)


# ── How many clicks are stored (in memory only; the address is never kept) ────

PER_CLIENT_PER_MINUTE = 30
EVERYONE_PER_MINUTE = 300
_WINDOW = 60.0
_MAX_CLIENTS = 10_000
_limit_lock = threading.Lock()
_by_client: Dict[bytes, deque] = {}
_everyone: deque = deque()
_salt = os.urandom(16)        # keys the per-client buckets: the address itself is never held
_monotonic = time.monotonic   # tests move it
_limited = {"since": None, "skipped": 0}     # clicks over the limit since the last note
_warn_lock = threading.Lock()
_warned = {"since": None, "failed": 0}       # clicks not stored since the last warning


def allow_click(client: str) -> bool:
    """Whether one more click from this client address may be stored now: at
    most PER_CLIENT_PER_MINUTE in the last 60 seconds for one client and
    EVERYONE_PER_MINUTE for everyone together. The buckets are kept in memory,
    keyed by a salted hash of the address; the address is never stored or
    logged. At most 10,000 buckets: idle ones go first."""
    now = _monotonic()
    key = hashlib.blake2b(str(client).encode("utf-8", "replace"), key=_salt, digest_size=16).digest()
    note = 0                                  # clicks over the limit to log, once a minute at most
    with _limit_lock:                         # the check and the count are one step
        while _everyone and now - _everyone[0] >= _WINDOW:
            _everyone.popleft()
        hits = _by_client.get(key)
        while hits and now - hits[0] >= _WINDOW:
            hits.popleft()
        allowed = not ((hits is not None and len(hits) >= PER_CLIENT_PER_MINUTE)
                       or len(_everyone) >= EVERYONE_PER_MINUTE)
        if not allowed:
            _limited["skipped"] += 1
            if _limited["since"] is None or now - _limited["since"] >= _WINDOW:
                note, _limited["skipped"], _limited["since"] = _limited["skipped"], 0, now
        else:
            if hits is None:
                if len(_by_client) >= _MAX_CLIENTS:
                    for k in [k for k, q in _by_client.items() if not q or now - q[-1] >= _WINDOW]:
                        del _by_client[k]
                    if len(_by_client) >= _MAX_CLIENTS:
                        _by_client.clear()          # the shared limit still holds
                hits = _by_client[key] = deque()
            hits.append(now)
            _everyone.append(now)
    if note:
        logger.info("click limit reached: %d click%s not stored since this was last logged (the links "
                    "still redirect)", note, "" if note == 1 else "s")
    return allowed


def reset_limits() -> None:
    """Forget every bucket (tests)."""
    with _limit_lock:
        _by_client.clear()
        _everyone.clear()
        _limited.update(since=None, skipped=0)
    with _warn_lock:
        _warned.update(since=None, failed=0)


# ── Storing a click (best effort) ─────────────────────────────────────────────

def _ledger():
    from core.board import ledger
    return ledger


def _warn_not_stored(e: Exception) -> None:
    """One warning a minute at most, with how many clicks went unstored. The
    reason names the call and its status, never a key, a row or an address."""
    from core.board.ledger import BoardDBError
    now = _monotonic()
    with _warn_lock:
        _warned["failed"] += 1
        if _warned["since"] is not None and now - _warned["since"] < _WINDOW:
            return
        failed, _warned["failed"], _warned["since"] = _warned["failed"], 0, now
    reason = str(e)[:200] if isinstance(e, (BoardDBError, ValueError)) else type(e).__name__
    logger.warning("a click was not stored (%s); %d not stored since the last warning", reason, failed)


def save_click(click: Click) -> bool:
    """Store `click` in public.clicks; True when it is stored. It never
    raises: a click that cannot be stored (the database down, the migration
    not applied) is logged and skipped. A stored click sends the silent
    Telegram click note, with no count."""
    try:
        if not 1 <= len(click.destination) <= DESTINATION_LONGEST:
            raise ValueError("the destination is longer than the clicks table holds")
        _ledger().insert_click(click.row())
    except Exception as e:  # noqa: BLE001 — a click is best effort, never an error for the visitor
        _warn_not_stored(e)
        return False
    try:
        from core.telegram import notify_click
        notify_click(partner=click.partner)
    except Exception:
        pass
    return True


# ── Public API ────────────────────────────────────────────────────────────────

def record_click(partner: str, referrer: str = "", ip: str = "") -> Optional[str]:
    """
    Log a click and return where it goes: the destination, with the click id
    when it is a Stripe Payment Link and the click was stored. None when the
    key is not a key or has no destination. `ip` is accepted for old callers
    and ignored: no visitor address is stored. The /go route itself uses
    new_click, allow_click and save_click, so the redirect never waits.
    """
    click = new_click(partner, referrer=referrer)
    if click is None:
        return None
    return click.url if save_click(click) else click.destination


def _old_shape(row: Dict) -> Dict:
    """A clicks row in the old click-log shape: partner, ts (UTC, '...Z'),
    referrer (the referring host, or ''), dest; plus id and utm."""
    at = _ledger().parse_ts(row.get("clicked_at"))
    return {"partner": str(row.get("partner") or ""),
            "ts": at.astimezone(timezone.utc).strftime(TS_FORMAT) if at else "",
            "referrer": row.get("referrer_host") or "", "dest": row.get("destination") or "",
            "id": str(row.get("id") or ""), "utm": row.get("utm") if isinstance(row.get("utm"), dict) else {}}


def _load_clicks() -> List[Dict]:
    """Every stored click, the oldest first, in the old click-log shape
    (_old_shape), read whole however many there are. [] with a warning when
    the clicks cannot be read."""
    ledger = _ledger()
    try:
        rows = ledger.read_clicks()
    except ledger.BoardDBError as e:
        logger.warning("clicks cannot be read (%s)", e)
        return []
    return [_old_shape(r) for r in rows]


def get_stats() -> Dict:
    """Click counts per key and the 20 newest clicks (no IP address: none is
    stored), from the clicks table; and the sales that came through a tracked
    link (a ledger sale whose click id names a stored click), counted per key,
    with their US dollars (summed in cents, before refunds). The old keys all
    stay, plus connected and note. total_clicks is the database's exact count.
    A store that cannot be read gives None for its counts and totals and
    empty dicts and lists, with connected False and a note: it never reads 0.
    More clicks than one whole read takes (ledger.READ_ALL_MOST) leaves only
    by_partner out, with a note: the database is up."""
    ledger = _ledger()
    out: Dict = {"total_clicks": None, "by_partner": {}, "recent": [], "total_conversions": None,
                 "conversions_by_partner": {}, "revenue_by_partner_usd": {}, "total_revenue_usd": None,
                 "connected": True, "note": ""}
    missing, notes = [], []
    try:
        out.update(total_clicks=ledger.count_clicks(),             # counted by the database, never len()
                   recent=[_old_shape(r) for r in ledger.newest_clicks(RECENT)])
        try:
            partners = Counter(str(r.get("partner") or "") for r in ledger.read_clicks("partner"))
            out["by_partner"] = dict(sorted(partners.items(), key=lambda kv: (-kv[1], kv[0])))
        except ledger.TooManyRows:
            notes.append(f"Clicks by key are left out: more than {ledger.READ_ALL_MOST:,} clicks to read.")
    except ledger.BoardDBError as e:
        logger.warning("click stats: the clicks cannot be read (%s)", e)
        missing.append("the clicks")
    try:
        sales = ledger.click_sales()
        clicks = ledger.clicks_by_id(s.get("click_id") for s in sales) if sales else {}
        count: Counter = Counter()
        cents: Dict[str, int] = {}
        unknown = set()                       # keys with a sale that has no US dollar amount yet
        for s in sales:
            click = clicks.get(ledger.click_uuid(s.get("click_id")) or "")
            key = str((click or {}).get("partner") or "unknown")
            count[key] += 1
            usd = s.get("amount_usd_cents")
            if isinstance(usd, int) and not isinstance(usd, bool):
                cents[key] = cents.get(key, 0) + usd
            else:
                unknown.add(key)
        out.update(total_conversions=len(sales), conversions_by_partner=dict(count),
                   revenue_by_partner_usd={k: None if k in unknown else cents.get(k, 0) / 100 for k in count},
                   total_revenue_usd=None if unknown else sum(cents.values()) / 100)
    except ledger.BoardDBError as e:
        logger.warning("click stats: the sales cannot be read (%s)", e)
        missing.append("the sales through tracked links")
    if missing:
        out.update(connected=False, note=f"Not connected: {' and '.join(missing)} cannot be read. "
                                         "The board's database is down or its migration is not applied.")
    elif notes:
        out["note"] = " ".join(notes)
    return out


def clicks_between(first: date, last: date) -> Optional[int]:
    """Clicks made on New York days `first` to `last`, counted by the
    database (each click's local_day); None when they cannot be counted."""
    ledger = _ledger()
    try:
        return ledger.count_clicks(first, last)
    except ledger.BoardDBError as e:
        logger.warning("clicks cannot be counted (%s)", e)
        return None


def clicks_on(day: date) -> Optional[int]:
    """Clicks made on one New York day; None when they cannot be counted."""
    return clicks_between(day, day)


def clicks_today() -> Optional[int]:
    """Clicks made so far today in New York; None when they cannot be counted."""
    return clicks_on(_clock().astimezone(NY).date())


def total_clicks() -> Optional[int]:
    """Every stored click, counted by the database; None when they cannot be counted."""
    ledger = _ledger()
    try:
        return ledger.count_clicks()
    except ledger.BoardDBError as e:
        logger.warning("clicks cannot be counted (%s)", e)
        return None


def tracking_url(partner: str, base_url: str = "") -> str:
    """
    Return the /go/{partner} tracking URL.
    base_url defaults to the CTA_URL host or localhost.
    """
    host = base_url or os.getenv("CTA_URL", "http://localhost:5050").rstrip("/")
    # Strip path from CTA_URL — we only want the host
    from urllib.parse import urlparse
    parsed = urlparse(host)
    host = f"{parsed.scheme}://{parsed.netloc}"
    return f"{host}/go/{partner}"


def inject_tracking_links(html: str, base_url: str = "") -> str:
    """
    Replace raw affiliate URLs in HTML with /go/{partner} tracking URLs.
    Safe to call on already-published HTML to upgrade it in place.
    """
    urls = _affiliate_urls()
    for partner, dest in urls.items():
        if dest and dest in html:
            track = tracking_url(partner, base_url)
            html = html.replace(dest, track)
    return html
