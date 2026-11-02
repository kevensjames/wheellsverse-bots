"""In-memory stand-ins for the two Supabase services board sign-in talks to:
Auth's password grant and PostgREST's public.owner_sessions. Served through
httpx.MockTransport (core.board.auth._transport), so no test reaches the network.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

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
    page that wrote one of them out would show this test's value."""
    from fastapi.testclient import TestClient
    import core.api as api
    monkeypatch.setenv("API_KEY", API_KEY)          # read per request by the admin API routers
    monkeypatch.setattr(api, "_API_KEY", API_KEY)   # read by api_key_middleware
    monkeypatch.setattr(api, "_SUPABASE_URL", URL)  # read by _serve_frontend
    monkeypatch.setattr(api, "_SUPABASE_ANON", ANON)
    return TestClient(api.app, raise_server_exceptions=False)


def cookie(token: str) -> dict:
    return {"Cookie": f"{COOKIE}={token}"}
