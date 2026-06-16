"""video_gen — KAI generates a short video from a text prompt via Runway ML.

Wraps core/video_engine.runway_generate (text→video). Registered ONLY when
RUNWAYML_API_KEY is set, so it's inert until configured. SLOW (submits a job +
polls, ~minutes) and costs Runway credits — so it's described as explicit-ask-
only. Fail-soft.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from app.services.tools.base import ToolContext, ToolError

logger = logging.getLogger(__name__)
_REPO = Path(__file__).resolve().parents[4]


def _run_runway(prompt: str, duration: int, ratio: str) -> dict:
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    from core import video_engine
    return video_engine.runway_generate(prompt, duration=duration, ratio=ratio)


class VideoGenTool:
    name = "video_gen"
    description = (
        "Generate a short (~5s) video from a text prompt via Runway ML; returns "
        "the local file path. SLOW (takes minutes) and costs credits — use only "
        "when the operator explicitly asks to create/generate a video."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "What the video should show."},
            "duration": {"type": "integer", "description": "Seconds (default 5)."},
            "ratio": {"type": "string", "description": "e.g. '1280:768' (default) or '768:1280'."},
        },
        "required": ["prompt"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        prompt = (kwargs.get("prompt") or "").strip()
        if not prompt:
            raise ToolError("prompt is required")
        duration = int(kwargs.get("duration") or 5)
        ratio = (kwargs.get("ratio") or "1280:768").strip()
        try:
            res = _run_runway(prompt, duration, ratio)
        except Exception as e:
            raise ToolError(f"video generation failed: {e}")
        if not isinstance(res, dict) or not res.get("success"):
            raise ToolError(str((res or {}).get("error", "video generation failed")))
        return {
            "prompt": prompt, "duration": duration,
            "video_path": res.get("local_path"), "video_url": res.get("video_url"),
            "note": "Generated via Runway ML — costs credits; took ~minutes.",
        }
