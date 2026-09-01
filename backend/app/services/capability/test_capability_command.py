"""KAI Brain → execution bridge tests (§27/§28/§29).

Proves the Brain SELECTS a capability and the SAME execution service runs it — one path, no second
brain. A greeting selects nothing; an explicit-only capability (yt-dlp) is not auto-selected.
Run: python3 <this file>.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capability.seed import seed_registry, seed_graph                       # noqa: E402
from capability.brain import CapabilityBrain, Principal                     # noqa: E402
from capability.execution import CapabilityExecutionService, Status         # noqa: E402
from capability.command import plan_and_execute, default_v1_operation       # noqa: E402

_p = 0
OWNER = Principal(id="owner-1", role="owner")


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _brain_and_service():
    reg, g = seed_registry(), seed_graph()
    return CapabilityBrain(reg, g), CapabilityExecutionService(reg)


def t_default_v1_operation_map():
    assert default_v1_operation("markitdown") == "convert"
    assert default_v1_operation("yt-dlp") == "metadata"
    assert default_v1_operation("empire") is None      # restricted → no V1 op


def t_brain_selects_and_service_executes():
    """A document-convert utterance routes to markitdown and runs through the ONE service.
    On base python the adapter is OFFLINE, so the honest result is CAPABILITY_UNAVAILABLE — but the
    Brain→service wiring is proven (selected + operation + a real governed execution attempt)."""
    brain, svc = _brain_and_service()
    out = plan_and_execute(brain, svc, "Please parse this file into markdown.", OWNER,
                           {"fixture": "sample-report"}, mission_id="m1")
    assert out["selected"] == "markitdown" and out["operation"] == "convert", out
    assert out["result"].status in (Status.OK, Status.CAPABILITY_UNAVAILABLE), out["result"].status


def t_greeting_selects_nothing():
    brain, svc = _brain_and_service()
    out = plan_and_execute(brain, svc, "Hello KAI.", OWNER, {})
    assert out["selected"] is None and out["result"] is None


def t_ytdlp_is_explicit_only_not_auto_selected():
    """§27: yt-dlp is automatic_activation_allowed=False → the Brain never auto-routes to it."""
    brain, svc = _brain_and_service()
    out = plan_and_execute(brain, svc, "Get the metadata for this public video url.", OWNER,
                           {"url": "https://1.1.1.1/"})
    assert out["selected"] != "yt-dlp", "yt-dlp must be explicit-invocation-only, never auto-selected"


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed" % _p)
