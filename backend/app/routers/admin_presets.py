"""Admin endpoints for KAI's expert-agent presets.

Two endpoints:
  GET  /admin/presets               list available presets (for the dropdown)
  POST /admin/presets/{id}/preview  show how a preset would shape a chat call
                                    — system prompt + filtered tool count
                                    Useful before committing to a preset.

The actual chat-time application happens in /admin/kai-chat (see
admin_chat.py) which accepts a preset_id field and routes the call
through the preset before reaching Brain.

This file routes the LIST through the governance layer with a read-only
scope so even "what presets exist" is audited. Cheap insurance.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.admin import require_admin_token
from app.services.governance import audited
from app.services.presets import (
    PresetSpec,
    filter_registry,
    get_preset,
    list_presets,
)
from app.services.tools import build_default_registry

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/presets",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


def _spec_to_json(p: PresetSpec) -> dict[str, Any]:
    """Public-safe JSON shape — same fields the dashboard dropdown needs."""
    return {
        "id": p.id,
        "name": p.name,
        "icon": p.icon,
        "description": p.description,
        "tool_whitelist": p.tool_whitelist,
        "system_prompt_preview": p.system_prompt[:200],
    }


@audited(scope="presets.list", destructive=False)
def _audited_list() -> list[dict[str, Any]]:
    return [_spec_to_json(p) for p in list_presets()]


@router.get("")
def get_all_presets():
    """Return all 5 shipped presets in display order."""
    try:
        return {"presets": _audited_list()}
    except Exception as e:
        # Governance.ScopeDenied lands here if KAI_SCOPE_PRESETS=0 in env —
        # surface helpfully so the operator knows what to enable.
        if "scope" in str(e).lower():
            raise HTTPException(status_code=403, detail=str(e))
        raise


@router.post("/{preset_id}/preview")
def preview_preset(preset_id: str):
    """Show what this preset would do to a chat call. Doesn't run a chat —
    just returns the system prompt that would be prepended + the count of
    tools that would survive the whitelist filter (against the daemon's
    current tool registry)."""
    preset = get_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=400, detail=f"unknown preset_id={preset_id!r}")

    # Build the default registry the SAME WAY admin_chat does, so the
    # tool count we report matches what the operator would actually see.
    full_registry = build_default_registry(operator=True)  # operator preset UI (require_admin_token)
    filtered = filter_registry(full_registry, preset)
    full_count = len(full_registry._tools)
    filtered_count = len(filtered._tools)

    return {
        "preset": _spec_to_json(preset),
        "system_prompt_full": preset.system_prompt,
        "tools": {
            "total_available": full_count,
            "after_filter": filtered_count,
            "kept_names": sorted(filtered._tools.keys()),
        },
    }
