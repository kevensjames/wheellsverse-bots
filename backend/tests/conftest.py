import os

import pytest
from faker import Faker
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from sqlalchemy import Column, Table, event
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base, get_db
from app.main import app
from app import models  # noqa: F401  — register all tables on Base.metadata


# ── Schema-drift stub: `profiles` ──────────────────────────────────────
# `Conversation.user_id`, `Message.user_id`, and `LLMCallLog.user_id` all
# FK to `profiles.id`, inherited from the NarAI v1 Supabase auth pattern
# (auth.users → profiles trigger). But the SQLAlchemy `User` model owns
# the `users` table, and `/auth/signup` writes there — so prod has a
# schema-drift bug (signup-created users have no profile row; downstream
# inserts violate FK). Operator must align this in Phase B (either move
# all FKs to users.id, or create a profiles row on signup via a trigger).
#
# For tests, declare a minimal `profiles` table on Base.metadata so
# create_all() can resolve the FK target — and event-mirror every User
# insert into profiles so the FK is always satisfied. Test-only;
# production schema is owned by Alembic + Supabase migrations.
if "profiles" not in Base.metadata.tables:
    _profiles = Table(
        "profiles",
        Base.metadata,
        Column("id", UUID(as_uuid=True), primary_key=True),
    )

    @event.listens_for(models.user.User, "after_insert")
    def _mirror_user_to_profiles(_mapper, connection, target):  # type: ignore[no-untyped-def]
        connection.execute(_profiles.insert().values(id=target.id))


# ── Schema-drift stub: `llm_call_log` ─────────────────────────────────
# Created in Alembic migration 0004 (Stage 2) but never given a SQLAlchemy
# model — `spend_tracker.py` writes via raw SQL. So `create_all()` doesn't
# know about it. Declare a matching shadow table here so test setup
# creates it. Schema mirrors alembic/versions/0004_add_llm_call_log_table.py
# exactly; keep them in sync if either changes.
from sqlalchemy import (  # noqa: E402
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402

if "llm_call_log" not in Base.metadata.tables:
    Table(
        "llm_call_log",
        Base.metadata,
        Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        ),
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
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("NOW()"),
        ),
        Index("ix_llm_call_log_user_id_created_at", "user_id", text("created_at DESC")),
        Index("ix_llm_call_log_adapter_created_at", "adapter", text("created_at DESC")),
        Index("ix_llm_call_log_created_at", text("created_at DESC")),
    )


TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/wheellsverse_test",
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL, pool_pre_ping=True, future=True)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    # Start from a clean slate — drop anything left from a prior failed run.
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db_session(engine):
    TestSession = sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        future=True,
    )
    session = TestSession()
    # Truncate every table before each test — cheap, reliable, tolerates commits
    # inside route handlers (unlike rollback-based isolation).
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
    session.commit()
    try:
        yield session
    finally:
        session.close()


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


@pytest.fixture
def test_asset(db_session):
    """A stock asset guaranteed to exist in the test DB for market-data tests."""
    from app.models.asset import Asset

    asset = Asset(symbol="TEST", name="Test Asset", asset_type="stock", is_active=True)
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    return asset


@pytest.fixture(autouse=True)
def _clear_prediction_cache():
    """The /predictions/stats endpoint caches in Redis. Without clearing, a
    test that seeds new predictions could read stale data. Fail open when
    Redis is unreachable — suite still runs."""
    try:
        import redis as redis_lib

        from app.config import settings as _app_settings

        r = redis_lib.Redis.from_url(_app_settings.REDIS_URL, decode_responses=True)
        r.delete("predictions:stats:30d")
    except Exception:
        pass
    yield


@pytest.fixture
def seeded_plans(db_session):
    """Insert the three plan tiers and return a {code: Plan} dict."""
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


def _make_user(db_session, email: str, plan_code: str | None, seeded_plans):
    from app.core.security import hash_password
    from app.models.subscription import Subscription
    from app.models.user import User

    user = User(
        email=email.lower(),
        password_hash=hash_password("testpass123"),
        full_name=email.split("@")[0],
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    if plan_code:
        plan = seeded_plans[plan_code]
        db_session.add(Subscription(user_id=user.id, plan_id=plan.id, status="active"))
        db_session.commit()
    return user


@pytest.fixture
def free_user(db_session, seeded_plans):
    """Authenticated user on the free tier (3 predictions/day)."""
    return _make_user(db_session, "free@test.com", None, seeded_plans)


@pytest.fixture
def pro_user(db_session, seeded_plans):
    """Authenticated user on the Pro tier (effectively unlimited)."""
    return _make_user(db_session, "pro@test.com", "pro", seeded_plans)


@pytest.fixture
def auth_headers():
    """Callable: given a User, return the Authorization header."""
    from app.core.security import create_access_token

    def _make(user) -> dict:
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    return _make


def seed_price_history(db_session, asset_id: int, rows: int = 250):
    """Deterministic synthetic OHLCV with a mild uptrend + sine wobble.
    Enough rows and variance to exercise indicator warmup + crossover logic.
    """
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
                open=base,
                high=base * 1.01,
                low=base * 0.99,
                close=base * (1 + math.sin(i / 7.0) * 0.002),
                volume=1_000_000 + i * 1000,
            )
        )
    db_session.add_all(records)
    db_session.commit()
