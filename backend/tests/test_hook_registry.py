"""Hook CATALOG tests (Phase-1 unit #2, corrected to catalog-only).

Load-bearing negative control: the registry has NO execution surface at all —
no handler binding, no arming, no dispatch, no flag evaluation — so no in-process
caller can activate a hook through it. If someone re-adds an execution path, the
`test_no_execution_surface_exists` control fails.
Pure (no DB); conftest's coupling means it runs under the dedicated test DB.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import app.services.hooks.registry as registry_module
from app.services.hooks.registry import HookError, HookRegistry
from app.services.hooks.schemas import HookDefinition, HookMode, HookStatus

_NOW = datetime(2026, 9, 12, 4, 0, tzinfo=timezone.utc)


def _hook(hid="deployment.failed.collect_evidence", event_type="deployment.failed.v1",
          mode=HookMode.OBSERVE, status=HookStatus.INERT, **over):
    base = dict(
        id=hid, owner="ops", event_type=event_type, mode=mode, status=status,
        evidence_contract="c", verification="v",
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


@pytest.mark.parametrize("status", [
    HookStatus.ACTIVE, HookStatus.QUARANTINED, HookStatus.EXPIRED, HookStatus.REVOKED,
])
def test_register_rejects_any_non_inert_hook(status):
    # Phase-1 catalog holds ONLY inert hooks (mirrors WorkforceCatalog's "status past
    # INERT" rejection), so a future HookDispatcher cannot find a pre-armed ACTIVE hook.
    r = HookRegistry()
    with pytest.raises(HookError, match="past INERT"):
        r.register(_hook(status=status))
    assert r.ids() == []  # nothing held


def test_for_event_matches_event_type():
    r = HookRegistry()
    r.register(_hook(hid="a.b", event_type="deployment.failed.v1"))
    r.register(_hook(hid="c.d", event_type="mission.created.v1"))
    assert [h.id for h in r.for_event("deployment.failed.v1")] == ["a.b"]
    assert r.for_event("nonexistent.event.v1") == []


def test_summary_reports_catalog_only():
    r = HookRegistry()
    r.register(_hook())
    s = r.summary()
    assert s["total"] == 1
    assert s["execution_supported"] is False
    assert s["by_status"] == {"INERT": 1} and s["by_mode"] == {"OBSERVE": 1}


def test_no_execution_surface_exists():
    """Catalog-only, by construction: no method or type through which any caller
    (in-process included) could bind or fire a hook, and no execution-flag
    evaluation. This control fails the moment an execution path is re-introduced."""
    r = HookRegistry()
    assert HookRegistry.execution_supported is False
    for forbidden in ("bind_handler", "is_armed", "matching_armed", "dispatch", "_handlers"):
        assert not hasattr(r, forbidden), f"{forbidden!r} must not exist on the catalog"
    # no handler type and no env/flag evaluation leaked into the module
    for forbidden in ("Handler", "_is_env_truthy", "Callable"):
        assert not hasattr(registry_module, forbidden), f"{forbidden!r} must not be in the registry module"
    # Allowlist teeth (independent-review hardening): the ONLY methods (public OR
    # private, dunders excluded) are the five catalog methods. This catches a
    # re-introduced execution method under ANY name — public (invoke/run/fire) or
    # private (_run/_dispatch) — that a public-only check would miss.
    methods = {n for n in dir(r) if callable(getattr(r, n)) and not (n.startswith("__") and n.endswith("__"))}
    assert methods == {"register", "get", "ids", "for_event", "summary"}, methods
