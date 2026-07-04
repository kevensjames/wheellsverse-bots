"""Stage 7 tests — Sol v1 legal disclosure + consent gate."""
from __future__ import annotations

import os
from decimal import Decimal
from uuid import uuid4

import pytest

from app.services.sol_v1 import disclosures as D
from app.services.sol_v1.lifecycle import SolError


# ── pure / static ─────────────────────────────────────────────────────────────

def test_current_document_shape():
    doc = D.current_document()
    assert doc["document_key"] and doc["version"] and doc["title"] and doc["url"]
    # returns a copy (mutating it must not change the module constant)
    doc["version"] = "hacked"
    assert D.CURRENT["version"] != "hacked"


def test_record_consent_rejects_non_current_version():
    with pytest.raises(SolError) as e:
        D.record_consent(None, user_id=uuid4(), document_key="non_custodial_terms", version="1999-01-01")
    assert e.value.status_code == 409


def test_legal_router_registers_routes():
    from app.routers.sol_v1_legal import router
    assert {r.path for r in router.routes} == {"/sol/v1/legal/current", "/sol/v1/legal/accept"}


def test_terms_document_is_non_custodial():
    from pathlib import Path
    terms = (Path(__file__).resolve().parents[1] / "app" / "static" / "sol_v1_app" / "terms.html").read_text().lower()
    assert "not a bank" in terms and "never" in terms and "pay each other directly" in terms
    assert "risk" in terms


# ── DB end-to-end: consent recording + the create gate (gated) ───────────────

@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set — DB consent flow DEFERRED")
def test_consent_and_create_gate_on_real_db():
    from fastapi import HTTPException
    from sqlalchemy import create_engine, text
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.orm import Session
    from sqlalchemy.schema import CreateTable

    from app.dependencies.supabase_jwt import UserPrincipal
    from app.models.sol import SolCircleTemplate, SolConsent, SolCycle, SolGroup, SolMembership, SolPayment
    from starlette.requests import Request as _Request

    from app.routers.sol_v1 import create_group as create_group_route
    from app.schemas.sol_v1 import GroupCreate

    # create_group is @limiter.limit-decorated → it now takes `request` first.
    # A minimal real Request satisfies slowapi (the limiter is disabled in tests).
    _req = _Request({"type": "http", "method": "POST", "path": "/sol/v1/groups",
                     "headers": [], "client": ("127.0.0.1", 0)})

    url = os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg2", "")
    engine = create_engine(url, future=True)
    schema = "sol_v1_legal_e2e"
    uid = uuid4()
    models = (SolCircleTemplate, SolGroup, SolMembership, SolCycle, SolPayment, SolConsent)

    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET search_path TO {schema}"))
        conn.execute(text("CREATE TABLE profiles (id UUID PRIMARY KEY)"))
        for m in models:
            conn.execute(text(str(CreateTable(m.__table__).compile(dialect=postgresql.dialect()))))
        conn.execute(text("INSERT INTO profiles (id) VALUES (:id)"), {"id": uid})

    try:
        conn = engine.connect()
        conn.execute(text(f"SET search_path TO {schema}"))
        db = Session(bind=conn)
        principal = UserPrincipal(id=uid, email=None, role="authenticated")
        body = GroupCreate(name="Gated circle", contribution_amount=Decimal("25.00"),
                           frequency="weekly", member_limit=3)

        # not accepted yet
        assert D.has_accepted(db, user_id=uid) is False
        with pytest.raises(SolError):
            D.require_consent(db, user_id=uid)

        # the create route is GATED: 403 before consent
        with pytest.raises(HTTPException) as ex:
            create_group_route(_req, body, current=principal, db=db)
        assert ex.value.status_code == 403

        # accept the current terms → idempotent
        c1 = D.record_consent(db, user_id=uid, document_key=D.CURRENT["document_key"], version=D.CURRENT["version"])
        c2 = D.record_consent(db, user_id=uid, document_key=D.CURRENT["document_key"], version=D.CURRENT["version"])
        assert c1.id == c2.id  # same row, no duplicate
        assert D.has_accepted(db, user_id=uid) is True
        assert D.consent_status(db, user_id=uid)["accepted"] is True

        # now the gate opens: create succeeds
        out = create_group_route(_req, body, current=principal, db=db)
        assert out.name == "Gated circle" and out.status == "open"

        db.close(); conn.close()
    finally:
        with engine.begin() as c2:
            c2.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        engine.dispose()
