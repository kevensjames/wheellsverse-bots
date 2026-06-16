"""site_builder — KAI generates HTML in the WheellsVerse style as a reviewable
DRAFT (never auto-publishes). Mocks the router (no LLM/network); asserts it
saves the artifact, fail-soft on junk, and is registered."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.tools import site_builder as sb
from app.services.tools.base import ToolContext, ToolError
from app.services.tools.site_builder import SiteBuilderTool

_HTML = "<!DOCTYPE html><html><head><style>body{background:#07080c}</style></head><body><h1>KAI</h1></body></html>"


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def _patch_router(monkeypatch, content):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=content, total_cost_usd=0.0)
    monkeypatch.setattr("app.services.router.build_default_router", lambda s: r)
    return r


def test_blank_brief_raises():
    with pytest.raises(ToolError):
        SiteBuilderTool().execute(_ctx(), brief="  ")


def test_generates_and_saves_draft(monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "_DRAFTS", tmp_path)
    _patch_router(monkeypatch, _HTML)
    out = SiteBuilderTool().execute(_ctx(), brief="a pricing section", kind="page")
    assert out["bytes"] > 0
    assert out["draft_path"].endswith("a_pricing_section.html")
    assert (tmp_path / "a_pricing_section.html").read_text() == _HTML
    assert "DRAFT saved" in out["note"]  # never auto-publishes


def test_strips_markdown_fences(monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "_DRAFTS", tmp_path)
    _patch_router(monkeypatch, "```html\n" + _HTML + "\n```")
    out = SiteBuilderTool().execute(_ctx(), brief="x")
    saved = (tmp_path / "x.html").read_text()
    assert saved.startswith("<!DOCTYPE") and "```" not in saved


def test_no_html_failsoft(monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "_DRAFTS", tmp_path)
    _patch_router(monkeypatch, "sorry, I can't do that")
    out = SiteBuilderTool().execute(_ctx(), brief="x")
    assert out["html_preview"] == "" and "did not return usable HTML" in out["note"]


def test_registered_always():
    from app.services.tools import build_default_registry
    reg = build_default_registry(include_composio=False, include_mcp=False)
    assert "site_builder" in reg.names()
