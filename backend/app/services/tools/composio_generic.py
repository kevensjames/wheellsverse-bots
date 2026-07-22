"""Composio generic tool — catch-all for the long tail of SaaS apps.

Companion to ``composio_notion``. Notion is wrapped narrowly because it's the
priority; this tool covers everything else (Gmail, Slack, GitHub, Linear,
Calendar, Drive, Sheets, Stripe, HubSpot, Airtable, Discord, … ~200 apps).

The hybrid pattern (Stage 6 design decision):
- Narrow tools for high-use apps (Notion, expanding from there)
- This generic tool for everything else, with two LLM-facing modes:

    1. action='discover'  — given a toolkit slug ("gmail"), return up to 20
       available action slugs + their descriptions. Lets the LLM ask
       "what can I do with Gmail?" before committing to a specific call.

    2. action='execute'   — given a tool_slug ("GMAIL_SEND_EMAIL") and
       arguments (or natural-language `text`), run the call. The LLM picks
       the slug from a discover round-trip OR from system-prompt context.

The discover-first pattern keeps the tool surface narrow while still
covering 200+ apps. Without it, the LLM would have to guess slugs blind.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.services.tools.base import ToolContext, ToolError
from app.services.tools.composio_auth import resolve_composio_user_id

logger = logging.getLogger(__name__)

# Cap discover results to keep responses small. 20 covers the common cases
# (Composio's most popular toolkits have 5-15 actions each).
_DISCOVER_LIMIT = 20

# Cap result content length sent back to the LLM. Composio responses can be
# large (full Gmail message bodies, big Slack threads); truncate so we don't
# blow the context window.
_RESULT_TEXT_BUDGET = 4000


class ComposioTool:
    name = "composio"
    writes = True  # executes external SaaS actions (email/Slack/Stripe/etc.) — side-effecting
    description = (
        "Catch-all SaaS tool for any third-party service NOT covered by a "
        "dedicated tool (Notion has its own tool — prefer that for Notion). "
        "Supports 200+ apps: Gmail, Slack, GitHub, Linear, Calendar, Drive, "
        "Sheets, Stripe, HubSpot, Airtable, Discord, etc.\n"
        "\n"
        "Two-step workflow:\n"
        "  1. action='discover' with toolkit='gmail' → returns available "
        "action slugs and their descriptions.\n"
        "  2. action='execute' with tool_slug='GMAIL_SEND_EMAIL' (from step 1) "
        "and arguments={...} OR text='send a thank-you note to bob@x.com'.\n"
        "\n"
        "The user must have connected the app through Composio's OAuth flow "
        "first. If they haven't, the tool returns a no_connected_account "
        "error with the connect URL — surface that and stop."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["discover", "execute"],
                "description": (
                    "'discover' lists available actions for a toolkit; "
                    "'execute' runs a specific tool_slug."
                ),
            },
            "toolkit": {
                "type": "string",
                "description": (
                    "For action=discover: which toolkit to inspect (lowercase, "
                    "e.g. 'gmail', 'slack', 'github', 'linear'). For "
                    "action=execute: not required, the slug already encodes it."
                ),
            },
            "tool_slug": {
                "type": "string",
                "description": (
                    "For action=execute: the Composio action slug to run "
                    "(uppercase snake_case, e.g. 'GMAIL_SEND_EMAIL'). "
                    "Either tool_slug+arguments OR text must be provided."
                ),
            },
            "arguments": {
                "type": "object",
                "description": (
                    "For action=execute: structured arguments for the tool "
                    "(mutually exclusive with text)."
                ),
                "additionalProperties": True,
            },
            "text": {
                "type": "string",
                "description": (
                    "For action=execute: natural-language description of the "
                    "task. Composio interprets it server-side (mutually "
                    "exclusive with arguments). Slower + less predictable than "
                    "structured arguments — prefer arguments when you know "
                    "the schema."
                ),
            },
        },
        "required": ["action"],
    }

    def __init__(self, api_key: str | None = None):
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
        if action == "discover":
            return self._discover(kwargs)
        if action == "execute":
            return self._execute(ctx, kwargs)
        raise ToolError(
            f"action must be 'discover' or 'execute', got {action!r}"
        )

    # ── discover ────────────────────────────────────────────────────────
    def _discover(self, kwargs: dict) -> dict[str, Any]:
        toolkit = (kwargs.get("toolkit") or "").strip().lower()
        if not toolkit:
            raise ToolError("discover requires non-empty 'toolkit'")

        try:
            resp = self._composio.client.tools.list(
                toolkit_slug=toolkit,
                limit=_DISCOVER_LIMIT,
            )
        except Exception as e:
            raise ToolError(
                f"discover failed for toolkit={toolkit!r}: {type(e).__name__}: {e}"
            )

        items = _items_from_list(resp)
        return {
            "toolkit": toolkit,
            "count": len(items),
            "actions": [
                {
                    "slug": _safe_get(t, "slug") or _safe_get(t, "name"),
                    "description": _truncate(
                        _safe_get(t, "description") or "",
                        300,
                    ),
                }
                for t in items[:_DISCOVER_LIMIT]
            ],
            "hint": (
                "Use one of these slugs as tool_slug with action='execute'. "
                "Call again with a different toolkit to discover more."
            ),
        }

    # ── execute ─────────────────────────────────────────────────────────
    def _execute(self, ctx: ToolContext, kwargs: dict) -> dict[str, Any]:
        tool_slug = (kwargs.get("tool_slug") or "").strip()
        arguments = kwargs.get("arguments")
        text = kwargs.get("text")

        if not tool_slug:
            raise ToolError("execute requires tool_slug")
        # Composio requires exactly one of arguments or text
        if arguments and text:
            raise ToolError(
                "provide either arguments OR text, not both (Composio mutex)"
            )
        if not arguments and not text:
            raise ToolError("provide either arguments (object) or text (string)")
        if arguments is not None and not isinstance(arguments, dict):
            raise ToolError("arguments must be a JSON object")

        call_kwargs: dict[str, Any] = {"user_id": resolve_composio_user_id(ctx.user_id)}
        if arguments:
            call_kwargs["arguments"] = arguments
        if text:
            call_kwargs["text"] = text

        try:
            resp = self._composio.client.tools.execute(tool_slug, **call_kwargs)
        except Exception as e:
            msg = str(e)
            if any(
                token in msg.lower()
                for token in ("connected", "auth", "401", "403", "not found")
            ):
                return {
                    "error": "no_connected_account",
                    "detail": (
                        f"User hasn't connected the app for tool_slug={tool_slug!r}. "
                        "Authorize at https://app.composio.dev, then retry."
                    ),
                    "raw": msg[:300],
                }
            raise

        out = _serialize_response(resp)
        out["_tool_slug"] = tool_slug
        # Catch upstream auth failures (Composio holds a token, SaaS rejects it)
        # — same translation as composio_notion uses.
        if _is_upstream_auth_failure(out):
            return {
                "error": "no_connected_account",
                "detail": (
                    f"The SaaS app behind tool_slug={tool_slug!r} rejected the "
                    "stored OAuth token. Visit https://app.composio.dev → "
                    "Connected Accounts → find the entry → Reconnect, then retry."
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


def _items_from_list(resp: Any) -> list[Any]:
    """ToolListResponse → list of tool entries. SDK shape: .items or .data."""
    if hasattr(resp, "items"):
        items = resp.items
    elif hasattr(resp, "data"):
        items = resp.data
    elif isinstance(resp, dict):
        items = resp.get("items") or resp.get("data") or []
    else:
        items = []
    return list(items) if items else []


def _safe_get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _truncate(s: str, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _serialize_response(resp: Any) -> dict[str, Any]:
    if hasattr(resp, "model_dump"):
        out = resp.model_dump()
    elif hasattr(resp, "dict"):
        out = resp.dict()
    elif isinstance(resp, dict):
        out = dict(resp)
    else:
        out = {"raw": str(resp)}
    # Bound the size we hand back to the LLM
    raw_data = out.get("data")
    if isinstance(raw_data, (str, bytes)) and len(raw_data) > _RESULT_TEXT_BUDGET:
        out["data"] = _truncate(
            raw_data if isinstance(raw_data, str) else raw_data.decode("utf-8", "replace"),
            _RESULT_TEXT_BUDGET,
        )
        out["_truncated"] = True
    return out
