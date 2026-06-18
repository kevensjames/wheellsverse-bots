from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Finding(BaseModel):
    id: str
    ts: str
    category: Literal["secret", "vuln", "backup"]
    severity: Literal["critical", "high", "medium", "low", "info"]
    tool: str
    title: str
    location: str
    fingerprint: str
    verified: bool = False
    metadata: dict = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        category: Literal["secret", "vuln", "backup"],
        severity: Literal["critical", "high", "medium", "low", "info"],
        tool: str,
        title: str,
        location: str,
        secret: str | None = None,
        verified: bool = False,
        metadata: dict | None = None,
    ) -> "Finding":
        basis = secret if secret is not None else f"{title}|{location}"
        fingerprint = hashlib.sha256(basis.encode("utf-8")).hexdigest()
        return cls(
            id=uuid.uuid4().hex,
            ts=_now_iso(),
            category=category,
            severity=severity,
            tool=tool,
            title=title,
            location=location,
            fingerprint=fingerprint,
            verified=verified,
            metadata=metadata if metadata is not None else {},
        )


class BackupStatus(BaseModel):
    repo: str = ""
    configured: bool = False
    last_snapshot_age_s: int | None = None
    check_ok: bool | None = None
    snapshot_count: int = 0


class RunnerStatus(BaseModel):
    tool: str
    ok: bool
    error: str | None = None
    duration_ms: int = 0


class Posture(BaseModel):
    mfa_enabled: bool = False
    user_table_present: bool = False
    plaintext_secret_files: list[str] = Field(default_factory=list)
    rate_limiting_present: bool | None = None
    governance_ok: bool = True
    scopes_enabled: list[str] = Field(default_factory=list)


class CategoryScore(BaseModel):
    name: str
    score: int | None  # None == "unknown"
    detail: str = ""


class SecurityScore(BaseModel):
    overall: int | None
    categories: list[CategoryScore] = Field(default_factory=list)


class SecuritySnapshot(BaseModel):
    generated_at: str = Field(default_factory=_now_iso)
    by: str = "scheduled"
    findings: list[Finding] = Field(default_factory=list)
    backup: BackupStatus = Field(default_factory=BackupStatus)
    runner_status: list[RunnerStatus] = Field(default_factory=list)
    posture: Posture = Field(default_factory=Posture)
    score: SecurityScore = Field(default_factory=lambda: SecurityScore(overall=None))
