"""KAI Supreme — bug-hunter daemon embedded in KAI.

Replaces the standalone WheellsverseNarAISupreme.app Login Item.
Runs every N minutes inside the always-on KAI uvicorn process, scans the
empire (processes, ports, logs, APIs, env, disk, git), saves JSON
proposals, and pings Telegram on medium+ severity.

Public API:
    from app.services.supreme import scan_once, save_proposal, latest_proposals
"""
from app.services.supreme.scanner import (
    Finding,
    SEVERITY_LEVELS,
    load_map,
    scan_once,
    save_proposal,
)
from app.services.supreme.storage import latest_proposals, list_proposals, read_proposal

__all__ = [
    "Finding",
    "SEVERITY_LEVELS",
    "latest_proposals",
    "list_proposals",
    "load_map",
    "read_proposal",
    "save_proposal",
    "scan_once",
]
