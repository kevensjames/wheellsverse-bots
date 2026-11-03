"""In-memory stand-ins for the services the board talks to, served through
httpx.MockTransport, so no test reaches the network:

  * FakeSupabase: Auth's password grant and PostgREST's public.owner_sessions
    (core.board.auth._transport), for sign-in.
  * FakeBoardDB: PostgREST over the board's tables and SQL functions
    (core.board.ledger._transport): the claims, board_ingest_ledger,
    board_ingest_leads, board_fill_fx and board_day, by New York day, the
    upsert on ad_spend_daily, the inserts into clicks, and the read-only views
    board_ledger and board_revenue_daily. Reads honour PostgREST's filters
    (eq, neq, in, lt, lte, gt, gte, is, not), order, offset, limit, Prefer:
    count=exact (Content-Range, 206 when partial, 416 past the end) and the
    API's row cap (max_rows, 1,000 by default, as on Supabase). It follows the rules of
    narai/migrations/0002_daily_numbers_board.sql that the board's code relies
    on; the real SQL is checked on PostgreSQL itself.
  * FakeStripe: the Stripe API's balance transactions and Checkout Sessions
    (core.board.connectors.stripe_sync._transport), with builders for them.

Builders for leads and Meta spend (optin, reply, spend) and the plan's leads
fixture (fixture_leads, load_fixture_leads) are at the end.
"""
from __future__ import annotations

import hashlib
import inspect
import itertools
import json
import re
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx

URL = "https://board-tests.supabase.invalid"
ANON = "anon-key-3c1d5e7f-for-tests"
SERVICE = "service-role-key-9a8b7c6d-for-tests"
OWNER_ID = "6f1c9b1e-7d2a-4c3b-9a55-0c1d2e3f4a5b"
OTHER_ID = "0b7e3c2a-1111-4222-8333-944455566677"
OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "correct horse battery staple"
OTHER_EMAIL = "someone@example.com"
OTHER_PASSWORD = "another good password"
API_KEY = "test-key-123"   # the value every core.api test agrees on
COOKIE = "__Host-board_session"

_HASH_FILTER = re.compile(r"^eq\.\\x([0-9a-f]{64})$")


class FakeSupabase:
    def __init__(self):
        self.users = {OWNER_EMAIL: (OWNER_PASSWORD, OWNER_ID), OTHER_EMAIL: (OTHER_PASSWORD, OTHER_ID)}
        self.sessions: dict[str, dict] = {}   # token sha256 hex -> row
        self.calls: list[httpx.Request] = []
        self.down = False                      # True: every call fails to connect
        self.unconfirmed: set[str] = set()     # emails whose sign-up was never confirmed

    # ── helpers for tests ──
    def add_session(self, user_id: str = OWNER_ID, days: float = 7, revoked: bool = False) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        self.sessions[hashlib.sha256(token.encode()).hexdigest()] = {
            "user_id": user_id, "expires_at": (now + timedelta(days=days)).isoformat(),
            "revoked_at": now.isoformat() if revoked else None, "user_agent": None}
        return token

    def calls_to(self, path: str, method: str | None = None) -> list[httpx.Request]:
        return [c for c in self.calls if c.url.path == path and (method is None or c.method == method)]

    # ── the fake services ──
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.down:
            raise httpx.ConnectError("fake Supabase is down", request=request)
        if not str(request.url).startswith(URL + "/"):
            return httpx.Response(404, json={"message": "unknown host"})
        if request.url.path == "/auth/v1/token":
            return self._grant(request)
        if request.url.path == "/rest/v1/owner_sessions":
            return self._sessions(request)
        return httpx.Response(404, json={"message": "no such route"})

    def _grant(self, request: httpx.Request) -> httpx.Response:
        if request.method != "POST" or request.url.params.get("grant_type") != "password":
            return httpx.Response(400, json={"error": "unsupported_grant_type"})
        if request.headers.get("apikey") != ANON or SERVICE in request.headers.get("authorization", ""):
            return httpx.Response(401, json={"message": "the grant takes the anon key only"})
        body = json.loads(request.content or b"{}")
        email = str(body.get("email", "")).lower()
        user = self.users.get(email)
        if not user or user[0] != body.get("password"):
            return httpx.Response(400, json={"code": 400, "error_code": "invalid_credentials",
                                              "msg": "Invalid login credentials"})
        if email in self.unconfirmed:   # GoTrue says so only after the password matched
            return httpx.Response(400, json={"code": 400, "error_code": "email_not_confirmed",
                                              "msg": "Email not confirmed"})
        return httpx.Response(200, json={"access_token": "fake-access", "refresh_token": "fake-refresh",
                                          "user": {"id": user[1], "email": body["email"]}})

    def _sessions(self, request: httpx.Request) -> httpx.Response:
        if (request.headers.get("apikey") != SERVICE
                or request.headers.get("authorization") != f"Bearer {SERVICE}"):
            return httpx.Response(401, json={"message": "service role required"})
        query = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        if request.method == "POST":
            row = json.loads(request.content)
            m = re.fullmatch(r"\\x([0-9a-f]{64})", row.get("token_sha256", ""))
            try:
                uuid.UUID(row["user_id"])
                expires = datetime.fromisoformat(row["expires_at"])
            except (KeyError, TypeError, ValueError):
                return httpx.Response(400, json={"message": "invalid input syntax"})
            if not m or not (timedelta(0) < expires - datetime.now(timezone.utc) <= timedelta(days=30)):
                return httpx.Response(400, json={"message": "check constraint"})
            if m.group(1) in self.sessions:
                return httpx.Response(409, json={"message": "duplicate key"})
            self.sessions[m.group(1)] = {"user_id": row["user_id"], "expires_at": row["expires_at"],
                                         "revoked_at": None, "user_agent": row.get("user_agent")}
            return httpx.Response(201)
        m = _HASH_FILTER.match(query.get("token_sha256", ""))
        if not m:
            return httpx.Response(400, json={"message": "filter by token_sha256"})
        row = self.sessions.get(m.group(1))
        if request.method == "GET":
            if not row:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{k: row[k] for k in ("user_id", "expires_at", "revoked_at")}])
        if request.method == "PATCH":
            if row and row["revoked_at"] is None and query.get("revoked_at") == "is.null":
                row["revoked_at"] = json.loads(request.content)["revoked_at"]
            return httpx.Response(204)
        return httpx.Response(405)


def install(monkeypatch, owner_id: str | None = OWNER_ID) -> FakeSupabase:
    """Point core.board.auth at a fresh fake and set the env sign-in needs."""
    from core.board import auth
    fake = FakeSupabase()
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_ANON_KEY", ANON)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", SERVICE)
    if owner_id is None:
        monkeypatch.delenv("BOARD_OWNER_USER_ID", raising=False)
    else:
        monkeypatch.setenv("BOARD_OWNER_USER_ID", owner_id)
    monkeypatch.setattr(auth, "_transport", httpx.MockTransport(fake.handler))
    auth.reset_state()
    return fake


def client(monkeypatch):
    """TestClient on core.api with a known API key for this test only. core.api
    reads API_KEY, SUPABASE_URL and SUPABASE_ANON_KEY once, at import, and an
    earlier test may have imported it first: set the module's copies too, so a
    page that wrote one of them out would show this test's value. The per-IP
    rate limiter gets a store of its own, so this test's requests neither hit
    nor use up the limit that other tests' clients share."""
    from collections import defaultdict
    from fastapi.testclient import TestClient
    import core.api as api       # before setenv: a first import here must not keep this test's key
    monkeypatch.setenv("API_KEY", API_KEY)          # read per request by the admin API routers
    monkeypatch.setattr(api, "_API_KEY", API_KEY)   # read by api_key_middleware
    monkeypatch.setattr(api, "_SUPABASE_URL", URL)  # read by _serve_frontend
    monkeypatch.setattr(api, "_SUPABASE_ANON", ANON)
    monkeypatch.setattr(api, "_rate_limit_store", defaultdict(list))
    return TestClient(api.app, raise_server_exceptions=False)


def cookie(token: str) -> dict:
    return {"Cookie": f"{COOKIE}={token}"}


# ═══ the board's tables and SQL functions (PostgREST) ═══════════════════════

NY = ZoneInfo("America/New_York")
SEED_SOURCES = (("stripe", "stripe", "api", "Stripe"), ("kit", "kit", "api", "Kit (Toodle opt-ins)"),
                ("instantly", "instantly", "api", "Instantly (SiteBoost replies)"),
                ("meta_ads", "meta_ads", "api", "Meta Ads"), ("kdp", "kdp", "upload", "Amazon KDP (report upload)"),
                ("manual", "manual", "manual", "Manual entries"))
MONEY_KINDS = ("sale", "refund", "dispute", "dispute_reversal", "adjustment")
INT_MAX = 2 ** 31 - 1
BIGINT_MAX = 2 ** 63 - 1
_LABEL = re.compile(r"[a-z0-9_]{1,32}")                     # funnel and channel checks
_DAY_TZ = re.compile(r"[A-Za-z_]+(/[A-Za-z0-9_+-]+)*")      # sources.day_tz's check
_JSON_NUL = re.compile(rb"(?<!\\)(?:\\\\)*\\u0000")         # \u0000 in a JSON body, not an escaped backslash
# board_currency_exponent, copied from the SQL: the fake does not borrow the code under test.
_EXPONENT = {**dict.fromkeys("BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX UYI VND VUV XAF XOF XPF".split(), 0),
             **dict.fromkeys("BHD IQD JOD KWD LYD OMR TND".split(), 3), **dict.fromkeys(("CLF", "UYW"), 4)}
SPEND_COLUMNS = ("source_id", "campaign_id", "campaign_name", "funnel", "day", "currency", "spend_minor",
                 "spend_usd_cents", "fx_source", "fx_rate", "impressions", "link_clicks", "platform_leads",
                 "pulled_at", "job_run_id")
# The columns PostgREST can select from these relations (a column outside them is a 400, as on PostgREST).
LEDGER_COLUMNS = ("id", "source_id", "external_id", "kind", "occurred_at", "occurred_on", "local_day",
                  "amount_minor", "currency", "amount_usd_cents", "fx_source", "fx_rate", "fee_usd_cents",
                  "is_estimate", "product", "quantity", "customer_email", "channel", "attribution", "click_id",
                  "order_ref", "via_platform", "source_event_id", "upload_id", "job_run_id", "raw", "created_at",
                  "updated_at")
BOARD_LEDGER_COLUMNS = ("id", "source_id", "external_id", "kind", "occurred_at", "occurred_on", "local_day",
                        "amount_minor", "currency", "amount_usd_cents", "fee_usd_cents", "is_estimate", "quantity",
                        "order_ref", "via_platform", "upload_id", "product", "customer_email", "channel",
                        "attribution")
REVENUE_DAILY_COLUMNS = ("local_day", "source_id", "channel", "sales", "units", "gross_usd_cents",
                         "refunds_usd_cents", "disputes_usd_cents", "net_usd_cents", "fees_usd_cents",
                         "unconverted_rows", "has_estimates")
