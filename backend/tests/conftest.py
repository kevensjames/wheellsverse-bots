"""Path X test fixtures.

The previous conftest fabricated a `public.users` table to make the Stage 6
self-managed User model satisfiable in tests — that's exactly what hid the
prod schema-drift bug. Path X removed the User model entirely; this conftest
now mirrors prod shape:

- `profiles` is the user table; tests insert into it directly.
- A fake Supabase Auth shim (in-memory) lets /auth/signup, /auth/login,
  /auth/refresh tests run without hitting real Supabase.
- A test JWT signer (HS256, swapped in via monkeypatching ``decode_supabase_jwt``)
  lets us mint tokens the validator will accept. Prod uses ES256/JWKS; tests
  swap to HS256 to skip the JWKS round-trip.
- ``auth_override`` fixture overrides ``get_current_user`` for endpoints we
  want to test without going through the auth flow at all.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any

import jwt
import pytest
from faker import Faker
from fastapi.testclient import TestClient
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    create_engine,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app import models  # noqa: F401  — register all tables on Base.metadata


# ── Test-only shadow tables ───────────────────────────────────────────
# `profiles` is now owned by app.models.Profile (Path X); models/__init__
# registered it on Base.metadata before this file ran. We only need to add
# the `llm_call_log` shadow — Alembic migration 0004 creates it in prod,
# but there's no SQLAlchemy model (spend_tracker.py writes raw SQL), so
# create_all() doesn't know about it without this declaration.

if "llm_call_log" not in Base.metadata.tables:
    Table(
        "llm_call_log",
        Base.metadata,
        Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
        Column(
            "user_id",
            UUID(as_uuid=True),
            ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("adapter", String(50), nullable=False),
        Column("model", String(100), nullable=False),
        Column("input_tokens", Integer, nullable=False, server_default="0"),
        Column("output_tokens", Integer, nullable=False, server_default="0"),
        Column("cost_usd", Numeric(10, 6), nullable=False, server_default="0"),
        Column("latency_ms", Integer, nullable=True),
        Column("success", Boolean, nullable=False, server_default=text("true")),
        Column("error_message", Text, nullable=True),
        Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("NOW()")),
        Index("ix_llm_call_log_user_id_created_at", "user_id", text("created_at DESC")),
        Index("ix_llm_call_log_adapter_created_at", "adapter", text("created_at DESC")),
        Index("ix_llm_call_log_created_at", text("created_at DESC")),
    )


TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/wheellsverse_test",
)

# Test JWT signing secret (HS256). Used by the supabase_auth shim to mint
# tokens AND by the patched ``decode_supabase_jwt`` to verify them. Prod uses
# ES256/JWKS; this just avoids the JWKS round-trip in tests.
_TEST_JWT_SECRET = "test-secret-not-prod"
_TEST_JWT_ALG = "HS256"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL, pool_pre_ping=True, future=True)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db_session(engine):
    TestSession = sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False, future=True,
    )
    session = TestSession()
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """Path X kept the slowapi rate limits. Disable for the default suite to
    avoid 429 mid-run; the dedicated rate-limit suite re-enables."""
    from app.core.rate_limit import limiter as _limiter

    was_enabled = _limiter.enabled
    _limiter.enabled = False
    _limiter.reset()
    try:
        yield
    finally:
        _limiter.reset()
        _limiter.enabled = was_enabled


@pytest.fixture(autouse=True)
def _clear_prediction_cache():
    """Redis prediction cache cleanup. Fail-open if Redis isn't running."""
    try:
        import redis as redis_lib
        from app.config import settings as _app_settings

        r = redis_lib.Redis.from_url(_app_settings.REDIS_URL, decode_responses=True)
        r.delete("predictions:stats:30d")
    except Exception:
        pass
    yield


# ── Fake Supabase Auth ────────────────────────────────────────────────


class _FakeSupabaseAuth:
    """Drop-in for app.services.supabase_auth: in-memory users + HS256 tokens."""

    def __init__(self):
        self.users: dict[str, dict] = {}  # email -> {id, password, full_name}
        self.refresh_to_user: dict[str, str] = {}  # refresh_token -> user_id

    def reset(self):
        self.users.clear()
        self.refresh_to_user.clear()

    def _mint(self, user_id: str, email: str, ttl_seconds: int = 3600) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "sub": user_id,
                "email": email,
                "role": "authenticated",
                "aud": "authenticated",
                "iat": now,
                "exp": now + ttl_seconds,
            },
            _TEST_JWT_SECRET,
            algorithm=_TEST_JWT_ALG,
        )

    def create_user(self, email: str, password: str, full_name: str | None = None) -> dict:
        email = email.lower()
        if email in self.users:
            from app.services.supabase_auth import AuthError

            raise AuthError("email already registered", status_code=409)
        uid = str(uuid.uuid4())
        self.users[email] = {"id": uid, "password": password, "full_name": full_name}
        return {"id": uid, "email": email}

    def password_login(self, email: str, password: str) -> dict:
        from app.services.supabase_auth import AuthError

        email = email.lower()
        u = self.users.get(email)
        if u is None or u["password"] != password:
            raise AuthError("invalid email or password", status_code=401)
        access = self._mint(u["id"], email)
        refresh = f"refresh-{uuid.uuid4()}"
        self.refresh_to_user[refresh] = u["id"]
        return {
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": 3600,
            "user_id": u["id"],
            "user_email": email,
        }

    def refresh_session(self, refresh: str) -> dict:
        from app.services.supabase_auth import AuthError

        uid = self.refresh_to_user.get(refresh)
        if uid is None:
            raise AuthError("invalid refresh token", status_code=401)
        # Look up email by id (linear scan; tests have at most a few users).
        email = next((e for e, u in self.users.items() if u["id"] == uid), "test@example.com")
        access = self._mint(uid, email)
        new_refresh = f"refresh-{uuid.uuid4()}"
        self.refresh_to_user[new_refresh] = uid
        self.refresh_to_user.pop(refresh, None)
        return {"access_token": access, "refresh_token": new_refresh, "expires_in": 3600}


