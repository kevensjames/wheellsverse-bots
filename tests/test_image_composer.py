"""
tests/test_image_composer.py
─────────────────────────────────────────────────────────────────────────────
Tests for narai_godmode/media/image_composer.py.

All tests run offline — no real DALL-E calls.
OCR check: if pytesseract is installed, verify <5 chars of raw text bleed
through from the background canvas (text must come from our overlay, not
DALL-E hallucinations).
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from narai_godmode.media.image_composer import (
    _load_font,
    _wrap_text,
    add_text_overlay,
    compose_post,
    generate_clean_image,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def blank_1024() -> Image.Image:
    """Plain black 1024×1024 canvas — no DALL-E needed."""
    return Image.new("RGBA", (1024, 1024), "#0a0a0a")


@pytest.fixture
def tmp_out(tmp_path: Path) -> Path:
    return tmp_path


# ── Font loading ──────────────────────────────────────────────────────────────

def test_load_font_returns_font():
    font = _load_font(48, "bold")
    assert font is not None


def test_load_font_regular():
    font = _load_font(32, "regular")
    assert font is not None


def test_load_font_small_size():
    font = _load_font(12)
    assert font is not None


# ── Text wrapping ─────────────────────────────────────────────────────────────

def test_wrap_text_short_fits_one_line(blank_1024):
    from PIL import ImageDraw
    draw = ImageDraw.Draw(blank_1024)
    font = _load_font(48, "bold")
    lines = _wrap_text(draw, "Short", font, max_width=900)
    assert len(lines) == 1
    assert lines[0] == "Short"


def test_wrap_text_long_wraps(blank_1024):
    from PIL import ImageDraw
    draw = ImageDraw.Draw(blank_1024)
    font = _load_font(48, "bold")
    long_text = "YOUR SAVINGS ACCOUNT IS PAYING YOU 0.5 PERCENT AND DEFI IS PAYING TEN PERCENT"
    lines = _wrap_text(draw, long_text, font, max_width=500)
    assert len(lines) > 1
    # All words preserved when rejoined
    assert " ".join(lines) == long_text


def test_wrap_text_empty_string(blank_1024):
    from PIL import ImageDraw
    draw = ImageDraw.Draw(blank_1024)
    font = _load_font(48)
    lines = _wrap_text(draw, "", font, max_width=900)
    assert isinstance(lines, list)


# ── add_text_overlay ──────────────────────────────────────────────────────────

def test_add_text_overlay_returns_rgb_image(blank_1024):
    blocks = [{"text": "DEFI IS PAYING 10%+", "position": (60, 300), "size": 72, "color": "#00F0FF", "weight": "bold"}]
    result = add_text_overlay(blank_1024, blocks)
    assert result.mode == "RGB"
    assert result.size == (1024, 1024)


def test_add_text_overlay_does_not_mutate_original(blank_1024):
    original_px = blank_1024.copy().tobytes()
    blocks = [{"text": "Test", "position": (100, 100), "size": 48, "color": "#FFFFFF"}]
    add_text_overlay(blank_1024, blocks)
    assert blank_1024.tobytes() == original_px


def test_add_text_overlay_multiple_blocks(blank_1024):
    blocks = [
        {"text": "HEADLINE", "position": (60, 300), "size": 72, "color": "#00F0FF", "weight": "bold"},
        {"text": "Subtext below the headline", "position": (60, 420), "size": 36, "color": "#FFFFFF", "weight": "regular"},
        {"text": "wheellsverse.com", "position": (60, 950), "size": 24, "color": "#FFD700"},
    ]
    result = add_text_overlay(blank_1024, blocks)
    assert result.size == (1024, 1024)


def test_add_text_overlay_shadow_does_not_crash(blank_1024):
    blocks = [{"text": "Drop Shadow Test", "position": (60, 300), "size": 60, "color": "#00F0FF", "shadow": True}]
    result = add_text_overlay(blank_1024, blocks)
    assert result is not None


def test_add_text_overlay_no_shadow(blank_1024):
    blocks = [{"text": "No Shadow", "position": (60, 300), "size": 60, "color": "#FFFFFF", "shadow": False}]
    result = add_text_overlay(blank_1024, blocks)
    assert result is not None


# ── OCR regression: text must come from overlay, not DALL-E canvas ────────────

def test_overlay_text_is_detectable_via_ocr(blank_1024, tmp_out):
    """
    Text written by add_text_overlay should be readable by OCR.
    (Proves our overlay is actually rendering text — not a blank canvas.)
    """
    pytest.importorskip("pytesseract", reason="pytesseract not installed — skipping OCR test")
    import pytesseract

    blocks = [{"text": "WHEELLSVERSE", "position": (60, 400), "size": 80, "color": "#FFFFFF", "weight": "bold", "shadow": False}]
    result = add_text_overlay(blank_1024, blocks)
    out = tmp_out / "ocr_test.png"
    result.save(str(out))
    ocr_text = pytesseract.image_to_string(str(out)).upper().replace(" ", "").replace("\n", "")
    # Our overlay text must be detectable
    assert "WHEELLSVERSE" in ocr_text, f"OCR didn't find overlay text; got: {ocr_text!r}"


def test_solid_canvas_has_minimal_ocr_text():
    """
    A plain solid canvas (simulating what we pass to DALL-E) should have
    near-zero OCR-readable text — confirms the baseline before overlay.
    """
    pytest.importorskip("pytesseract", reason="pytesseract not installed — skipping OCR test")
    import pytesseract

    canvas = Image.new("RGB", (1024, 1024), "#0a0a0a")
    ocr_text = pytesseract.image_to_string(canvas).strip()
    assert len(ocr_text) <= 5, f"Blank canvas returned unexpected text: {ocr_text!r}"


# ── generate_clean_image (mocked) ─────────────────────────────────────────────

def test_generate_clean_image_appends_no_text_suffix():
    """Verify the no-text suffix is appended to the prompt sent to DALL-E."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        if "generations" in req.full_url:
            import json
            body = json.loads(req.data)
            captured["prompt"] = body["prompt"]
            # Return a fake image URL response
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = json.dumps(
                {"data": [{"url": "https://fake.example.com/img.png"}]}
            ).encode()
            return mock_resp
        else:
            # Second call: download the image URL → return a 1×1 PNG
            import io
            img = Image.new("RGB", (1, 1), "#000000")
            buf = io.BytesIO()
            img.save(buf, "PNG")
            buf.seek(0)
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = buf.read()
            return mock_resp

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}), \
         patch("urllib.request.urlopen", fake_urlopen), \
         patch("PIL.Image.open", return_value=Image.new("RGBA", (1024, 1024))):
        result = generate_clean_image("A dark financial cityscape")

    assert "no text" in captured.get("prompt", "").lower()
    assert "no letters" in captured.get("prompt", "").lower()


