"""Confused-deputy regression: operator-host tools must not reach the public chat.

The 2026-07-12 audit HIGH: build_default_registry() registered the operator's
Composio tools (which act on the OPERATOR's connected Gmail/Slack/GitHub/Stripe via
COMPOSIO_USER_ID) and MCP servers (filesystem/git running as the KAI host process)
for BOTH the operator chat and the public multi-user /nai chat — so any customer
could be steered into acting as the operator or reading the operator's disk.

Fix: those tools are gated behind ``operator=True``; the public chat (routers/nai.py)
uses the default (False). These tests monkeypatch the tool constructors so the
``operator`` gate is the ONLY thing deciding inclusion — the assertions hold whether
or not the composio SDK / a real MCP server is present in the environment.
"""
import app.services.mcp_tools as mcp_mod
import app.services.tools as tools_pkg
from app.services.tools import build_default_registry


class _FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = f"fake {name}"
        self.parameters = {"type": "object", "properties": {}}

    def execute(self, ctx, **kwargs):
        return {"ok": True}


def test_public_registry_excludes_composio(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "fake-key")
    monkeypatch.setattr(tools_pkg, "NotionTool", lambda: _FakeTool("notion"))
    monkeypatch.setattr(tools_pkg, "ComposioTool", lambda: _FakeTool("composio"))
    pub = set(build_default_registry(operator=False).names())
    op = set(build_default_registry(operator=True).names())
    # public multi-user chat: never expose operator-credentialed Composio tools
    assert "composio" not in pub and "notion" not in pub
    # operator chat: they ARE available
    assert "composio" in op and "notion" in op


def test_public_registry_excludes_twenty_and_dwolla(monkeypatch):
    # Both use a GLOBAL operator credential to reach the operator's CRM / ACH account.
    monkeypatch.setenv("TWENTY_API_URL", "https://crm.example.com")
    monkeypatch.setenv("TWENTY_API_KEY", "fake")
    monkeypatch.setenv("DWOLLA_KEY", "fake")
    monkeypatch.setenv("DWOLLA_SECRET", "fake")
    monkeypatch.setattr(tools_pkg, "TwentyCrmTool", lambda: _FakeTool("twenty_crm"))
    monkeypatch.setattr(tools_pkg, "DwollaTool", lambda: _FakeTool("dwolla"))
    pub = set(build_default_registry(operator=False).names())
    op = set(build_default_registry(operator=True).names())
    assert "twenty_crm" not in pub and "dwolla" not in pub
    assert "twenty_crm" in op and "dwolla" in op


def test_public_registry_excludes_mcp(monkeypatch):
    monkeypatch.setattr(mcp_mod, "load_mcp_tools", lambda: [_FakeTool("mcp_filesystem")])
    pub = set(build_default_registry(operator=False).names())
    op = set(build_default_registry(operator=True).names())
    # public chat must not load operator-host MCP servers (filesystem/git)
    assert "mcp_filesystem" not in pub
    assert "mcp_filesystem" in op


def test_default_is_public_safe(monkeypatch):
    # No `operator` arg → defaults to the PUBLIC (safe) set, even with keys/config present.
    monkeypatch.setenv("COMPOSIO_API_KEY", "fake-key")
    monkeypatch.setattr(tools_pkg, "ComposioTool", lambda: _FakeTool("composio"))
    monkeypatch.setattr(tools_pkg, "NotionTool", lambda: _FakeTool("notion"))
    monkeypatch.setattr(mcp_mod, "load_mcp_tools", lambda: [_FakeTool("mcp_filesystem")])
    names = set(build_default_registry().names())
    assert not ({"composio", "notion", "mcp_filesystem"} & names)


def test_public_registry_excludes_operator_data_readers():
    # Tools that read GLOBAL operator/system data with no per-user scoping — the
    # operator self-model/voice, infra knowledge graph, plans, learnings, failure
    # log, self-audit. Real SQLite-backed tools (no monkeypatch needed).
    operator_data = {
        "twin_query", "kg_query", "plan_query",
        "learning_query", "failure_lookup", "audit_query",
    }
    pub = set(build_default_registry(operator=False).names())
    op = set(build_default_registry(operator=True).names())
    assert operator_data.isdisjoint(pub)   # never exposed to a public customer
    assert operator_data.issubset(op)      # all available to the operator


def test_public_is_subset_of_operator(monkeypatch):
    # Operator-host tools only ever ADD to the set; nothing is public-only.
    monkeypatch.setenv("COMPOSIO_API_KEY", "fake-key")
    pub = set(build_default_registry(operator=False).names())
    op = set(build_default_registry(operator=True).names())
    assert pub.issubset(op)


def test_explicit_include_overrides_gate(monkeypatch):
    # An explicit include_composio=True is an intentional override (tests/dev) and
    # bypasses the operator gate; include_composio=False forces off even for operator.
    monkeypatch.setenv("COMPOSIO_API_KEY", "fake-key")
    monkeypatch.setattr(tools_pkg, "NotionTool", lambda: _FakeTool("notion"))
    monkeypatch.setattr(tools_pkg, "ComposioTool", lambda: _FakeTool("composio"))
    forced_on = set(build_default_registry(operator=False, include_composio=True).names())
    forced_off = set(build_default_registry(operator=True, include_composio=False).names())
    assert "composio" in forced_on
    assert "composio" not in forced_off
