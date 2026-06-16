"""image_gen (local SDXL) + video_gen (Runway) — KAI media tools. Mocks the
generator helpers so no model/network runs. Asserts validation, success shape,
fail-soft, and conditional registration."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.services.tools import image_gen as ig
from app.services.tools import video_gen as vg
from app.services.tools.base import ToolContext, ToolError
from app.services.tools.image_gen import ImageGenTool
from app.services.tools.video_gen import VideoGenTool


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


# ─── image_gen ───────────────────────────────────────────────────────


def test_image_blank_prompt_raises():
    with pytest.raises(ToolError):
        ImageGenTool().execute(_ctx(), prompt="  ")


def test_image_success(monkeypatch):
    monkeypatch.setattr(ig, "_run_local_image", lambda p, s: "/data/img/out.png")
    out = ImageGenTool().execute(_ctx(), prompt="a fox", size="512x512")
    assert out["image_path"] == "/data/img/out.png"
    assert out["size"] == "512x512" and "no API quota" in out["note"]


def test_image_failsoft(monkeypatch):
    def _boom(p, s):
        raise RuntimeError("diffusers not installed")
    monkeypatch.setattr(ig, "_run_local_image", _boom)
    with pytest.raises(ToolError):
        ImageGenTool().execute(_ctx(), prompt="x")


def test_image_registered_always():
    from app.services.tools import build_default_registry
    reg = build_default_registry(include_composio=False, include_mcp=False)
    assert "image_gen" in reg.names()


# ─── video_gen ───────────────────────────────────────────────────────


def test_video_blank_prompt_raises():
    with pytest.raises(ToolError):
        VideoGenTool().execute(_ctx(), prompt="")


def test_video_success(monkeypatch):
    monkeypatch.setattr(vg, "_run_runway",
                        lambda p, d, r: {"success": True, "local_path": "/data/vid/x.mp4",
                                         "video_url": "https://runway/x.mp4"})
    out = VideoGenTool().execute(_ctx(), prompt="a city flythrough", duration=5)
    assert out["video_path"] == "/data/vid/x.mp4" and out["duration"] == 5


def test_video_failure_raises(monkeypatch):
    monkeypatch.setattr(vg, "_run_runway",
                        lambda p, d, r: {"success": False, "error": "Runway timed out"})
    with pytest.raises(ToolError):
        VideoGenTool().execute(_ctx(), prompt="x")


def test_video_registered_only_when_key(monkeypatch):
    from app.services.tools import build_default_registry
    monkeypatch.delenv("RUNWAYML_API_KEY", raising=False)
    assert "video_gen" not in build_default_registry(include_composio=False, include_mcp=False).names()
    monkeypatch.setenv("RUNWAYML_API_KEY", "rw_test")
    assert "video_gen" in build_default_registry(include_composio=False, include_mcp=False).names()
