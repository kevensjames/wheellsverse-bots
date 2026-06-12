#!/usr/bin/env python3
"""
narai/godmode/media/image_composer.py
─────────────────────────────────────────────────────────────────────────────
Two-layer image pipeline:
  1. generate_clean_image()  →  DALL-E 3 with text-suppression suffix
  2. add_text_overlay()      →  Pillow draws headline/subtext on top
  3. compose_post()          →  orchestrates both + WheellsVerse branding

Fonts: Inter-Bold.ttf / Inter-Regular.ttf (narai/godmode/media/fonts/)
       falls back to system Helvetica or PIL default.

Logging: narai/godmode/logs/media_pipeline.log
Format:  timestamp | stage | status | asset_id | detail
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
FONTS_DIR = Path(__file__).parent / "fonts"
MEDIA_LOG = Path(__file__).parent.parent / "logs" / "media_pipeline.log"

load_dotenv(ROOT / ".env")

log = logging.getLogger("image_composer")

# WheellsVerse brand palette
BRAND_DEFAULTS: dict[str, str] = {
    "bg":     "#0a0a0a",
    "cyan":   "#00F0FF",
    "gold":   "#FFD700",
    "white":  "#FFFFFF",
}

# Appended to every DALL-E prompt to suppress text generation
_NO_TEXT_SUFFIX = (
    ", no text, no letters, no words, no typography, no writing, "
    "no labels, no captions, no titles, no watermarks, "
    "clean composition, visual only"
)

_DALLE_URL = "https://api.openai.com/v1/images/generations"
_TTS_URL   = "https://api.openai.com/v1/audio/speech"


# ── SSRF guard ────────────────────────────────────────────────────────────────

class _UnsafeURLError(Exception):
    """Raised when an external URL fails the SSRF allowlist."""


def _assert_safe_https_url(url: str) -> None:
    """
    Reject anything that isn't HTTPS pointing at a public IP.

    Defends against the OpenAI image-fetch path being redirected at
    file://, http://, or RFC1918/link-local/loopback addresses
    (e.g. AWS metadata 169.254.169.254).
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise _UnsafeURLError(f"non-https scheme rejected: {parsed.scheme!r}")
    if not parsed.hostname:
        raise _UnsafeURLError("missing hostname")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise _UnsafeURLError(f"DNS resolution failed: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise _UnsafeURLError(f"resolved to disallowed address: {ip}")


# ── Font loading ──────────────────────────────────────────────────────────────

def _load_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """Load Inter (or fallback) at the requested size."""
    candidates: dict[str, list[str]] = {
        "bold":    ["Inter-Bold.ttf", "Inter_Bold.ttf", "Montserrat-Bold.ttf"],
        "regular": ["Inter-Regular.ttf", "Inter_Regular.ttf", "Montserrat-Regular.ttf"],
    }
    for name in candidates.get(weight, candidates["regular"]):
        path = FONTS_DIR / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    # System font fallbacks
    for sys_path in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if Path(sys_path).exists():
            try:
                return ImageFont.truetype(sys_path, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ── Core functions ────────────────────────────────────────────────────────────

def generate_clean_image(prompt: str, size: str = "1024x1024") -> Optional[Image.Image]:
    """
    Call DALL-E 3 with text-suppression suffix appended to prompt.
    Returns PIL Image (RGBA) or None on failure.
    """
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        log.warning("OPENAI_API_KEY not set — cannot generate image")
        return None

    clean_prompt = prompt.rstrip(". ,") + _NO_TEXT_SUFFIX
    body = json.dumps({
        "model": "dall-e-3",
        "prompt": clean_prompt,
        "n": 1,
        "size": size,
        "quality": "standard",
        "response_format": "url",
    }).encode()

    req = urllib.request.Request(
        _DALLE_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        url = data["data"][0]["url"]
        _assert_safe_https_url(url)
        _media_log("generate_clean_image", "ok", detail=url[:80])
        with urllib.request.urlopen(url, timeout=30) as img_resp:
            img = Image.open(img_resp)
            img.load()
            return img.convert("RGBA")
    except Exception as exc:
        log.error(f"generate_clean_image failed: {exc}")
        _media_log("generate_clean_image", "error", detail=str(exc)[:120])
        return None


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Break text into lines that fit within max_width pixels."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines or [text]


def add_text_overlay(
    image: Image.Image,
    text_blocks: list[dict],
    brand: str = "wheellsverse",
) -> Image.Image:
    """
    Draw text blocks onto image with drop-shadow support.

    Each block dict keys:
      text       str   — content to draw
      position   (x,y) — top-left origin (default (50,50))
      size       int   — font size in px (default 48)
      color      str   — hex color (default #FFFFFF)
      weight     str   — "bold" | "regular" (default "bold")
      max_width  int   — wrap width in px (default image_width - x - 50)
      shadow     bool  — drop shadow (default True)
    """
    img = image.copy().convert("RGBA")
    draw = ImageDraw.Draw(img)

    for block in text_blocks:
        text = block["text"]
        x, y = block.get("position", (50, 50))
        size = block.get("size", 48)
        color = block.get("color", "#FFFFFF")
        weight = block.get("weight", "bold")
        max_width = block.get("max_width", img.width - x - 50)
        shadow = block.get("shadow", True)

        font = _load_font(size, weight)
        lines = _wrap_text(draw, text, font, max_width)
        line_height = int(size * 1.25)

        for i, line in enumerate(lines):
            lx = x
            ly = y + i * line_height
            if shadow:
                draw.text((lx + 2, ly + 2), line, font=font, fill="#000000CC")
            draw.text((lx, ly), line, font=font, fill=color)

    return img.convert("RGB")


def compose_post(
    visual_prompt: str,
    headline: str,
    subtext: Optional[str] = None,
    brand_config: Optional[dict] = None,
    out_dir: Optional[Path] = None,
) -> Optional[str]:
    """
    Full pipeline: DALL-E 3 (text-free) → Pillow text overlay → save PNG.
    Returns absolute file path or None on failure.

    Falls back to a solid brand-color canvas if DALL-E is unavailable.
    """
    brand = {**BRAND_DEFAULTS, **(brand_config or {})}
    out_dir = out_dir or (ROOT / "outputs" / "media")
    out_dir.mkdir(parents=True, exist_ok=True)

    _media_log("compose_post", "start", detail=headline[:60])

    img = generate_clean_image(visual_prompt)
    if img is None:
        # Fallback: solid dark canvas so publishing can still proceed
        img = Image.new("RGBA", (1024, 1024), brand["bg"])
        _media_log("compose_post", "fallback_canvas", detail="solid bg — DALL-E unavailable")

    w, h = img.size
    headline_y = h // 3
    headline_size = 72

    # Pre-measure wrapped headline height so subtext never overlaps
    _tmp_draw = ImageDraw.Draw(Image.new("RGBA", (w, h)))
    _headline_font = _load_font(headline_size, "bold")
    _headline_lines = _wrap_text(_tmp_draw, headline, _headline_font, w - 120)
    subtext_y = headline_y + len(_headline_lines) * int(headline_size * 1.25) + 20

    text_blocks: list[dict] = [
        {
            "text": headline,
            "position": (60, headline_y),
            "size": headline_size,
            "color": brand["cyan"],
            "weight": "bold",
            "max_width": w - 120,
            "shadow": True,
        },
    ]
    if subtext:
        text_blocks.append({
            "text": subtext,
            "position": (60, subtext_y),
            "size": 40,
            "color": brand["white"],
            "weight": "regular",
            "max_width": w - 120,
            "shadow": True,
        })
    # Brand watermark
    text_blocks.append({
        "text": "wheellsverse.com",
        "position": (60, h - 70),
        "size": 28,
        "color": brand["gold"],
        "weight": "regular",
        "max_width": 500,
        "shadow": True,
    })

    final = add_text_overlay(img, text_blocks)

    slug = "".join(c if c.isalnum() else "_" for c in headline.lower())[:30] or "post"
    out_path = out_dir / f"post_{slug}_{time.time_ns()}.png"
    final.save(str(out_path), "PNG")

    _media_log("compose_post", "saved", detail=str(out_path))
    log.info(f"[ImageComposer] Saved → {out_path}")
    return str(out_path)


# ── Logging ───────────────────────────────────────────────────────────────────

def _media_log(
    stage: str,
    status: str,
    asset_id: str = "-",
    detail: str = "",
) -> None:
    """Append one structured line to media_pipeline.log."""
    MEDIA_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} | {stage:<30} | {status:<10} | {asset_id:<20} | {detail}\n"
    try:
        with open(MEDIA_LOG, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass
