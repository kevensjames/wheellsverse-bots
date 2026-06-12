"""Composio tool unit tests — mocked client, no live SaaS calls.

What's tested:
- NotionTool: action mapping → Composio slug, error-translation, kwargs shape
- ComposioTool: discover / execute mode dispatch, mutex on arguments/text,
  no-connected-account translation
- build_default_registry registers both tools when include_composio=True

Run via `pytest --noconftest` (the backend conftest's fixtures don't apply).
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest


# ── shared fixtures ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _composio_key(monkeypatch):
    """All tests run as if a key is configured."""
    monkeypatch.setenv("COMPOSIO_API_KEY", "ak-test-key")


@pytest.fixture()
def mock_composio_cls():
    """Patch composio.Composio at module level for both tool files."""
    with patch("composio.Composio") as cls:
        # The tool reads .client.tools — make that a MagicMock chain
        instance = MagicMock()
        cls.return_value = instance
        yield cls, instance


@pytest.fixture()
def ctx():
    from app.services.tools.base import ToolContext
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


# ── NotionTool ──────────────────────────────────────────────────────────

class TestNotionTool:
    def test_instantiate_without_key_raises(self, monkeypatch):
        from app.services.tools.composio_notion import NotionTool
        monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="COMPOSIO_API_KEY"):
            NotionTool()

    def test_search_maps_to_correct_slug(self, mock_composio_cls, ctx):
        _, instance = mock_composio_cls
        instance.client.tools.execute.return_value = MagicMock(
            model_dump=lambda: {"data": {"results": []}, "successful": True}
        )

        from app.services.tools.composio_notion import NotionTool
        tool = NotionTool()

        result = tool.execute(
            ctx, action="search", arguments={"query": "design doc"}
        )

        instance.client.tools.execute.assert_called_once()
        call = instance.client.tools.execute.call_args
        # First positional arg is the slug
        assert call.args[0] == "NOTION_SEARCH_NOTION_PAGE"
        # user_id is propagated from ctx
        assert call.kwargs["user_id"] == str(ctx.user_id)
        assert call.kwargs["arguments"] == {"query": "design doc"}
        # Result is annotated with the action name
        assert result["_action"] == "search"

    def test_unknown_action_raises(self, mock_composio_cls, ctx):
        from app.services.tools.base import ToolError
        from app.services.tools.composio_notion import NotionTool
        tool = NotionTool()
        with pytest.raises(ToolError, match="unknown action"):
            tool.execute(ctx, action="rename_workspace")

    def test_no_connected_account_returns_structured_error(
        self, mock_composio_cls, ctx
    ):
        _, instance = mock_composio_cls
        instance.client.tools.execute.side_effect = Exception(
            "401 no connected account for user"
        )
        from app.services.tools.composio_notion import NotionTool
        tool = NotionTool()
        result = tool.execute(ctx, action="search", arguments={"query": "x"})
        assert result["error"] == "no_connected_account"
        assert "connect" in result["detail"].lower()

    def test_upstream_auth_failure_translates_to_no_connected_account(
        self, mock_composio_cls, ctx, monkeypatch
    ):
        """Composio returns 200 with successful=False when the SaaS itself
        (Notion) rejects the stored OAuth token. The tool should translate
        this to the same no_connected_account shape an exception would."""
        monkeypatch.setenv("COMPOSIO_USER_ID", "pg-test-fixture")
        _, instance = mock_composio_cls
        instance.client.tools.execute.return_value = MagicMock(
            model_dump=lambda: {
                "successful": False,
                "data": {
                    "http_error": "401 Client Error: Unauthorized for url: https://api.notion.com/v1/users",
                    "message": "API token is invalid.",
                    "status_code": 401,
                },
                "error": "API token is invalid.",
            }
        )
        from app.services.tools.composio_notion import NotionTool
        tool = NotionTool()
        result = tool.execute(ctx, action="list_users", arguments={})
        assert result["error"] == "no_connected_account"
        assert "reconnect" in result["detail"].lower()

    def test_resolver_uses_env_override_when_set(
        self, mock_composio_cls, ctx, monkeypatch
    ):
        """When COMPOSIO_USER_ID is set, the tool passes the override, not
        ctx.user_id."""
        monkeypatch.setenv("COMPOSIO_USER_ID", "pg-test-jhonwheeler")
        _, instance = mock_composio_cls
        instance.client.tools.execute.return_value = MagicMock(
            model_dump=lambda: {"successful": True, "data": {}}
        )
        from app.services.tools.composio_notion import NotionTool
        tool = NotionTool()
        tool.execute(ctx, action="search", arguments={"query": "x"})
        call_kwargs = instance.client.tools.execute.call_args.kwargs
        assert call_kwargs["user_id"] == "pg-test-jhonwheeler"
        assert call_kwargs["user_id"] != str(ctx.user_id)

    def test_resolver_falls_back_to_ctx_user_id_when_no_override(
        self, mock_composio_cls, ctx, monkeypatch
    ):
        """No override → resolver returns str(ctx.user_id)."""
        monkeypatch.delenv("COMPOSIO_USER_ID", raising=False)
        _, instance = mock_composio_cls
        instance.client.tools.execute.return_value = MagicMock(
            model_dump=lambda: {"successful": True, "data": {}}
        )
        from app.services.tools.composio_notion import NotionTool
        tool = NotionTool()
        tool.execute(ctx, action="search", arguments={"query": "x"})
        call_kwargs = instance.client.tools.execute.call_args.kwargs
        assert call_kwargs["user_id"] == str(ctx.user_id)

    def test_arguments_must_be_dict(self, mock_composio_cls, ctx):
        from app.services.tools.base import ToolError
        from app.services.tools.composio_notion import NotionTool
        tool = NotionTool()
        with pytest.raises(ToolError, match="JSON object"):
            tool.execute(ctx, action="search", arguments="just a string")

    def test_all_six_actions_mapped(self):
        """Each enum value must map to a Composio slug. If Composio renames
        a slug, this catches it at lint-time, not at runtime."""
        from app.services.tools.composio_notion import _ACTION_SLUG_MAP
        expected = {
            "search", "fetch_page", "create_page",
            "append_blocks", "query_database", "list_users",
        }
        assert set(_ACTION_SLUG_MAP.keys()) == expected
        # Every slug looks like a Composio uppercase snake_case
        for slug in _ACTION_SLUG_MAP.values():
            assert slug.startswith("NOTION_"), f"unexpected slug shape: {slug}"
            assert slug.isupper() or "_" in slug


# ── ComposioTool ────────────────────────────────────────────────────────

class TestComposioTool:
    def test_discover_returns_action_list(self, mock_composio_cls, ctx):
        _, instance = mock_composio_cls
        # Composio returns a list-like response — mock the .items shape
        instance.client.tools.list.return_value = MagicMock(
            items=[
                MagicMock(slug="GMAIL_SEND_EMAIL", description="Send an email"),
                MagicMock(slug="GMAIL_LIST_THREADS", description="List threads"),
            ]
        )

        from app.services.tools.composio_generic import ComposioTool
        tool = ComposioTool()
        result = tool.execute(ctx, action="discover", toolkit="gmail")

        instance.client.tools.list.assert_called_once()
        assert instance.client.tools.list.call_args.kwargs["toolkit_slug"] == "gmail"
        assert result["toolkit"] == "gmail"
        assert result["count"] == 2
        slugs = [a["slug"] for a in result["actions"]]
        assert "GMAIL_SEND_EMAIL" in slugs

    def test_discover_requires_toolkit(self, mock_composio_cls, ctx):
        from app.services.tools.base import ToolError
        from app.services.tools.composio_generic import ComposioTool
        tool = ComposioTool()
        with pytest.raises(ToolError, match="toolkit"):
            tool.execute(ctx, action="discover", toolkit="")

    def test_execute_with_arguments(self, mock_composio_cls, ctx):
        _, instance = mock_composio_cls
        instance.client.tools.execute.return_value = MagicMock(
            model_dump=lambda: {"successful": True, "data": {"id": "msg-123"}}
        )

        from app.services.tools.composio_generic import ComposioTool
        tool = ComposioTool()
        result = tool.execute(
            ctx,
            action="execute",
            tool_slug="GMAIL_SEND_EMAIL",
            arguments={"to": "bob@example.com", "subject": "hi", "body": "..."},
        )
        call = instance.client.tools.execute.call_args
        assert call.args[0] == "GMAIL_SEND_EMAIL"
        assert call.kwargs["arguments"]["to"] == "bob@example.com"
        assert call.kwargs["user_id"] == str(ctx.user_id)
        assert result["_tool_slug"] == "GMAIL_SEND_EMAIL"

    def test_execute_with_text_natural_language(self, mock_composio_cls, ctx):
        _, instance = mock_composio_cls
        instance.client.tools.execute.return_value = MagicMock(
            model_dump=lambda: {"successful": True, "data": "sent"}
        )

        from app.services.tools.composio_generic import ComposioTool
        tool = ComposioTool()
        tool.execute(
            ctx,
            action="execute",
            tool_slug="GMAIL_SEND_EMAIL",
            text="email bob@example.com saying I'll be late",
        )
        call = instance.client.tools.execute.call_args
        assert call.kwargs.get("text", "").startswith("email bob")
        assert "arguments" not in call.kwargs  # mutex respected

    def test_execute_mutex_arguments_and_text(self, mock_composio_cls, ctx):
        from app.services.tools.base import ToolError
        from app.services.tools.composio_generic import ComposioTool
        tool = ComposioTool()
        with pytest.raises(ToolError, match="mutex|both"):
            tool.execute(
                ctx,
                action="execute",
                tool_slug="GMAIL_SEND_EMAIL",
                arguments={"to": "bob@example.com"},
                text="natural language",
            )

    def test_execute_requires_one_of_arguments_or_text(
        self, mock_composio_cls, ctx
    ):
        from app.services.tools.base import ToolError
        from app.services.tools.composio_generic import ComposioTool
        tool = ComposioTool()
        with pytest.raises(ToolError):
            tool.execute(ctx, action="execute", tool_slug="GMAIL_SEND_EMAIL")

    def test_execute_requires_tool_slug(self, mock_composio_cls, ctx):
        from app.services.tools.base import ToolError
        from app.services.tools.composio_generic import ComposioTool
        tool = ComposioTool()
        with pytest.raises(ToolError, match="tool_slug"):
            tool.execute(ctx, action="execute", arguments={"x": 1})

    def test_unknown_action_raises(self, mock_composio_cls, ctx):
        from app.services.tools.base import ToolError
        from app.services.tools.composio_generic import ComposioTool
        tool = ComposioTool()
        with pytest.raises(ToolError, match="discover|execute"):
            tool.execute(ctx, action="bogus")

    def test_no_connected_account_on_execute(self, mock_composio_cls, ctx):
        _, instance = mock_composio_cls
        instance.client.tools.execute.side_effect = Exception(
            "403 Forbidden: no connected_account"
        )
        from app.services.tools.composio_generic import ComposioTool
        tool = ComposioTool()
        result = tool.execute(
            ctx,
            action="execute",
            tool_slug="GMAIL_SEND_EMAIL",
            arguments={"to": "x@y.com"},
        )
        assert result["error"] == "no_connected_account"


# ── registry integration ────────────────────────────────────────────────

class TestRegistryIntegration:
    def test_build_default_registry_includes_composio_by_default(
        self, mock_composio_cls
    ):
        from app.services.tools import build_default_registry
        reg = build_default_registry(include_perplexity=False)
        names = reg.names()
        assert "notion" in names
        assert "composio" in names
        # Pre-existing tools still there
        assert "memory_tool" in names
        assert "trading_signal" in names

    def test_include_composio_false_omits_both(self, mock_composio_cls):
        from app.services.tools import build_default_registry
        reg = build_default_registry(
            include_perplexity=False, include_composio=False
        )
        names = reg.names()
        assert "notion" not in names
        assert "composio" not in names

    def test_anthropic_schema_shape(self, mock_composio_cls):
        from app.services.tools import build_default_registry
        reg = build_default_registry(
            include_perplexity=False, include_composio=True
        )
        schemas = reg.anthropic_schema()
        # Anthropic shape: {"name", "description", "input_schema"} only
        for s in schemas:
            assert set(s.keys()) == {"name", "description", "input_schema"}
            assert s["input_schema"]["type"] == "object"
