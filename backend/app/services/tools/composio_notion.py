"""Notion tool — Composio-backed, dedicated.

Why dedicated (not just the generic catch-all): Notion is the priority surface
for NAI's first SaaS integration. Giving the LLM a tool named `notion` with a
curated `action` enum yields better tool-selection than asking it to pick a
toolkit+slug pair out of 200+ Composio apps.

Per-user auth: each NAI user_id (UUID) is passed to Composio as `user_id=`,
which Composio uses to look up that user's connected Notion workspace. If the
user hasn't connected Notion yet, Composio raises — the tool catches that and
returns a structured error the LLM can show the user (along with the
connect-account hint).

Curated action set (high-value reads + writes):
    - search        → NOTION_SEARCH_NOTION_PAGE (query across pages + databases)
    - fetch_page    → NOTION_FETCH_NOTION_PAGE
    - create_page   → NOTION_CREATE_NOTION_PAGE (in a parent page OR database)
    - append_blocks → NOTION_APPEND_BLOCK_CHILDREN (write content into a page)
    - query_database→ NOTION_QUERY_DATABASE
    - list_users    → NOTION_LIST_USERS

For anything outside this set, `composio_generic` tool handles it via raw
toolkit+slug args.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.services.tools.base import ToolContext, ToolError
from app.services.tools.composio_auth import resolve_composio_user_id

logger = logging.getLogger(__name__)


# Composio's Notion action slugs. If Composio renames these in the future, this
# map is the single point of update. Verify against the Notion toolkit list at
# https://app.composio.dev/toolkit/notion.
_ACTION_SLUG_MAP: dict[str, str] = {
    "search": "NOTION_SEARCH_NOTION_PAGE",
    "fetch_page": "NOTION_FETCH_NOTION_PAGE",
    "create_page": "NOTION_CREATE_NOTION_PAGE",
    "append_blocks": "NOTION_APPEND_BLOCK_CHILDREN",
    "query_database": "NOTION_QUERY_DATABASE",
    "list_users": "NOTION_LIST_USERS",
}


class NotionTool:
    name = "notion"
    writes = True  # reads AND writes Notion (create/update pages) — side-effecting
    description = (
        "Read or write the user's Notion workspace. Use this whenever the user "
        "asks about their Notion content (notes, databases, project pages, "
        "knowledge base). The user must have connected Notion through Composio's "
        "OAuth flow first; if not, this tool returns a structured error with the "
        "connect URL — surface that to the user before retrying.\n"
        "\n"
        "Actions:\n"
        "  search          — full-text search across pages and databases\n"
        "  fetch_page      — retrieve a page's content by ID\n"
        "  create_page     — create a new page under a parent page or database\n"
        "  append_blocks   — add content blocks to an existing page\n"
        "  query_database  — filter rows from a Notion database\n"
        "  list_users      — list workspace members"
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTION_SLUG_MAP.keys()),
                "description": "Which Notion operation to perform.",
            },
            "arguments": {
                "type": "object",
                "description": (
                    "Operation-specific arguments. For 'search': {query: str}. "
                    "For 'fetch_page': {page_id: str}. For 'create_page': "
                    "{parent: {page_id|database_id: str}, properties|title: ...}. "
                    "For 'append_blocks': {block_id: str, children: [...]}. "
                    "For 'query_database': {database_id: str, filter?: ..., sorts?: [...]}. "
                    "For 'list_users': {}."
                ),
                "additionalProperties": True,
            },
        },
        "required": ["action"],
    }

    def __init__(self, api_key: str | None = None):
        # Lazy-import composio so module load doesn't fail when the package is
        # absent in test environments that mock the tool out.
        try:
            from composio import Composio
        except ImportError as e:
            raise RuntimeError(
                "composio package not installed — pip install -r requirements.txt"
            ) from e

        key = api_key or os.environ.get("COMPOSIO_API_KEY")
        if not key:
            raise RuntimeError("COMPOSIO_API_KEY not set")
        self._composio = Composio(api_key=key)

    def execute(self, ctx: ToolContext, **kwargs) -> dict[str, Any]:
        action = kwargs.get("action")
        if action not in _ACTION_SLUG_MAP:
            raise ToolError(
                f"unknown action {action!r}. Valid: {list(_ACTION_SLUG_MAP.keys())}"
            )

        slug = _ACTION_SLUG_MAP[action]
        arguments = kwargs.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ToolError("arguments must be a JSON object")

        try:
            resp = self._composio.client.tools.execute(
                slug,
                arguments=arguments,
                user_id=resolve_composio_user_id(ctx.user_id),
            )
        except Exception as e:
            # Composio raises auth-related errors when no connected account
            # exists for the user. Surface the connect-URL hint so the LLM
            # can guide the user.
            msg = str(e)
            if any(token in msg.lower() for token in ("connected", "auth", "401", "403", "not found")):
                return {
                    "error": "no_connected_account",
                    "detail": (
                        "The user hasn't connected Notion through Composio yet. "
                        "They need to authorize at https://app.composio.dev → "
                        "Notion toolkit → Connect, then retry."
                    ),
                    "raw": msg[:300],
                }
            raise

        # ToolExecuteResponse → JSON-serializable dict. The SDK returns a
        # pydantic-like model with .data, .successful, .error attrs.
        out = _serialize_response(resp, action=action)
        # Composio returns 200 with successful=False when the upstream API
        # (Notion) rejects the OAuth token. status=ACTIVE in connected_accounts
        # only means "Composio has a token on file" — not that it works.
        # Translate this to no_connected_account so the LLM handles it
        # identically to a missing connection.
        if _is_upstream_auth_failure(out):
            return {
                "error": "no_connected_account",
                "detail": (
                    "Notion rejected the stored OAuth token (it expired or was "
                    "revoked). Visit https://app.composio.dev → Connected "
                    "Accounts → Notion → Reconnect, then retry."
                ),
                "raw": str(out.get("error") or out.get("data"))[:300],
            }
        return out


def _is_upstream_auth_failure(resp_dict: dict[str, Any]) -> bool:
    """Detect Composio responses where the SaaS rejected our token."""
    if resp_dict.get("successful") is True:
        return False
    blob = str(resp_dict.get("error") or "") + " " + str(resp_dict.get("data") or "")
    blob_lower = blob.lower()
    return any(
        token in blob_lower
        for token in ("401", "unauthorized", "api token is invalid", "token expired", "invalid_grant")
    )


def _serialize_response(resp: Any, *, action: str) -> dict[str, Any]:
    """Convert Composio's ToolExecuteResponse to a JSON-friendly dict."""
    if hasattr(resp, "model_dump"):
        out = resp.model_dump()
    elif hasattr(resp, "dict"):
        out = resp.dict()
    else:
        # Fallback for plain dicts or unknown shapes
        out = dict(resp) if hasattr(resp, "__iter__") else {"raw": str(resp)}
    out["_action"] = action
    return out
