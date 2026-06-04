"""API key issuance, lookup, and revocation.

Keys are returned in plaintext exactly once (at create time) — only the
SHA-256 hash is stored. Lookup is a single indexed query; we hash the
incoming bearer token and look for a matching row.

Key format
----------
    kai_<32 url-safe chars>            (44 chars total)

Why SHA-256 over bcrypt:
    Keys are 256 bits of entropy from a CSPRNG. bcrypt's work factor is
    designed to slow down brute-force of LOW-entropy human passwords.
    Brute-forcing a 256-bit random token requires guessing 2^256 — bcrypt
    adds zero security here, just latency. A constant-time SHA hash is the
    standard pattern (Stripe, Linear, Anthropic all do this).
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.api_key import ApiKey

_KEY_PREFIX = "kai_"


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def issue(db: Session, user_id: uuid.UUID, label: Optional[str] = None) -> tuple[ApiKey, str]:
    """Mint a new key for the given user. Returns (row, plaintext). The plaintext
    is shown ONCE to the user and never again."""
    raw = _KEY_PREFIX + secrets.token_urlsafe(24)  # 32-ish url-safe chars
    row = ApiKey(
        user_id=user_id,
        key_hash=_hash(raw),
        prefix=raw[:11],  # 'kai_xxxxxxx' visible in dashboards / logs
        label=label.strip() if label else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, raw


def verify(db: Session, plaintext: str) -> Optional[ApiKey]:
    """Return the ApiKey row if the plaintext matches an active (not-revoked)
    key, else None. Updates last_used_at as a side effect."""
    if not plaintext or not plaintext.startswith(_KEY_PREFIX):
        return None
    row = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == _hash(plaintext), ApiKey.revoked_at.is_(None))
        .first()
    )
    if row is None:
        return None
    # Best-effort touch — not in a hot loop, so commit cost is fine.
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return row


def list_active(db: Session, user_id: uuid.UUID) -> list[ApiKey]:
    return (
        db.query(ApiKey)
        .filter(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
        .all()
    )


def revoke(db: Session, user_id: uuid.UUID, key_id: uuid.UUID) -> bool:
    """Revoke a key. Returns True if found+revoked, False if not found
    (404 case) or already revoked (idempotent — still returns True)."""
    row = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.user_id == user_id)
        .first()
    )
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return True