def test_generate_clean_image_returns_none_without_api_key():
    with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
        result = generate_clean_image("Some visual prompt")
    assert result is None


def test_generate_clean_image_returns_none_on_api_error():
    import urllib.error
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}), \
         patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        result = generate_clean_image("Some visual prompt")
    assert result is None


# ── compose_post ──────────────────────────────────────────────────────────────

def test_compose_post_uses_fallback_canvas_when_dalle_unavailable(tmp_out):
    """When DALL-E returns None, compose_post should still produce a valid PNG."""
    with patch(
        "narai_godmode.media.image_composer.generate_clean_image",
        return_value=None,
    ):
        path = compose_post(
            visual_prompt="Abstract fintech scene",
            headline="YOUR BANK IS ROBBING YOU BLIND",
            subtext="DeFi pays 10x more than your savings account",
            out_dir=tmp_out,
        )
    assert path is not None
    assert Path(path).exists()
    assert Path(path).suffix == ".png"
    assert Path(path).stat().st_size > 0


def test_compose_post_output_is_valid_image(tmp_out):
    with patch(
        "narai_godmode.media.image_composer.generate_clean_image",
        return_value=Image.new("RGBA", (1024, 1024), "#1a1a2e"),
    ):
        path = compose_post(
            visual_prompt="Crypto bull run visualization",
            headline="BITCOIN $82K",
            out_dir=tmp_out,
        )
    img = Image.open(path)
    assert img.size == (1024, 1024)
    assert img.mode == "RGB"


