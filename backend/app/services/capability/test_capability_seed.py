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
    """Native caps + CERTIFIED foundation MCPs + the HERO policy are AVAILABLE (§73/§3/§4/§11)."""
    reg = seed_registry()
    available = [m.id for m in reg.list(availability=AV.AVAILABLE)]
    assert set(available) == {"kai-memory", "claude-code", "context7", "playwright", "hero"}, f"unexpected available set: {available}"


def t_external_not_selectable():
    """An upstream-verified-but-uninstalled capability is not selectable → never planned."""
    reg = seed_registry()
    for cid in ("geolibre", "airllm", "jcode", "openwork", "reverse-skill", "github", "filesystem"):
        assert not reg.get(cid).selectable(), f"{cid} must not be selectable until installed/certified"


def t_context7_certified_and_auto_routes():
    """§3: on the REAL seed the Brain selects Context7 for a docs query (no tool named); a greeting selects none."""
    reg, g = seed_registry(), seed_graph()
    brain = CapabilityBrain(reg, g)
    docs = brain.plan("Check the current official documentation for this FastAPI behavior.", Principal("u"))
    assert "context7" in docs.selected_ids(), f"docs query must auto-route to Context7, got {docs.summary}"
    greeting = brain.plan("Hello KAI.", Principal("u"))
    assert "context7" not in greeting.selected_ids() and greeting.selected_ids() == [], "a greeting must select nothing"


def t_playwright_certified_and_auto_routes():
    """§4: a browser-verification query auto-routes to Playwright (no tool named); a greeting selects none."""
    reg, g = seed_registry(), seed_graph()
    brain = CapabilityBrain(reg, g)
    plan = brain.plan("Verify the Nexus works correctly on a mobile viewport.", Principal("u"))
    assert "playwright" in plan.selected_ids(), f"a browser-verify query must auto-route to Playwright, got {plan.summary}"
    assert brain.plan("Hi there.", Principal("u")).selected_ids() == []


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


# ── expansion pack (§Expansion) ───────────────────────────────────────────────
def t_expansion_catalog_present():
    reg = seed_registry()
    for cid in ("appllama", "hero", "awesome-osint", "awesome-hacking",
                "payloads-all-the-things", "seclists", "cybersecurity-reference", "empire"):
        assert reg.has(cid), f"missing expansion capability {cid}"


def t_empire_is_restricted_disabled_and_never_auto():
    m = seed_registry().get("empire")
    assert m.security_tier == 4 and m.risk_class.value == "RESTRICTED" and m.activation.value == "DISABLED"
    assert m.automatic_activation_allowed is False and m.auto_selectable() is False
    assert m.target_allowlist_required and m.operator_approval_required and m.sandbox_required


def t_offensive_data_not_auto_selectable():
    reg = seed_registry()
    for cid in ("payloads-all-the-things", "seclists"):
        assert reg.get(cid).automatic_activation_allowed is False, f"{cid} must not auto-load (§7)"
        assert reg.get(cid).security_tier == 2 and reg.get(cid).authorized_context_required


def t_cybersecurity_reference_unresolved_disabled():
    m = seed_registry().get("cybersecurity-reference")
    assert m.certification.value == "UPSTREAM_UNRESOLVED" and m.activation.value == "DISABLED"


def t_appllama_not_selectable_until_installed():
    """Honesty: AppLlama is upstream-verified but NOT installed → DISCOVERED → not auto-routed live."""
    assert seed_registry().get("appllama").auto_selectable() is False


def t_appllama_routing_logic_when_installed():
    """§4/§29: IF installed, a mobile-design task auto-routes to AppLlama; ordinary backend work does not."""
    reg, g = seed_registry(), seed_graph()
    reg.get("appllama").availability = AV.AVAILABLE   # simulate install to exercise the routing logic
    brain = CapabilityBrain(reg, g)
    mobile = brain.plan("Build a premium mobile onboarding flow for a pregnancy app.", Principal("u"))
    assert "appllama" in mobile.selected_ids(), f"mobile task must route to AppLlama, got {mobile.summary}"
    backend = brain.plan("Fix the database connection pool in the billing service.", Principal("u"))
    assert "appllama" not in backend.selected_ids(), "AppLlama must NOT activate for ordinary backend work"


def t_empire_never_selected_by_natural_language():
    reg, g = seed_registry(), seed_graph()
    brain = CapabilityBrain(reg, g)
    for prompt in ("Explain what cross-site scripting is.",
                   "Run a penetration test.",
                   "Do adversary emulation against example.com."):
        assert "empire" not in brain.plan(prompt, Principal("u")).selected_ids(), f"Empire auto-selected for: {prompt}"


# ── coding agent pool (§Coding) ───────────────────────────────────────────────
def t_coding_pool_present():
    reg = seed_registry()
    for cid in ("claude-code", "codex", "cline", "gemini-cli", "github-copilot-cli", "windsurf", "roo", "jcode"):
        assert reg.has(cid), f"missing coding worker {cid}"
        if cid != "windsurf" and cid != "roo":
            assert reg.get(cid).worker_profile is not None, f"{cid} needs a worker_profile"


def t_windsurf_interactive_only_never_auto():
    m = seed_registry().get("windsurf")
    assert m.worker_profile.interactive_only is True and m.worker_profile.headless_support is False
    assert m.auto_selectable() is False, "an interactive-only IDE cannot be auto-routed for unattended work"


def t_roo_archived_disabled():
    m = seed_registry().get("roo")
    assert m.certification.value == "REJECTED" and m.activation.value == "DISABLED"
    assert m.auto_selectable() is False


def t_coding_workers_not_auto_until_installed():
    reg = seed_registry()
    for cid in ("codex", "cline", "gemini-cli", "github-copilot-cli"):
        assert reg.get(cid).auto_selectable() is False, f"{cid} verified-but-not-installed → not auto-routed"


def t_live_coding_routes_to_claude_code():
    """On the real seed only claude-code is an AVAILABLE coding worker, so an implement task routes to it."""
    reg, g = seed_registry(), seed_graph()
    plan = CapabilityBrain(reg, g).plan("Implement this API endpoint and write the tests.", Principal("u"))
    ids = plan.selected_ids()
    assert "claude-code" in ids, f"implement task must route to the available worker, got {plan.summary}"
    for other in ("codex", "cline", "gemini-cli"):
        assert other not in ids, f"{other} is not installed and must not be selected"


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed" % _p)
