"""Hook-foundation contract tests (Phase 1). Pure schema validation — no DB, no
app runtime. The load-bearing checks are the fail-closed negative controls:
unsupported version, unknown field, digest tamper, and the authority-mode
obligations (a SAFE_AUTOMATIC hook missing any safeguard is refused).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.services.hooks.schemas import (
    DataSensitivity,
    EventEnvelope,
    HookDefinition,
    HookMode,
    HookStatus,
    payload_digest,
)

_NOW = datetime(2026, 9, 12, 3, 0, tzinfo=timezone.utc)


def _event(**over):
    base = dict(
        event_id="e1", event_type="deployment.failed.v1", source="ci",
        occurred_at=_NOW, received_at=_NOW, tenant_id="owner", principal="owner",
        payload={"b": 2, "a": 1},
    )
    base.update(over)
    return EventEnvelope(**base)


def _hook(**over):
    base = dict(
        id="deployment.failed.collect_evidence", owner="holding-operations",
        event_type="deployment.failed.v1", mode=HookMode.OBSERVE,
        evidence_contract="deployment_failure_v1", verification="logs_and_provider_status",
    )
    base.update(over)
    return HookDefinition(**base)


# ─── EventEnvelope ──────────────────────────────────────────────────────


def test_event_valid_and_digest_autocomputed():
    e = _event()
    assert e.data_sensitivity is DataSensitivity.INTERNAL
    # digest is order-independent and matches the payload
    assert e.payload_digest == payload_digest({"a": 1, "b": 2})


def test_event_rejects_unsupported_version():
    with pytest.raises(ValidationError, match="unsupported schema_version"):
        _event(schema_version="2")


def test_event_rejects_unknown_field():
    with pytest.raises(ValidationError):
        _event(surprise="x")  # extra='forbid' — fail closed


def test_event_rejects_bad_event_type():
    with pytest.raises(ValidationError, match="family.action.vN"):
        _event(event_type="deployment.failed")  # missing .vN


def test_event_rejects_digest_tamper():
    with pytest.raises(ValidationError, match="tamper"):
        _event(payload_digest="deadbeef")  # disagrees with payload


def test_event_accepts_matching_digest():
    good = payload_digest({"a": 1, "b": 2})
    assert _event(payload_digest=good).payload_digest == good


# ─── HookDefinition ─────────────────────────────────────────────────────


def test_hook_observe_minimal_defaults_inert():
    h = _hook()
    assert h.status is HookStatus.INERT
    assert h.kill_switch == ""  # OBSERVE needs no kill switch


def test_hook_nonobserve_requires_kill_switch():
    with pytest.raises(ValidationError, match="kill_switch"):
        _hook(mode=HookMode.DRAFT)  # DRAFT with no kill switch


def test_hook_approval_required_needs_policy():
    with pytest.raises(ValidationError, match="approval_policy"):
        _hook(mode=HookMode.APPROVAL_REQUIRED, kill_switch="KAI_HOOK_X")
    ok = _hook(mode=HookMode.APPROVAL_REQUIRED, kill_switch="KAI_HOOK_X",
               approval_policy="named + fresh bound single-use approval")
    assert ok.mode is HookMode.APPROVAL_REQUIRED


@pytest.mark.parametrize("drop", ["allowed_effects", "rollback", "expires_at"])
def test_hook_safe_automatic_requires_each_safeguard(drop):
    """Negative control: dropping ANY required safeguard refuses the hook, so the
    SAFE_AUTOMATIC obligation can't be silently weakened by a future edit."""
    full = dict(
        mode=HookMode.SAFE_AUTOMATIC, kill_switch="KAI_HOOK_X",
        allowed_effects=("quarantine_download",), rollback="restore_prev",
        expires_at=_NOW,
    )
    full.pop(drop)
    with pytest.raises(ValidationError, match=drop):
        _hook(**full)


def test_hook_safe_automatic_fully_specified_ok():
    h = _hook(
        id="mission.duplicate.suppress", mode=HookMode.SAFE_AUTOMATIC,
        kill_switch="KAI_HOOK_MISSION_DUP", allowed_effects=("suppress_duplicate",),
        rollback="none_needed_idempotent", expires_at=_NOW,
    )
    assert h.mode is HookMode.SAFE_AUTOMATIC and h.status is HookStatus.INERT


def test_hook_rejects_bad_id_and_extra_field():
    with pytest.raises(ValidationError):
        _hook(id="NotAHookId")
    with pytest.raises(ValidationError):
        _hook(surprise="x")
