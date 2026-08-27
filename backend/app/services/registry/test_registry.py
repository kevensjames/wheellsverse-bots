"""Canonical-registry guard. Runnable with `python3 test_registry.py` (no framework).

Its whole job: make it impossible to silently lose a company or admin surface
from the Command Center again (directive §25), and to keep the registry honest
(no fabricated metric). If any assert fails, the registry regressed.
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from backend.app.services.registry.catalog import (   # noqa: E402
    registry_snapshot, systems, companies, CANONICAL_IDS,
    Status, DeployState, DataClass,
    TIER_HOLDING, TIER_BRAIN, TIER_COMPANY, TIER_PLATFORM, TIER_GOVERNANCE,
)

_TIERS = {TIER_HOLDING, TIER_BRAIN, TIER_COMPANY, TIER_PLATFORM, TIER_GOVERNANCE}
_STATUSES = {v for k, v in vars(Status).items() if not k.startswith("_") and isinstance(v, str)}
_DEPLOYS = {v for k, v in vars(DeployState).items() if not k.startswith("_") and isinstance(v, str)}
_DATACLASSES = {v for k, v in vars(DataClass).items() if not k.startswith("_") and isinstance(v, str)}

# The companies/surfaces the front door MUST always show. Losing any of these is
# exactly the incident that started Phase 0 — the test exists so it can't recur.
_MUST_EXIST = {
    "wheellsverse", "kai", "kai-capability-fabric",
    "sol", "narai", "nexora", "suprema", "nurtelle",
    "toodle", "siteboost", "shopify-merchants", "second-brain-inbox",
    "leadgen", "scoreboard", "hub", "app-a", "app-b",
}
# Surfaces verified LOST from the current /admin — recovery must keep them flagged
# so the UI resurfaces them (and nobody quietly re-drops them).
_MUST_BE_LOST = {"hub", "sol", "narai", "toodle", "siteboost", "scoreboard",
                 "leadgen", "second-brain-inbox"}


def test_snapshot_builds():
    snap = registry_snapshot()
    assert snap["counts"]["total"] == len(systems()) >= 35, snap["counts"]
    assert snap["systems"], "no systems"
    assert set(snap["tiers"]) == _TIERS


def test_no_company_or_surface_disappears():
    ids = {n.id for n in systems()}
    missing = _MUST_EXIST - ids
    assert not missing, f"REGRESSION — vanished from registry: {sorted(missing)}"
    # CANONICAL_IDS is the frozen contract; it must cover the must-exist set.
    assert _MUST_EXIST <= CANONICAL_IDS


def test_lost_surfaces_stay_flagged_for_recovery():
    lost = {n.id for n in systems() if n.lost_from_current}
    missing = _MUST_BE_LOST - lost
    assert not missing, f"lost surfaces silently un-flagged (would not resurface): {sorted(missing)}"


def test_ids_unique_and_wellformed():
    seen = set()
    for n in systems():
        assert n.id and n.id not in seen, f"dup/empty id: {n.id}"
        seen.add(n.id)
        assert n.name and n.summary, f"{n.id} missing name/summary"
        assert n.tier in _TIERS, f"{n.id} bad tier {n.tier}"
        assert n.status in _STATUSES, f"{n.id} bad status {n.status}"
        assert n.deploy in _DEPLOYS, f"{n.id} bad deploy {n.deploy}"
        if n.route:
            assert n.route.startswith("/"), f"{n.id} bad route {n.route}"
        if n.url:
            assert n.url.startswith("https://"), f"{n.id} non-https url {n.url}"


def test_honest_no_metric_without_a_real_source():
    """A node may only claim REAL/DERIVED metrics if it exposes a live probe.
    UNKNOWN status must never be paired with a REAL/DERIVED metric class."""
    for n in systems():
        assert n.metrics_class in _DATACLASSES, f"{n.id} bad metrics_class"
        if n.metrics_class in (DataClass.REAL, DataClass.DERIVED):
            assert n.probe, f"{n.id} claims {n.metrics_class} metrics but has no probe"
        if n.status == Status.UNKNOWN:
            assert n.metrics_class == DataClass.UNAVAILABLE, \
                f"{n.id} is UNKNOWN but shows {n.metrics_class} — never render UNKNOWN as healthy"


def test_nasa_hierarchy_shape():
    """WHEELLSVERSE on top (exactly one holding), KAI governing in the middle."""
    nodes = systems()
    holdings = [n for n in nodes if n.tier == TIER_HOLDING]
    assert len(holdings) == 1 and holdings[0].id == "wheellsverse", holdings
    brain_ids = {n.id for n in nodes if n.tier == TIER_BRAIN}
    assert "kai" in brain_ids, "KAI must sit in the BRAIN tier"
    assert companies(), "no company tier"


def test_sol_money_honesty():
    """SOL must never be shown as real-money live — prod is MOCK by design."""
    sol = next(n for n in systems() if n.id == "sol")
    assert "MOCK" in sol.summary, "SOL summary must state money mode is MOCK"
    assert sol.repo == "wheellsverse-sol", "SOL real backend is the separate repo"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        print(f"  ✓ {t.__name__}")
        passed += 1
    print(f"\n{passed}/{len(tests)} registry guard tests passed")
