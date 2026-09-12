"""Inert hook-registry tests (Phase-1 unit #2).

Load-bearing invariant: with no handlers bound (Stage 1), nothing is armed and
dispatch fires nothing — and the arming gate requires handler + ACTIVE status +
kill-switch env all together (negative controls prove each is necessary).
Pure (no DB); conftest's DB coupling means it runs under the isolated test DB.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.hooks.registry import HookError, HookRegistry
from app.services.hooks.schemas import (
    EventEnvelope,
    HookDefinition,
    HookMode,
    HookStatus,
)

_NOW = datetime(2026, 9, 12, 4, 0, tzinfo=timezone.utc)


def _event(event_type="deployment.failed.v1"):
    return EventEnvelope(
        event_id="e1", event_type=event_type, source="ci",
        occurred_at=_NOW, received_at=_NOW, tenant_id="ws", principal="p",
        payload={},
    )


def _hook(hid="deployment.failed.collect_evidence", event_type="deployment.failed.v1",
          mode=HookMode.OBSERVE, status=HookStatus.INERT, kill_switch="", **over):
    base = dict(
        id=hid, owner="ops", event_type=event_type, mode=mode, status=status,
        kill_switch=kill_switch, evidence_contract="c", verification="v",
    )
    base.update(over)
    return HookDefinition(**base)


def test_register_get_list_and_duplicate():
    r = HookRegistry()
    r.register(_hook())
    assert r.ids() == ["deployment.failed.collect_evidence"]
    assert r.get("deployment.failed.collect_evidence").owner == "ops"
    with pytest.raises(HookError):
        r.register(_hook())
    with pytest.raises(KeyError):
        r.get("nope.hook")


def test_for_event_matches_event_type():
    r = HookRegistry()
    r.register(_hook(hid="a.b", event_type="deployment.failed.v1"))
    r.register(_hook(hid="c.d", event_type="mission.created.v1"))
    assert [h.id for h in r.for_event("deployment.failed.v1")] == ["a.b"]
    assert r.for_event("nonexistent.event.v1") == []


def test_bind_handler_unknown_refused():
    r = HookRegistry()
    with pytest.raises(KeyError):
        r.bind_handler("ghost.hook", lambda e: None)


def test_stage1_inert_nothing_armed_dispatch_empty():
    r = HookRegistry()
    r.register(_hook())
    r.register(_hook(hid="x.y", mode=HookMode.DRAFT, kill_switch="KAI_HOOK_X"))
    assert r.summary()["handlers_bound"] == 0
    assert all(not r.is_armed(hid) for hid in r.ids())
    assert r.dispatch(_event()) == []  # nothing fires


def test_arming_requires_handler_active_and_killswitch(monkeypatch):
    r = HookRegistry()
    r.register(_hook(hid="x.y", mode=HookMode.DRAFT, status=HookStatus.ACTIVE,
                     kill_switch="KAI_HOOK_X"))
    calls = []
    # no handler yet → not armed
    monkeypatch.setenv("KAI_HOOK_X", "1")
    assert r.is_armed("x.y") is False
    r.bind_handler("x.y", lambda e: calls.append(e.event_id) or "fired")
    # handler + ACTIVE + kill switch ON → armed, dispatch fires it
    assert r.is_armed("x.y") is True
    assert r.dispatch(_event()) == ["fired"] and calls == ["e1"]
    # kill switch OFF → not armed, dispatch fires nothing
    monkeypatch.delenv("KAI_HOOK_X")
    assert r.is_armed("x.y") is False
    calls.clear()
    assert r.dispatch(_event()) == [] and calls == []


def test_non_active_status_never_arms(monkeypatch):
    monkeypatch.setenv("KAI_HOOK_X", "1")
    for st in (HookStatus.INERT, HookStatus.QUARANTINED, HookStatus.EXPIRED, HookStatus.REVOKED):
        r = HookRegistry()
        r.register(_hook(hid="x.y", mode=HookMode.DRAFT, status=st, kill_switch="KAI_HOOK_X"))
        r.bind_handler("x.y", lambda e: "fired")
        assert r.is_armed("x.y") is False, st


def test_matching_armed_excludes_nonmatching_event(monkeypatch):
    monkeypatch.setenv("KAI_HOOK_X", "1")
    r = HookRegistry()
    r.register(_hook(hid="x.y", event_type="deployment.failed.v1", mode=HookMode.DRAFT,
                     status=HookStatus.ACTIVE, kill_switch="KAI_HOOK_X"))
    r.bind_handler("x.y", lambda e: "fired")
    assert [h.id for h in r.matching_armed(_event("deployment.failed.v1"))] == ["x.y"]
    assert r.matching_armed(_event("mission.created.v1")) == []


def test_summary_shape():
    r = HookRegistry()
    r.register(_hook())
    s = r.summary()
    assert s["total"] == 1 and s["handlers_bound"] == 0 and s["armed"] == 0
    assert s["by_status"] == {"INERT": 1} and s["by_mode"] == {"OBSERVE": 1}