CLICK_COLUMNS = ("id", "partner", "clicked_at", "local_day", "referrer_host", "destination", "utm", "import_key",
                 "created_at", "updated_at")
CLICK_INSERT_COLUMNS = ("id", "partner", "clicked_at", "referrer_host", "destination", "utm", "import_key")
_SELECTABLE = {"ledger_entries": LEDGER_COLUMNS, "board_ledger": BOARD_LEDGER_COLUMNS,
               "board_revenue_daily": REVENUE_DAILY_COLUMNS, "clicks": CLICK_COLUMNS}
_PARTNER = re.compile(r"[a-z0-9_-]{1,64}")                  # clicks.partner's check
_UUID_TEXT = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", re.I)   # board_ingest_ledger's click id test


class FakeSQLError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _ts(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _pg_ts(value: datetime | None) -> str | None:
    """A timestamptz as Postgres writes it into JSON (session time zone UTC):
    fractional seconds without trailing zeros, none when whole."""
    if value is None:
        return None
    text = value.astimezone(timezone.utc).isoformat()
    if "." in text:
        head, tail = text.split(".", 1)
        fraction = tail[:6].rstrip("0")
        text = f"{head}.{fraction}{tail[6:]}" if fraction else head + tail[6:]
    return text


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _known_zone(name: str) -> bool:
    """Whether Postgres would know the zone (Python's tz database stands in for
    it; Postgres also takes a few abbreviations, such as PST, that it does not)."""
    try:
        ZoneInfo(name)
        return True
    except (KeyError, ValueError, OSError):
        return False


def _round_half_away(value: Fraction) -> int:
    """Postgres round() on numeric: to the nearest integer, a half away from zero."""
    whole, rest = divmod(abs(value.numerator), value.denominator)
    whole += 1 if 2 * rest >= value.denominator else 0
    return whole if value >= 0 else -whole


def _fx_cents(minor: int, currency: str, rate: Decimal) -> int:
    """board_fill_fx's round(minor / 10^exponent * rate * 100): exact numeric
    arithmetic, then round half away from zero."""
    return _round_half_away(Fraction(minor, 10 ** _EXPONENT.get(currency, 2)) * Fraction(rate) * 100)


# ── jsonb_to_recordset and PostgREST's casts from JSON to a column type ──

def _text(value):
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value)


_SPECIAL_DAYS = {"yesterday": -1, "today": 0, "tomorrow": 1}


def _special_time(text: str, now: datetime | None) -> datetime | None:
    """Postgres's special date and time words, in the session time zone (UTC):
    'epoch', 'now', and midnight 'today', 'yesterday' or 'tomorrow'."""
    word = text.strip().lower()
    if word in ("infinity", "-infinity"):
        raise AssertionError("an infinite timestamp is not faked")
    if word == "epoch":
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if word != "now" and word not in _SPECIAL_DAYS:
        return None
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if word == "now":
        return now
    return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=_SPECIAL_DAYS[word])


def _timestamptz(value, now: datetime | None = None):
    """ISO 8601 or a special word; a time without an offset is UTC (the session's zone)."""
    if value is None:
        return None
    special = _special_time(str(value), now)
    if special is not None:
        return special
    try:
        return _ts(str(value))
    except ValueError:
        raise FakeSQLError("22007", f'invalid input syntax for type timestamp with time zone: "{value}"') from None


def _date_in(value, now: datetime | None = None):
    if value is None:
        return None
    special = _special_time(str(value), now)
    if special is not None:
        return special.date()
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise FakeSQLError("22007", f'invalid input syntax for type date: "{value}"') from None


def _integer(value, top: int = BIGINT_MAX, kind: str = "bigint"):
    """A JSON number or numeric string as a Postgres integer type: 12.0 is not one."""
    if value is None:
        return None
    if isinstance(value, str) and re.fullmatch(r"\s*[+-]?[0-9]+\s*", value):
        value = int(value)
    if not _is_int(value):
        raise FakeSQLError("22P02", f'invalid input syntax for type {kind}: "{_text(value)}"')
    if not -top - 1 <= value <= top:
        raise FakeSQLError("22003", f"value \"{value}\" is out of range for type {kind}")
    return value


