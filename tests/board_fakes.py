"""In-memory stand-ins for the services the board talks to, served through
httpx.MockTransport, so no test reaches the network:

  * FakeSupabase: Auth's password grant and PostgREST's public.owner_sessions
    (core.board.auth._transport), for sign-in.
  * FakeBoardDB: PostgREST over the board's tables and SQL functions
    (core.board.ledger._transport): the claims, board_ingest_ledger and
    board_day, by New York day. It follows the rules of
    narai/migrations/0002_daily_numbers_board.sql that the board's code relies
    on; the real SQL is checked on PostgreSQL itself.
  * FakeStripe: the Stripe API's balance transactions and Checkout Sessions
    (core.board.connectors.stripe_sync._transport), with builders for them.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone
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
    """A timestamptz as Postgres writes it into JSON (session time zone UTC)."""
    return value.astimezone(timezone.utc).isoformat() if value else None


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class FakeBoardDB:
    """PostgREST over the board's tables and functions, in memory. Answers
    errors the way PostgREST does: {"code", "message", "details"}, where
    details can quote a failing row (so the board must never pass it on)."""

    def __init__(self):
        self.clock = lambda: datetime.now(timezone.utc)
        self.sources = {sid: {"id": sid, "kind": kind, "method": method, "display_name": name,
                              "day_tz": "America/New_York", "enabled": True, "measured_from": None,
                              "synced_through": None, "last_ok_at": None, "last_error": None,
                              "last_error_at": None}
                        for sid, kind, method, name in SEED_SOURCES}
        self.job_runs: dict[str, dict] = {}
        self.webhook_events: dict[tuple, dict] = {}
        self.ledger: dict[tuple, dict] = {}
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
            if path.startswith("rpc/"):
                fn = getattr(self, "_rpc_" + path[4:], None)
                if fn is None:
                    return httpx.Response(404, json={"code": "PGRST202", "message": "Could not find the function"})
                return httpx.Response(200, json=fn(**json.loads(request.content or b"{}")))
            return self._table(request, path)
        except FakeSQLError as e:
            return httpx.Response(400, json={"code": e.code, "message": e.message,
                                             "details": "Failing row contains (x@example.com)"})

    # ── tables ──
    def _tables(self) -> dict:
        return {"sources": self.sources, "job_runs": self.job_runs,
                "webhook_events": self.webhook_events, "ledger_entries": self.ledger}

    @staticmethod
    def _cmp(row_value, op: str, value: str) -> bool:
        if op == "is":
            return row_value is None if value == "null" else False
        if op == "eq":
            return row_value is not None and str(row_value) == value
        if op == "in":
            return row_value is not None and str(row_value) in value.strip("()").split(",")
        if op == "lt":
            if row_value is None:
                return False
            if isinstance(row_value, datetime):
                return row_value < _ts(value)
            return str(row_value) < value
        raise AssertionError(f"filter operator {op} is not faked")

    def _match(self, row: dict, filters: list[tuple[str, str]]) -> bool:
        for key, expr in filters:
            if key == "or":
                parts = re.findall(r'(\w+)\.(\w+)\.("[^"]*"|[^,()]+)', expr)
                if not any(self._cmp(row.get(f), op, v.strip('"')) for f, op, v in parts):
                    return False
                continue
            op, _, value = expr.partition(".")
            if not self._cmp(row.get(key), op, value):
                return False
        return True

    def _check(self, table: str, row: dict) -> None:
        if table == "job_runs":
            if row["status"] not in ("running", "ok", "failed", "skipped"):
                raise FakeSQLError("23514", "violates check constraint job_runs_status")
            if (row["status"] == "running") != (row["finished_at"] is None):
                raise FakeSQLError("23514", 'violates check constraint "job_runs_finished"')
            if not isinstance(row["detail"], dict) or row["rows_written"] < 0:
                raise FakeSQLError("23514", "violates check constraint on job_runs")
        if table == "sources" and (row["last_error"] is None) != (row["last_error_at"] is None):
            raise FakeSQLError("23514", 'violates check constraint "sources_error_pair"')
        if table == "webhook_events":
            if row["status"] not in ("received", "processed", "failed", "ignored"):
                raise FakeSQLError("23514", "violates check constraint webhook_events_status")
            if (row["status"] == "processed") != (row["processed_at"] is not None):
                raise FakeSQLError("23514", 'violates check constraint "webhook_events_processed"')

    def _table(self, request: httpx.Request, table: str) -> httpx.Response:
        rows = self._tables().get(table)
        if rows is None:
            return httpx.Response(404, json={"code": "42P01", "message": f"relation {table} does not exist"})
        params = list(request.url.params.multi_items())
        select = next((v for k, v in params if k == "select"), None)
        filters = [(k, v) for k, v in params if k not in ("select", "limit", "order")]
        matched = [r for r in rows.values() if self._match(r, filters)]
        if request.method == "GET":
            out = [{k: (_pg_ts(v) if isinstance(v, datetime) else v.isoformat() if isinstance(v, date) else v)
                    for k, v in r.items() if select is None or k in select.split(",")} for r in matched]
            return httpx.Response(200, json=out)
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
            return httpx.Response(204)
        return httpx.Response(405)

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
                       order_ref=old["order_ref"] or new["order_ref"],
                       via_platform=new["via_platform"] or old["via_platform"],
                       fee_usd_cents=old["fee_usd_cents"] if old["fee_usd_cents"] is not None else new["fee_usd_cents"])
        return [{"received": len(incoming), "inserted": len(incoming) - len(existing),
                 "relabelled": len(existing), "money_mismatches": mismatches}]

    @staticmethod
    def _ledger_row(source_id, run_id, x: dict) -> dict:
        """One p_rows element as the SQL would write it, with its checks."""
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
        if attribution == "none" or channel is None or attribution == "click_id":   # no clicks table here
            attribution, channel = "none", None
        row = {"source_id": source_id, "external_id": x.get("external_id"), "kind": kind,
               "occurred_at": _ts(x.get("occurred_at")),
               "occurred_on": date.fromisoformat(x["occurred_on"]) if x.get("occurred_on") else None,
               "amount_minor": minor, "currency": currency, "amount_usd_cents": usd, "fx_source": fx,
               "fee_usd_cents": x.get("fee_usd_cents"), "is_estimate": bool(x.get("is_estimate")),
               "product": (str(x.get("product")).strip() or None) if x.get("product") else None,
               "quantity": x.get("quantity"), "customer_email": email, "channel": channel,
               "attribution": attribution, "order_ref": x.get("order_ref"), "via_platform": x.get("via_platform"),
               "raw": x.get("raw") or {}, "job_run_id": run_id}
        if not row["external_id"] or minor is None or not re.fullmatch(r"[A-Z]{3}", currency):
            raise FakeSQLError("23502", "null value or bad currency in ledger_entries")
        if kind not in ("sale", "refund", "dispute", "dispute_reversal", "fee", "adjustment"):
            raise FakeSQLError("23514", 'violates check constraint "ledger_entries_kind_check"')
        if (row["occurred_at"] is None) == (row["occurred_on"] is None):
            raise FakeSQLError("23514", 'violates check constraint "ledger_entries_one_time"')
        if kind in ("sale", "dispute_reversal") and (minor < 0 or (usd or 0) < 0) or \
                kind in ("refund", "dispute", "fee") and (minor > 0 or (usd or 0) > 0):
            raise FakeSQLError("23514", 'violates check constraint "ledger_entries_sign"')
        if (usd is None) != (fx is None) or fx not in (None, "identity", "stripe", "ecb"):
            raise FakeSQLError("23514", 'violates check constraint "ledger_entries_usd_has_source"')
        if fx == "identity" and (currency != "USD" or usd != minor):
            raise FakeSQLError("23514", 'violates check constraint "ledger_entries_identity"')
        return row

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

    def board_ledger(self) -> list[dict]:
        """public.board_ledger: a refund or dispute takes its sale's labels (no lead matching here)."""
        out = []
        for r in self.ledger.values():
            sale = None
            if r["kind"] != "sale" and r["order_ref"]:
                sales = [x for x in self.ledger.values() if x["source_id"] == r["source_id"]
                         and x["order_ref"] == r["order_ref"] and x["kind"] == "sale"]
                sale = min(sales, key=lambda x: x["occurred_at"]) if sales else None
            s = sale or {}
            local_day = r["occurred_at"].astimezone(NY).date() if r["occurred_at"] else r["occurred_on"]
            channel = s.get("channel") or r["channel"] or "unattributed"
            attribution = (s["attribution"] if s.get("channel") else r["attribution"] if r["channel"] else "none")
            out.append({**r, "local_day": local_day, "product": r["product"] or s.get("product"),
                        "customer_email": r["customer_email"] or s.get("customer_email"),
                        "channel": channel, "attribution": attribution})
        return out

    def _rpc_board_day(self, p_day=None, p_cpl_days=5, p_cpl_stop_cents=500):
        day = date.fromisoformat(p_day) if p_day else self.clock().astimezone(NY).date() - timedelta(days=1)
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
        }


def install_board(monkeypatch) -> FakeBoardDB:
    """Point core.board.ledger at a fresh FakeBoardDB (same URL and service key
    as install(), which a test may call too for sign-in)."""
    from core.board import ledger
    db = FakeBoardDB()
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", SERVICE)
    monkeypatch.setattr(ledger, "_transport", httpx.MockTransport(db.handler))
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


class FakeStripe:
    """GET /v1/balance_transactions (created filters, newest first, cursor
    pages) and GET /v1/checkout/sessions?payment_intent=..."""

    def __init__(self, key: str = STRIPE_KEY):
        self.key = key
        self.balance_transactions: list[dict] = []
        self.sessions: dict[str, dict] = {}
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
