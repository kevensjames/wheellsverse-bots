"""Sol v1 disclosures — versioned non-custodial terms + a consent gate.

A member must accept the current non-custodial terms + risk disclosure before
they can create or join a circle (the point where money coordination begins).
Acceptance is recorded per (user, document, version) in sol_consents; bump
CURRENT["version"] to force re-consent when the terms materially change.

The binding legal text lives at the served document (CURRENT["url"]); this
module only tracks WHICH version a member accepted and WHEN. The plumbing is
production-grade; the legal language itself is a template pending attorney
review before launch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.sol import SolConsent
from app.services.sol_v1.lifecycle import SolError

# The current disclosure. Bump `version` (ISO date) on any material change to
# force every member to re-accept before their next create/join.
CURRENT = {
    "document_key": "non_custodial_terms",
    "version": "2026-07-03",
    "title": "Sol Non-Custodial Terms & Risk Disclosure",
    "url": "/sol-app/terms.html",
}


def current_document() -> dict:
    return dict(CURRENT)


def has_accepted(db: Session, *, user_id: UUID, document_key: str | None = None, version: str | None = None) -> bool:
    document_key = document_key or CURRENT["document_key"]
    version = version or CURRENT["version"]
    row = db.scalar(
        select(SolConsent.id).where(
            SolConsent.user_id == user_id,
            SolConsent.document_key == document_key,
            SolConsent.version == version,
        )
    )
    return row is not None


def consent_status(db: Session, *, user_id: UUID) -> dict:
    """The current document + whether this user has accepted it."""
    return {**CURRENT, "accepted": has_accepted(db, user_id=user_id)}


def record_consent(db: Session, *, user_id: UUID, document_key: str, version: str) -> SolConsent:
    """Record acceptance of the CURRENT document. Idempotent (re-accepting the
    same version returns the existing row). Rejects accepting a stale/unknown
    document or version — a client can only accept what's currently in force."""
    if document_key != CURRENT["document_key"] or version != CURRENT["version"]:
        raise SolError(409, "that is not the current terms version — reload and try again")

    existing = db.scalar(
        select(SolConsent).where(
            SolConsent.user_id == user_id,
            SolConsent.document_key == document_key,
            SolConsent.version == version,
        )
    )
    if existing is not None:
        return existing

    consent = SolConsent(
        user_id=user_id, document_key=document_key, version=version,
        accepted_at=datetime.now(timezone.utc),
    )
    db.add(consent)
    try:
        db.commit()
    except IntegrityError:
        # concurrent accept won the race — return the persisted row
        db.rollback()
        return db.scalar(
            select(SolConsent).where(
                SolConsent.user_id == user_id,
                SolConsent.document_key == document_key,
                SolConsent.version == version,
            )
        )
    db.refresh(consent)
    return consent


def require_consent(db: Session, *, user_id: UUID) -> None:
    """Gate: raise 403 unless the user has accepted the current terms."""
    if not has_accepted(db, user_id=user_id):
        raise SolError(403, "Please accept the current terms before creating or joining a circle.")