_fake_supabase = _FakeSupabaseAuth()


@pytest.fixture(autouse=True)
def fake_supabase_auth(monkeypatch, db_session):
    """Replace app.services.supabase_auth with the in-memory fake AND ensure
    that when the fake creates a user, a matching profiles row exists in the
    DB (in prod this happens via the Supabase trigger; here we do it
    explicitly so chat-table FKs resolve)."""
    _fake_supabase.reset()

    from app.services import supabase_auth as real_module
    from app.dependencies import supabase_jwt as jwt_module

    # 1) Wrap create_user so DB-side profile insert happens too.
    real_create = _fake_supabase.create_user

    def _create_user_with_profile(email, password, full_name=None):
        result = real_create(email, password, full_name=full_name)
        db_session.execute(
            text(
                "INSERT INTO profiles (id, email, name, tier) "
                "VALUES (:id, :email, :name, 'free') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": result["id"], "email": result["email"], "name": full_name},
        )
        db_session.commit()
        return result

    monkeypatch.setattr(real_module, "create_user", _create_user_with_profile)
    monkeypatch.setattr(real_module, "password_login", _fake_supabase.password_login)
    monkeypatch.setattr(real_module, "refresh_session", _fake_supabase.refresh_session)

    # 2) Swap JWT validator to use HS256 + the test secret instead of JWKS.
    def _test_decode(token: str) -> dict:
        try:
            return jwt.decode(
                token,
                _TEST_JWT_SECRET,
                algorithms=[_TEST_JWT_ALG],
                audience="authenticated",
            )
        except jwt.InvalidTokenError:
            from app.dependencies.supabase_jwt import _INVALID
            raise _INVALID

    monkeypatch.setattr(jwt_module, "decode_supabase_jwt", _test_decode)
    yield _fake_supabase


@pytest.fixture
def client(db_session):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def faker_fixture():
    return Faker()


# ── Direct profile + auth-override helpers ────────────────────────────


def _insert_profile(db_session, *, email: str | None = None, name: str | None = None,
                    tier: str = "free") -> uuid.UUID:
    pid = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO profiles (id, email, name, tier) "
            "VALUES (:id, :email, :name, :tier)"
        ),
        {"id": str(pid), "email": email or f"t-{pid}@test.com", "name": name, "tier": tier},
    )
    db_session.commit()
    return pid


@pytest.fixture
def test_profile(db_session):
    """A bare profiles row for tests that need a user_id but don't care about auth."""
    return _insert_profile(db_session)


@pytest.fixture
def free_user(db_session, seeded_plans):
    """Path X equivalent of the old free_user — a profiles row, no subscription.
    Returned object has .id and .email attributes for backward compat with tests
    that did ``free_user.id``."""

    pid = _insert_profile(db_session, email="free@test.com")

    class _Profile:
        def __init__(self, id, email):
            self.id = id
            self.email = email

    return _Profile(pid, "free@test.com")


@pytest.fixture
def pro_user(db_session, seeded_plans):
    """Path X equivalent of pro_user. Insert a profiles row + Pro subscription."""
    from app.models.subscription import Subscription

    pid = _insert_profile(db_session, email="pro@test.com", tier="pro")
    plan = seeded_plans["pro"]
    db_session.add(Subscription(user_id=pid, plan_id=plan.id, status="active"))
    db_session.commit()

    class _Profile:
        def __init__(self, id, email):
            self.id = id
            self.email = email

    return _Profile(pid, "pro@test.com")


@pytest.fixture
def auth_headers():
    """Mint a Path-X-style Authorization header for a Profile-like object."""

    def _make(profile) -> dict:
        token = _fake_supabase._mint(str(profile.id), profile.email)
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest.fixture
def seeded_plans(db_session):
    from app.models.subscription import Plan

    rows = [
        {"code": "free", "name": "Free", "price_cents": 0, "predictions_per_day": 3, "sms_alerts": False},
        {"code": "pro", "name": "Pro", "price_cents": 1900, "predictions_per_day": 999, "sms_alerts": False},
        {"code": "elite", "name": "Elite", "price_cents": 4900, "predictions_per_day": 999, "sms_alerts": True},
    ]
    for row in rows:
        db_session.add(Plan(**row))
    db_session.commit()
    return {p.code: p for p in db_session.query(Plan).all()}


@pytest.fixture
def test_asset(db_session):
    """Stock asset for market-data tests."""
    from app.models.asset import Asset

    asset = Asset(symbol="TEST", name="Test Asset", asset_type="stock", is_active=True)
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    return asset


def seed_price_history(db_session, asset_id: int, rows: int = 250):
    import math
    from datetime import datetime, timedelta, timezone
    from app.models.asset import PriceHistory

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    records = []
    for i in range(rows):
        base = 100.0 + i * 0.1 + math.sin(i / 10.0) * 5.0
        records.append(
            PriceHistory(
                asset_id=asset_id,
                timestamp=start + timedelta(days=i),
                open=base, high=base * 1.01, low=base * 0.99,
                close=base * (1 + math.sin(i / 7.0) * 0.002),
                volume=1_000_000 + i * 1000,
            )
        )
    db_session.add_all(records)
    db_session.commit()
