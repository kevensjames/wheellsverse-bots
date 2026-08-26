"""Pure tests for the seeded capability catalog — HONEST status, verified provenance (§73/§74).
Run: python3 backend/app/services/capability/test_capability_seed.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capability.manifest import CapabilityType as CT, Availability as AV, Certification as CE  # noqa: E402
from capability.seed import seed_registry, seed_graph, seed_manifests  # noqa: E402
from capability.brain import CapabilityBrain, Principal  # noqa: E402

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def t_catalog_loads():
    reg = seed_registry()
    assert len(reg) >= 15, f"expected the full catalog, got {len(reg)}"
    # every taxonomy target is represented
    for cid in ("kai-memory", "context7", "playwright", "reverse-skill", "airllm", "jcode",
                "geolibre", "openwork", "buzz", "tencentdb-memory", "book-to-skill", "focus-output"):
        assert reg.has(cid), f"missing {cid}"


def t_only_certified_are_available():
    """Only native caps + the CERTIFIED Context7 (connected+exercised) are AVAILABLE (§73/§3)."""
    reg = seed_registry()
    available = [m.id for m in reg.list(availability=AV.AVAILABLE)]
    assert set(available) == {"kai-memory", "claude-code", "context7"}, f"unexpected available set: {available}"


def t_external_not_selectable():
    """An upstream-verified-but-uninstalled capability is not selectable → never planned."""
    reg = seed_registry()
    for cid in ("geolibre", "airllm", "jcode", "openwork", "reverse-skill", "playwright"):
        assert not reg.get(cid).selectable(), f"{cid} must not be selectable until installed/certified"


def t_context7_certified_and_auto_routes():
    """§3: on the REAL seed the Brain selects Context7 for a docs query (no tool named); a greeting selects none."""
    reg, g = seed_registry(), seed_graph()
    brain = CapabilityBrain(reg, g)
    docs = brain.plan("Check the current official documentation for this FastAPI behavior.", Principal("u"))
    assert "context7" in docs.selected_ids(), f"docs query must auto-route to Context7, got {docs.summary}"
    greeting = brain.plan("Hello KAI.", Principal("u"))
    assert "context7" not in greeting.selected_ids() and greeting.selected_ids() == [], "a greeting must select nothing"


def t_reverse_skill_is_restricted_and_disabled():
    m = seed_registry().get("reverse-skill")
    assert m.risk_class.value == "RESTRICTED" and m.activation.value == "DISABLED"


def t_provenance_verified():
    for m in seed_manifests():
        if m.provenance.upstream:   # external ones carry a verified upstream
            assert m.provenance.verified is True and m.provenance.license, f"{m.id} provenance incomplete"


def t_geolibre_canonical_not_the_fork():
    m = seed_registry().get("geolibre")
    assert "opengeos/GeoLibre" in m.provenance.upstream, "must point at canonical opengeos, not the taka015 fork"


def t_memory_single_source_of_truth():
    """§31: TencentDB memory conflicts with KAI memory so both can never co-own canonical memory."""
    g = seed_graph()
    assert "kai-memory" in g.conflicts_with("tencentdb-memory")


def t_live_brain_on_real_seed_is_honest():
    """With the honest seed, the Brain plans only genuinely-available capabilities — no fake routing."""
    reg, g = seed_registry(), seed_graph()
    plan = CapabilityBrain(reg, g).plan("map these coordinates by region", Principal("u"))
    # geolibre matches by trigger but is DISCOVERED → must not be selected
    assert "geolibre" not in plan.selected_ids()
    # a memory ask routes to the native, available kai-memory
    plan2 = CapabilityBrain(reg, g).plan("remember what we learned here", Principal("u"))
    assert "kai-memory" in plan2.selected_ids()


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed" % _p)
