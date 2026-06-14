"""Preset registry + tool filter tests."""
from __future__ import annotations

import pytest

from app.services.presets import (
    PRESETS,
    PresetSpec,
    filter_registry,
    get_preset,
    list_presets,
)
from app.services.tools.base import Tool, ToolContext
from app.services.tools.registry import ToolRegistry


# ─── registry: shape + lookup ────────────────────────────────────────


def test_list_presets_ships_expected_set():
    rows = list_presets()
    ids = {p.id for p in rows}
    # original 5 + 4 professional-domain research agents + self-improvement scout
    assert ids == {
        "swe", "marketing", "finance", "research", "legal_research",
        "medical_research", "dental_research", "engineering", "accounting",
        "self_improvement",
    }
    assert len(rows) == 10


def test_domain_agents_are_research_not_advice_and_grounded():
    # The regulated-profession presets must (a) frame as RESEARCH not advice and
    # (b) be wired to the knowledge base (document_search) for citations.
    for pid in ("medical_research", "dental_research", "engineering", "accounting"):
        p = get_preset(pid)
        assert p is not None, pid
        assert "document_search" in p.tool_whitelist, pid
        sp = p.system_prompt.lower()
        assert "research" in sp, pid
        # each defers to a licensed professional / is not a substitute
        assert ("licensed" in sp) or ("not a substitute" in sp) or ("not a " in sp), pid


def test_get_preset_known():
    p = get_preset("swe")
    assert p is not None
    assert p.name == "Software Engineer"


def test_get_preset_unknown():
    assert get_preset("not-a-real-preset") is None
    assert get_preset("") is None
    assert get_preset("   ") is None


def test_get_preset_strips_whitespace():
    # Defensive against query-string padding
    assert get_preset("  swe  ") is not None


def test_each_preset_has_required_fields():
    for p in PRESETS:
        assert p.id and isinstance(p.id, str)
        assert p.name and isinstance(p.name, str)
        assert p.system_prompt and len(p.system_prompt) >= 40, (
            f"preset {p.id} system_prompt too short to be useful"
        )
        assert isinstance(p.tool_whitelist, list)


def test_preset_specs_are_frozen():
    """Mutability would let one chat permanently alter a preset for
    every subsequent request — guard against it."""
    p = get_preset("swe")
    with pytest.raises(Exception):
        p.system_prompt = "tampered"  # type: ignore[misc]


def test_legal_preset_refuses_advice_in_prompt():
    """Specific guard: the legal preset MUST tell the model not to give
    legal advice. If someone edits it carelessly, this test catches it."""
    p = get_preset("legal_research")
    assert p is not None
    assert "advice" in p.system_prompt.lower()
    assert "never" in p.system_prompt.lower() or "not" in p.system_prompt.lower()


# ─── tool filter ─────────────────────────────────────────────────────


class _FakeTool:
    """Minimal Tool-protocol implementer for filter tests."""
    def __init__(self, name):
        self.name = name
        self.description = "fake"
        self.parameters = {"type": "object", "properties": {}}

    def execute(self, ctx, **kwargs):
        return {"ran": self.name}


def _make_registry(*names):
    r = ToolRegistry()
    for n in names:
        r.register(_FakeTool(n))
    return r


def test_filter_keeps_only_whitelisted():
    reg = _make_registry("web_fetch", "web_search", "memory", "notion", "trading_signal")
    preset = PresetSpec(
        id="t", name="t", icon="·", description="",
        system_prompt="x" * 50,
        tool_whitelist=["web_fetch", "memory"],
    )
    filtered = filter_registry(reg, preset)
    names = set(filtered._tools.keys())
    assert names == {"web_fetch", "memory"}


def test_filter_wildcards_work():
    """MCP tools come in namespaced — `mcp_filesystem__read`, etc. The
    SWE preset whitelists `mcp_filesystem__*` and we expect every
    filesystem tool to come through."""
    reg = _make_registry(
        "web_fetch",
        "mcp_filesystem__read_file",
        "mcp_filesystem__list_dir",
        "mcp_filesystem__write_file",
        "mcp_git__diff",
        "memory",
    )
    preset = PresetSpec(
        id="t", name="t", icon="·", description="",
        system_prompt="x" * 50,
        tool_whitelist=["mcp_filesystem__*", "memory"],
    )
    filtered = filter_registry(reg, preset)
    names = set(filtered._tools.keys())
    assert names == {
        "mcp_filesystem__read_file",
        "mcp_filesystem__list_dir",
        "mcp_filesystem__write_file",
        "memory",
    }
    # web_fetch and the git MCP tool were NOT whitelisted
    assert "web_fetch" not in names
    assert "mcp_git__diff" not in names


def test_filter_empty_whitelist_returns_empty_registry():
    reg = _make_registry("web_fetch", "memory")
    preset = PresetSpec(
        id="t", name="t", icon="·", description="",
        system_prompt="x" * 50,
        tool_whitelist=[],
    )
    filtered = filter_registry(reg, preset)
    assert filtered._tools == {}


