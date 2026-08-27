"""Canonical-registry guard. Runnable with `python3 test_registry.py` (no framework).

Its whole job: make it impossible to silently lose a company or admin surface
from the Command Center again (directive §25), and to keep the registry honest
(no fabricated metric). If any assert fails, the registry regressed.
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from backend.app.services.registry.catalog import (   # noqa: E402
    registry_snapshot, systems, companies,
    Status, DeployState, DataClass,
    TIER_HOLDING, TIER_BRAIN, TIER_COMPANY, TIER_PLATFORM, TIER_GOVERNANCE,
)

_TIERS = {TIER_HOLDING, TIER_BRAIN, TIER_COMPANY, TIER_PLATFORM, TIER_GOVERNANCE}
_STATUSES = {v for k, v in vars(Status).items() if not k.startswith("_") and isinstance(v, str)}
_DEPLOYS = {v for k, v in vars(DeployState).items() if not k.startswith("_") and isinstance(v, str)}
_DATACLASSES = {v for k, v in vars(DataClass).items() if not k.startswith("_") and isinstance(v, str)}

# FROZEN CONTRACT (directive §25). These literals are the FULL id-sets present when
# the Command Center shipped — NOT a hand-picked subset. The guard asserts the live
# catalog is a SUPERSET of each: ADDING a node passes freely (no edit needed here),
# REMOVING one FAILS CI. A surface may leave the front door only by a deliberate,
# reviewed edit to this set — never silently. This is the real fix for the Phase-0
# '/admin wipeout': a subset allowlist cannot catch the deletion of an *unlisted*
# surface, so it must cover every id and be checked as a superset, not a sample.
# Derived from `python3 catalog.py`; regenerate deliberately when retiring a system.
_GOLDEN_IDS = frozenset({
    'wheellsverse', 'kai', 'kai-capability-fabric', 'kai-command-nexus',
    'kai-mission-nexus', 'kai-voice', 'ai-workforce', 'wmos-portfolio-hq',
    'sol', 'narai', 'nexora', 'suprema',
    'nurtelle', 'toodle', 'siteboost', 'shopify-merchants',
    'second-brain-inbox', 'leadgen', 'scoreboard', 'amazon-kdp',
    'printify', 'app-a', 'app-b', 'apex-proxy',
    'ci-docker-push', 'ci-phase0-gate', 'hub', 'legacy-dashboard',
    'ceo-dashboard', 'wvkey', 'avatar-lab', 'theme-picker',
    'auth-rbac', 'kai-bridge', 'governance-audit', 'kai-self-audit',
    'reasoning-sanitizer', 'spend-caps', 'sentry',
})
# Every company/startup — none may be dropped or moved out of the COMPANY tier.
_GOLDEN_COMPANIES = frozenset({
    'sol', 'narai', 'nexora', 'suprema', 'nurtelle', 'toodle', 'siteboost',
    'shopify-merchants', 'second-brain-inbox', 'leadgen', 'scoreboard',
    'amazon-kdp', 'printify',
})
# Every surface verified LOST from the current /admin. The set of currently-lost ids
# must never SHRINK below this — un-flagging any of them would silently drop its
# RECOVERED label and under-report the 'Recovered Surfaces' KPI.
_GOLDEN_LOST = frozenset({
    'kai-voice', 'wmos-portfolio-hq', 'sol', 'narai', 'nexora', 'suprema',
    'toodle', 'siteboost', 'second-brain-inbox', 'leadgen', 'scoreboard',
    'amazon-kdp', 'printify', 'hub', 'legacy-dashboard', 'wvkey',
})


def test_snapshot_builds():
    snap = registry_snapshot()
    # floor is the golden size — the catalog can only grow, never silently shrink
    assert snap["counts"]["total"] == len(systems()) >= len(_GOLDEN_IDS), snap["counts"]
    assert snap["systems"], "no systems"
    assert set(snap["tiers"]) == _TIERS
    # defense-in-depth: the contract itself must not be gutted below its shipped size
    assert len(_GOLDEN_IDS) >= 39, "golden contract shrank — never weaken the guard to pass"


def test_no_company_or_surface_disappears():
    ids = {n.id for n in systems()}
    missing = _GOLDEN_IDS - ids   # SUPERSET check: any removal from the catalog fails here
    assert not missing, f"REGRESSION — vanished from the front door: {sorted(missing)}"
    # every frozen company must still be present AND still tiered as a company
    companies_now = {n.id for n in systems() if n.tier == TIER_COMPANY}
    dropped = _GOLDEN_COMPANIES - companies_now
    assert not dropped, f"company dropped or moved out of the COMPANY tier: {sorted(dropped)}"


def test_lost_surfaces_stay_flagged_for_recovery():
    lost = {n.id for n in systems() if n.lost_from_current}
    missing = _GOLDEN_LOST - lost   # the lost-set may never shrink below the golden lost-set
    assert not missing, f"lost surfaces silently un-flagged (RECOVERED label + KPI under-report): {sorted(missing)}"


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


def test_serving_now_never_counts_nonrunning():
    """'serving_now' is the honest liveness count. A DORMANT/HISTORICAL/LOCAL/
    PRE_DEPLOY node — even if deploy-classified LIVE_PROD — must never be counted
    as serving (configured != running). serving_now <= live_prod always."""
    c = registry_snapshot()["counts"]
    running = [n for n in systems()
               if n.deploy == DeployState.LIVE_PROD and n.status in (Status.HEALTHY, Status.DEGRADED)]
    assert c["serving_now"] == len(running), (c["serving_now"], len(running))
    assert c["serving_now"] <= c["live_prod"], "serving_now cannot exceed deploy-classified prod"
    # no node reported as serving may carry a not-running status
    for n in running:
        assert n.status not in (Status.DORMANT, Status.LOCAL, Status.PRE_DEPLOY, Status.HISTORICAL, Status.UNKNOWN)


def test_public_snapshot_strips_evidence():
    """The HTTP endpoint serves include_evidence=False: no source file:line pointer
    reaches an anonymous caller. The internal snapshot keeps it (for the inspector)."""
    pub = registry_snapshot(include_evidence=False)
    assert all("evidence" not in s for s in pub["systems"]), "public snapshot leaked evidence pointers"
    internal = registry_snapshot(include_evidence=True)
    assert any(s.get("evidence") for s in internal["systems"]), "internal snapshot lost its evidence"


def test_no_status_deploy_contradiction():
    """A node whose status says it only runs locally must not also be deploy=LIVE_PROD
    (the wvkey contradiction the review caught). LOCAL means 'not deployed'."""
    for n in systems():
        if n.status == Status.LOCAL:
            assert n.deploy != DeployState.LIVE_PROD, \
                f"{n.id}: status LOCAL contradicts deploy LIVE_PROD"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        print(f"  ✓ {t.__name__}")
        passed += 1
    print(f"\n{passed}/{len(tests)} registry guard tests passed")
