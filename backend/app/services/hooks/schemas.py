"""Versioned hook-foundation contracts — the first Phase-1 deliverable.

Two schemas, both fail closed:

* ``EventEnvelope`` — the typed, versioned envelope every KAI event must carry
  (identity, tenant/principal, causal chain, digested payload, sensitivity).
  Unknown fields, unsupported versions, and payload-digest tampering are refused.

* ``HookDefinition`` — the declarative description of one hook (§2.2 of the build
  plan). Its authority mode carries governance obligations that are enforced at
  CONSTRUCTION, mirroring the capability-exchange invariant: a ``SAFE_AUTOMATIC``
  hook that cannot prove it has an allowlisted effect + rollback + expiry + kill
  switch is refused before it can ever be registered.

Nothing here executes. There is no event bus, no worker, no registry. These are
contracts; the runtime that consumes them is a later, separately-gated stage.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bump only with a migration path; unknown/absent versions fail closed.
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1"})

# family.action.vN — lowercase, dot-separated, explicitly versioned.
_EVENT_TYPE_RE = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_]+)+\.v\d+$")
# family.action[.qualifier] — a hook id (not necessarily version-suffixed).
_HOOK_ID_RE = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_]+)+$")


class HookMode(str, Enum):
    """Authority a hook may exercise (build plan §2.1)."""

    OBSERVE = "OBSERVE"                    # read/classify/measure/record
    DRAFT = "DRAFT"                        # produce an artifact, no external effect
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"  # pause with an exact proposed effect
    SAFE_AUTOMATIC = "SAFE_AUTOMATIC"     # narrow, reversible, pre-authorized effect


class HookStatus(str, Enum):
    INERT = "INERT"              # declared, cannot fire (Phase 1 default)
    ACTIVE = "ACTIVE"           # eligible to fire (a later, separately-gated stage)
    QUARANTINED = "QUARANTINED"  # held after a fault; no firing
    EXPIRED = "EXPIRED"         # past expires_at; no firing
    REVOKED = "REVOKED"         # owner/security disabled; no firing


class DataSensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    SENSITIVE = "SENSITIVE"
    SECRET = "SECRET"


def payload_digest(payload: Any) -> str:
    """SHA-256 of the canonical JSON of a payload. Stable, order-independent."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class EventEnvelope(BaseModel):
    """Typed, versioned envelope for one KAI event. Frozen and fail-closed:
    unknown fields are rejected (extra='forbid'), an unsupported schema_version
    is refused, and payload_digest is derived from the payload — a caller-supplied
    digest that disagrees is treated as tampering and rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1"
    event_id: str
    event_type: str
    source: str
    occurred_at: datetime
    received_at: datetime
    # Single-owner backend: tenant is the owning principal. The field exists so
    # the contract stays correct if real multi-tenancy is added later; today it
    # is owner-scoped, and cross-"tenant" checks are structurally present.
    tenant_id: str
    principal: str
    mission_id: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    trace_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_digest: Optional[str] = None
    data_sensitivity: DataSensitivity = DataSensitivity.INTERNAL

    @model_validator(mode="before")
    @classmethod
    def _validate_and_digest(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        version = data.get("schema_version", "1")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"unsupported schema_version {version!r} "
                f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}) — failing closed"
            )
        etype = data.get("event_type", "")
        if not _EVENT_TYPE_RE.match(etype or ""):
            raise ValueError(
                f"event_type {etype!r} must look like 'family.action.vN'"
            )
        computed = payload_digest(data.get("payload") or {})
        supplied = data.get("payload_digest")
        if supplied is not None and supplied != computed:
            raise ValueError("payload_digest does not match payload — refusing (tamper)")
        data["payload_digest"] = computed
        return data


class HookDefinition(BaseModel):
    """Declarative description of one hook (build plan §2.2). Frozen, fail-closed.
    Authority obligations are enforced at construction so the registry can never
    hold a hook whose declared mode outruns its declared safeguards."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    version: int = 1
    owner: str
    event_type: str
    mode: HookMode
    conditions: tuple[str, ...] = ()
    tenant_scope: tuple[str, ...] = ()
    data_classes: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    allowed_effects: tuple[str, ...] = ()
    network_domains: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    timeout_seconds: int = 30
    retry_policy: str = "bounded_exponential"
    idempotency_template: str = "{event_id}:{hook_id}:{version}"
    budget_policy: str = "no_spend"
    approval_policy: Optional[str] = None
    evidence_contract: str
    verification: str
    rollback: Optional[str] = None
    kill_switch: str = ""
    status: HookStatus = HookStatus.INERT
    expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _enforce_authority_obligations(self) -> "HookDefinition":
        if not _HOOK_ID_RE.match(self.id):
            raise ValueError(f"hook id {self.id!r} must look like 'family.action[.qualifier]'")
        if not _EVENT_TYPE_RE.match(self.event_type):
            raise ValueError(f"event_type {self.event_type!r} must look like 'family.action.vN'")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not self.idempotency_template.strip():
            raise ValueError("idempotency_template is required (at-least-once delivery)")

        # Any hook that can cause an effect needs a kill switch.
        if self.mode is not HookMode.OBSERVE and not self.kill_switch.strip():
            raise ValueError(f"{self.id}: mode {self.mode.value} requires a kill_switch")

        if self.mode is HookMode.APPROVAL_REQUIRED:
            if not self.approval_policy or self.approval_policy.strip().lower() in ("", "none"):
                raise ValueError(f"{self.id}: APPROVAL_REQUIRED needs an approval_policy")

        if self.mode is HookMode.SAFE_AUTOMATIC:
            # §2.1: an automatic action needs an explicit allowlisted operation,
            # rollback, expiration, owner, and kill switch. Refuse to even declare
            # one that skips any of these.
            missing = [
                name for name, ok in (
                    ("allowed_effects", bool(self.allowed_effects)),
                    ("rollback", bool(self.rollback)),
                    ("expires_at", self.expires_at is not None),
                    ("owner", bool(self.owner.strip())),
                    ("kill_switch", bool(self.kill_switch.strip())),
                ) if not ok
            ]
            if missing:
                raise ValueError(
                    f"{self.id}: SAFE_AUTOMATIC requires {', '.join(missing)} "
                    "(explicit allowlisted effect + rollback + expiry + owner + kill switch)"
                )
        return self
