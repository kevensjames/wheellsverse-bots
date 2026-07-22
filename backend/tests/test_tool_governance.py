"""Governed tool loop: every call audited; side-effecting tools blocked unless
the request carries operator authorization (allow_writes). Closes the gap where
the LLM tool loop invoked writes with no scope/approval/audit."""
import uuid
from unittest.mock import MagicMock

import pytest

from app.services.tools import registry as reg_mod
from app.services.tools.base import ToolContext
from app.services.tools.registry import ToolRegistry


class FakeReadTool:
    name = "fake_read"
    description = "read-only"
    parameters = {"type": "object", "properties": {}}

    def execute(self, ctx, **kwargs):
        return {"ok": True, "did": "read"}


class FakeWriteTool:
    name = "fake_write"
    description = "side-effecting"
    parameters = {"type": "object", "properties": {}}
    writes = True

    def __init__(self):
        self.executed = False

    def execute(self, ctx, **kwargs):
        self.executed = True
        return {"ok": True, "did": "write"}


class FakeScopedWriteTool(FakeWriteTool):
    name = "fake_scoped"
    scope = "tools.fakescoped"


@pytest.fixture(autouse=True)
def capture_audit(monkeypatch):
    """Intercept record_action so tests assert audit behavior without writing
    the real audit.jsonl."""
    calls = []
    monkeypatch.setattr(reg_mod, "record_action", lambda **kw: calls.append(kw) or {})
    return calls


def _ctx(allow_writes=False):
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock(), allow_writes=allow_writes)


# ── read tools: unaffected ─────────────────────────────────────────────────
def test_read_tool_executes_regardless_of_allow_writes():
    r = ToolRegistry(); r.register(FakeReadTool())
    res = r.execute("fake_read", {}, _ctx(allow_writes=False))
    assert res.is_error is False
    assert res.output["did"] == "read"


def test_every_call_is_audited(capture_audit):
    r = ToolRegistry(); r.register(FakeReadTool())
    r.execute("fake_read", {}, _ctx())
    assert any(c["action"] == "tool.fake_read" and c["success"] for c in capture_audit)


# ── write tools: default-deny, authorized-allow ────────────────────────────
def test_write_tool_blocked_without_authorization(capture_audit):
    r = ToolRegistry(); t = FakeWriteTool(); r.register(t)
    res = r.execute("fake_write", {}, _ctx(allow_writes=False))
    assert res.is_error is True
    assert "blocked" in res.output["error"].lower()
    assert t.executed is False  # the core guarantee — the write did NOT run
    assert any(c["destructive"] and not c["success"] for c in capture_audit)


def test_write_tool_executes_with_authorization(capture_audit):
    r = ToolRegistry(); t = FakeWriteTool(); r.register(t)
    res = r.execute("fake_write", {}, _ctx(allow_writes=True))
    assert res.is_error is False
    assert t.executed is True
    assert any(c["destructive"] and c["success"] for c in capture_audit)


# ── optional scope gate (defense in depth) ─────────────────────────────────
def test_scoped_write_blocked_when_scope_disabled(monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_TOOLS_FAKESCOPED", raising=False)
    monkeypatch.delenv("KAI_SCOPE_TOOLS", raising=False)
    r = ToolRegistry(); t = FakeScopedWriteTool(); r.register(t)
    res = r.execute("fake_scoped", {}, _ctx(allow_writes=True))  # authorized but scope off
    assert res.is_error is True
    assert "scope" in res.output["error"].lower()
    assert t.executed is False


def test_scoped_write_allowed_when_scope_enabled(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_TOOLS_FAKESCOPED", "1")
    r = ToolRegistry(); t = FakeScopedWriteTool(); r.register(t)
    res = r.execute("fake_scoped", {}, _ctx(allow_writes=True))
    assert res.is_error is False
    assert t.executed is True


# ── misc ───────────────────────────────────────────────────────────────────
def test_unknown_tool_errors_and_is_audited(capture_audit):
    r = ToolRegistry()
    res = r.execute("does_not_exist", {}, _ctx())
    assert res.is_error is True
    assert "unknown" in str(res.output).lower()
    assert len(capture_audit) >= 1


def test_real_write_tools_declare_writes():
    from app.services.mcp_tools import MCPTool
    from app.services.tools.composio_generic import ComposioTool
    from app.services.tools.composio_notion import NotionTool
    from app.services.tools.twenty_crm import TwentyCrmTool
    from app.services.tools.video_gen import VideoGenTool

    for cls in (ComposioTool, NotionTool, TwentyCrmTool, VideoGenTool, MCPTool):
        assert getattr(cls, "writes", False) is True, f"{cls.__name__} must be writes=True"


def test_safe_by_default():
    # allow_writes defaults False on the context AND on brain.chat.
    ctx = ToolContext(user_id=uuid.uuid4(), session=MagicMock())
    assert ctx.allow_writes is False
    import inspect

    from app.services.nai_brain.brain import Brain
    assert inspect.signature(Brain.chat).parameters["allow_writes"].default is False
