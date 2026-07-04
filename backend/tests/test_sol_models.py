"""Stage 1 tests — Sol data model.

Pure-unit checks on the mapper definitions (no DB required) plus a DB-gated
round-trip test. Validates the sol_* tables match the spec: correct columns,
FK targets, enumerated domains, and CHECK/UNIQUE constraints — including the
non-custodial guarantees (payment handles are external rails only; amounts are
plain recorded numbers; no bank/routing fields exist).
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.sol import (
    CYCLE_STATUSES,
    FREQUENCIES,
    GROUP_STATUSES,
    MEMBERSHIP_ROLES,
    PAYMENT_METHODS,
    PAYMENT_STATUSES,
    PROFILE_METHODS,
    SolCircleTemplate,
    SolCycle,
    SolGroup,
    SolMembership,
    SolPayment,
    SolPaymentProfile,
    SolPaymentProof,
)

ALL_MODELS = [
    SolCircleTemplate,  # created first: sol_groups.template_id FKs to it
    SolGroup,
    SolMembership,
    SolCycle,
    SolPayment,
    SolPaymentProfile,
    SolPaymentProof,
]


def _cols(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


def _fk_target(model, col: str) -> str:
    fks = list(model.__table__.columns[col].foreign_keys)
    assert fks, f"{model.__tablename__}.{col} has no FK"
    return fks[0].column.table.name


# ── table names ──────────────────────────────────────────────────────────────

def test_table_names_namespaced():
    assert SolGroup.__tablename__ == "sol_groups"
    assert SolMembership.__tablename__ == "sol_memberships"
    assert SolCycle.__tablename__ == "sol_cycles"
    assert SolPayment.__tablename__ == "sol_payments"
    assert SolPaymentProfile.__tablename__ == "sol_payment_profiles"
    assert SolPaymentProof.__tablename__ == "sol_payment_proofs"


# ── columns per spec ─────────────────────────────────────────────────────────

def test_group_columns():
    assert _cols(SolGroup) >= {
        "id", "organizer_id", "name", "contribution_amount", "frequency",
        "member_limit", "status", "invite_code", "created_at", "updated_at",
    }


def test_membership_columns():
    assert _cols(SolMembership) >= {
        "id", "user_id", "group_id", "payout_position", "role", "created_at",
    }


def test_cycle_columns():
    assert _cols(SolCycle) >= {
        "id", "group_id", "cycle_number", "recipient_membership_id",
        "due_date", "status",
    }


def test_payment_columns():
    assert _cols(SolPayment) >= {
        "id", "cycle_id", "payer_id", "payee_id", "amount", "method",
        "payer_marked_at", "payee_confirmed_at", "status",
    }


def test_payment_profile_columns():
    assert _cols(SolPaymentProfile) >= {
        "id", "user_id", "method", "handle", "is_default",
    }


def test_payment_proof_columns():
    assert _cols(SolPaymentProof) >= {"id", "payment_id", "image_url", "uploaded_at"}


# ── non-custodial guarantees: no money/bank fields anywhere ───────────────────

def test_no_bank_or_balance_fields():
    banned = {"routing", "routing_number", "account_number", "bank", "balance",
              "iban", "card_number", "cvv", "ssn"}
    for model in ALL_MODELS:
        leaked = {c for c in _cols(model) if any(b in c for b in banned)}
        assert not leaked, f"{model.__tablename__} exposes custodial field(s): {leaked}"


# ── foreign keys point at the right tables ───────────────────────────────────

def test_foreign_key_targets():
    assert _fk_target(SolGroup, "organizer_id") == "profiles"
    assert _fk_target(SolMembership, "user_id") == "profiles"
    assert _fk_target(SolMembership, "group_id") == "sol_groups"
    assert _fk_target(SolCycle, "group_id") == "sol_groups"
    assert _fk_target(SolCycle, "recipient_membership_id") == "sol_memberships"
    assert _fk_target(SolPayment, "cycle_id") == "sol_cycles"
    assert _fk_target(SolPayment, "payer_id") == "profiles"
    assert _fk_target(SolPayment, "payee_id") == "profiles"
    assert _fk_target(SolPaymentProfile, "user_id") == "profiles"
    assert _fk_target(SolPaymentProof, "payment_id") == "sol_payments"


# ── enumerated domains match the spec ────────────────────────────────────────

def test_enumerated_domains():
    assert FREQUENCIES == ("weekly", "biweekly", "monthly")
    assert GROUP_STATUSES == ("open", "locked", "complete")
    assert MEMBERSHIP_ROLES == ("organizer", "member")
    assert CYCLE_STATUSES == ("pending", "active", "complete")
    assert PAYMENT_METHODS == ("zelle", "cashapp", "venmo", "cash", "other", "stripe")
    assert PAYMENT_STATUSES == ("pending", "marked", "confirmed", "disputed", "late")
    assert PROFILE_METHODS == ("zelle", "cashapp", "venmo", "applepay", "cash")


# ── DDL compiles with the guard constraints ──────────────────────────────────

def test_payment_ddl_has_check_and_defaults():
    ddl = str(CreateTable(SolPayment.__table__).compile(dialect=postgresql.dialect()))
    assert "CHECK" in ddl and "payer_id <> payee_id" in ddl
    assert "NUMERIC(12, 2)" in ddl


def test_group_ddl_has_status_and_frequency_checks():
    ddl = str(CreateTable(SolGroup.__table__).compile(dialect=postgresql.dialect()))
    assert "frequency IN" in ddl
    assert "status IN" in ddl
    assert "invite_code" in ddl and "UNIQUE" in ddl


# ── DB round-trip (gated on a reachable TEST_DATABASE_URL) ────────────────────

@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — DB round-trip DEFERRED",
)
def test_ddl_creates_on_real_db():
    """Create just the sol_* tables on a scratch schema and drop them.

    Uses a temporary schema so it never touches profiles or real data. Proves
    the DDL is valid Postgres (rung 4-ish for the schema, without seeding users).
    """
    from sqlalchemy import create_engine, text

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS sol_ddl_test"))
        conn.execute(text("SET search_path TO sol_ddl_test"))
        # profiles + sol_ tables need to exist in this schema for FK compilation;
        # create a minimal profiles stub so the FKs resolve.
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for model in ALL_MODELS:
            conn.execute(text(str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))))
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA sol_ddl_test CASCADE"))
    engine.dispose()
