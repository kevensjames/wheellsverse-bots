"""image_gen — KAI generates an image locally (SDXL-Turbo) from a text prompt.

Wraps the legacy local image pipeline (core/local_image.py): runs on the host
GPU, FREE, no API quota (works even with OpenAI at 429). Saves a PNG and returns
its path. Fail-soft — if the diffusers/torch deps aren't present, returns a
clear ToolError rather than crashing the chat.

The legacy bots live in core/ (repo root), a separate package from the daemon's
app/ — so we add the repo root to sys.path before importing it.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from app.services.tools.base import ToolContext, ToolError

logger = logging.getLogger(__name__)
_REPO = Path(__file__).resolve().parents[4]  # backend/app/services/tools/ -> repo root


def _run_local_image(prompt: str, size: str) -> str:
    """Generate one PNG via core.local_image; return its file path. Raises on
    failure (missing deps, model error)."""
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    from core import local_image
    if not local_image.is_available():
        raise RuntimeError("local image deps (diffusers/torch) not installed on host")
    resp = local_image.generate(prompt=prompt, size=size, n=1)
    url = resp.data[0].url  # 'file:///…png'
    return url.replace("file://", "", 1)


class ImageGenTool:
    name = "image_gen"
    description = (
        "Generate an image from a text prompt LOCALLY (SDXL-Turbo on the host "
        "GPU — free, no API quota). Saves a PNG and returns its file path. Use "
        "when asked to create/generate/draw an image, cover art, or a visual."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "What to depict (be descriptive)."},
            "size": {"type": "string",
                     "description": "WxH — '1024x1024' (default), '1024x1536', '512x512'."},
        },
        "required": ["prompt"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        prompt = (kwargs.get("prompt") or "").strip()
        if not prompt:
            raise ToolError("prompt is required")
        size = (kwargs.get("size") or "1024x1024").strip()
        try:
            path = _run_local_image(prompt, size)
        except Exception as e:
            raise ToolError(f"image generation failed: {e}")
        return {
            "prompt": prompt, "size": size, "image_path": path,
            "note": f"Generated locally (SDXL-Turbo) → {path}. Free, on-device, no API quota.",
        }