def test_filter_does_not_mutate_original_registry():
    """Concurrent requests must not see each other's filtered registries."""
    reg = _make_registry("web_fetch", "memory", "notion")
    preset = PresetSpec(
        id="t", name="t", icon="·", description="",
        system_prompt="x" * 50,
        tool_whitelist=["web_fetch"],
    )
    filter_registry(reg, preset)
    # Original untouched
    assert set(reg._tools.keys()) == {"web_fetch", "memory", "notion"}


def test_filter_handles_none_registry():
    """Caller might pass None when no tools are configured — don't crash."""
    preset = PresetSpec(
        id="t", name="t", icon="·", description="",
        system_prompt="x" * 50,
        tool_whitelist=["anything"],
    )
    assert filter_registry(None, preset) is None


# ─── per-preset whitelist sanity ────────────────────────────────────


def test_swe_whitelist_has_filesystem_and_git():
    p = get_preset("swe")
    assert any("filesystem" in pat for pat in p.tool_whitelist)
    assert any("git" in pat for pat in p.tool_whitelist)


def test_marketing_no_trading_no_filesystem():
    """Defense-in-depth — make sure the marketing preset can't
    accidentally execute trades or touch the filesystem."""
    p = get_preset("marketing")
    assert not any("trading" in pat for pat in p.tool_whitelist)
    assert not any("filesystem" in pat for pat in p.tool_whitelist)


def test_legal_no_dangerous_tools():
    p = get_preset("legal_research")
    # Legal preset is search/read only — no fs, no git, no trading, no notion
    for pat in p.tool_whitelist:
        assert all(banned not in pat for banned in (
            "filesystem", "git", "trading", "notion",
        )), f"legal preset shouldn't whitelist {pat}"


def test_finance_has_trading_signal():
    p = get_preset("finance")
    assert "trading_signal" in p.tool_whitelist


def test_research_no_writes():
    p = get_preset("research")
    # Research is read-only — no fs, no git, no notion writes
    for pat in p.tool_whitelist:
        assert "filesystem" not in pat
        assert "git" not in pat
        assert "notion" not in pat


# ─── admin endpoints ────────────────────────────────────────────────


from app.config import settings as _settings  # noqa: E402
from app.services.governance import audit_log as _al  # noqa: E402
from app.services.tools import build_default_registry as _bdr  # noqa: E402

ADMIN_HEADERS = {"X-Admin-Token": _settings.admin_token}


@pytest.fixture
def _scope_on(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_PRESETS", "1")


@pytest.fixture
def _isolated_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(_al, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")


def test_admin_presets_list_requires_token(client):
    r = client.get("/admin/presets")
    assert r.status_code == 403


def test_admin_presets_list_returns_all(client, _scope_on, _isolated_audit):
    r = client.get("/admin/presets", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "presets" in body
    assert len(body["presets"]) == 10
    ids = {p["id"] for p in body["presets"]}
    assert ids == {
        "swe", "marketing", "finance", "research", "legal_research",
        "medical_research", "dental_research", "engineering", "accounting",
        "self_improvement",
    }


def test_admin_presets_list_audited(
    client, _scope_on, _isolated_audit, monkeypatch
):
    """Every list call lands in the audit log under scope=presets.list."""
    from app.services import governance
    client.get("/admin/presets", headers=ADMIN_HEADERS)
    rows = governance.list_actions(scope="presets.list")
    assert len(rows) >= 1
    assert rows[0]["success"] is True
    assert rows[0]["destructive"] is False


def test_admin_presets_preview_requires_token(client):
    r = client.post("/admin/presets/swe/preview")
    assert r.status_code == 403


def test_admin_presets_preview_unknown_id_400(client, monkeypatch):
    # Mock build_default_registry to avoid network/dep init
    from app.routers import admin_presets as ap
    monkeypatch.setattr(ap, "build_default_registry", lambda: _bdr() if False else __import__("app.services.tools.registry", fromlist=["ToolRegistry"]).ToolRegistry())
    r = client.post(
        "/admin/presets/not-a-preset/preview",
        headers=ADMIN_HEADERS,
    )
    assert r.status_code == 400


def test_admin_presets_preview_returns_filtered_count(
    client, monkeypatch
):
    """The preview must reflect the actual filter that would apply during
    a real chat — not a hardcoded number."""
    from app.routers import admin_presets as ap
    from app.services.tools.registry import ToolRegistry as _TR

    # Fake registry with 4 tools — 2 in SWE whitelist, 2 not
    class _T:
        def __init__(self, name):
            self.name = name
            self.description = ""
            self.parameters = {"type": "object", "properties": {}}
        def execute(self, ctx, **kw):
            return {}

    def fake_registry():
        r = _TR()
        r.register(_T("web_fetch"))
        r.register(_T("web_search"))
        r.register(_T("notion"))
        r.register(_T("trading_signal"))
        return r

    monkeypatch.setattr(ap, "build_default_registry", fake_registry)
    r = client.post("/admin/presets/swe/preview", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["preset"]["id"] == "swe"
    assert body["tools"]["total_available"] == 4
    # SWE whitelist: web_fetch, web_search, memory, mcp_filesystem__*, mcp_git__*
    # Of our 4 tools, only web_fetch + web_search match
    assert body["tools"]["after_filter"] == 2
    assert set(body["tools"]["kept_names"]) == {"web_fetch", "web_search"}