def test_compose_post_with_subtext(tmp_out):
    with patch(
        "narai_godmode.media.image_composer.generate_clean_image",
        return_value=None,
    ):
        path = compose_post(
            visual_prompt="DeFi visualization",
            headline="DEFI IS PAYING 10%+",
            subtext="Traditional banks pay 0.5% — DeFi pays 10%+",
            out_dir=tmp_out,
        )
    assert Path(path).exists()


def test_compose_post_without_subtext(tmp_out):
    with patch(
        "narai_godmode.media.image_composer.generate_clean_image",
        return_value=None,
    ):
        path = compose_post(
            visual_prompt="Abstract scene",
            headline="100+ AI BOTS",
            out_dir=tmp_out,
        )
    assert Path(path).exists()


def test_compose_post_brand_config_applied(tmp_out):
    custom_brand = {"bg": "#FF0000", "cyan": "#00FF00", "gold": "#0000FF", "white": "#EEEEEE"}
    with patch(
        "narai_godmode.media.image_composer.generate_clean_image",
        return_value=None,
    ):
        path = compose_post(
            visual_prompt="Test scene",
            headline="Custom Brand",
            brand_config=custom_brand,
            out_dir=tmp_out,
        )
    assert Path(path).exists()


def test_assert_safe_https_url_rejects_non_https():
    """SSRF guard must reject http://, file://, ftp:// schemes."""
    from narai_godmode.media.image_composer import _assert_safe_https_url, _UnsafeURLError
    for bad in [
        "http://example.com/img.png",
        "file:///etc/passwd",
        "ftp://example.com/img.png",
    ]:
        with pytest.raises(_UnsafeURLError):
            _assert_safe_https_url(bad)


def test_assert_safe_https_url_rejects_private_addresses(monkeypatch):
    """SSRF guard must reject loopback / RFC1918 / link-local resolutions."""
    from narai_godmode.media.image_composer import _assert_safe_https_url, _UnsafeURLError
    import narai_godmode.media.image_composer as ic_mod

    # Force resolution to AWS metadata IP (link-local)
    monkeypatch.setattr(
        ic_mod.socket,
        "getaddrinfo",
        lambda host, port: [(0, 0, 0, "", ("169.254.169.254", 0))],
    )
    with pytest.raises(_UnsafeURLError, match="disallowed address"):
        _assert_safe_https_url("https://attacker.example.com/img.png")


def test_compose_post_subtext_does_not_overlap_headline(tmp_out):
    """Subtext y-position must start below the last wrapped headline line."""
    from PIL import ImageDraw
    from narai_godmode.media.image_composer import _load_font, _wrap_text

    captured: list[list[dict]] = []
    original_overlay = add_text_overlay

    def capturing_overlay(img, blocks, **kw):
        captured.append(list(blocks))
        return original_overlay(img, blocks, **kw)

    with patch("narai_godmode.media.image_composer.generate_clean_image", return_value=None), \
         patch("narai_godmode.media.image_composer.add_text_overlay", side_effect=capturing_overlay):
        compose_post(
            visual_prompt="test",
            headline="YOUR SAVINGS ACCOUNT IS ROBBING YOU BLIND",
            subtext="DeFi pays 10x more than your bank.",
            out_dir=tmp_out,
        )

    blocks = captured[0]
    headline_block = next(b for b in blocks if b["size"] == 72)
    subtext_block  = next(b for b in blocks if b["size"] == 40)

    # Compute actual wrapped headline height
    tmp_draw = ImageDraw.Draw(Image.new("RGBA", (1024, 1024)))
    font = _load_font(72, "bold")
    lines = _wrap_text(tmp_draw, headline_block["text"], font, headline_block["max_width"])
    headline_bottom = headline_block["position"][1] + len(lines) * int(72 * 1.25)

    subtext_top = subtext_block["position"][1]
    assert subtext_top > headline_bottom, (
        f"Subtext (y={subtext_top}) overlaps headline (bottom y={headline_bottom})"
    )


def test_compose_post_writes_media_log(tmp_out, monkeypatch):
    log_path = tmp_out / "media_pipeline.log"
    monkeypatch.setattr(
        "narai_godmode.media.image_composer.MEDIA_LOG", log_path
    )
    with patch("narai_godmode.media.image_composer.generate_clean_image", return_value=None):
        compose_post("Test", "LOG TEST", out_dir=tmp_out)
    assert log_path.exists()
    content = log_path.read_text()
    assert "compose_post" in content
