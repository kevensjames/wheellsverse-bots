"""Pure tests for graph + lifecycle + the Capability Brain (routing/§60/§61/§65/§66).
Run: python3 backend/app/services/capability/test_capability_brain.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capability.manifest import (  # noqa: E402
    CapabilityManifest as CM, CapabilityType as CT, RiskClass, ActionClass, ActivationMode,
    Availability, Certification, ResourceProfile,
)
from capability.registry import CapabilityRegistry  # noqa: E402
from capability.graph import CapabilityGraph, Relation  # noqa: E402
from capability.lifecycle import PluginLifecycleManager, State  # noqa: E402
from capability.brain import CapabilityBrain, Principal, ResourceState, classify_intent  # noqa: E402

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def cap(cid, typ, triggers, risk=RiskClass.LOW, action=ActionClass.READ_ONLY, **kw):
    return CM(id=cid, name=cid, type=typ, triggers=triggers, risk_class=risk,
              default_action_class=action, availability=Availability.AVAILABLE,
              activation=ActivationMode.ON_DEMAND, certification=Certification.CERTIFIED, **kw)


def fixture():
    reg = CapabilityRegistry()
    reg.register_all([
        cap("filesystem", CT.MCP, ["repository", "file", "codebase"]),
        cap("context7", CT.MCP, ["documentation", "docs", "framework", "library"]),
        cap("github", CT.MCP, ["github", "commit", "pull request"], risk=RiskClass.MEDIUM),
        cap("playwright", CT.BROWSER_TOOL, ["browser", "mobile", "page", "screenshot"]),
        cap("jcode", CT.CODE_TOOL, ["coding worker", "lightweight"], risk=RiskClass.HIGH, action=ActionClass.REVERSIBLE_WRITE),
        cap("reverse-skill", CT.SECURITY_ROUTER, ["binary", "reverse", "malware"], risk=RiskClass.RESTRICTED),
        cap("geolibre", CT.GEOSPATIAL_TOOL, ["map", "coordinates", "region"], risk=RiskClass.MEDIUM),
        cap("kai-memory", CT.MEMORY_PROVIDER, ["remember", "memory", "recall"]),
        cap("book-to-skill", CT.AGENT_SKILL, ["pdf", "book", "learn this"], risk=RiskClass.MEDIUM),
        cap("ollama", CT.MODEL_RUNTIME, ["locally", "local model"]),
        cap("airllm", CT.MODEL_RUNTIME, ["locally", "local model"], risk=RiskClass.MEDIUM,
            resource_profile=ResourceProfile(vram_mb=4000, heavy=True, est_latency_ms=4000)),
        cap("doc-parser", CT.NATIVE_KAI_TOOL, ["__internal__"]),
    ])
    g = CapabilityGraph()
    g.add("ollama", Relation.ALTERNATIVE_TO, "airllm")          # interchangeable runtimes (§61)
    g.add("book-to-skill", Relation.REQUIRES, "doc-parser")      # dependency (§60)
    g.add("ollama", Relation.FALLBACK_FOR, "airllm")            # §30
    return reg, g


# ── graph ─────────────────────────────────────────────────────────────────────
def t_graph_symmetric_and_closure():
    g = CapabilityGraph()
    g.add("a", Relation.CONFLICTS_WITH, "b")
    assert "a" in g.conflicts_with("b") and "b" in g.conflicts_with("a")   # symmetric
    g.add("x", Relation.REQUIRES, "y"); g.add("y", Relation.REQUIRES, "z")
    assert g.requires_closure("x") == ["z", "y"]                            # deps first


def t_graph_cycle_raises():
    g = CapabilityGraph()
    g.add("a", Relation.REQUIRES, "b"); g.add("b", Relation.REQUIRES, "a")
    try:
        g.requires_closure("a"); assert False, "cycle should raise"
    except ValueError:
        pass


def t_graph_any_conflict():
    g = CapabilityGraph(); g.add("a", Relation.CONFLICTS_WITH, "b")
    assert g.any_conflict(["a", "b", "c"]) is not None
    assert g.any_conflict(["a", "c"]) is None


# ── lifecycle ─────────────────────────────────────────────────────────────────
def t_lifecycle_no_ready_without_health():
    lc = PluginLifecycleManager()
    lc.start("x")
    assert lc.mark_ready("x", health_ok=False) == State.FAILED     # failing health → FAILED, not READY
    lc2 = PluginLifecycleManager(); lc2.start("y")
    assert lc2.mark_ready("y", health_ok=True) == State.READY


def t_lifecycle_illegal_transition_raises():
    lc = PluginLifecycleManager()
    try:
        lc.activate("x"); assert False, "DISCOVERED → ACTIVE is illegal"
    except ValueError:
        pass


def t_lifecycle_deactivate_tears_down():
    lc = PluginLifecycleManager()
    lc.start("m"); lc.mark_ready("m", True); lc.activate("m")
    assert lc.deactivate("m", "task_complete") == State.OFFLINE
    try:
        lc.deactivate("m", "bogus_trigger"); assert False
    except ValueError:
        pass


# ── brain: intent ─────────────────────────────────────────────────────────────
def t_classify_intent():
    assert "docs" in classify_intent("Check current FastAPI documentation")
    assert "security" in classify_intent("reverse this binary")
    assert classify_intent("hello there") == set()


# ── brain: §65 automatic routing (no tool named by the user) ──────────────────
def t_route_docs():
    reg, g = fixture()
    plan = CapabilityBrain(reg, g).plan("Check the current FastAPI documentation for this problem.", Principal("u"))
    assert "context7" in plan.selected_ids(), plan.summary
    assert "playwright" not in plan.selected_ids()


def t_route_browser():
    reg, g = fixture()
    plan = CapabilityBrain(reg, g).plan("Verify this page on mobile.", Principal("u"))
    assert "playwright" in plan.selected_ids()


def t_route_security_needs_approval():
    reg, g = fixture()
    plan = CapabilityBrain(reg, g).plan("Analyze this binary from my authorized lab.", Principal("u"))
    rev = [s for s in plan.steps if s.cap_id == "reverse-skill"]
    assert rev and rev[0].needs_approval is True, "RESTRICTED capability must be approval-gated in the plan"


def t_route_geo():
    reg, g = fixture()
    plan = CapabilityBrain(reg, g).plan("Show these coordinates on a map.", Principal("u"))
    assert "geolibre" in plan.selected_ids()


def t_route_learning_with_dependency():
    reg, g = fixture()
    plan = CapabilityBrain(reg, g).plan("Learn this PDF.", Principal("u"))
    ids = plan.selected_ids()
    assert "book-to-skill" in ids
    # §60: the required doc-parser is emitted BEFORE book-to-skill
    assert ids.index("doc-parser") < ids.index("book-to-skill")


# ── brain: §61 conflict/alternative + §26 resources ───────────────────────────
def t_local_model_alternatives_pick_one():
    reg, g = fixture()
    plan = CapabilityBrain(reg, g).plan("Run the strongest model this machine can support locally.", Principal("u"))
    ids = [s.cap_id for s in plan.steps if not s.is_dependency]
    assert ("ollama" in ids) ^ ("airllm" in ids), f"exactly one runtime, got {ids}"
    assert "ollama" in ids, "the lighter/lower-risk alternative should win the tie"
    assert any(cid == "airllm" for cid, _ in plan.rejected)


def t_resource_filter_drops_unrunnable():
    reg, g = fixture()
    reg.unregister("ollama")   # force airllm to be the only runtime candidate
    tight = ResourceState(vram_mb=2000)   # less than airllm's 4000MB
    plan = CapabilityBrain(reg, g).plan("run this model locally", Principal("u"), resources=tight)
    assert "airllm" not in plan.selected_ids()
    assert any(cid == "airllm" and "resource" in reason for cid, reason in plan.rejected)


# ── brain: §66 do NOT activate everything ─────────────────────────────────────
def t_greeting_selects_nothing():
    reg, g = fixture()
    plan = CapabilityBrain(reg, g).plan("Hello there, how are you?", Principal("u"))
    assert plan.selected_ids() == [] and "No capability required" in plan.summary


def t_math_selects_nothing():
    reg, g = fixture()
    plan = CapabilityBrain(reg, g).plan("what is 2 + 2", Principal("u"))
    assert plan.selected_ids() == []


# ── brain: honesty — a non-selectable capability is never planned ─────────────
def t_unavailable_capability_not_selected():
    reg, g = fixture()
    reg.get("geolibre").availability = Availability.EXTERNAL_BLOCKED   # not runnable here
    plan = CapabilityBrain(reg, g).plan("map these coordinates by region", Principal("u"))
    assert "geolibre" not in plan.selected_ids(), "EXTERNAL_BLOCKED must never be selected (no fake availability)"


def t_selection_is_observable():
    reg, g = fixture()
    plan = CapabilityBrain(reg, g).plan("check the framework documentation", Principal("u"))
    step = [s for s in plan.steps if s.cap_id == "context7"][0]
    assert step.rationale.startswith("Selected context7 —") and "documentation" in step.rationale


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed" % _p)
