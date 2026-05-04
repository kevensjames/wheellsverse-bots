#!/usr/bin/env python3
"""
core/social_image.py
─────────────────────────────────────────────────────────────────────────────
Sharp social-media images for Instagram and Facebook.

DALL-E 3 (HD) renders a clean *background* with deliberate empty space at top
and bottom. Pillow then composites a crisp TrueType headline on top — DALL-E
can't reliably render readable text, so we never ask it to.

Output is JPEG at platform-native resolution with high quality + 4:4:4 chroma
so headline text doesn't bleed under platform recompression.

Public surface:
    generate_social_image(headline, subtext="", platform="instagram_feed",
                          style_hint="") -> Path
    upload_to_public_url(local_path) -> str | None

Both Instagram and Facebook publishers should call generate_social_image()
followed by upload_to_public_url() instead of asking DALL-E to render text.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger("social_image")

OUTPUT_DIR = ROOT / "outputs" / "social_images"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
DALLE_URL = "https://api.openai.com/v1/images/generations"

# Bundled Inter (SIL OFL) — works on Linux Railway containers + Mac dev.
_FONT_BOLD_CANDIDATES = [
    ROOT / "assets" / "fonts" / "Inter-Bold.ttf",
    Path("/System/Library/Fonts/HelveticaNeue.ttc"),
    Path("/System/Library/Fonts/Helvetica.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
_FONT_REGULAR_CANDIDATES = [
    ROOT / "assets" / "fonts" / "Inter-Regular.ttf",
    Path("/System/Library/Fonts/HelveticaNeue.ttc"),
    Path("/System/Library/Fonts/Helvetica.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]


# ─── Platform geometry ───────────────────────────────────────────────────────

# (final_w, final_h, dalle_size, has_subtext_band)
_PLATFORMS = {
    "instagram_feed":       (1080, 1080, "1024x1024", True),
    "instagram_story":      (1080, 1920, "1024x1792", True),
    "instagram_reel_cover": (1080, 1920, "1024x1792", True),
    "facebook_feed":        (1200,  630, "1792x1024", True),
    # Profile/branding assets — no headline overlay (logo art on the DALL-E pass).
    "profile_avatar":       (1080, 1080, "1024x1024", False),
    "facebook_cover":       (1640,  924, "1792x1024", False),
    "instagram_story_banner": (1080, 1920, "1024x1792", False),
}


# ─── Font helpers ────────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool):
    """First TTF that exists on disk wins. Falls back to PIL default (last resort)."""
    from PIL import ImageFont
    candidates = _FONT_BOLD_CANDIDATES if bold else _FONT_REGULAR_CANDIDATES
    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size=size)
            except Exception as e:
                log.warning("Font %s unreadable: %s", p, e)
    log.warning("No TrueType font found — falling back to PIL default (text will look poor)")
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int, draw) -> list[str]:
    """Greedy word-wrap that respects the rendered width of each line."""
    words = text.split()
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        trial = " ".join(cur + [w])
        if draw.textlength(trial, font=font) <= max_width:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def _autosize_headline(text: str, max_width: int, max_lines: int,
                       max_height: int, draw, start: int = 96, floor: int = 36):
    """Bisect down on font size until the headline fits both width and height."""
    size = start
    while size >= floor:
        font = _load_font(size, bold=True)
        lines = _wrap_text(text, font, max_width, draw)
        line_h = font.getbbox("Hg")[3] - font.getbbox("Hg")[1]
        total_h = line_h * len(lines) + (len(lines) - 1) * int(line_h * 0.25)
        if len(lines) <= max_lines and total_h <= max_height:
            return font, lines, line_h
        size -= 4
    # Couldn't fit — return floor size + as many lines as it produced.
    font = _load_font(floor, bold=True)
    lines = _wrap_text(text, font, max_width, draw)
    line_h = font.getbbox("Hg")[3] - font.getbbox("Hg")[1]
    return font, lines[:max_lines], line_h


# ─── DALL-E background ───────────────────────────────────────────────────────

def _dalle_background(prompt: str, size: str) -> Optional[bytes]:
    """One HD DALL-E 3 generation. Returns raw image bytes or None."""
    if not OPENAI_KEY:
        log.warning("OPENAI_API_KEY not set — cannot generate background image")
        return None
    try:
        body = json.dumps({
            "model": "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": size,
            "quality": "hd",
            "response_format": "url",
        }).encode()
        req = urllib.request.Request(
            DALLE_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        url = data.get("data", [{}])[0].get("url")
        if not url:
            log.warning("DALL-E returned no URL: %s", str(data)[:200])
            return None
        with urllib.request.urlopen(url, timeout=60) as img_resp:
            return img_resp.read()
    except Exception as e:
        log.warning("DALL-E HD generation failed: %s", e)
        return None


def _build_prompt(headline: str, style_hint: str = "") -> str:
    """Background prompt — explicitly avoid embedded text."""
    base_style = (
        style_hint
        or "Dark futuristic tech aesthetic, deep navy and indigo background, "
           "subtle cyan and gold highlights, soft volumetric lighting, "
           "abstract geometric shapes and glowing particles, premium SaaS brand visual"
    )
    return (
        f"{base_style}. The image is a clean atmospheric background scene loosely inspired by "
        f"the theme: '{headline[:140]}'. "
        "Composition leaves the top third and bottom third visually calm with smooth gradients "
        "so headline text can be overlaid later. "
        "Absolutely no embedded text, no letters, no words, no logos, no watermarks. "
        "8k commercial photography quality, ultra-sharp."
    )


# ─── Public composer ─────────────────────────────────────────────────────────

def generate_social_image(headline: str, subtext: str = "",
                          platform: str = "instagram_feed",
                          style_hint: str = "") -> Optional[Path]:
    """
    Build a publish-ready social image: HD DALL-E background + Pillow text overlay.

    Returns the local Path to the JPEG, or None if generation failed.
    """
    if platform not in _PLATFORMS:
        log.warning("Unknown platform %r — using instagram_feed geometry", platform)
        platform = "instagram_feed"
    final_w, final_h, dalle_size, with_text = _PLATFORMS[platform]

    img_bytes = _dalle_background(_build_prompt(headline, style_hint), dalle_size)
    if not img_bytes:
        return None

    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFilter

    bg = Image.open(BytesIO(img_bytes)).convert("RGB")
    # Cover-fit to platform aspect (crop center) then upscale with LANCZOS.
    target_ratio = final_w / final_h
    src_ratio = bg.width / bg.height
    if src_ratio > target_ratio:
        # source wider than target — crop sides
        new_w = int(bg.height * target_ratio)
        left = (bg.width - new_w) // 2
        bg = bg.crop((left, 0, left + new_w, bg.height))
    elif src_ratio < target_ratio:
        # source taller than target — crop top/bottom
        new_h = int(bg.width / target_ratio)
        top = (bg.height - new_h) // 2
        bg = bg.crop((0, top, bg.width, top + new_h))
    bg = bg.resize((final_w, final_h), Image.Resampling.LANCZOS)

    # Brand-asset platforms (avatar, cover, story banner) skip the text overlay
    # — DALL-E art only, save and return.
    if not with_text:
        safe = "".join(c if c.isalnum() else "_" for c in (headline or platform).lower()[:40]).strip("_") or platform
        fname = f"{safe}_{platform}_{int(time.time())}.jpg"
        out_path = OUTPUT_DIR / fname
        bg.save(out_path, "JPEG", quality=92, subsampling=0, optimize=True,
                progressive=True, dpi=(144, 144))
        log.info("Composed brand asset: %s (%dx%d, no text overlay)",
                 out_path.name, final_w, final_h)
        return out_path

    # Top dark gradient band so headline contrasts no matter the background.
    band_h = int(final_h * 0.42)
    overlay = Image.new("RGBA", (final_w, final_h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(band_h):
        alpha = int(190 * (1 - (y / band_h) ** 1.4))
        od.rectangle([(0, y), (final_w, y + 1)], fill=(8, 10, 22, alpha))
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")

    # Compose the headline + optional subtext.
    draw = ImageDraw.Draw(bg)
    pad_x = int(final_w * 0.07)
    text_zone_w = final_w - 2 * pad_x
    safe_h = int(band_h * 0.78)

    headline_font, hl_lines, hl_line_h = _autosize_headline(
        headline.strip() or "WheellsVerse",
        max_width=text_zone_w,
        max_lines=4,
        max_height=safe_h,
        draw=draw,
        start=int(final_h * 0.085),
        floor=int(final_h * 0.035),
    )
    line_gap = int(hl_line_h * 0.25)
    block_h = hl_line_h * len(hl_lines) + line_gap * (len(hl_lines) - 1)
    y = max(int(final_h * 0.07), (band_h - block_h) // 2)

    # Soft drop shadow for headline so platform compression can't smear it.
    shadow_layer = Image.new("RGBA", (final_w, final_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    for line in hl_lines:
        sd.text((pad_x + 3, y + 3), line, font=headline_font, fill=(0, 0, 0, 180))
        y += hl_line_h + line_gap
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=3))
    bg = Image.alpha_composite(bg.convert("RGBA"), shadow_layer).convert("RGB")

    draw = ImageDraw.Draw(bg)
    y = max(int(final_h * 0.07), (band_h - block_h) // 2)
    for line in hl_lines:
        draw.text((pad_x, y), line, font=headline_font, fill=(255, 255, 255))
        y += hl_line_h + line_gap

    if subtext:
        sub_size = max(22, int(hl_line_h * 0.42))
        sub_font = _load_font(sub_size, bold=False)
        sub_lines = _wrap_text(subtext.strip(), sub_font, text_zone_w, draw)[:2]
        sub_y = y + int(hl_line_h * 0.4)
        for line in sub_lines:
            draw.text((pad_x, sub_y), line, font=sub_font, fill=(220, 230, 245))
            sub_y += int(sub_size * 1.25)

    # Save high-quality JPEG with 4:4:4 chroma so text edges stay crisp.
    safe = "".join(c if c.isalnum() else "_" for c in headline.lower()[:40]).strip("_") or "post"
    fname = f"{safe}_{platform}_{int(time.time())}.jpg"
    out_path = OUTPUT_DIR / fname
    bg.save(out_path, "JPEG",
            quality=92, subsampling=0, optimize=True, progressive=True,
            dpi=(144, 144))
    log.info("Composed social image: %s (%dx%d)", out_path.name, final_w, final_h)
    return out_path


# ─── Public URL upload ───────────────────────────────────────────────────────

def upload_to_public_url(local_path: Path) -> Optional[str]:
    """
    Return an HTTPS URL Meta Graph API can fetch for this image.

    Today: relies on the FastAPI app exposing /social-media/* statically backed
    by OUTPUT_DIR (mount added in core/api.py). The base URL comes from
    RAILWAY_PUBLIC_URL, which is the Railway public hostname in production.

    Returns None if RAILWAY_PUBLIC_URL is not configured — callers should
    handle that and either fall back to browser publishing or skip.
    """
    base = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
    if not base:
        log.warning("RAILWAY_PUBLIC_URL not set — cannot expose %s publicly", local_path.name)
        return None
    if not str(local_path).startswith(str(OUTPUT_DIR)):
        log.warning("Image %s is outside %s — cannot publish via /social-media mount",
                    local_path, OUTPUT_DIR)
        return None
    return f"{base}/social-media/{local_path.name}"
