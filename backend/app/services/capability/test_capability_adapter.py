"""Pure tests for the adapter boundary (§21/§22). Run: python3 .../test_capability_adapter.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capability.adapter import ExternalBlockedAdapter, CapabilityAdapter, Transport  # noqa: E402
from capability.results import ResultKind, Provenance  # noqa: E402

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def t_blocked_adapter_is_honest():
    a = ExternalBlockedAdapter("geolibre", "sandboxed network")
    assert a.health()["state"] == "OFFLINE"
    r = a.invoke({"op": "map"})
    assert r.kind == ResultKind.FAILURE and r.provenance == Provenance.UNAVAILABLE
    assert r.authorized is False and "EXTERNAL_BLOCKED" in r.summary


def t_blocked_adapter_cannot_start():
    a = ExternalBlockedAdapter("airllm")
    try:
        a.start(); assert False, "a blocked adapter must not start"
    except RuntimeError:
        pass


def t_abc_requires_all_methods():
    class Partial(CapabilityAdapter):
        pass
    try:
        Partial("x", Transport.MCP); assert False, "incomplete adapter must not instantiate"
    except TypeError:
        pass


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed" % _p)
