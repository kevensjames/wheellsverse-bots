"""Computer-operation missions persisted on the EXISTING holding_worker_jobs table.

No new table and no new migration. `holding_worker_jobs` already provides everything a
remote mission needs -- mission_id, worker, task JSONB, status, claimed_by,
lease_expires_at, heartbeat_at, attempt/max_attempts, correlation_id, evidence JSONB and
a unique idempotency_key -- and it is the leased, exactly-once channel that has already
been proven in this codebase. Adding a parallel `kai_computer_missions` table would mean
a second lease implementation, a second reclaim path and a second place for the two to
disagree about which one is authoritative.

Mapping:
    worker            'kai-device:<device_id>'  -- who may claim it
    mission_id        the mission id
    task (JSONB)      the mission spec plus approvals and history
    status            the dispatch status
    claimed_by        the device holding the lease
    evidence (JSONB)  accumulated evidence entries

STOP is not stored here. It is a global condition, so it reuses `brakes`, which the rest
of the system already consults.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import SessionLocal
from app.services.holding import worker_jobs
from app.services.holding.computer_ops_dispatch import QUEUED, TERMINAL, Mission

WORKER_PREFIX = "kai-device:"
_STOP_KEY = "computer_ops_stop"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PgMissionStore:
    """Implements the dispatch MissionStore protocol over holding_worker_jobs."""

    # --- mapping ---------------------------------------------------------
    @staticmethod
    def _to_mission(row) -> Mission:
        task = row.task if isinstance(row.task, dict) else json.loads(row.task or "{}")
        m = Mission(
            mission_id=row.mission_id,
            tenant=task.get("tenant", "default"),
            device_id=task.get("device_id", ""),
            autonomy_mode=task.get("autonomy_mode", "OBSERVE"),
            objective=task.get("objective", ""),
            status=row.status,
            lease_owner=row.claimed_by,
            lease_expires_at=row.lease_expires_at,
            attempts=row.attempt or 0,
            evidence=(row.evidence if isinstance(row.evidence, list)
                      else json.loads(row.evidence or "[]")),
            approvals=task.get("approvals", []),
            history=task.get("history", []),
            attestation_digest=task.get("attestation_digest", ""),
        )
        m.spec = task.get("spec", {})  # type: ignore[attr-defined]
        m.correlation_id = row.correlation_id  # type: ignore[attr-defined]
        return m

    def _write(self, m: Mission) -> None:
        task = {
            "tenant": m.tenant, "device_id": m.device_id, "autonomy_mode": m.autonomy_mode,
            "objective": m.objective, "approvals": m.approvals, "history": m.history,
            "attestation_digest": m.attestation_digest,
            "spec": getattr(m, "spec", {}),
        }
        with SessionLocal() as s:
            worker_jobs._ensure(s)
            s.execute(text(
                "UPDATE holding_worker_jobs SET status=:st, claimed_by=:cb, "
                " lease_expires_at=:le, attempt=:at, task=CAST(:t AS JSONB), "
                " evidence=CAST(:ev AS JSONB) WHERE mission_id=:mid"),
                {"st": m.status, "cb": m.lease_owner, "le": m.lease_expires_at,
                 "at": m.attempts, "t": json.dumps(task), "ev": json.dumps(m.evidence),
                 "mid": m.mission_id})
            s.commit()

    # --- MissionStore protocol -------------------------------------------
    def get(self, mission_id: str) -> Mission | None:
        with SessionLocal() as s:
            worker_jobs._ensure(s)
            row = s.execute(text(
                "SELECT mission_id,status,claimed_by,lease_expires_at,attempt,task,evidence,"
                "correlation_id FROM holding_worker_jobs WHERE mission_id=:m"),
                {"m": mission_id}).fetchone()
        return self._to_mission(row) if row else None

    def put(self, m: Mission) -> None:
        self._write(m)

    def queued_for_device(self, device_id: str) -> list[Mission]:
        with SessionLocal() as s:
            worker_jobs._ensure(s)
            rows = s.execute(text(
                "SELECT mission_id,status,claimed_by,lease_expires_at,attempt,task,evidence,"
                "correlation_id FROM holding_worker_jobs WHERE worker=:w AND status=:q "
                "ORDER BY created_at ASC"),
                {"w": WORKER_PREFIX + device_id, "q": QUEUED}).fetchall()
        return [self._to_mission(r) for r in rows]

    def burn(self, key: str, expires_at: datetime) -> bool:
        """Single-use claim for approvals, on the same primitive device nonces use."""
        with SessionLocal() as s:
            s.execute(text(
                "CREATE TABLE IF NOT EXISTS kai_device_nonces ("
                " device_id TEXT NOT NULL, nonce TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL,"
                " burned_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (device_id, nonce))"))
            row = s.execute(text(
                "INSERT INTO kai_device_nonces (device_id,nonce,expires_at) VALUES "
                "('__approval__',:n,:e) ON CONFLICT (device_id,nonce) DO NOTHING RETURNING nonce"),
                {"n": key, "e": expires_at}).fetchone()
            s.commit()
        return row is not None

    # --- creation and queries --------------------------------------------
    def create(self, *, tenant: str, device_id: str, objective: str, autonomy_mode: str,
               workspace: str, allowed_apps: list[str], allowed_domains: list[str],
               max_duration_seconds: int, actor: str) -> Mission:
        mission_id = "cop-" + secrets.token_hex(8)
        corr = "corr-" + secrets.token_hex(6)
        spec = {"workspace": workspace, "allowed_apps": allowed_apps,
                "allowed_domains": allowed_domains,
                "max_duration_seconds": max_duration_seconds,
                "model_policy": "LOCAL_ONLY"}
        task = {"tenant": tenant, "device_id": device_id, "autonomy_mode": autonomy_mode,
                "objective": objective, "approvals": [], "attestation_digest": "",
                "spec": spec,
                "history": [{"event": "created", "at": _now().isoformat(), "actor": actor,
                             "autonomy_mode": autonomy_mode}]}
        with SessionLocal() as s:
            worker_jobs._ensure(s)
            s.execute(text(
                "INSERT INTO holding_worker_jobs (mission_id, idempotency_key, worker, task, "
                " status, correlation_id, evidence) VALUES "
                "(:mid,:key,:w,CAST(:t AS JSONB),:st,:corr,'[]'::jsonb)"),
                {"mid": mission_id, "key": "cop:" + mission_id,
                 "w": WORKER_PREFIX + device_id, "t": json.dumps(task),
                 "st": QUEUED, "corr": corr})
            s.commit()
        m = self.get(mission_id)
        assert m is not None
        return m

    def list_recent(self, limit: int = 50) -> list[Mission]:
        with SessionLocal() as s:
            worker_jobs._ensure(s)
            rows = s.execute(text(
                "SELECT mission_id,status,claimed_by,lease_expires_at,attempt,task,evidence,"
                "correlation_id FROM holding_worker_jobs WHERE worker LIKE :p "
                "ORDER BY created_at DESC LIMIT :l"),
                {"p": WORKER_PREFIX + "%", "l": limit}).fetchall()
        return [self._to_mission(r) for r in rows]

    def list_active(self) -> list[Mission]:
        return [m for m in self.list_recent(200) if m.status not in TERMINAL]

    def pause(self, mission_id: str, *, actor: str) -> Mission:
        m = self.get(mission_id)
        if m is None:
            raise ValueError("unknown mission")
        if m.status not in TERMINAL:
            m.status = "PAUSED"
            m.log("paused", actor=actor)
            self.put(m)
        return m

    # --- STOP (global, reuses the brakes concept) -------------------------
    def set_stop(self, engaged: bool, *, reason: str) -> None:
        with SessionLocal() as s:
            s.execute(text(
                "CREATE TABLE IF NOT EXISTS kai_computer_ops_stop ("
                " k TEXT PRIMARY KEY, engaged BOOLEAN NOT NULL, reason TEXT,"
                " changed_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
            s.execute(text(
                "INSERT INTO kai_computer_ops_stop (k,engaged,reason,changed_at) "
                "VALUES (:k,:e,:r,now()) ON CONFLICT (k) DO UPDATE SET "
                "engaged=EXCLUDED.engaged, reason=EXCLUDED.reason, changed_at=now()"),
                {"k": _STOP_KEY, "e": engaged, "r": reason})
            s.commit()

    def stop_engaged(self) -> bool:
        """Fails CLOSED: an unreachable stop table is treated as STOP engaged.

        If we cannot prove STOP is released, we must not hand out work. The opposite
        default would mean a database blip silently re-enables computer control.
        """
        try:
            with SessionLocal() as s:
                s.execute(text(
                    "CREATE TABLE IF NOT EXISTS kai_computer_ops_stop ("
                    " k TEXT PRIMARY KEY, engaged BOOLEAN NOT NULL, reason TEXT,"
                    " changed_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
                s.commit()
                row = s.execute(text("SELECT engaged FROM kai_computer_ops_stop WHERE k=:k"),
                                {"k": _STOP_KEY}).fetchone()
            return bool(row[0]) if row else False
        except Exception:
            return True

    def stop_state(self) -> dict[str, Any]:
        try:
            with SessionLocal() as s:
                row = s.execute(text(
                    "SELECT engaged,reason,changed_at FROM kai_computer_ops_stop WHERE k=:k"),
                    {"k": _STOP_KEY}).fetchone()
            if row is None:
                return {"engaged": False, "reason": None, "changed_at": None}
            return {"engaged": bool(row[0]), "reason": row[1],
                    "changed_at": row[2].isoformat() if row[2] else None}
        except Exception as exc:  # noqa: BLE001
            return {"engaged": True, "reason": f"stop state unreadable ({type(exc).__name__}); "
                                               "failing closed", "changed_at": None}

    # --- serialisation ----------------------------------------------------
    def to_json(self, m: Mission, *, full: bool = False) -> dict[str, Any]:
        base = {
            "mission_id": m.mission_id, "status": m.status, "device_id": m.device_id,
            "autonomy_mode": m.autonomy_mode, "objective": m.objective,
            "correlation_id": getattr(m, "correlation_id", None),
            "lease_owner": m.lease_owner,
            "lease_expires_at": m.lease_expires_at.isoformat() if m.lease_expires_at else None,
            "attempts": m.attempts,
            "attestation_digest": m.attestation_digest,
            "spec": getattr(m, "spec", {}),
            # A worker's claim and KAI's verdict are separate fields on purpose: the panel
            # must be able to show "the worker says it worked" WITHOUT implying it did.
            "worker_claimed_success": any(
                e.get("claim") == "succeeded" for e in m.evidence),
            "kai_verified_complete": m.status == "COMPLETED",
        }
        if full:
            base["evidence"] = m.evidence
            base["approvals"] = m.approvals
            base["history"] = m.history
        return base
