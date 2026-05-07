"""Unit tests for the tool-use protocol parser + helpers."""
from __future__ import annotations

import json

import pytest

from infra.brain.tools.agent_loop import (
    DEFAULT_MAX_TOOL_ITERATIONS,
    ToolCall,
    build_tool_use_prompt,
    format_tool_result,
    parse_tool_call,
)
from infra.brain.tools.schema import ToolSchema


# ── parse_tool_call cases ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected_name",
    [
        # 1) raw JSON
        ('{"tool": "web_search", "input": {"query": "x"}}', "web_search"),
        # 2) leading / trailing whitespace
        ('  {"tool": "web_search", "input": {}}  ', "web_search"),
        # 3) embedded JSON in surrounding prose
        ('Sure! {"tool":"web_search","input":{"query":"abc"}} done.', "web_search"),
        # 4) ```json fence
        ('```json\n{"tool":"web_search","input":{"query":"abc"}}\n```', "web_search"),
        # 5) ``` (no language) fence
        ('```\n{"tool":"web_search","input":{"query":"abc"}}\n```', "web_search"),
        # 6) "input": null is normalised to {}
        ('{"tool": "x", "input": null}', "x"),
    ],
)
def test_parser_accepts_valid_envelope(raw, expected_name):
    call = parse_tool_call(raw)
    assert call is not None
    assert call.name == expected_name


@pytest.mark.parametrize(
    "raw",
    [
        # plain prose — final answer
        "Here is your answer: 42.",
        # missing tool field
        '{"not_a_tool": true}',
        # empty tool name
        '{"tool": ""}',
        # whitespace-only tool name
        '{"tool": "   "}',
        # input must be a dict (or null)
        '{"tool": "x", "input": "string-not-dict"}',
        '{"tool": "x", "input": [1, 2]}',
        # entirely empty content
        "",
        # whitespace
        "   ",
        # malformed JSON
        '{"tool": "x", "input": {',
    ],
)
def test_parser_rejects_non_envelope(raw):
    assert parse_tool_call(raw) is None


def test_parser_strips_whitespace_in_tool_name():
    call = parse_tool_call('{"tool": "  web_search  ", "input": {}}')
    assert call is not None and call.name == "web_search"


def test_parser_returns_tool_call_dataclass():
    call = parse_tool_call('{"tool": "x", "input": {"a": 1}}')
    assert isinstance(call, ToolCall)
    assert call.name == "x"
    assert call.input == {"a": 1}


# ── build_tool_use_prompt ───────────────────────────────────────────────────


def test_build_tool_use_prompt_empty_when_no_schemas():
    assert build_tool_use_prompt([]) == ""


def test_build_tool_use_prompt_lists_each_schema():
    s = ToolSchema(
        name="web_search",
        description="Search the web.",
        input_schema={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
    )
    prompt = build_tool_use_prompt([s])
    assert "## Tools" in prompt
    assert "web_search" in prompt
    assert "Search the web." in prompt
    assert '"tool": "TOOL_NAME"' in prompt


# ── format_tool_result ──────────────────────────────────────────────────────


def test_format_tool_result_ok():
    msg = format_tool_result("web_search", {"results": [{"title": "x"}]})
    assert msg.startswith("[tool:web_search OK]")
    assert "results" in msg


def test_format_tool_result_error():
    msg = format_tool_result("web_search", None, error="rate limit")
    assert msg == "[tool:web_search ERROR] rate limit"


def test_format_tool_result_truncates_huge_payloads():
    big = {"x": "a" * 10_000}
    msg = format_tool_result("t", big)
    # Total message capped near 8 KB
    assert len(msg) < 9_000
    assert "[truncated]" in msg


def test_format_tool_result_falls_back_on_unserializable():
    class Custom:
        def __repr__(self):
            return "<Custom>"

    msg = format_tool_result("t", Custom())
    assert "[tool:t OK]" in msg
    # Either repr or json fallback — the contract is just "no exception"
    assert "<Custom>" in msg or "Custom" in msg


# ── Constants ───────────────────────────────────────────────────────────────


def test_default_max_tool_iterations_is_three():
    """The hard cap is part of the public contract."""
    assert DEFAULT_MAX_TOOL_ITERATIONS == 3
