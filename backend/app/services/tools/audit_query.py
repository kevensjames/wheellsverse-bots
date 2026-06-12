"""Audit query tool — lets KAI report its own system health in a chat turn
("KAI, audit yourself"). READ-ONLY introspection.
"""
from __future__ import annotations

from typing import Any

from app.services.audit import run_audit
from app.services.tools.base import ToolContext


class AuditQueryTool:
    name = "audit_query"
    description = (
        "Run a live self-audit of KAI's subsystems and report health: which "
        "features are enabled, how many records each has stored, and any issues. "
        "READ-ONLY. Use when asked 'what can you do', 'audit yourself', or "
        "'what's your status'."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        a = run_audit()
        return {
            "summary": a["summary"],
            "runtime": a["runtime"],
            "enabled": [
                x["name"] for x in a["subsystems"] if x["scope_enabled"]
            ],
            "subsystems": [
                {"name": x["name"], "enabled": x["scope_enabled"], "records": x["records"]}
                for x in a["subsystems"]
            ],
            "issues": a["issues"],
        }
