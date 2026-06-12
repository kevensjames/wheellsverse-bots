"""ToolRegistry unit tests — no API calls, no DB."""
import uuid
from unittest.mock import MagicMock

import pytest

from app.services.tools.base import ToolContext, ToolError
from app.services.tools.registry import ToolRegistry


class FakeTool:
    name = "fake"
    description = "A fake tool for testing"
    parameters = {
        "type": "object",
        "properties": {"x": {"type": "integer"}},
        "required": ["x"],
    }

    def execute(self, ctx: ToolContext, *, x: int):
        if x < 0:
            raise ToolError("x must be non-negative")
        return {"doubled": x * 2}


@pytest.fixture()
def ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_register_and_get():
    reg = ToolRegistry()
    t = FakeTool()
    reg.register(t)
    assert reg.get("fake") is t
    assert "fake" in reg.names()


def test_duplicate_register_raises():
    reg = ToolRegistry()
    reg.register(FakeTool())
    with pytest.raises(ValueError):
        reg.register(FakeTool())


def test_get_unknown_raises():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("missing")


def test_openai_schema():
    reg = ToolRegistry()
    reg.register(FakeTool())
    s = reg.openai_schema()
    assert s[0]["type"] == "function"
    assert s[0]["function"]["name"] == "fake"
    assert "parameters" in s[0]["function"]


def test_anthropic_schema():
    reg = ToolRegistry()
    reg.register(FakeTool())
    s = reg.anthropic_schema()
    assert s[0]["name"] == "fake"
    assert "input_schema" in s[0]
    # Anthropic must not see OpenAI-only keys
    assert "function" not in s[0]
    assert "type" not in s[0]


def test_execute_happy(ctx):
    reg = ToolRegistry()
    reg.register(FakeTool())
    result = reg.execute("fake", {"x": 3}, ctx)
    assert result.is_error is False
    assert result.output == {"doubled": 6}


def test_execute_tool_error_returns_error_result(ctx):
    reg = ToolRegistry()
    reg.register(FakeTool())
    result = reg.execute("fake", {"x": -1}, ctx)
    assert result.is_error is True
    assert "non-negative" in result.output["error"]


def test_execute_unknown_tool_returns_error(ctx):
    reg = ToolRegistry()
    result = reg.execute("missing", {}, ctx)
    assert result.is_error is True
