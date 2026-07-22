"""Authenticated approver identity for the SWE agent's destructive gates.

Until now `approver` was a self-declared string in the request body — the audit
trail recorded whatever the caller typed. This resolves it against a real row in
`admin_users` (already in 0001_initial_schema) via a per-human token, so an
approval names an identity the caller had to prove.

Token hashing reuses the api_keys precedent (SHA-256 over a high-entropy random
token; see app/services/api_keys.py for why not bcrypt). The token hash lives in
admin_users.password_hash.

Provision an approver:
    python -c "import secrets,hashlib; t=secrets.token_urlsafe(32); \
print('token:',t); print('hash:',hashlib.sha256(t.encode()).hexdigest())"
    psql -c "INSERT INTO admin_users (email, password_hash, role) \
VALUES ('you@example.com', '<hash>', 'approver')"

Separation of duties (approver != submitter) is enforced only when
KAI_SWE_REQUIRE_TWO_PERSON=1 — meaningless on a single-operator install, three
lines when a second operator exists.
"""
from __future__ import annotations

import hashlib
import os

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db


def two_person_required() -> bool:
    return (os.environ.get("KAI_SWE_REQUIRE_TWO_PERSON") or "").strip().lower() in (
        "1", "true", "yes", "on")


def require_approver(
    x_approver_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> str:
    """Return the approver's email, or 403. The identity comes from the token —
    never from the request body."""
    if not x_approver_token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "X-Approver-Token required")
    digest = hashlib.sha256(x_approver_token.encode("utf-8")).hexdigest()
    row = db.execute(
        text("SELECT email FROM admin_users WHERE password_hash = :h"), {"h": digest}
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "unknown approver token")
    return row[0]