def _numeric(value, scale: int = 10, precision: int = 20):
    """numeric(20,10): rounded to 10 places, half away from zero."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise FakeSQLError("22P02", f'invalid input syntax for type numeric: "{_text(value)}"')
    try:
        out = Decimal(str(value)).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise FakeSQLError("22P02", f'invalid input syntax for type numeric: "{value}"') from None
    if abs(out) >= Decimal(10) ** (precision - scale):
        raise FakeSQLError("22003", "numeric field overflow")
    return out


def _boolean(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "t", "f"):
        return value.strip().lower() in ("true", "t")
    raise FakeSQLError("22P02", f'invalid input syntax for type boolean: "{_text(value)}"')


def _text_array(value):
    if value is None:
        return None
    if not isinstance(value, list) or any(isinstance(v, (list, dict)) for v in value):
        raise FakeSQLError("22P02", f'malformed array literal: "{_text(value)}"')
    return [_text(v) for v in value]


def _before(a: datetime | None, b: datetime | None) -> bool:
    """`a` sorts strictly before `b` in `order by occurred_at` (nulls last)."""
    return a is not None and (b is None or a < b)


def _sorted_distinct(values: list) -> list:
    """array(select distinct u from unnest(..) u order by u): code-point order,
    which is Postgres's under the C collation (another collation can order
    punctuation differently; the set is the same)."""
    return sorted(set(values), key=lambda v: (v is None, v or ""))


def _violates(table: str, name: str) -> FakeSQLError:
    return FakeSQLError("23514", f'new row for relation "{table}" violates check constraint "{name}"')


def _not_null(table: str, row: dict, columns) -> None:
    for column in columns:
        if row.get(column) is None:
            raise FakeSQLError("23502", f'null value in column "{column}" of relation "{table}" '
                                        f"violates not-null constraint")


class FakeBoardDB:
    """PostgREST over the board's tables and functions, in memory. Answers
    errors the way PostgREST does: {"code", "message", "details"}, where
    details can quote a failing row (so the board must never pass it on).
    A call is one statement: when it fails, nothing it would have written is
    kept. Check constraints run in name order, as Postgres runs them.

    Tables a test may read or fill: sources, job_runs, webhook_events, ledger
    (ledger_entries; add_estimate puts a provisional KDP row there), leads
    (lead_events), ad_spend (ad_spend_daily), fx_rates (add_fx_rate) and
    clicks (by id). board_ingest_ledger keeps a row's click id only when it
    names a stored click (in any case), also with attribution 'none'; it keeps
    attribution 'click_id' only with a stored click and a channel, as the SQL
    does. No upload covers a day."""

    def __init__(self):
        self.clock = lambda: datetime.now(timezone.utc)
        self.max_rows = 1000                     # the API's row cap on one read (Supabase's db-max-rows)
        self.exact_counts = True                 # False: a server that ignores Prefer: count=exact
        self.clicks: dict[str, dict] = {}        # public.clicks, by id
        self.sources = {sid: {"id": sid, "kind": kind, "method": method, "display_name": name,
                              "account_ref": None, "day_tz": "America/New_York", "currency": None,
                              "enabled": True, "measured_from": None, "synced_through": None,
                              "last_ok_at": None, "last_error": None, "last_error_at": None}
                        for sid, kind, method, name in SEED_SOURCES}
        self.job_runs: dict[str, dict] = {}
        self.webhook_events: dict[tuple, dict] = {}
        self.ledger: dict[tuple, dict] = {}
        self.leads: dict[tuple, dict] = {}       # public.lead_events, by (source_id, external_id)
        self.ad_spend: dict[tuple, dict] = {}    # public.ad_spend_daily, by (source_id, campaign_id, day)
        self.fx_rates: dict[tuple, dict] = {}    # public.fx_rates, by (currency, day)
        self.calls: list[httpx.Request] = []
        self.down = False
        self.fail: dict[str, int] = {}          # "rpc/board_day" or a table -> HTTP status to answer

    # ── helpers for tests ──
    def rpc_calls(self, name: str) -> list[dict]:
        return [json.loads(c.content or b"{}") for c in self.calls if c.url.path == f"/rest/v1/rpc/{name}"]

    def runs(self, job: str) -> list[dict]:
        return sorted((r for r in self.job_runs.values() if r["job"] == job), key=lambda r: r["created_at"])

    def rows(self, source_id: str = "stripe") -> dict[str, dict]:
        return {ext: r for (sid, ext), r in self.ledger.items() if sid == source_id}

    def lead_rows(self, source_id: str | None = None) -> dict[str, dict]:
        """lead_events by external_id (of one source, or of all)."""
        return {ext: r for (sid, ext), r in self.leads.items() if source_id is None or sid == source_id}

    def spend_rows(self, source_id: str = "meta_ads") -> dict[tuple, dict]:
        """ad_spend_daily by (campaign_id, day as YYYY-MM-DD)."""
        return {(cid, d.isoformat()): r for (sid, cid, d), r in self.ad_spend.items() if sid == source_id}

    def add_fx_rate(self, currency: str, day, usd_per_unit) -> None:
        """One ECB rate: USD per 1 unit of `currency` on `day` (what fx_sync will write)."""
        d = date.fromisoformat(day) if isinstance(day, str) else day
        if not re.fullmatch(r"[A-Z]{3}", currency) or currency == "USD":
            raise FakeSQLError("23514", 'new row for relation "fx_rates" violates check constraint '
                                        '"fx_rates_currency_check"')
        rate = _numeric(usd_per_unit)
        if rate <= 0:
            raise _violates("fx_rates", "fx_rates_usd_per_unit_check")
        self.fx_rates[(currency, d)] = {"id": str(uuid.uuid4()), "currency": currency, "day": d,
                                        "usd_per_unit": rate, "source": "ecb"}

    def add_estimate(self, external_id: str, day: str, cents: int, product: str = "KDP royalties") -> None:
        """A provisional KDP royalty, as board_apply_upload writes one: a date
        (no time), USD, no processor fee (0), is_estimate true."""
        d = date.fromisoformat(day)
        self.ledger[("kdp", external_id)] = {
            "id": str(uuid.uuid4()), "source_id": "kdp", "external_id": external_id,
            "kind": "sale" if cents >= 0 else "refund", "occurred_at": None, "occurred_on": d, "local_day": d,
            "amount_minor": cents, "currency": "USD", "amount_usd_cents": cents, "fx_source": "identity",
            "fx_rate": None, "fee_usd_cents": 0, "is_estimate": True, "product": product, "quantity": 1,
            "customer_email": None, "channel": None, "attribution": "none", "click_id": None, "order_ref": None,
            "via_platform": None, "raw": {}, "job_run_id": None}

    def set_source(self, source_id: str = "stripe", **values) -> None:
        for k in ("synced_through", "last_ok_at", "last_error_at"):
            if k in values:
                values[k] = _ts(values[k])
        if isinstance(values.get("measured_from"), str):
            values["measured_from"] = date.fromisoformat(values["measured_from"])
        self.sources[source_id].update(values)

    # ── transport ──
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.down:
            raise httpx.ConnectError("fake Supabase is down", request=request)
        if (request.headers.get("apikey") != SERVICE
                or request.headers.get("authorization") != f"Bearer {SERVICE}"):
            return httpx.Response(401, json={"message": "service role required"})
        path = request.url.path.removeprefix("/rest/v1/")
        if path in self.fail:
            return httpx.Response(self.fail[path], json={"code": "XX000", "message": "injected failure",
                                                         "details": "Failing row contains (x@example.com)"})
        try:
            if _JSON_NUL.search(request.content or b""):
                raise FakeSQLError("22P05", "unsupported Unicode escape sequence")
            if path.startswith("rpc/"):
                fn = getattr(self, "_rpc_" + path[4:], None)
                args = json.loads(request.content or b"{}")
                try:
                    if fn is None:
                        raise TypeError
                    inspect.signature(fn).bind(**args)
                except TypeError:
                    return httpx.Response(404, json={"code": "PGRST202", "message": (
                        f"Could not find the function public.{path[4:]}({', '.join(sorted(args))}) "
                        "in the schema cache")})
                return httpx.Response(200, json=fn(**args))
            return self._table(request, path)
        except FakeSQLError as e:
            status = 409 if e.code in ("23505", "23503") else 500 if e.code == "21000" else 400
            return httpx.Response(status, json={"code": e.code, "message": e.message,
                                                "details": "Failing row contains (x@example.com)"})

    # ── tables ──
    def _tables(self) -> dict:
        return {"sources": self.sources, "job_runs": self.job_runs,
                "webhook_events": self.webhook_events, "ledger_entries": self.ledger,
                "lead_events": self.leads, "ad_spend_daily": self.ad_spend, "fx_rates": self.fx_rates,
                "clicks": self.clicks}

    def _views(self) -> dict:
        """The read-only views, computed when read."""
        return {"board_ledger": self.board_ledger, "board_revenue_daily": self.board_revenue_daily}

    @staticmethod
    def _typed(row_value, value: str):
        """The filter's text as the column's type, so it compares as Postgres
        compares (a date as a date, a timestamptz as an instant)."""
        if isinstance(row_value, datetime):
            return _ts(value)
        if isinstance(row_value, date):
            return date.fromisoformat(value)
        if _is_int(row_value):
            return int(value)
        return value

    @staticmethod
    def _cmp(row_value, op: str, value: str) -> bool:
        if op == "is":
            if value == "null":
                return row_value is None
            if value in ("true", "false"):               # IS TRUE / IS FALSE: a NULL is neither
                return isinstance(row_value, bool) and row_value == (value == "true")
            raise AssertionError(f"is.{value} is not faked")
        if isinstance(row_value, bool) and op in ("eq", "neq"):
            if value not in ("true", "false"):
                raise FakeSQLError("22P02", f'invalid input syntax for type boolean: "{value}"')
            return (row_value == (value == "true")) == (op == "eq")
        if op == "eq":
            return row_value is not None and str(row_value) == value
        if op == "neq":                          # SQL's <>: a NULL never matches
            return row_value is not None and str(row_value) != value
        if op == "in":
            return row_value is not None and str(row_value) in value.strip("()").split(",")
        if op in ("lt", "lte", "gt", "gte"):
            if row_value is None:
                return False
            a = row_value if isinstance(row_value, (date, int)) else str(row_value)
            b = FakeBoardDB._typed(row_value, value)
            return {"lt": a < b, "lte": a <= b, "gt": a > b, "gte": a >= b}[op]
        raise AssertionError(f"filter operator {op} is not faked")

    def _match(self, row: dict, filters: list[tuple[str, str]]) -> bool:
        for key, expr in filters:
            if key == "or":
                parts = re.findall(r'(\w+)\.(\w+)\.("[^"]*"|[^,()]+)', expr)
                if not any(self._cmp(row.get(f), op, v.strip('"')) for f, op, v in parts):
                    return False
                continue
            op, _, value = expr.partition(".")
            if op == "not":
                # PostgREST's not.<op> is SQL's NOT: NOT (NULL IN (...)) is NULL, so a NULL
                # never matches, except for not.is.null (IS NOT NULL).
                op, _, value = value.partition(".")
                cell = row.get(key)
                if op == "is" and self._cmp(cell, op, value):
                    return False
                if op != "is" and (cell is None or self._cmp(cell, op, value)):
                    return False
                continue
            if not self._cmp(row.get(key), op, value):
                return False
        return True

    @staticmethod
    def _ordered(rows: list[dict], order: str | None) -> list[dict]:
        """PostgREST's order=col[.asc|.desc][.nullsfirst|.nullslast],...: as
        Postgres sorts, NULLs last going up and first going down unless told."""
        for item in reversed(order.split(",") if order else []):
            column, *mods = item.split(".")
            desc = "desc" in mods
            nulls_first = "nullsfirst" in mods or (desc and "nullslast" not in mods)
            known = sorted((r for r in rows if r.get(column) is not None), key=lambda r: r[column], reverse=desc)
            unknown = [r for r in rows if r.get(column) is None]
            rows = unknown + known if nulls_first else known + unknown
        return rows

    def _check(self, table: str, row: dict) -> None:
        if table == "job_runs":
            if row["status"] not in ("running", "ok", "failed", "skipped"):
                raise FakeSQLError("23514", "violates check constraint job_runs_status")
            if (row["status"] == "running") != (row["finished_at"] is None):
                raise FakeSQLError("23514", 'violates check constraint "job_runs_finished"')
            if not isinstance(row["detail"], dict) or row["rows_written"] < 0:
                raise FakeSQLError("23514", "violates check constraint on job_runs")
        if table == "sources":
            currency = row.get("currency")
            if currency is not None and len(currency.rstrip(" ")) > 3:
                raise FakeSQLError("22001", "value too long for type character(3)")
            _not_null("sources", row, ("day_tz",))
            if currency is not None and not re.fullmatch(r"[A-Z]{3}", currency):
                raise _violates("sources", "sources_currency_check")
            if not _DAY_TZ.fullmatch(row["day_tz"]):
                raise _violates("sources", "sources_day_tz_check")
            if not _known_zone(row["day_tz"]):           # sources_day_tz_known: the cast raises
                raise FakeSQLError("22023", f'time zone "{row["day_tz"]}" not recognized')
            if (row["last_error"] is None) != (row["last_error_at"] is None):
                raise FakeSQLError("23514", 'violates check constraint "sources_error_pair"')
        if table == "webhook_events":
            if row["status"] not in ("received", "processed", "failed", "ignored"):
                raise FakeSQLError("23514", "violates check constraint webhook_events_status")
            if (row["status"] == "processed") != (row["processed_at"] is not None):
                raise FakeSQLError("23514", 'violates check constraint "webhook_events_processed"')
        if table == "ad_spend_daily":
            self._check_spend(row)

    @staticmethod
    def _out(value):
        """A column value as PostgREST writes it into JSON."""
        if isinstance(value, datetime):
            return _pg_ts(value)
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        return value

    def _table(self, request: httpx.Request, table: str) -> httpx.Response:
        view = self._views().get(table)
        if view is not None:
            if request.method != "GET":
                return httpx.Response(405, json={"code": "PGRST", "message": f"cannot write to the view {table}"})
            rows = dict(enumerate(view()))
        else:
            rows = self._tables().get(table)
        if rows is None:
            return httpx.Response(404, json={"code": "42P01", "message": f"relation {table} does not exist"})
        if request.method == "POST":
            return self._insert(request, table)
        params = list(request.url.params.multi_items())
        select = next((v for k, v in params if k == "select"), None)
        known = _SELECTABLE.get(table)
        for column in (select.split(",") if select and known else []):
            if column not in known:
                return httpx.Response(400, json={"code": "42703",
                                                 "message": f"column {table}.{column} does not exist"})
        filters = [(k, v) for k, v in params if k not in ("select", "limit", "order", "offset")]
        matched = [r for r in rows.values() if self._match(r, filters)]
        if request.method == "GET":
            total = len(matched)
            matched = self._ordered(matched, next((v for k, v in params if k == "order"), None))
            offset = int(next((v for k, v in params if k == "offset"), 0) or 0)
            exact = self.exact_counts and "count=exact" in request.headers.get("prefer", "")
            if exact and offset > total:                 # PostgREST: a range past the end of a counted read
                return httpx.Response(416, json={"code": "PGRST103", "message": "Requested range not satisfiable"},
                                      headers={"Content-Range": f"*/{total}"})
            matched = matched[offset:]
            limit = next((v for k, v in params if k == "limit"), None)
            if limit is not None:
                matched = matched[:int(limit)]
            matched = matched[:self.max_rows]          # the API never answers more than its cap
            columns = select.split(",") if select else known
            out = [{k: self._out(v) for k, v in r.items() if columns is None or k in columns} for r in matched]
            # PostgREST: Content-Range on every read; the total only with count=exact, and 206 when partial
            of = str(total) if exact else "*"
            headers = {"Content-Range": f"{offset}-{offset + len(out) - 1}/{of}" if out else f"*/{of}"}
            return httpx.Response(206 if exact and len(out) < total else 200, json=out, headers=headers)
        if request.method == "PATCH":
            body = json.loads(request.content)
            for k, v in body.items():
                if k in ("finished_at", "processed_at", "synced_through", "last_ok_at", "last_error_at",
                         "window_start", "window_end", "covered_until"):
                    body[k] = _ts(v)
                if k == "measured_from" and v is not None:
                    body[k] = date.fromisoformat(v)
            for r in matched:
                self._check(table, {**r, **body})
            for r in matched:
                r.update(body)
                if "updated_at" in r:                    # the board_touch_updated_at trigger
                    r["updated_at"] = self.clock()
            return httpx.Response(204)
        return httpx.Response(405)

    def _insert(self, request: httpx.Request, table: str) -> httpx.Response:
        """PostgREST's insert, for ad_spend_daily: a JSON object or an array of
        objects with the same keys, which are the columns written. With
        `Prefer: resolution=merge-duplicates` and on_conflict naming the
        table's unique key, a row already on the key gets those columns
        (ignore-duplicates leaves it); with no on_conflict the conflict target
        is the primary key, so a row already on (source_id, campaign_id, day)
        is a unique violation, as is any repeat without a resolution. One
        statement: one bad row writes nothing."""
        if table == "clicks":
            return self._insert_clicks(request)
        if table != "ad_spend_daily":
            return httpx.Response(405, json={"message": f"inserting into {table} is not faked"})
        try:
            body = json.loads(request.content or b"")
        except ValueError:
            return httpx.Response(400, json={"code": "PGRST102", "message": "Empty or invalid json"})
        items = body if isinstance(body, list) else [body]
        if not all(isinstance(x, dict) for x in items):
            return httpx.Response(400, json={"code": "PGRST102", "message": "Empty or invalid json"})
        columns = list(items[0]) if items else []
        if any(set(x) != set(columns) for x in items):
            return httpx.Response(400, json={"code": "PGRST102", "message": "All object keys must match"})
        for c in columns:
            if c not in SPEND_COLUMNS:
                return httpx.Response(400, json={"code": "PGRST204", "message": (
                    f"Could not find the '{c}' column of 'ad_spend_daily' in the schema cache")})
        prefer = {p.strip() for p in request.headers.get("prefer", "").split(",") if p.strip()}
        resolution = ("merge" if "resolution=merge-duplicates" in prefer
                      else "ignore" if "resolution=ignore-duplicates" in prefer else None)
        target = request.url.params.get("on_conflict")
        target_cols = {c.strip() for c in target.split(",")} if target else {"id"}
        if target and target_cols not in ({"source_id", "campaign_id", "day"}, {"id"}):
            raise FakeSQLError("42P10", "there is no unique or exclusion constraint matching the "
                                        "ON CONFLICT specification")
        on_key = resolution is not None and target_cols == {"source_id", "campaign_id", "day"}
        staged, touched, written = dict(self.ad_spend), set(), []
        for x in items:
            new = self._spend_row(x)
            key = (new["source_id"], new["campaign_id"], new["day"])
            old = staged.get(key)
            if old is None:
                staged[key] = new
            elif not on_key:
                raise FakeSQLError("23505", 'duplicate key value violates unique constraint "ad_spend_daily_once"')
            elif resolution == "ignore":
                continue
            elif key in touched:
                raise FakeSQLError("21000", "ON CONFLICT DO UPDATE command cannot affect row a second time")
            else:
                row = {**old, **{c: new[c] for c in columns}, "updated_at": self.clock()}
                self._check_spend(row)
                staged[key] = row
            touched.add(key)
            written.append(staged[key])
        for row in written:
            if row["source_id"] not in self.sources:
                raise FakeSQLError("23503", 'insert or update on table "ad_spend_daily" violates foreign key '
                                            'constraint "ad_spend_daily_source_id_fkey"')
            if row["job_run_id"] is not None and row["job_run_id"] not in self.job_runs:
                raise FakeSQLError("23503", 'insert or update on table "ad_spend_daily" violates foreign key '
                                            'constraint "ad_spend_daily_job_run_id_fkey"')
        self.ad_spend.clear()
        self.ad_spend.update(staged)
        if "return=representation" in prefer:
            return httpx.Response(201, json=[{k: self._out(v) for k, v in r.items()} for r in written])
        return httpx.Response(201)

    def _insert_clicks(self, request: httpx.Request) -> httpx.Response:
        """PostgREST's insert into clicks: a JSON object or an array of objects
        with the same keys. With on_conflict=import_key and `Prefer:
        resolution=ignore-duplicates` (ON CONFLICT (import_key) DO NOTHING) a
        row whose import_key is there already, or came earlier in the same
        call, is skipped; any other repeated key is a unique violation. With
        `return=representation`, the rows inserted (only those), in `select`'s
        columns. One statement: one bad row writes nothing."""
        try:
            body = json.loads(request.content or b"")
        except ValueError:
            return httpx.Response(400, json={"code": "PGRST102", "message": "Empty or invalid json"})
        items = body if isinstance(body, list) else [body]
        if not all(isinstance(x, dict) for x in items):
            return httpx.Response(400, json={"code": "PGRST102", "message": "Empty or invalid json"})
        columns = list(items[0]) if items else []
        if any(set(x) != set(columns) for x in items):
            return httpx.Response(400, json={"code": "PGRST102", "message": "All object keys must match"})
        for c in columns:
            if c not in CLICK_INSERT_COLUMNS:
                return httpx.Response(400, json={"code": "PGRST204", "message": (
                    f"Could not find the '{c}' column of 'clicks' in the schema cache")})
        prefer = {p.strip() for p in request.headers.get("prefer", "").split(",") if p.strip()}
        ignore = "resolution=ignore-duplicates" in prefer
        target = request.url.params.get("on_conflict")
        target_cols = {c.strip() for c in target.split(",")} if target else {"id"}
        if target_cols not in ({"import_key"}, {"id"}):
            raise FakeSQLError("42P10", "there is no unique or exclusion constraint matching the "
                                        "ON CONFLICT specification")
        if "resolution=merge-duplicates" in prefer:
            raise AssertionError("an upsert on clicks is not faked")
        staged, written = dict(self.clicks), []
        keys = {r["import_key"] for r in staged.values() if r["import_key"] is not None}
        for x in items:
            new = self._click_row(x)
            clash_id, clash_key = new["id"] in staged, new["import_key"] is not None and new["import_key"] in keys
            if (clash_id and ignore and target_cols == {"id"}) or (clash_key and ignore and target_cols == {"import_key"}):
                continue
            if clash_id:
                raise FakeSQLError("23505", 'duplicate key value violates unique constraint "clicks_pkey"')
            if clash_key:
                raise FakeSQLError("23505", 'duplicate key value violates unique constraint "clicks_import_once"')
            staged[new["id"]] = new
            written.append(new)
            if new["import_key"] is not None:
                keys.add(new["import_key"])
        self.clicks.clear()
        self.clicks.update(staged)
        if "return=representation" in prefer:
            select = request.url.params.get("select")
            cols = select.split(",") if select else CLICK_COLUMNS
            return httpx.Response(201, json=[{k: self._out(r[k]) for k in cols} for r in written])
        return httpx.Response(201)

    def _click_row(self, x: dict) -> dict:
        """One payload object as the clicks row Postgres would insert, with its checks."""
        now = self.clock()
        clicked = _timestamptz(x["clicked_at"], now) if "clicked_at" in x else now
        utm = x.get("utm", {}) if "utm" in x else {}
        row = {"id": self._uuid_arg(x["id"]) if "id" in x else str(uuid.uuid4()),
               "partner": _text(x.get("partner")), "clicked_at": clicked,
               "local_day": clicked.astimezone(NY).date() if clicked is not None else None,
               "referrer_host": _text(x.get("referrer_host")), "destination": _text(x.get("destination")),
               "utm": utm, "import_key": _text(x.get("import_key")), "created_at": now, "updated_at": now}
        _not_null("clicks", row, ("id", "partner", "clicked_at", "destination", "utm"))
        checks = (
            ("clicks_destination_check", 1 <= len(row["destination"]) <= 2048),
            ("clicks_partner_check", bool(_PARTNER.fullmatch(row["partner"]))),
            ("clicks_referrer_host_check", row["referrer_host"] is None or len(row["referrer_host"]) <= 255),
            ("clicks_utm_check", isinstance(row["utm"], dict)))
        for name, ok in checks:
            if not ok:
                raise _violates("clicks", name)
        return row

    def _spend_row(self, x: dict) -> dict:
        """One payload object as the row Postgres would insert: missing columns
        take their defaults; explicit nulls stay null."""
        now = self.clock()

        def given(column, default=None):
            return x[column] if column in x else default

        currency = _text(given("currency"))
        if currency is not None and len(currency.rstrip(" ")) > 3:
            raise FakeSQLError("22001", "value too long for type character(3)")
        row = {"id": str(uuid.uuid4()), "source_id": _text(given("source_id")),
               "campaign_id": _text(given("campaign_id")), "campaign_name": _text(given("campaign_name")),
               "funnel": _text(given("funnel")), "day": _date_in(given("day"), now),
               "currency": currency.rstrip(" ") if currency is not None else None,
               "spend_minor": _integer(given("spend_minor")),
               "spend_usd_cents": _integer(given("spend_usd_cents")), "fx_source": _text(given("fx_source")),
               "fx_rate": _numeric(given("fx_rate")), "impressions": _integer(given("impressions", 0)),
               "link_clicks": _integer(given("link_clicks", 0)),
               "platform_leads": _integer(given("platform_leads"), INT_MAX, "integer"),
               "pulled_at": _timestamptz(given("pulled_at"), now) if "pulled_at" in x else now,
               "job_run_id": self._uuid_arg(given("job_run_id")), "created_at": now, "updated_at": now}
        self._check_spend(row)
        return row

    @staticmethod
    def _check_spend(r: dict) -> None:
        t = "ad_spend_daily"
        _not_null(t, r, ("source_id", "campaign_id", "day", "currency", "spend_minor", "impressions",
                         "link_clicks", "pulled_at"))
        usd, fx, rate = r["spend_usd_cents"], r["fx_source"], r["fx_rate"]
        checks = (
            ("ad_spend_daily_campaign_id_check", 1 <= len(r["campaign_id"]) <= 64),
            ("ad_spend_daily_currency_check", bool(re.fullmatch(r"[A-Z]{3}", r["currency"]))),
            ("ad_spend_daily_ecb_has_rate", fx != "ecb" or rate is not None),
            ("ad_spend_daily_funnel_check", r["funnel"] is None or bool(_LABEL.fullmatch(r["funnel"]))),
            ("ad_spend_daily_fx_rate_check", rate is None or rate > 0),
            ("ad_spend_daily_fx_source_check", fx in (None, "identity", "ecb")),
            # NULL passes a check: only a false expression violates it
            ("ad_spend_daily_identity", fx != "identity" or not (
                r["currency"] != "USD" or (usd is not None and usd != r["spend_minor"]))),
            ("ad_spend_daily_impressions_check", r["impressions"] >= 0),
            ("ad_spend_daily_link_clicks_check", r["link_clicks"] >= 0),
            ("ad_spend_daily_platform_leads_check", r["platform_leads"] is None or r["platform_leads"] >= 0),
            ("ad_spend_daily_rate_needs_ecb", rate is None or fx == "ecb"),
            ("ad_spend_daily_spend_minor_check", r["spend_minor"] >= 0),
            ("ad_spend_daily_spend_usd_cents_check", usd is None or usd >= 0),
            ("ad_spend_daily_usd_has_source", (usd is None) == (fx is None)))
        for name, ok in checks:
            if not ok:
                raise _violates(t, name)

    @staticmethod
    def _uuid_arg(value) -> str | None:
        """A uuid parameter or column: canonical text, 22P02 when malformed."""
        if value is None:
            return None
        try:
            return str(uuid.UUID(str(value)))
        except ValueError:
            raise FakeSQLError("22P02", f'invalid input syntax for type uuid: "{value}"') from None

    @staticmethod
    def _int_arg(value):
        return _integer(value, INT_MAX, "integer")

    # ── functions ──
    def _rpc_board_claim_run(self, p_job, p_run_key, p_trigger_kind="schedule", p_source_id=None):
        now = self.clock()
        for r in self.job_runs.values():
            if r["job"] == p_job and r["status"] == "running" and r["started_at"] < now - timedelta(minutes=30):
                r.update(status="failed", finished_at=now,
                         error=r["error"] or "abandoned: still running after 30 minutes")
        running = any(r["job"] == p_job and r["status"] == "running" for r in self.job_runs.values())
        same = next((r for r in self.job_runs.values() if r["job"] == p_job and r["run_key"] == p_run_key), None)
        if same is None:
            if running:
                return None                     # job_runs_one_running_uq
            rid = str(uuid.uuid4())
            self.job_runs[rid] = {"id": rid, "job": p_job, "run_key": p_run_key, "trigger_kind": p_trigger_kind,
                                  "source_id": p_source_id, "status": "running", "started_at": now,
                                  "finished_at": None, "attempts": 1, "error": None, "detail": {},
                                  "rows_written": 0, "window_start": None, "window_end": None,
                                  "covered_until": None, "created_at": now}
            return rid
        if same["status"] == "failed" and not running:
            same.update(status="running", started_at=now, finished_at=None, error=None,
                        trigger_kind=p_trigger_kind, attempts=same["attempts"] + 1)
            return same["id"]
        return None

    def _rpc_board_claim_webhook(self, p_source_id, p_event_id, p_event_type, p_livemode):
        now, key = self.clock(), (p_source_id, p_event_id)
        row = self.webhook_events.get(key)
        if row is None:
            status = "ignored" if p_livemode is False else "received"
            self.webhook_events[key] = {"source_id": p_source_id, "event_id": p_event_id,
                                        "event_type": p_event_type, "livemode": p_livemode, "status": status,
                                        "attempts": 1, "error": None, "received_at": now, "processed_at": None}
            return "done" if status == "ignored" else "run"
        if row["status"] == "failed" or (row["status"] == "received"
                                         and row["received_at"] < now - timedelta(minutes=10)):
            row.update(status="received", attempts=row["attempts"] + 1, error=None, received_at=now)
            return "run"
        return "busy" if row["status"] == "received" else "done"

    def _rpc_board_ingest_ledger(self, p_source_id, p_job_run_id, p_rows):
        src = self.sources.get(p_source_id)
        if src is None or src["method"] not in ("api", "manual"):
            raise FakeSQLError("P0001", f"board_ingest_ledger: {p_source_id} is not an API or manual source")
        parsed: dict[str, dict] = {}
        for x in sorted(p_rows, key=lambda r: str(r.get("external_id"))):
            parsed.setdefault(x.get("external_id"), x)
        incoming = [self._ledger_row(p_source_id, p_job_run_id, x) for x in parsed.values()]
        existing = {r["external_id"] for r in incoming if (p_source_id, r["external_id"]) in self.ledger}
        mismatches = 0
        for new in incoming:
            key = (p_source_id, new["external_id"])
            old = self.ledger.get(key)
            if old is None:
                self.ledger[key] = new
                continue
            if any(old[k] != new[k] for k in ("kind", "amount_minor", "currency", "occurred_at", "occurred_on")):
                mismatches += 1
            labelled = new["attribution"] != "none"
            old.update(product=new["product"] or old["product"], quantity=new["quantity"] or old["quantity"],
                       customer_email=new["customer_email"] or old["customer_email"],
                       channel=new["channel"] if labelled else old["channel"],
                       attribution=new["attribution"] if labelled else old["attribution"],
                       click_id=new["click_id"] if labelled else old["click_id"],
                       order_ref=old["order_ref"] or new["order_ref"],
                       via_platform=new["via_platform"] or old["via_platform"],
                       fee_usd_cents=old["fee_usd_cents"] if old["fee_usd_cents"] is not None else new["fee_usd_cents"])
        return [{"received": len(incoming), "inserted": len(incoming) - len(existing),
                 "relabelled": len(existing), "money_mismatches": mismatches}]

    def _ledger_row(self, source_id, run_id, x: dict) -> dict:
        """One p_rows element as the SQL would write it, with its checks. A
        click id is kept when it is a uuid (any case) of a stored click, also
        with attribution 'none'; 'click_id' stays only with that click and a
        channel. Labels never fail the row."""
        for k in ("amount_minor", "amount_usd_cents", "fee_usd_cents", "quantity"):
            if x.get(k) is not None and not _is_int(x[k]):
                raise FakeSQLError("22P02", f'invalid input syntax for type bigint: "{x[k]}"')
        kind, minor = x.get("kind"), x.get("amount_minor")
        currency = str(x.get("currency") or "").upper()
        usd, fx = x.get("amount_usd_cents"), x.get("fx_source")
        if usd is None and fx is None and currency == "USD":
            usd, fx = minor, "identity"
        email = str(x.get("customer_email") or "").strip().lower()
        email = email if re.fullmatch(r".+@.+", email) and "@" in email[1:-1] else None
        raw_channel = str(x.get("channel") or "").strip().lower()
        channel = (None if not raw_channel else raw_channel if re.fullmatch(r"[a-z0-9_]{1,32}", raw_channel)
                   else "other")
        attribution = x.get("attribution") or "none"
        raw_click = x.get("click_id")
        click_id = None
        if isinstance(raw_click, str) and _UUID_TEXT.fullmatch(raw_click):
            click_id = raw_click.lower() if raw_click.lower() in self.clicks else None   # left join public.clicks
        if attribution == "none" or channel is None or (attribution == "click_id" and click_id is None):
            attribution, channel = "none", None
        row = {"id": str(uuid.uuid4()), "source_id": source_id, "external_id": x.get("external_id"), "kind": kind,
               "occurred_at": _ts(x.get("occurred_at")),
               "occurred_on": date.fromisoformat(x["occurred_on"]) if x.get("occurred_on") else None,
               "amount_minor": minor, "currency": currency, "amount_usd_cents": usd, "fx_source": fx,
               "fx_rate": _numeric(x.get("fx_rate")),
               "fee_usd_cents": x.get("fee_usd_cents"), "is_estimate": bool(x.get("is_estimate")),
               "product": (str(x.get("product")).strip() or None) if x.get("product") else None,
               "quantity": x.get("quantity"), "customer_email": email, "channel": channel,
               "attribution": attribution, "click_id": click_id, "order_ref": x.get("order_ref"),
               "via_platform": x.get("via_platform"), "raw": x.get("raw") or {}, "job_run_id": run_id}
        if not row["external_id"] or minor is None or not re.fullmatch(r"[A-Z]{3}", currency):
            raise FakeSQLError("23502", "null value or bad currency in ledger_entries")
        if kind not in ("sale", "refund", "dispute", "dispute_reversal", "fee", "adjustment"):
            raise FakeSQLError("23514", 'violates check constraint "ledger_entries_kind_check"')
        if (row["occurred_at"] is None) == (row["occurred_on"] is None):
            raise FakeSQLError("23514", 'violates check constraint "ledger_entries_one_time"')
        # the generated column: the New York day of occurred_at, or occurred_on
        row["local_day"] = row["occurred_at"].astimezone(NY).date() if row["occurred_at"] else row["occurred_on"]
        if kind in ("sale", "dispute_reversal") and (minor < 0 or (usd or 0) < 0) or \
                kind in ("refund", "dispute", "fee") and (minor > 0 or (usd or 0) > 0):
            raise FakeSQLError("23514", 'violates check constraint "ledger_entries_sign"')
        if (usd is None) != (fx is None) or fx not in (None, "identity", "stripe", "ecb"):
            raise FakeSQLError("23514", 'violates check constraint "ledger_entries_usd_has_source"')
        if fx == "identity" and (currency != "USD" or usd != minor):
            raise FakeSQLError("23514", 'violates check constraint "ledger_entries_identity"')
        return row

    def _rpc_board_ingest_leads(self, p_source_id, p_job_run_id, p_rows):
        """board_ingest_leads: one row per external_id per call, the earliest
        (a tie goes to the first sent; Postgres picks either), labels
        normalised; a key already there keeps its earliest time, gains a known
        channel where its own is 'unknown', unions its tags (sorted, distinct),
        fills a missing email, funnel or campaign, and ORs is_auto_reply. Kind,
        raw and job_run_id stay as first written."""
        run_id = self._uuid_arg(p_job_run_id)            # parameters are cast before the body runs
        src = self.sources.get(p_source_id)
        if src is None or src["method"] not in ("api", "manual"):
            raise FakeSQLError("P0001", f"board_ingest_leads: {p_source_id} is not an API or manual source")
        if p_rows is not None and not isinstance(p_rows, list):
            raise FakeSQLError("22023", "cannot call jsonb_to_recordset on a non-array")
        best: dict = {}
        for x in p_rows or []:
            if not isinstance(x, dict):
                raise FakeSQLError("22023", "argument of jsonb_to_recordset must be an array of objects")
            x = {"external_id": _text(x.get("external_id")), "kind": _text(x.get("kind")),
                 "occurred_at": _timestamptz(x.get("occurred_at"), self.clock()), "email": _text(x.get("email")),
                 "funnel": _text(x.get("funnel")), "channel": _text(x.get("channel")),
                 "campaign_ref": _text(x.get("campaign_ref")), "tags": _text_array(x.get("tags")),
                 "is_auto_reply": _boolean(x.get("is_auto_reply")), "raw": x.get("raw")}
            held = best.get(x["external_id"])
            if held is None or _before(x["occurred_at"], held["occurred_at"]):
                best[x["external_id"]] = x
        incoming = [self._lead_row(p_source_id, run_id, x) for x in best.values()]
        existing = sum(1 for r in incoming if (p_source_id, r["external_id"]) in self.leads)
        staged, inserted_any = {}, False
        for new in incoming:
            key = (p_source_id, new["external_id"])
            old = self.leads.get(key)
            if old is None:
                staged[key], inserted_any = new, True
                continue
            row = {**old, "occurred_at": min(old["occurred_at"], new["occurred_at"]),
                   "channel": new["channel"] if old["channel"] == "unknown" else old["channel"],
                   "tags": _sorted_distinct(old["tags"] + new["tags"]),
                   "email": old["email"] if old["email"] is not None else new["email"],
                   "funnel": old["funnel"] if old["funnel"] is not None else new["funnel"],
                   "campaign_ref": old["campaign_ref"] if old["campaign_ref"] is not None else new["campaign_ref"],
                   "is_auto_reply": old["is_auto_reply"] or new["is_auto_reply"], "updated_at": self.clock()}
            row["local_day"] = row["occurred_at"].astimezone(NY).date()
            self._check_lead(row)
            staged[key] = row
        if inserted_any and run_id is not None and run_id not in self.job_runs:
            raise FakeSQLError("23503", 'insert or update on table "lead_events" violates foreign key '
                                        'constraint "lead_events_job_run_id_fkey"')
        self.leads.update(staged)
        return [{"received": len(incoming), "inserted": len(incoming) - existing, "relabelled": existing}]

    def _lead_row(self, source_id: str, run_id, x: dict) -> dict:
        """One kept p_rows element as the row board_ingest_leads would insert."""
        email = x["email"].strip(" ").lower() if x["email"] is not None else None
        channel = x["channel"].strip(" ") if x["channel"] is not None else ""
        if not channel:
            channel = "unknown"
        else:
            channel = channel.lower() if _LABEL.fullmatch(channel.lower()) else "other"
        now = self.clock()
        row = {"id": str(uuid.uuid4()), "source_id": source_id, "external_id": x["external_id"],
               "kind": x["kind"], "occurred_at": x["occurred_at"],
               "local_day": x["occurred_at"].astimezone(NY).date() if x["occurred_at"] else None,
               "email": email if email is not None and "@" in email[1:-1] else None,
               "funnel": (x["funnel"].strip(" ").lower() or None) if x["funnel"] is not None else None,
               "channel": channel, "campaign_ref": x["campaign_ref"],
               "tags": [t.lower() if t is not None else None for t in x["tags"] or []],
               "is_auto_reply": bool(x["is_auto_reply"]), "job_run_id": run_id,
               "raw": x["raw"] if x["raw"] is not None else {}, "created_at": now, "updated_at": now}
        self._check_lead(row)
        return row

    @staticmethod
    def _check_lead(r: dict) -> None:
        t = "lead_events"
        _not_null(t, r, ("external_id", "kind", "occurred_at"))
        checks = (
            ("lead_events_auto_reply_is_reply", r["kind"] == "reply" or not r["is_auto_reply"]),
            ("lead_events_channel_check", bool(_LABEL.fullmatch(r["channel"]))),
            ("lead_events_email_check", r["email"] is None or (r["email"] == r["email"].strip(" ").lower()
                                                               and "@" in r["email"][1:-1])),
            ("lead_events_external_id_check", 1 <= len(r["external_id"]) <= 255),
            ("lead_events_funnel_check", r["funnel"] is None or bool(_LABEL.fullmatch(r["funnel"]))),
            ("lead_events_kind_check", r["kind"] in ("optin", "reply")),
            ("lead_events_raw_check", isinstance(r["raw"], dict)))
        for name, ok in checks:
            if not ok:
                raise _violates(t, name)

    def _rpc_board_fill_fx(self):
        """board_fill_fx: USD from the ECB rate on or before the row's day, at
        most 6 days back; never for a Stripe row."""
        def rate(currency, day):
            found = [r for (c, d), r in self.fx_rates.items() if c == currency and day - timedelta(days=7) < d <= day]
            return max(found, key=lambda r: r["day"])["usd_per_unit"] if found else None

        converted = 0
        for r in self.ledger.values():
            src = self.sources.get(r["source_id"])
            if r["amount_usd_cents"] is not None or r["currency"] == "USD" or not src or src["kind"] == "stripe":
                continue
            k = rate(r["currency"], r["occurred_at"].astimezone(NY).date() if r["occurred_at"] else r["occurred_on"])
            if k is not None:
                r.update(amount_usd_cents=_fx_cents(r["amount_minor"], r["currency"], k), fx_source="ecb", fx_rate=k)
                converted += 1
        for a in self.ad_spend.values():
            if a["spend_usd_cents"] is not None or a["currency"] == "USD":
                continue
            k = rate(a["currency"], a["day"])
            if k is not None:
                a.update(spend_usd_cents=_fx_cents(a["spend_minor"], a["currency"], k), fx_source="ecb", fx_rate=k,
                         updated_at=self.clock())
                converted += 1
        return converted

    def _state(self, s: dict, day: date) -> str:
        if not s["enabled"]:
            return "not_connected"
        if s["method"] == "manual":
            return "final"
        if s["method"] == "upload":
            return "not_connected"                  # no uploads in this fake
        if s["measured_from"] is None or day < s["measured_from"]:
            return "not_connected"
        end = datetime.combine(day + timedelta(days=1), time(0), ZoneInfo(s["day_tz"]))
        return "final" if s["synced_through"] is not None and s["synced_through"] >= end else "partial"

    def _first_touch(self, email, at):
        """board_ledger's lead match: the channel of the buyer's first opt-in or
        reply with a known channel, at or before the sale (no auto-replies)."""
        if email is None or at is None:
            return None
        touches = [l for l in self.leads.values() if l["email"] == email and l["occurred_at"] <= at
                   and not l["is_auto_reply"] and l["channel"] != "unknown"]
        return min(touches, key=lambda l: l["occurred_at"])["channel"] if touches else None

    def board_ledger(self) -> list[dict]:
        """public.board_ledger: a refund or dispute takes its sale's labels; a
        row with no stored channel takes the buyer's first lead touch
        ('lead_email')."""
        out = []
        for r in self.ledger.values():
            sale = None
            if r["kind"] != "sale" and r["order_ref"]:
                sales = [x for x in self.ledger.values() if x["source_id"] == r["source_id"]
                         and x["order_ref"] == r["order_ref"] and x["kind"] == "sale"]
                sale = min(sales, key=lambda x: x["occurred_at"]) if sales else None
            s = sale or {}
            local_day = r["occurred_at"].astimezone(NY).date() if r["occurred_at"] else r["occurred_on"]
            email = r["customer_email"] or s.get("customer_email")
            touch = self._first_touch(email, s.get("occurred_at") or r["occurred_at"])
            channel = s.get("channel") or r["channel"] or touch or "unattributed"
            attribution = (s["attribution"] if s.get("channel") else r["attribution"] if r["channel"]
                           else "lead_email" if touch else "none")
            out.append({**r, "local_day": local_day, "product": r["product"] or s.get("product"),
                        "customer_email": email, "channel": channel, "attribution": attribution})
        return out

    def board_revenue_daily(self) -> list[dict]:
        """public.board_revenue_daily: board_ledger grouped by New York day,
        source and channel, as the SQL sums it. Net is the money kinds' USD;
        fees are the known fees minus the fee rows' amounts; rows without USD
        are left out of the sums and counted; has_estimates is any estimate."""
        groups: dict = {}
        for r in self.board_ledger():
            g = groups.setdefault((r["local_day"], r["source_id"], r["channel"]), {
                "local_day": r["local_day"], "source_id": r["source_id"], "channel": r["channel"], "sales": 0,
                "units": 0, "gross_usd_cents": 0, "refunds_usd_cents": 0, "disputes_usd_cents": 0,
                "net_usd_cents": 0, "fees_usd_cents": 0, "unconverted_rows": 0, "has_estimates": False})
            usd = r["amount_usd_cents"]
            if r["kind"] == "sale":
                g["sales"] += 1
                g["units"] += r["quantity"] if r["quantity"] is not None else 1
                g["gross_usd_cents"] += usd or 0
            if r["kind"] == "refund":
                g["refunds_usd_cents"] -= usd or 0
            if r["kind"] in ("dispute", "dispute_reversal"):
                g["disputes_usd_cents"] -= usd or 0
            if r["kind"] in MONEY_KINDS:
                g["net_usd_cents"] += usd or 0
            g["fees_usd_cents"] += r["fee_usd_cents"] or 0
            if r["kind"] == "fee":
                g["fees_usd_cents"] -= usd or 0
            g["unconverted_rows"] += usd is None
            g["has_estimates"] = g["has_estimates"] or bool(r["is_estimate"])
        return list(groups.values())

    def _cpl(self, day: date, p_days, p_stop, lookback: int = 30) -> dict:
        """board_cpl(day, p_days, p_stop): the stop rule over the last p_days
        days with Toodle spend within `lookback` days. A NULL setting is
        Postgres's NULL: no limit, and no comparison holds."""
        per_day: dict = {}
        for a in self.ad_spend.values():
            if a["funnel"] == "toodle" and day - timedelta(days=lookback - 1) <= a["day"] <= day:
                d = per_day.setdefault(a["day"], {"usd": [], "unconverted": 0, "minor": 0})
                d["minor"] += a["spend_minor"]
                if a["spend_usd_cents"] is None:
                    d["unconverted"] += 1
                else:
                    d["usd"].append(a["spend_usd_cents"])
        sd = sorted(((d, v) for d, v in per_day.items() if v["minor"] > 0), key=lambda p: p[0], reverse=True)
        if p_days is not None:
            if p_days < 0:
                raise FakeSQLError("2201W", "LIMIT must not be negative")
            sd = sd[:p_days]
        days = {d for d, _ in sd}
        spend = sum(sum(v["usd"]) for _, v in sd if v["usd"])
        unconverted = sum(v["unconverted"] for _, v in sd)
        optins = [l for l in self.leads.values()
                  if l["kind"] == "optin" and l["funnel"] == "toodle" and l["local_day"] in days]
        meta, everyone = sum(1 for l in optins if l["channel"] == "meta"), len(optins)
        if not sd:
            verdict = "no_spend"
        elif unconverted > 0:
            verdict = "check_currency"
        elif p_days is not None and len(sd) < p_days:
            verdict = "collecting"
        elif meta == 0 and everyone > 0:
            verdict = "check_tags"
        elif meta == 0 and p_stop is not None and spend > p_stop:
            verdict = "stop"
        elif meta == 0:
            verdict = "collecting"
        elif p_stop is not None and Fraction(spend, meta) > p_stop:
            verdict = "stop"
        else:
            verdict = "ok"
        return {"spend_days": len(sd), "first_day": min(days).isoformat() if days else None,
                "last_day": max(days).isoformat() if days else None, "spend_usd_cents": spend,
                "unconverted_spend_rows": unconverted, "meta_optins": meta, "toodle_optins": everyone,
                "cpl_meta_usd_cents": _round_half_away(Fraction(spend, meta)) if meta else None,
                "cpl_all_usd_cents": _round_half_away(Fraction(spend, everyone)) if everyone else None,
                "stop_above_cents": p_stop, "verdict": verdict}

    def _rpc_board_day(self, p_day=None, p_cpl_days=5, p_cpl_stop_cents=500):
        day = _date_in(p_day, self.clock()) if p_day else self.clock().astimezone(NY).date() - timedelta(days=1)
        cpl_days, cpl_stop = self._int_arg(p_cpl_days), self._int_arg(p_cpl_stop_cents)
        # In UTC: Python ignores the offsets when both sides share one tzinfo.
        starts = datetime.combine(day, time(0), NY).astimezone(timezone.utc)
        ends = datetime.combine(day + timedelta(days=1), time(0), NY).astimezone(timezone.utc)
        led = [r for r in self.board_ledger() if r["local_day"] == day]
        money = [r for r in led if r["kind"] in MONEY_KINDS]

        def usd_sum(rows):
            return sum(r["amount_usd_cents"] for r in rows if r["amount_usd_cents"] is not None)

        def by(key):
            out: dict = {}
            for r in money:
                out[r[key]] = out.get(r[key], 0) + (r["amount_usd_cents"] or 0)
            return out

        def mask(email):
            return None if email is None else email[0] + "***" + email[email.index("@"):]

        def person(lead):
            return lead["email"] if lead["email"] is not None else lead["external_id"]

        products: dict = {}
        for r in money:
            p = products.setdefault((r["source_id"], r["product"] or "(no product name)"),
                                    {"source_id": r["source_id"], "product": r["product"] or "(no product name)",
                                     "sales": 0, "units": 0, "net_usd_cents": 0, "estimate": False})
            if r["kind"] == "sale":
                p["sales"] += 1
                p["units"] += r["quantity"] or 1
            p["net_usd_cents"] += r["amount_usd_cents"] or 0
        far = datetime.max.replace(tzinfo=timezone.utc)
        optins = [l for l in self.leads.values()
                  if l["kind"] == "optin" and l["funnel"] == "toodle" and l["local_day"] == day]
        replies = [l for l in self.leads.values() if l["kind"] == "reply" and l["funnel"] == "siteboost"
                   and day - timedelta(days=6) <= l["local_day"] <= day]
        spend = [a for a in self.ad_spend.values() if a["day"] == day]
        toodle = [a for a in spend if a["funnel"] == "toodle"]
        by_optin_channel: dict = {}
        for l in optins:
            by_optin_channel[l["channel"]] = by_optin_channel.get(l["channel"], 0) + 1
        return {
            "day": day.isoformat(), "tz": "America/New_York",
            "starts_at": _pg_ts(starts), "ends_at": _pg_ts(ends),
            "hours_in_day": int((ends - starts).total_seconds() // 3600),
            "sources": [{"id": s["id"], "kind": s["kind"], "method": s["method"], "name": s["display_name"],
                         "state": self._state(s, day), "day_tz": s["day_tz"],
                         "measured_from": s["measured_from"].isoformat() if s["measured_from"] else None,
                         "synced_through": _pg_ts(s["synced_through"]), "last_ok_at": _pg_ts(s["last_ok_at"]),
                         "last_error": (s["last_error"] or None) and s["last_error"][:300],
                         "last_error_at": _pg_ts(s["last_error_at"])}
                        for s in sorted(self.sources.values(), key=lambda s: s["id"])],
            "revenue": {"net_usd_cents": usd_sum(money),
                        "gross_usd_cents": usd_sum([r for r in money if r["kind"] == "sale"]),
                        "refunds_usd_cents": -usd_sum([r for r in money if r["kind"] == "refund"]),
                        "disputes_usd_cents": -usd_sum([r for r in money
                                                        if r["kind"] in ("dispute", "dispute_reversal")]),
                        "attributed_usd_cents": usd_sum([r for r in money if r["channel"] != "unattributed"]),
                        "unconverted_rows": sum(1 for r in money if r["amount_usd_cents"] is None),
                        "has_estimates": any(r["is_estimate"] for r in money)},
            "fees": {"fees_usd_cents": sum(r["fee_usd_cents"] or 0 for r in led)
                                       - usd_sum([r for r in led if r["kind"] == "fee"]),
                     "unknown_fee_rows": sum(1 for r in led if r["fee_usd_cents"] is None
                                             and r["kind"] in ("sale", "refund"))},
            "by_source": by("source_id"), "by_channel": by("channel"),
            "products": sorted(products.values(), key=lambda p: (-p["net_usd_cents"], p["product"])),
            "sales": [{"at": _pg_ts(r["occurred_at"]),
                       "on": r["occurred_on"].isoformat() if r["occurred_on"] else None,
                       "source": r["source_id"], "kind": r["kind"], "product": r["product"],
                       "amount_minor": r["amount_minor"], "currency": r["currency"],
                       "amount_usd_cents": r["amount_usd_cents"], "channel": r["channel"],
                       "attribution": r["attribution"], "estimate": r["is_estimate"], "via": r["via_platform"],
                       "buyer": mask(r["customer_email"])}
                      for r in sorted(money, key=lambda r: (r["occurred_at"] or far, r["source_id"],
                                                            r["external_id"]))],
            "optins": {"total": len(optins), "by_channel": by_optin_channel},
            "replies": {"people": len({person(l) for l in replies if not l["is_auto_reply"] and l["local_day"] == day}),
                        "auto_replies": sum(1 for l in replies if l["is_auto_reply"] and l["local_day"] == day),
                        "people_7d": len({person(l) for l in replies if not l["is_auto_reply"]})},
            "spend": {"toodle_usd_cents": sum(a["spend_usd_cents"] or 0 for a in toodle),
                      "all_usd_cents": sum(a["spend_usd_cents"] or 0 for a in spend),
                      "toodle_link_clicks": sum(a["link_clicks"] for a in toodle),
                      "impressions": sum(a["impressions"] for a in spend),
                      "unconverted_rows": sum(1 for a in spend if a["spend_usd_cents"] is None),
                      "last_pulled_at": _pg_ts(max(a["pulled_at"] for a in spend)) if spend else None},
            "cpl": self._cpl(day, cpl_days, cpl_stop),
            "kdp": {"covers_day": False, "recent_uploads": []},           # no uploads in this fake
        }


class FakeGoals:
    """core.goal_tracker.GoalTracker.get() in a board test. An ok Stripe sync
    and a manual entry move the monthly revenue goal (core.revenue); the real
    tracker writes data/goals.json under the working directory and can send a
    Telegram message, which a test must never do. Updates are kept here."""

    def __init__(self):
        self.updates: list[tuple] = []
        self._goals: dict = {}

    def update(self, goal_key, value):
        self.updates.append((goal_key, value))


def install_board(monkeypatch) -> FakeBoardDB:
    """Point core.board.ledger at a fresh FakeBoardDB (same URL and service key
    as install(), which a test may call too for sign-in), and GoalTracker at
    db.goals, a FakeGoals."""
    from core import goal_tracker
    from core.board import ledger
    db = FakeBoardDB()
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", SERVICE)
    monkeypatch.setattr(ledger, "_transport", httpx.MockTransport(db.handler))
    db.goals = FakeGoals()
    monkeypatch.setattr(goal_tracker.GoalTracker, "get", classmethod(lambda cls: db.goals))
    return db


# ═══ Stripe's API ═══════════════════════════════════════════════════════════

STRIPE_KEY = "rk_live_FAKEboardRead1"      # fake, and too short to pass for a real key


def unix(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def charge_bt(txn, charge, cents, at, fee, *, payment_intent=None, email=None, currency="usd",
              settled=None, exchange_rate=None, livemode=True, settled_currency="usd", **charge_fields):
    """A charge's balance transaction, its charge expanded."""
    amount = cents if settled is None else settled
    return {"id": txn, "object": "balance_transaction", "type": "charge", "reporting_category": "charge",
            "amount": amount, "currency": settled_currency, "fee": fee, "net": amount - fee,
            "created": unix(at), "status": "available", "exchange_rate": exchange_rate,
            "source": {"id": charge, "object": "charge", "amount": cents, "amount_captured": cents,
                       "currency": currency, "payment_intent": payment_intent, "livemode": livemode,
                       "billing_details": {"email": email}, "metadata": {}, **charge_fields}}


def refund_bt(txn, refund, charge, cents, at, fee=0, kind="refund"):
    return {"id": txn, "object": "balance_transaction", "type": kind, "reporting_category": "refund",
            "amount": -cents, "currency": "usd", "fee": fee, "net": -cents - fee, "created": unix(at),
            "status": "available",
            "source": {"id": refund, "object": "refund", "amount": cents, "currency": "usd", "charge": charge}}


def dispute_bt(txn, dispute, charge, cents, at, fee, won=False):
    amount = cents if won else -cents
    return {"id": txn, "object": "balance_transaction", "type": "adjustment",
            "reporting_category": "dispute_reversal" if won else "dispute", "amount": amount,
            "currency": "usd", "fee": fee, "net": amount - fee, "created": unix(at), "status": "available",
            "source": {"id": dispute, "object": "dispute", "amount": cents, "currency": "usd", "charge": charge}}


def plain_bt(txn, kind, amount, at, fee=0, category="fee", source=None):
    """A balance transaction with no charge behind it (a Stripe fee, a payout)."""
    return {"id": txn, "object": "balance_transaction", "type": kind, "reporting_category": category,
            "amount": amount, "currency": "usd", "fee": fee, "net": amount - fee, "created": unix(at),
            "status": "available", "source": source}


def session(payment_intent, *items, email=None, client_reference_id=None, metadata=None):
    return {"id": "cs_" + payment_intent, "object": "checkout.session", "payment_intent": payment_intent,
            "customer_details": {"email": email}, "client_reference_id": client_reference_id,
            "metadata": metadata or {},
            "line_items": {"object": "list", "data": [{"description": name, "quantity": qty}
                                                      for name, qty in items]}}


def fixture_day() -> tuple[list[dict], list[dict]]:
    """The plan's test day, Sun 1 Nov 2026 in New York (04:00Z to 05:00Z the next
    day: 25 hours): a $29.99 sale, the refund of a 31 Oct sale, and a $15.00
    dispute that was won; a $2.00 Stripe fee; a payout. Net $10.00, fees $3.17."""
    bts = [
        charge_bt("txn_sale0", "ch_0", 1999, "2026-10-31T15:00:00Z", 88, payment_intent="pi_0",
                  email="old@example.com"),
        refund_bt("txn_ref0", "re_0", "ch_0", 1999, "2026-11-01T14:00:00Z"),
        charge_bt("txn_sale9", "ch_9", 1500, "2026-10-20T15:00:00Z", 74, payment_intent="pi_9"),
        dispute_bt("txn_dsp9", "du_9", "ch_9", 1500, "2026-11-01T10:00:00Z", fee=1500),
        dispute_bt("txn_dsr9", "du_9", "ch_9", 1500, "2026-11-01T20:00:00Z", fee=-1500, won=True),
        plain_bt("txn_fee1", "stripe_fee", -200, "2026-11-01T12:00:00Z"),
        plain_bt("txn_po1", "payout", -5000, "2026-11-01T18:00:00Z", category="payout", source="po_1"),
        charge_bt("txn_sale1", "ch_1", 2999, "2026-11-02T04:30:00Z", 117, payment_intent="pi_1",
                  email="Buyer@Example.com"),
        charge_bt("txn_next", "ch_n", 500, "2026-11-02T05:00:00Z", 45),
    ]
    sessions = [session("pi_0", ("Toodle Guide", 1), email="old@example.com"),
                session("pi_1", ("AI Entrepreneur Blueprint Kit", 1), email="buyer@example.com")]
    return bts, sessions


def subscription(sub_id: str, *prices, status: str = "active") -> dict:
    """A subscription with one item per price: (unit_amount, interval[,
    quantity[, currency[, interval_count]]])."""
    items = []
    for n, (amount, interval, *rest) in enumerate(prices):
        quantity = rest[0] if len(rest) > 0 else 1
        currency = rest[1] if len(rest) > 1 else "usd"
        every = rest[2] if len(rest) > 2 else 1
        items.append({"id": f"si_{sub_id}_{n}", "object": "subscription_item", "quantity": quantity,
                      "price": {"id": f"price_{sub_id}_{n}", "object": "price", "unit_amount": amount,
                                "currency": currency, "recurring": {"interval": interval, "interval_count": every}}})
    return {"id": sub_id, "object": "subscription", "status": status,
            "items": {"object": "list", "data": items, "has_more": False}}


class FakeStripe:
    """GET /v1/balance_transactions (created filters, newest first, cursor
    pages), GET /v1/checkout/sessions?payment_intent=... and GET
    /v1/subscriptions?status=active (cursor pages)."""

    def __init__(self, key: str = STRIPE_KEY):
        self.key = key
        self.balance_transactions: list[dict] = []
        self.sessions: dict[str, dict] = {}
        self.subscriptions: list[dict] = []
        self.calls: list[httpx.Request] = []
        self.fail_next: list[int] = []          # statuses to answer, one per call, before any data
        self.session_status = 200               # e.g. 403: a key without Checkout read access
        self.page_size = 100

    def add(self, bts=(), sessions=()) -> "FakeStripe":
        self.balance_transactions.extend(bts)
        for s in sessions:
            self.sessions[s["payment_intent"]] = s
        return self

    def calls_to(self, path: str) -> list[httpx.Request]:
        return [c for c in self.calls if c.url.path == path]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.url.host != "api.stripe.com":
            return httpx.Response(404)
        if request.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401, json={"error": {"type": "invalid_request_error",
                                                       "message": "Invalid API Key provided: rk_live_****0000"}})
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), json={"error": {"type": "api_error"}},
                                  headers={"retry-after": "0"})
        q = request.url.params
        if request.url.path == "/v1/balance_transactions":
            assert q.get("expand[]") == "data.source"
            gte, lt = int(q.get("created[gte]", 0)), int(q.get("created[lt]", 2 ** 40))
            rows = sorted((b for b in self.balance_transactions if gte <= b["created"] < lt),
                          key=lambda b: (b["created"], b["id"]), reverse=True)
            after = q.get("starting_after")
            if after:
                rows = rows[[b["id"] for b in rows].index(after) + 1:]
            limit = min(int(q.get("limit", 10)), self.page_size)
            return httpx.Response(200, json={"object": "list", "data": rows[:limit],
                                             "has_more": len(rows) > limit})
        if request.url.path == "/v1/checkout/sessions":
            if self.session_status != 200:
                return httpx.Response(self.session_status, json={"error": {"type": "invalid_request_error",
                                                                           "code": "secret_key_required"}})
            found = self.sessions.get(q.get("payment_intent"))
            return httpx.Response(200, json={"object": "list", "data": [found] if found else [],
                                             "has_more": False})
        if request.url.path == "/v1/subscriptions":
            rows = [s for s in self.subscriptions if s["status"] == q.get("status", "active")]
            after = q.get("starting_after")
            if after:
                rows = rows[[s["id"] for s in rows].index(after) + 1:]
            limit = min(int(q.get("limit", 10)), self.page_size)
            return httpx.Response(200, json={"object": "list", "data": rows[:limit], "has_more": len(rows) > limit})
        return httpx.Response(404, json={"error": {"type": "invalid_request_error"}})


