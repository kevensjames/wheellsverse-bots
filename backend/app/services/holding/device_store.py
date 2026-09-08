"""Postgres-backed stores for device identity and computer-operation missions.

Raw SQL against the DDL in migration 0008 rather than ORM models: the tables are narrow,
the queries are few, and the security-critical operations (nonce burn, lease claim) are
single statements whose exact semantics matter more than mapping convenience. An ORM
would obscure precisely the parts that must be read carefully.

Every burn/claim is written so the DATABASE arbitrates concurrency -- `ON CONFLICT DO
NOTHING RETURNING` and `FOR UPDATE SKIP LOCKED` -- so correctness does not depend on
there being one worker process.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text

from app.database import SessionLocal
from app.services.holding.device_identity import DeviceRecord, PairingRecord


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PgDeviceStore:
    """Implements the DeviceStore protocol from device_identity."""

    # --- devices ---------------------------------------------------------
    def get_device(self, device_id: str) -> DeviceRecord | None:
        with SessionLocal() as s:
            row = s.execute(text(
                "SELECT device_id,name,public_key,status,granted_scopes,os,arch,"
                "created_at,confirmed_at,last_seen_at,key_rotated_at,revoked_at,revocation_reason "
                "FROM kai_devices WHERE device_id=:d"), {"d": device_id}).fetchone()
        if row is None:
            return None
        return DeviceRecord(
            device_id=row[0], name=row[1], public_key=bytes(row[2]), status=row[3],
            granted_scopes=set(row[4] or []), os=row[5] or "", arch=row[6] or "",
            created_at=row[7], confirmed_at=row[8], last_seen_at=row[9],
            key_rotated_at=row[10], revoked_at=row[11], revocation_reason=row[12] or "")

    def put_device(self, r: DeviceRecord) -> None:
        with SessionLocal() as s:
            s.execute(text(
                "INSERT INTO kai_devices (device_id,name,public_key,status,granted_scopes,os,arch,"
                " created_at,confirmed_at,last_seen_at,key_rotated_at,revoked_at,revocation_reason) "
                "VALUES (:d,:n,:k,:st,CAST(:sc AS jsonb),:os,:ar,:c,:cf,:ls,:kr,:rv,:rr) "
                "ON CONFLICT (device_id) DO UPDATE SET name=EXCLUDED.name, "
                " public_key=EXCLUDED.public_key, status=EXCLUDED.status, "
                " granted_scopes=EXCLUDED.granted_scopes, os=EXCLUDED.os, arch=EXCLUDED.arch, "
                " confirmed_at=EXCLUDED.confirmed_at, last_seen_at=EXCLUDED.last_seen_at, "
                " key_rotated_at=EXCLUDED.key_rotated_at, revoked_at=EXCLUDED.revoked_at, "
                " revocation_reason=EXCLUDED.revocation_reason"),
                {"d": r.device_id, "n": r.name, "k": r.public_key, "st": r.status,
                 "sc": json.dumps(sorted(r.granted_scopes)), "os": r.os, "ar": r.arch,
                 "c": r.created_at, "cf": r.confirmed_at, "ls": r.last_seen_at,
                 "kr": r.key_rotated_at, "rv": r.revoked_at, "rr": r.revocation_reason})
            s.commit()

    def list_devices(self) -> list[DeviceRecord]:
        with SessionLocal() as s:
            ids = [r[0] for r in s.execute(text(
                "SELECT device_id FROM kai_devices ORDER BY created_at DESC")).fetchall()]
        return [d for d in (self.get_device(i) for i in ids) if d is not None]

    # --- pairings --------------------------------------------------------
    def get_pairing(self, code_hash: str) -> PairingRecord | None:
        with SessionLocal() as s:
            row = s.execute(text(
                "SELECT code_hash,device_name,expires_at,created_by,consumed_at "
                "FROM kai_device_pairings WHERE code_hash=:h"), {"h": code_hash}).fetchone()
        if row is None:
            return None
        return PairingRecord(code_hash=row[0], device_name=row[1], expires_at=row[2],
                             created_by=row[3], consumed_at=row[4])

    def put_pairing(self, r: PairingRecord) -> None:
        with SessionLocal() as s:
            s.execute(text(
                "INSERT INTO kai_device_pairings (code_hash,device_name,created_by,expires_at,consumed_at) "
                "VALUES (:h,:n,:b,:e,:c) ON CONFLICT (code_hash) DO UPDATE "
                "SET consumed_at=EXCLUDED.consumed_at"),
                {"h": r.code_hash, "n": r.device_name, "b": r.created_by,
                 "e": r.expires_at, "c": r.consumed_at})
            s.commit()

    # --- nonces ----------------------------------------------------------
    def seen_nonce(self, device_id: str, nonce: str) -> bool:
        with SessionLocal() as s:
            return s.execute(text(
                "SELECT 1 FROM kai_device_nonces WHERE device_id=:d AND nonce=:n"),
                {"d": device_id, "n": nonce}).fetchone() is not None

    def burn_nonce(self, device_id: str, nonce: str, expires_at: datetime) -> bool:
        """Atomic single-use claim.

        The RETURNING row is the whole mechanism: exactly one concurrent caller gets a
        row back, so two identical requests arriving together cannot both proceed. An
        unreachable database raises rather than returning True, so the caller fails CLOSED.
        """
        with SessionLocal() as s:
            row = s.execute(text(
                "INSERT INTO kai_device_nonces (device_id,nonce,expires_at) "
                "VALUES (:d,:n,:e) ON CONFLICT (device_id,nonce) DO NOTHING RETURNING nonce"),
                {"d": device_id, "n": nonce, "e": expires_at}).fetchone()
            s.commit()
        return row is not None

    def sweep_expired(self) -> int:
        """Bounded retention: burned nonces are only needed until they could be replayed."""
        with SessionLocal() as s:
            n = s.execute(text("DELETE FROM kai_device_nonces WHERE expires_at < now()")).rowcount
            s.execute(text("DELETE FROM kai_device_pairings WHERE expires_at < now() - interval '1 day'"))
            s.commit()
        return n or 0
