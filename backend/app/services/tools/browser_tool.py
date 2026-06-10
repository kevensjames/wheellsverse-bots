"""Browser tool — lets KAI navigate an allowlisted site and READ it, or
PROPOSE a write action (dry-run). v1 envelope: read + propose. It NEVER
clicks/types/submits; `propose_write` only records what KAI *would* do for
the operator to review.

Registered only when KAI_BROWSER_ENABLED is set (build_default_registry skips
it otherwise, like WebSearchTool skips without a key). Every action is logged
to data/browser/actions.jsonl; navigation is policy-checked (allowlist + SSRF
+ scheme) before any browser launches.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.browser import config, log, session
from app.services.tools.base import ToolContext, ToolError

logger = logging.getLogger(__name__)


class BrowserTool:
    name = "browser"
    description = (
        "Browse an allowlisted website and READ it, or PROPOSE a write action "
        "(dry-run — KAI cannot click/type/submit in v1). Actions:\n"
        "  read          — navigate to a URL (must be on the operator's "
        "allowlist) and return the page title, visible text, and links. "
        "Read-only.\n"
        "  propose_write — describe a write action you WOULD take (click/type/"
        "submit) so the operator can review it. This does NOT execute — it is "
        "recorded for human approval."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "propose_write"],
                "description": "Which action to run.",
            },
            "url": {
                "type": "string",
                "description": "read: the URL to navigate to (allowlisted "
                "domains only). propose_write: the page the action targets.",
            },
            "action_type": {
                "type": "string",
                "enum": ["click", "type", "submit"],
                "description": "propose_write only — the kind of write action.",
            },
            "selector": {
                "type": "string",
                "description": "propose_write only — CSS selector of the target element.",
            },
            "value": {
                "type": "string",
                "description": "propose_write only — text to type (for action_type=type).",
            },
            "description": {
                "type": "string",
                "description": "propose_write only — a plain-language description "
                "of what this action accomplishes (shown to the operator).",
            },
        },
        "required": ["action"],
    }

    def __init__(self) -> None:
        if not config.browser_enabled():
            raise RuntimeError("KAI_BROWSER_ENABLED not set")

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        action = (kwargs.get("action") or "").strip().lower()
        if not action:
            raise ToolError("action is required")

        if action == "read":
            url = (kwargs.get("url") or "").strip()
            try:
                safe = config.check_url(url)
            except config.BrowserPolicyError as e:
                log.record_action(kind="blocked", status="blocked", url=url, detail=str(e))
                raise ToolError(f"blocked: {e}")
            try:
                result = session.read_page(safe)
            except session.BrowserUnavailable as e:
                log.record_action(kind="navigate", status="error", url=safe, detail=str(e))
                raise ToolError(f"browser error: {e}")
            log.record_action(
                kind="navigate", status="ok",
                url=result.get("url", safe), detail=result.get("title", ""),
            )
            return {
                "action": "read",
                "url": result.get("url", safe),
                "title": result.get("title", ""),
                "text": result.get("text", ""),
                "links": result.get("links", []),
            }

        if action == "propose_write":
            description = (kwargs.get("description") or "").strip()
            proposed = {
                "action_type": kwargs.get("action_type"),
                "selector": kwargs.get("selector"),
                "value": kwargs.get("value"),
            }
            log.record_action(
                kind="propose_write", status="ok",
                url=(kwargs.get("url") or ""), detail=description, proposed=proposed,
            )
            return {
                "action": "propose_write",
                "note": "DRY RUN — not executed. Recorded for operator review/approval.",
                "description": description,
                "proposed": proposed,
            }

        raise ToolError(f"unknown action {action!r}; use read|propose_write")
