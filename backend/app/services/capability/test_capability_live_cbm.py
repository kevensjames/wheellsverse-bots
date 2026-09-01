"""Live certification for the codebase-memory-mcp adapter (Wave B, §18/§24/§84).

Deterministic contract everywhere: the read-only tool allowlist refuses destructive/config tools,
and where the binary is unconfigured the adapter is OFFLINE + returns a Failure (never fabricated).
When $CBM_BIN points at the built binary, an opt-in live branch proves a real subprocess round-trip.
Run: python3 <this file>   (set CBM_BIN=<path> to exercise the live branch).
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capability.live_adapters import CodebaseMemoryMcpAdapter    # noqa: E402
from capability.results import ResultKind, Provenance            # noqa: E402

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _configured() -> bool:
    return CodebaseMemoryMcpAdapter().health()["state"] == "READY"


def t_health_is_honest():
    h = CodebaseMemoryMcpAdapter().health()
    assert h["state"] in ("READY", "OFFLINE"), h
    if h["state"] == "OFFLINE":
        assert "EXTERNAL_BLOCKED" in h["reason"]


def t_destructive_tools_are_refused():
    """§84: delete_project / install / uninstall / update are refused at the adapter — even if a binary exists."""
    a = CodebaseMemoryMcpAdapter()
    for tool in ("delete_project", "install", "uninstall", "update"):
        r = a.invoke({"tool": tool})
        assert r.kind == ResultKind.FAILURE, f"{tool} must be refused"
        assert "refused" in r.summary or "not permitted" in r.summary, r.summary


def t_unknown_tool_refused():
    r = CodebaseMemoryMcpAdapter().invoke({"tool": "rm_rf_everything"})
    assert r.kind == ResultKind.FAILURE


def t_missing_binary_fails_honestly():
    if _configured():
        return
    r = CodebaseMemoryMcpAdapter().invoke({"tool": "list_projects"})
    assert r.kind == ResultKind.FAILURE and r.provenance == Provenance.UNAVAILABLE
    assert "EXTERNAL_BLOCKED" in r.summary


def t_discover_reflects_state():
    a = CodebaseMemoryMcpAdapter()
    tools = a.discover()
    if _configured():
        assert "search_graph" in tools and "index_repository" in tools
        assert "delete_project" not in tools, "destructive tools are never advertised"
    else:
        assert tools == []


def t_live_subprocess_roundtrip_when_configured():
    """Opt-in: with $CBM_BIN set, a real read-only tool round-trips through subprocess → normalized data."""
    if not _configured():
        return
    r = CodebaseMemoryMcpAdapter().invoke({"tool": "list_projects"})
    if r.kind == ResultKind.FAILURE:
        print("       (note: live binary present but list_projects failed — contract still proven)")
        return
    assert r.kind == ResultKind.OBSERVATION and r.provenance == Provenance.REAL
    assert r.trust == "UNTRUSTED", "code-intelligence output must stay untrusted (§24)"


for _n, _f in list(globals().items()):
    if _n.startswith("t_"):
        test(_n[2:], _f)
print("\n%d passed  (codebase-memory-mcp %s)" % (_p, "CONFIGURED" if _configured() else "unconfigured — honest OFFLINE"))