def install_stripe(monkeypatch, key: str = STRIPE_KEY, env: str = "STRIPE_READ_KEY") -> FakeStripe:
    """Point the Stripe sync at a fresh FakeStripe and set its key."""
    from core.board.connectors import stripe_sync
    fake = FakeStripe(key)
    for name in ("STRIPE_READ_KEY", "STRIPE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(env, key)
    monkeypatch.setattr(stripe_sync, "_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(stripe_sync, "_sleep", lambda seconds: None)
    return fake


# ═══ leads and Meta spend: builders and the plan's fixture ══════════════════

TOODLE_CAMPAIGN = "120249191226470279"      # the plan's Toodle campaign (marketing/GLOBAL_PLAN.md:125)


def optin(sub_id, at: str, channel=None, *, email=None, tags=("toodle",), funnel="toodle"):
    """A Kit opt-in as the Kit sync writes it: one per subscriber and funnel."""
    from core.board.ledger import LeadRow
    return LeadRow(external_id=f"{funnel}:sub:{sub_id}", kind="optin", occurred_at=_ts(at), email=email,
                   funnel=funnel, channel=channel, tags=tuple(tags))


def reply(email_id, at: str, email=None, *, auto=False, campaign="sb-campaign-1"):
    """An Instantly reply in the SiteBoost campaign: one per received email."""
    from core.board.ledger import LeadRow
    return LeadRow(external_id=email_id, kind="reply", occurred_at=_ts(at), email=email, funnel="siteboost",
                   channel="outreach", campaign_ref=campaign, is_auto_reply=auto)


def spend(day: str, cents: int, *, campaign=TOODLE_CAMPAIGN, funnel="toodle", currency="USD", link_clicks=0,
          impressions=0, name="Toodle opt-in"):
    """One campaign's Meta spend on one ad-account day, in minor units."""
    from core.board.ledger import AdSpendRow
    return AdSpendRow(campaign_id=campaign, campaign_name=name, funnel=funnel, day=date.fromisoformat(day),
                      currency=currency, spend_minor=cents, impressions=impressions, link_clicks=link_clicks)


def fixture_leads():
    """The plan's leads and Meta spend around Sun 1 Nov 2026 (the morning
    message in replica/architecture.md, "Phase 1 in one screen"). For 1 Nov:
    2 Toodle opt-ins, meta 1 (at 23:30, in the 25-hour day's last hour) and
    organic 1 (its blog tag comes on a second Kit run); 1 SiteBoost prospect
    who replied twice, plus 1 auto-reply, and 2 prospects over 7 days; $5.02 of
    Toodle spend and 9 link clicks. The stop rule: $25.10 over 28 Oct to 1 Nov
    for 4 Meta opt-ins is $6.28 a lead, so stop. sub 1's email is the Stripe
    fixture buyer's, so that sale is attributed to meta by lead email.

    Returns (kit_runs, replies, spend_rows); kit_runs holds one batch per Kit
    sync run."""
    meta = ("toodle", "meta_ad")
    first_run = [optin(1, "2026-10-30T12:00:00Z", "meta", email="buyer@example.com", tags=meta),
                 optin(2, "2026-11-02T04:30:00Z", "meta", email="a@example.com", tags=meta),  # 23:30 EST, 1 Nov
                 optin(3, "2026-11-01T16:00:00Z", email="b@example.com"),                    # no channel yet
                 optin(4, "2026-10-29T16:00:00Z", "meta", email="c@example.com", tags=meta),
                 optin(5, "2026-10-31T16:00:00Z", "meta", email="d@example.com", tags=meta),
                 optin(6, "2026-11-02T05:00:00Z", "meta", email="e@example.com", tags=meta)]  # 00:00, 2 Nov
    second_run = [optin(3, "2026-11-01T18:00:00Z", "organic", email="b@example.com", tags=("blog",))]
    replies = [reply("em1", "2026-11-01T13:00:00Z", "p1@shop.example"),
               reply("em2", "2026-11-01T18:00:00Z", "P1@Shop.example"),                     # the same prospect
               reply("em3", "2026-11-01T19:00:00Z", "p2@shop.example", auto=True),
               reply("em4", "2026-10-28T19:00:00Z", "p3@shop.example"),
               reply("em5", "2026-10-25T12:00:00Z", "p4@shop.example")]                     # 7 days back: out
    spend_rows = [spend(d, 502, link_clicks=9 if d == "2026-11-01" else 7, impressions=1200)
                  for d in ("2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01")]
    spend_rows.append(spend("2026-11-01", 1000, campaign="120000000000000001", funnel=None,
                            name="Brand awareness", link_clicks=40, impressions=9000))
    return [first_run, second_run], replies, spend_rows


_meta_runs = itertools.count(1)


def record_meta_run(db: FakeBoardDB, campaigns=(TOODLE_CAMPAIGN,), *, unseen=(), since: str = "2026-10-05") -> str:
    """An ok meta_sync run in job_runs, through the board's own write path,
    with the detail the Meta sync records: `campaigns`, the Toodle campaign
    list it labelled every stored spend row with, and `unseen`, the listed
    campaigns it saw no spend for in the days it read from `since`. Each run
    finishes after the one before, so it is the last complete run."""
    from core.board import ledger
    run_id = ledger.claim_run("meta_sync", f"fixture-{next(_meta_runs)}", "schedule", "meta_ads")
    ledger.finish_run(run_id, "ok", detail={"toodle_campaigns": sorted(campaigns),
                                            "toodle_campaigns_unseen": list(unseen),
                                            "days": {"since": since}})
    before = [r["finished_at"] for r in db.job_runs.values()
              if r["job"] == "meta_sync" and r["id"] != run_id and r["finished_at"] is not None]
    if before and max(before) >= db.job_runs[run_id]["finished_at"]:
        db.job_runs[run_id]["finished_at"] = max(before) + timedelta(milliseconds=1)
    return run_id


def load_fixture_leads(db: FakeBoardDB, synced_through: str = "2026-11-02T11:55:00Z") -> None:
    """Write fixture_leads() through the board's own write path
    (core.board.ledger, which install_board pointed at `db`), and mark Kit,
    Instantly and Meta measured from 1 Jan 2026 and synced to `synced_through`,
    so 1 Nov reads final for all three. The Meta run that labelled the spend
    is recorded with its list, the plan's Toodle campaign."""
    from core.board import ledger
    kit_runs, replies, spend_rows = fixture_leads()
    for batch in kit_runs:
        ledger.ingest_leads("kit", None, batch)
    ledger.ingest_leads("instantly", None, replies)
    ledger.upsert_ad_spend("meta_ads", None, spend_rows)
    record_meta_run(db)
    for source_id in ("kit", "instantly", "meta_ads"):
        db.set_source(source_id, measured_from="2026-01-01", synced_through=synced_through)


# ═══ the connectors' settings, for tests of the whole board ═════════════════

KIT_KEY = "kit_FAKEboardKey0123456789"                     # fake values, never real keys
KIT_TAGS = "toodle:,meta_ad:meta,blog:organic"
INSTANTLY_KEY = "FAKEinstantlyBoardKey0123456789=="
SITEBOOST_CAMPAIGN = "0f6c2b1e-9a4d-4e8b-8c3a-5d7e9f1a2b3c"
META_TOKEN = "FAKEMETAboardInsightsToken0123456789"
AD_ACCOUNT = "1234567890"
CONNECTOR_ENV = ("STRIPE_READ_KEY", "STRIPE_SECRET_KEY", "KIT_API_KEY", "BOARD_TOODLE_KIT_TAGS",
                 "INSTANTLY_API_KEY", "BOARD_SITEBOOST_CAMPAIGN_IDS",
                 "META_INSIGHTS_TOKEN", "META_ACCESS_TOKEN", "AD_ACCOUNT_ID", "FB_AD_ACCOUNT_ID",
                 "META_GRAPH_VERSION", "META_APP_SECRET", "BOARD_TOODLE_META_CAMPAIGN_IDS", "BOARD_CPL_DAYS",
                 "BOARD_CPL_STOP_CENTS", "BOARD_BACKFILL_FROM")


def clear_connectors(monkeypatch) -> None:
    """Stripe, Kit, Instantly and Meta unconfigured, and the stop rule at its
    defaults, whatever the machine running the tests has set (install_stripe
    and configure_connectors then set what a test needs)."""
    for name in CONNECTOR_ENV:
        monkeypatch.delenv(name, raising=False)


def configure_connectors(monkeypatch, *which: str) -> None:
    """Give the named connectors ('kit', 'instantly', 'meta_ads'; all three when
    none is named) the settings their configured() check wants. Nothing is
    called: the tests fake the database, and each connector's own tests fake
    its vendor."""
    which = which or ("kit", "instantly", "meta_ads")
    if "kit" in which:
        monkeypatch.setenv("KIT_API_KEY", KIT_KEY)
        monkeypatch.setenv("BOARD_TOODLE_KIT_TAGS", KIT_TAGS)
    if "instantly" in which:
        monkeypatch.setenv("INSTANTLY_API_KEY", INSTANTLY_KEY)
        monkeypatch.setenv("BOARD_SITEBOOST_CAMPAIGN_IDS", SITEBOOST_CAMPAIGN)
    if "meta_ads" in which:
        monkeypatch.setenv("META_INSIGHTS_TOKEN", META_TOKEN)
        monkeypatch.setenv("AD_ACCOUNT_ID", AD_ACCOUNT)
        monkeypatch.setenv("BOARD_TOODLE_META_CAMPAIGN_IDS", TOODLE_CAMPAIGN)
