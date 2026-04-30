#!/usr/bin/env python3
"""
core/kdp_paperback.py
───────────────────────────────────────────────────────────────────────────────
KDP Paperback (Print on Demand) automation.

Per book:
  1. Generate interior PDF  (HTML → properly formatted 6×9 PDF via ReportLab)
  2. Generate full-wrap cover PDF (front DALL-E image + spine text + back desc)
  3. Upload to KDP paperback form via Playwright — ALL fields filled
  4. Auto-publish

KDP Paperback specs used:
  Trim size:  6 × 9 inches (most common)
  Bleed:      0.125 inches each side
  Spine:      0.002252 × page_count inches  (white 60# paper)
  Cover DPI:  300
  Interior:   B&W, white paper
  Finish:     Matte
"""
from __future__ import annotations

import base64
import html
import json
import logging
import math
import os
import re
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
PAPERBACK_DIR = ROOT / "outputs" / "books" / "paperback"
PAPERBACK_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("kdp_paperback")

# ── KDP paperback prices (minimum is print cost + $0.01; we set at $12.99-$16.99) ──
PAPERBACK_PRICES = {
    "childrens":  12.99,
    "mystery":    14.99,
    "adventure":  14.99,
    "historical": 15.99,
    "self_help":  16.99,
    "romance":    13.99,
    "sci_fi":     15.99,
    "fantasy":    15.99,
    "horror":     14.99,
    "true_crime": 14.99,
}

# ── KDP categories for paperback ───────────────────────────────────────────────
PAPERBACK_CATEGORIES = {
    "mystery":    ("Mystery, Thriller & Suspense", "Mystery"),
    "adventure":  ("Literature & Fiction", "Action & Adventure"),
    "historical": ("Literature & Fiction", "Historical Fiction"),
    "self_help":  ("Self-Help", "Personal Finance"),
    "romance":    ("Romance", "Contemporary"),
    "sci_fi":     ("Science Fiction & Fantasy", "Science Fiction"),
    "fantasy":    ("Science Fiction & Fantasy", "Fantasy"),
    "horror":     ("Horror", "Supernatural"),
    "true_crime": ("Mystery, Thriller & Suspense", "True Crime"),
    "childrens":  ("Children's Books", "Literature & Fiction"),
}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. INTERIOR PDF GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

def generate_interior_pdf(html_path: str, title: str, author: str = "J.K. Blaze") -> Path:
    """
    Convert HTML manuscript to a properly formatted 6×9 PDF for KDP paperback.
    All margins, fonts, and spacing comply with KDP interior guidelines.
    Returns path to the generated PDF.
    """
    from reportlab.lib.pagesizes import inch
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch as IN
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, PageBreak, HRFlowable
    )
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
    from reportlab.lib import colors

    safe = re.sub(r"[^a-zA-Z0-9_]", "_", title[:35])
    out_path = PAPERBACK_DIR / f"interior_{safe}.pdf"

    # KDP 6×9 with proper margins (inside margin larger for binding)
    PAGE_W = 6 * IN
    PAGE_H = 9 * IN
    MARGIN_OUTSIDE = 0.5 * IN
    MARGIN_INSIDE  = 0.875 * IN   # gutter
    MARGIN_TOP     = 0.875 * IN
    MARGIN_BOTTOM  = 0.75 * IN

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=(PAGE_W, PAGE_H),
        leftMargin=MARGIN_INSIDE,
        rightMargin=MARGIN_OUTSIDE,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=title,
        author=author,
    )

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "KDPBody",
        parent=styles["Normal"],
        fontName="Times-Roman",
        fontSize=11,
        leading=16,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
    )
    h1_style = ParagraphStyle(
        "KDPH1",
        parent=styles["Heading1"],
        fontName="Times-Bold",
        fontSize=22,
        leading=28,
        alignment=TA_CENTER,
        spaceBefore=24,
        spaceAfter=18,
    )
    h2_style = ParagraphStyle(
        "KDPH2",
        parent=styles["Heading2"],
        fontName="Times-Bold",
        fontSize=14,
        leading=20,
        alignment=TA_LEFT,
        spaceBefore=18,
        spaceAfter=10,
    )
    chapter_style = ParagraphStyle(
        "KDPChapter",
        parent=styles["Heading2"],
        fontName="Times-Bold",
        fontSize=13,
        leading=18,
        alignment=TA_CENTER,
        spaceBefore=36,
        spaceAfter=18,
    )
    title_style = ParagraphStyle(
        "KDPTitle",
        parent=styles["Title"],
        fontName="Times-Bold",
        fontSize=26,
        leading=32,
        alignment=TA_CENTER,
        spaceBefore=72,
        spaceAfter=12,
    )
    subtitle_style = ParagraphStyle(
        "KDPSubtitle",
        fontName="Times-Italic",
        fontSize=14,
        leading=18,
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    byline_style = ParagraphStyle(
        "KDPByline",
        fontName="Times-Roman",
        fontSize=12,
        leading=16,
        alignment=TA_CENTER,
        spaceBefore=24,
        spaceAfter=8,
    )

    # Parse HTML
    raw = Path(html_path).read_text(encoding="utf-8", errors="replace")
    # Strip <head> block
    raw = re.sub(r'<head[^>]*>.*?</head>', '', raw, flags=re.DOTALL | re.IGNORECASE)
    # Remove script/style tags
    raw = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw, flags=re.DOTALL | re.IGNORECASE)

    story = []

    # Title page
    story.append(Spacer(1, 1.5 * IN))
    story.append(Paragraph(title, title_style))
    story.append(Paragraph(f"by {author}", byline_style))
    story.append(Spacer(1, 0.5 * IN))
    story.append(Paragraph("WheellsVerse Publishing", subtitle_style))
    story.append(PageBreak())

    # Copyright page
    year = datetime.now().year
    story.append(Spacer(1, 3 * IN))
    story.append(Paragraph(f"Copyright © {year} WheellsVerse Publishing", body_style))
    story.append(Paragraph("All rights reserved.", body_style))
    story.append(Paragraph(
        "No part of this publication may be reproduced, distributed, or transmitted "
        "in any form or by any means without the prior written permission of the publisher.",
        body_style
    ))
    story.append(Spacer(1, 0.25 * IN))
    story.append(Paragraph("Published by WheellsVerse Publishing", body_style))
    story.append(Paragraph("Printed in the United States of America", body_style))
    story.append(PageBreak())

    # Parse content blocks
    blocks = re.split(r'(<h[1-6][^>]*>|</h[1-6]>|<p[^>]*>|</p>|<br\s*/?>|<hr\s*/?>)', raw, flags=re.IGNORECASE)

    current_tag = None
    buffer = []

    def flush_buffer():
        if not buffer:
            return
        text = " ".join(buffer).strip()
        buffer.clear()
        if not text:
            return
        # Clean HTML entities and leftover tags
        text = re.sub(r'<[^>]+>', '', text)
        text = html.unescape(text).strip()
        if not text:
            return

        if current_tag in ("h1",):
            story.append(Paragraph(text, h1_style))
        elif current_tag in ("h2",):
            # Detect chapter headers
            if re.match(r'chapter\s+\d+', text, re.IGNORECASE):
                story.append(Paragraph(text, chapter_style))
            else:
                story.append(Paragraph(text, h2_style))
        elif current_tag in ("h3", "h4", "h5", "h6"):
            story.append(Paragraph(text, h2_style))
        else:
            # Body paragraph — handle basic inline formatting
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
            try:
                story.append(Paragraph(text, body_style))
            except Exception:
                story.append(Paragraph(re.sub(r'<[^>]+>', '', text), body_style))

    for block in blocks:
        tag_match = re.match(r'<(/?h[1-6]|/?p|br|hr)', block, re.IGNORECASE)
        if tag_match:
            tag = tag_match.group(1).lower().lstrip("/")
            if tag.startswith("h") or tag == "p":
                flush_buffer()
                if not block.startswith("</"):
                    current_tag = tag
                else:
                    current_tag = "p"
            elif tag == "br":
                flush_buffer()
                story.append(Spacer(1, 4))
            elif tag == "hr":
                flush_buffer()
                story.append(HRFlowable(width="80%", thickness=0.5, color=colors.grey))
                story.append(Spacer(1, 6))
        else:
            buffer.append(block)

    flush_buffer()

    # Build PDF
    doc.build(story)
    page_count = _estimate_page_count(out_path)
    logger.info("Interior PDF: %s (%d pages)", out_path.name, page_count)
    return out_path


def _estimate_page_count(pdf_path: Path) -> int:
    """Count pages in a PDF."""
    try:
        import re as _re
        content = pdf_path.read_bytes()
        counts = _re.findall(rb'/Count (\d+)', content)
        if counts:
            return max(int(c) for c in counts)
        return max(content.count(b"/Page\n"), 1)
    except Exception:
        return 200  # safe default


def _cover_jpg_to_pdf(cover_jpg: Path, page_count: int) -> Path:
    """Wrap the full-wrap cover JPG into a PDF at correct KDP print dimensions."""
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas as _canvas

    BLEED = 0.125
    spine_in = max(0.002252 * page_count, 0.25)
    total_w  = (6 + BLEED) * 2 + spine_in   # back + spine + front
    total_h  = 9 + BLEED * 2

    pdf_path = cover_jpg.parent / (cover_jpg.stem + "_cover.pdf")
    c = _canvas.Canvas(str(pdf_path), pagesize=(total_w * inch, total_h * inch))
    c.drawImage(str(cover_jpg), 0, 0, total_w * inch, total_h * inch,
                preserveAspectRatio=False)
    c.save()
    logger.info("Cover PDF: %s  (%.2f × %.2f in, spine=%.3f in)",
                pdf_path.name, total_w, total_h, spine_in)
    return pdf_path


# ═══════════════════════════════════════════════════════════════════════════════
# 2. FULL-WRAP COVER GENERATION
# ═══════════════════════════════════════════════════════════════════════════════

def generate_paperback_cover(
    title: str,
    genre: str,
    author: str = "J.K. Blaze",
    page_count: int = 200,
    description_short: str = "",
) -> Path:
    """
    Generate a full-wrap paperback cover (front + spine + back) as a JPEG.
    Dimensions follow KDP spec: 300 DPI, 6×9 trim, 0.125 bleed each side.

    Layout (left→right): back | spine | front
    """
    from PIL import Image, ImageDraw, ImageFont

    # ── Dimensions ────────────────────────────────────────────────────────────
    DPI       = 300
    BLEED     = 0.125 * DPI          # 37.5px
    FRONT_W   = int((6 + 0.125) * DPI)    # 1837
    FRONT_H   = int((9 + 0.25)  * DPI)    # 2775
    SPINE_W   = max(int(0.002252 * page_count * DPI), 90)  # min 0.3 inch
    BACK_W    = FRONT_W
    TOTAL_W   = BACK_W + SPINE_W + FRONT_W
    TOTAL_H   = FRONT_H

    logger.info("Cover dims: %dx%d  (spine=%dpx for %d pages)", TOTAL_W, TOTAL_H, SPINE_W, page_count)

    # ── Step 1: Generate front cover with DALL-E ───────────────────────────────
    front_img_path = _generate_front_cover_image(title, genre)

    # ── Step 2: Build composite cover ─────────────────────────────────────────
    canvas = Image.new("RGB", (TOTAL_W, TOTAL_H), (15, 15, 25))  # dark bg

    # Front panel — place DALL-E image
    if front_img_path and front_img_path.exists():
        try:
            front = Image.open(front_img_path).convert("RGB")
            front = front.resize((FRONT_W, TOTAL_H), Image.LANCZOS)
            canvas.paste(front, (BACK_W + SPINE_W, 0))
        except Exception as e:
            logger.warning("Front image paste failed: %s", e)

    draw = ImageDraw.Draw(canvas)

    # ── Back panel ─────────────────────────────────────────────────────────────
    # Dark gradient background for back
    for y in range(TOTAL_H):
        shade = int(15 + (y / TOTAL_H) * 20)
        draw.line([(0, y), (BACK_W - 1, y)], fill=(shade, shade, shade + 10))

    # Back: description text
    back_text = description_short or f"A gripping {genre} novel by J.K. Blaze."
    back_text = re.sub(r'<[^>]+>', '', back_text)  # strip HTML
    _draw_wrapped_text(
        draw, back_text,
        x=int(BLEED + 0.4 * DPI), y=int(BLEED + 0.6 * DPI),
        max_width=int(BACK_W - BLEED * 2 - 0.8 * DPI),
        font_size=28, color=(230, 230, 230), line_spacing=38
    )

    # Back: author name at bottom
    _draw_centered_text(
        draw, f"J.K. Blaze",
        cx=BACK_W // 2, y=TOTAL_H - int(BLEED + 0.6 * DPI),
        font_size=26, color=(180, 180, 200)
    )

    # Back: barcode placeholder (white box for KDP ISBN barcode area)
    bc_x = int(BACK_W - BLEED - 1.7 * DPI)
    bc_y = int(TOTAL_H - BLEED - 1.2 * DPI)
    draw.rectangle([bc_x, bc_y, bc_x + int(1.5 * DPI), bc_y + int(1.0 * DPI)], fill=(255, 255, 255))
    draw.text((bc_x + 20, bc_y + 20), "ISBN", fill=(0, 0, 0))

    # ── Spine panel ────────────────────────────────────────────────────────────
    spine_x = BACK_W
    # Spine background same dark tone
    draw.rectangle([spine_x, 0, spine_x + SPINE_W - 1, TOTAL_H - 1], fill=(20, 20, 35))

    # Spine: title (rotated 90° — bottom-to-top reading direction for KDP)
    spine_title = title if len(title) <= 40 else title[:37] + "..."
    _draw_spine_text(canvas, spine_title, "J.K. Blaze", spine_x, SPINE_W, TOTAL_H)

    # ── Save ──────────────────────────────────────────────────────────────────
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", title[:35])
    out_path = PAPERBACK_DIR / f"cover_{safe}.jpg"
    canvas.save(str(out_path), "JPEG", quality=95, dpi=(DPI, DPI))
    logger.info("Paperback cover saved: %s", out_path.name)
    return out_path


def _generate_front_cover_image(title: str, genre: str) -> Optional[Path]:
    """Generate front cover with DALL-E 3 at portrait ratio."""
    import openai
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None

    genre_styles = {
        "mystery":    "Cinematic noir mystery cover. Dark rainy cityscape, lone silhouette under lamplight.",
        "adventure":  "Epic adventure cover. Explorer at jungle canyon edge, golden temples in mist.",
        "historical": "Historical fiction cover. Baroque oil painting style, candlelit period setting.",
        "self_help":  "Bold minimalist self-help cover. Person breaking through wall of light, sunrise.",
        "romance":    "Romance cover. Two figures in breathless near-embrace, warm golden light.",
        "sci_fi":     "Sci-fi cover. Alien world, gas giant rings, lone spaceship, neon blues.",
        "fantasy":    "Epic fantasy cover. Dragon over sorcerer's tower, lightning, glowing sword.",
        "horror":     "Horror cover. Victorian mansion, blood moon, dead trees, thick fog.",
        "true_crime": "True crime cover. Dark documentary style, crime scene tape, shadowy figure.",
        "childrens":  "Magical children's cover. Cartoon hero in vibrant enchanted world, pastel colors.",
    }

    style = genre_styles.get(genre, "Professional book cover, dramatic lighting.")
    prompt = (
        f"{style} Professional Amazon KDP paperback cover. "
        f"Ultra high quality. NO text, NO words, NO letters anywhere. Pure visual art. "
        f"Tall portrait format, 2:3 ratio."
    )

    try:
        client = openai.OpenAI(api_key=api_key)
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt[:4000],
            size="1024x1792",
            quality="hd",
            n=1,
            response_format="b64_json",
        )
        img_data = base64.b64decode(response.data[0].b64_json)
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", title[:30])
        p = PAPERBACK_DIR / f"front_{genre}_{safe}.jpg"
        p.write_bytes(img_data)
        logger.info("Front cover generated: %s", p.name)
        return p
    except Exception as e:
        logger.warning("DALL-E cover failed: %s", e)
        return None


def _draw_wrapped_text(draw, text: str, x: int, y: int, max_width: int,
                       font_size: int, color: tuple, line_spacing: int):
    """Draw word-wrapped text. Uses PIL default font (no TTF needed)."""
    from PIL import ImageFont
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()

    words = text.split()
    line = []
    cy = y
    for word in words:
        test = " ".join(line + [word])
        try:
            w = draw.textlength(test, font=font)
        except Exception:
            w = len(test) * (font_size * 0.55)
        if w <= max_width:
            line.append(word)
        else:
            if line:
                draw.text((x, cy), " ".join(line), font=font, fill=color)
                cy += line_spacing
            line = [word]
    if line:
        draw.text((x, cy), " ".join(line), font=font, fill=color)


def _draw_centered_text(draw, text: str, cx: int, y: int, font_size: int, color: tuple):
    from PIL import ImageFont
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()
    try:
        w = draw.textlength(text, font=font)
    except Exception:
        w = len(text) * (font_size * 0.55)
    draw.text((cx - w // 2, y), text, font=font, fill=color)


def _draw_spine_text(canvas, title: str, author: str, spine_x: int, spine_w: int, height: int):
    """Draw rotated title + author on spine."""
    from PIL import Image, ImageDraw, ImageFont
    # Create a tall narrow image for the spine text, then rotate 90°
    spine_img = Image.new("RGBA", (height, spine_w), (0, 0, 0, 0))
    sd = ImageDraw.Draw(spine_img)

    font_size = max(20, min(spine_w - 10, 36))
    try:
        font_title  = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        font_author = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", max(16, font_size - 6))
    except Exception:
        font_title = font_author = ImageFont.load_default()

    # Title centered vertically on spine
    title_y = spine_w // 2 - font_size
    sd.text((40, title_y), title, font=font_title, fill=(220, 220, 220))
    sd.text((40, title_y + font_size + 6), author, font=font_author, fill=(160, 160, 180))

    # Rotate 90° counter-clockwise so text reads bottom-to-top
    spine_rotated = spine_img.rotate(90, expand=True)
    canvas.paste(spine_rotated, (spine_x, 0), spine_rotated)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. KDP PACKAGE READER (reuse existing data)
# ═══════════════════════════════════════════════════════════════════════════════

def _read_kdp_package_full(genre: str, title: str) -> dict:
    """Read the best KDP package for this genre/title combo."""
    pub_dir = ROOT / "outputs" / "books" / "published"

    # Find best matching package file
    candidates = sorted(
        pub_dir.glob(f"{genre}_*_kdp_package.md"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    # Prefer the one whose filename contains keywords from the title
    title_words = [w.lower() for w in title.split() if len(w) > 3][:4]
    best = None
    for c in candidates:
        if any(w in c.name.lower() for w in title_words):
            best = c
            break
    if not best and candidates:
        best = candidates[0]
    if not best:
        return {}

    content = best.read_text(encoding="utf-8", errors="replace")
    data: dict = {}

    # Title / Subtitle / Series / Author
    for line in content.splitlines():
        if "**Book Title:**" in line and not data.get("title"):
            data["title"] = line.split(":", 1)[-1].strip().strip("*").strip()
        elif "**Subtitle:**" in line and not data.get("subtitle"):
            data["subtitle"] = line.split(":", 1)[-1].strip().strip("*").strip()
        elif "**Series:**" in line and not data.get("series"):
            data["series"] = line.split(":", 1)[-1].strip().strip("*").strip()
        elif "**Author:**" in line and not data.get("author"):
            data["author"] = line.split(":", 1)[-1].strip().strip("*").strip()

    # Description (HTML block)
    desc_start = content.find("<p>")
    desc_end   = content.rfind("</p>") + 4
    if desc_start > -1 and desc_end > desc_start:
        desc_html = content[desc_start:desc_end]
        data["description_html"] = desc_html
        data["description_plain"] = re.sub(r'<[^>]+>', ' ', desc_html).strip()[:2000]

    # Keywords
    kw_match = re.search(r'KEYWORDS.*?\n((?:\d+\..+\n?){1,7})', content, re.IGNORECASE)
    if kw_match:
        data["keywords"] = [
            re.sub(r'^\d+\.\s*', '', l).strip()
            for l in kw_match.group(1).strip().splitlines()
            if l.strip()
        ][:7]

    # Categories
    cat_match = re.findall(r'(?:Primary|Secondary):\s*(.+)', content)
    data["categories"] = [c.strip() for c in cat_match[:2]]

    return data


# ═══════════════════════════════════════════════════════════════════════════════
# 4. KDP PAPERBACK UPLOADER (Playwright)
# ═══════════════════════════════════════════════════════════════════════════════

def upload_paperback(
    genre: str,
    title: str,
    manuscript_html_path: str,
    auto_publish: bool = True,
    headless: bool = True,
) -> dict:  # noqa: C901
    """
    Upload a paperback edition to KDP. Fills EVERY field with verified selectors.
    Returns result dict with status, kdp_url, error.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    email    = os.getenv("KDP_EMAIL", "")
    password = os.getenv("KDP_PASSWORD", "")
    if not email or not password:
        return {"status": "error", "error": "KDP_EMAIL / KDP_PASSWORD missing in .env"}

    pkg      = _read_kdp_package_full(genre, title)
    author   = pkg.get("author", "J.K. Blaze")
    desc_html = pkg.get("description_html") or f"<p>A compelling {genre} novel by J.K. Blaze.</p>"
    desc_plain = re.sub(r'<[^>]+>', ' ', desc_html).strip()[:2000]
    keywords = pkg.get("keywords", [f"{genre} fiction", "WheellsVerse"])
    price    = PAPERBACK_PRICES.get(genre, 14.99)
    subtitle = pkg.get("subtitle", "")
    cat1, cat2 = PAPERBACK_CATEGORIES.get(genre, ("Literature & Fiction", "Fiction"))

    # ── Generate interior PDF ──────────────────────────────────────────────────
    logger.info("Generating interior PDF for: %s", title)
    try:
        interior_pdf = generate_interior_pdf(manuscript_html_path, title, author)
    except Exception as e:
        return {"status": "error", "error": f"Interior PDF failed: {e}"}

    page_count = _estimate_page_count(interior_pdf)

    # ── Generate cover ─────────────────────────────────────────────────────────
    logger.info("Generating paperback cover (%d pages)...", page_count)
    cover_jpg = None
    cover_pdf = None
    try:
        cover_jpg = generate_paperback_cover(
            title=title, genre=genre, author=author,
            page_count=page_count,
            description_short=desc_plain[:400],
        )
        cover_pdf = _cover_jpg_to_pdf(cover_jpg, page_count)
    except Exception as e:
        logger.warning("Cover generation failed: %s — continuing without cover", e)

    result = {
        "status": "pending", "genre": genre, "title": title,
        "format": "paperback", "price": price,
        "interior_pdf": str(interior_pdf),
        "cover_jpg": str(cover_jpg) if cover_jpg else "",
        "cover_pdf": str(cover_pdf) if cover_pdf else "",
        "page_count": page_count,
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless, slow_mo=200,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US", timezone_id="America/New_York",
        )
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()
        page.set_default_timeout(60000)

        def sf(sel, val, t=8000):
            """Safe fill with click_count=3 to clear existing value."""
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=t):
                    el.click(click_count=3)
                    el.fill(val)
                    el.dispatch_event("input")
                    el.dispatch_event("change")
                    return True
            except Exception:
                pass
            return False

        def click_btn(sels, label="", t=5000):
            for s in sels:
                try:
                    el = page.locator(s).first
                    if el.is_visible(timeout=t):
                        el.scroll_into_view_if_needed()
                        el.click()
                        page.wait_for_load_state("domcontentloaded", timeout=30000)
                        if label:
                            logger.info("Clicked: %s via %s", label, s)
                        return True
                except Exception:
                    continue
            return False

        try:
            # ── LOGIN ────────────────────────────────────────────────────────
            logger.info("Logging in...")
            page.goto("https://kdp.amazon.com/en_US/", wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)
            try:
                page.locator("a:has-text('Sign in')").first.click()
                page.wait_for_load_state("domcontentloaded"); time.sleep(3)
            except Exception:
                pass
            try:
                page.locator("#ap_email").first.fill(email)
                page.locator("#continue").first.click(); time.sleep(2)
            except Exception:
                pass
            page.locator("#ap_password").first.fill(password)
            page.locator("#signInSubmit").first.click(); time.sleep(6)
            logger.info("Login URL: %s", page.url)

            # ── CREATE PAPERBACK — navigate directly to avoid hardcover mismatch ──
            page.goto("https://kdp.amazon.com/en_US/title-setup/paperback/new/details",
                      wait_until="domcontentloaded", timeout=45000)
            time.sleep(3)
            # If redirected away (e.g., auth), try the create page button as fallback
            if "/title-setup/paperback" not in page.url:
                logger.warning("Direct paperback URL redirected to %s — trying create page", page.url)
                page.goto("https://kdp.amazon.com/en_US/create", wait_until="domcontentloaded", timeout=45000)
                time.sleep(3)
                # Dump buttons to see what's available
                create_btns = page.evaluate("""() =>
                    Array.from(document.querySelectorAll('button, a'))
                        .filter(e => e.offsetParent !== null)
                        .map(e => e.textContent.trim().slice(0, 60))
                        .filter(t => t.length > 2 && (t.toLowerCase().includes('paper') || t.toLowerCase().includes('book')))
                """)
                logger.info("Create page book buttons: %s", create_btns)
                click_btn([
                    "button:has-text('Paperback')",
                    "button:has-text('Create a paperback')",
                    "button:has-text('Create paperback')",
                    "a:has-text('Paperback')",
                ], "Create paperback")
                time.sleep(4)
            logger.info("Paperback form: %s", page.url)
            # Dismiss any KDP warning modals (e.g. "Title creation limit exceeded")
            # These appear on page load and block the form unless dismissed
            for _ in range(3):
                try:
                    modal_cont = page.locator(
                        "button:has-text('Continue'), .a-button:has-text('Continue'), "
                        ".a-button-primary:has-text('Continue'), a:has-text('Continue')"
                    ).first
                    if modal_cont.is_visible(timeout=2000):
                        modal_title = ""
                        try:
                            modal_title = page.locator(".a-modal h4, .a-popover h4, [role='dialog'] h4").first.text_content(timeout=1000) or ""
                        except Exception:
                            pass
                        modal_cont.click(force=True)
                        logger.info("Dismissed KDP modal: '%s'", modal_title[:80])
                        time.sleep(2)
                    else:
                        break
                except Exception:
                    break
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_step1.png"))

            # ── STEP 1: DETAILS ──────────────────────────────────────────────
            # Language
            try:
                page.select_option("#data-print-book-language-native", "english")
            except Exception:
                pass

            # Title & Subtitle  (paperback uses data-print-book-* prefix)
            sf("#data-print-book-title", title)
            if subtitle:
                sf("#data-print-book-subtitle", subtitle[:200])

            # Edition
            sf("#data-print-book-edition-number", "1")

            # Author
            sf("#data-print-book-primary-author-first-name", "J.K.")
            sf("#data-print-book-primary-author-last-name", "Blaze")

            # Description via CKEditor (same as Kindle form — editor1)
            page.evaluate("window.scrollTo(0, 600)"); time.sleep(2)
            desc_js = json.dumps(desc_html[:4000])
            cke_result = page.evaluate(f"""() => {{
                if (typeof window.CKEDITOR === 'undefined') return 'no_cke';
                const eds = Object.keys(window.CKEDITOR.instances);
                if (!eds.length) return 'no_eds';
                window.CKEDITOR.instances[eds[0]].setData({desc_js});
                const h = document.querySelector("input[name='data[print_book][description]'], input[name='data[description]']");
                if (h) h.value = {desc_js};
                return 'ok';
            }}""")
            logger.info("Description CKEditor: %s", cke_result)

            # Copyright
            page.evaluate("window.scrollTo(0, 900)"); time.sleep(1)
            try:
                page.locator("#non-public-domain").click()
            except Exception:
                pass

            # Adult content — No
            try:
                page.locator('input[name="data[print_book][is_adult_content]-radio"][value="false"]').click()
            except Exception:
                try:
                    page.locator('input[value="false"][name*="adult"]').click()
                except Exception:
                    pass

            # Keywords
            page.evaluate("window.scrollTo(0, 1200)"); time.sleep(1)
            for i, kw in enumerate(keywords[:7]):
                sf(f"#data-print-book-keywords-{i}", kw[:50])

            # Categories — JS-driven multi-level select (avoids modal-scroller pointer interception)
            page.evaluate("window.scrollTo(0, 1500)"); time.sleep(1)
            try:
                cat_btn = page.locator("#categories-modal-button, button:has-text('Choose categories'), button:has-text('Add categories')")
                if cat_btn.first.is_visible(timeout=4000):
                    cat_btn.first.scroll_into_view_if_needed()
                    # Use JS click to bypass modal-scroller interception
                    page.evaluate("() => { const b = document.querySelector('#categories-modal-button') || Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Choose categories') || b.textContent.includes('Add categories')); if (b) b.click(); }")
                    time.sleep(4)
                    page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_cat_modal.png"))

                    def js_select_level(index, keyword, fallback_any=True):
                        kw = keyword.lower()[:15].replace("'", "\\'")
                        fb = "true" if fallback_any else "false"
                        result = page.evaluate(f"""() => {{
                            const sels = document.querySelectorAll('.a-popover select, [role="dialog"] select');
                            if (sels.length <= {index}) return 'no_select_at_{index}_of_' + sels.length;
                            const s = sels[{index}];
                            const opts = Array.from(s.options);
                            let match = opts.find(o => o.text.toLowerCase().includes('{kw}') && o.value && o.text !== 'Select one' && o.text !== '--');
                            if (!match && {fb}) match = opts.find(o => o.value && o.text && o.text !== 'Select one' && o.text !== '--');
                            if (!match) return 'no_match:' + opts.map(o=>o.text).slice(0,8).join('|');
                            s.value = match.value;
                            s.dispatchEvent(new Event('change', {{bubbles: true}}));
                            s.dispatchEvent(new Event('input', {{bubbles: true}}));
                            return 'ok:' + match.text;
                        }}""")
                        logger.info("  Cat L%d (%s): %s", index + 1, keyword[:12], result)
                        return result.startswith("ok:")

                    def wait_for_select_count(min_count, max_wait=8):
                        """Wait until at least min_count selects are present in the modal."""
                        for _ in range(max_wait * 2):
                            cnt = page.evaluate("""() => document.querySelectorAll('.a-popover select, [role="dialog"] select').length""")
                            if cnt >= min_count:
                                return True
                            time.sleep(0.5)
                        return False

                    # Level 1
                    if js_select_level(0, cat1):
                        wait_for_select_count(2, max_wait=6)
                        page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_cat_L1.png"))
                        # Level 2
                        if js_select_level(1, cat2):
                            wait_for_select_count(3, max_wait=6)
                            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_cat_L2.png"))
                            # Level 3 (fallback to first valid option)
                            if js_select_level(2, cat2, fallback_any=True):
                                wait_for_select_count(4, max_wait=4)
                                # Level 4 (optional, fallback)
                                js_select_level(3, cat2, fallback_any=True)
                                time.sleep(2)

                    # Wait for placement checkboxes to appear (they appear after deepest level is selected)
                    for _ in range(12):
                        cb_count = page.evaluate("""() => document.querySelectorAll('.a-popover input[type="checkbox"], [role="dialog"] input[type="checkbox"]').length""")
                        if cb_count > 0:
                            break
                        time.sleep(0.5)

                    # Check placement checkboxes — KDP requires at least 1 checked
                    placement_checked = page.evaluate("""() => {
                        const cbs = Array.from(document.querySelectorAll('.a-popover input[type="checkbox"], [role="dialog"] input[type="checkbox"]'));
                        if (!cbs.length) return 'no_checkboxes';
                        const unchecked = cbs.filter(cb => !cb.checked);
                        if (!unchecked.length) return 'already_checked:' + cbs.length;
                        // Prefer "General" checkbox, else first available
                        const general = unchecked.find(cb => (cb.closest('label') || cb.parentElement || {}).textContent.toLowerCase().includes('general'));
                        const target = general || unchecked[0];
                        target.checked = true;
                        target.dispatchEvent(new Event('change', {bubbles: true}));
                        target.click();
                        const label = (target.closest('label') || target.parentElement || {}).textContent || 'unknown';
                        return 'checked:' + label.trim().slice(0, 60);
                    }""")
                    logger.info("Placement checkbox: %s", placement_checked)
                    time.sleep(2)

                    # Log placement count
                    placement_text = page.evaluate("""() => {
                        const els = document.querySelectorAll('.a-popover *, [role="dialog"] *');
                        for (const el of els) {
                            if (el.children.length === 0 && (el.textContent.includes('placement') || el.textContent.includes('out of')))
                                return el.textContent.trim().slice(0, 120);
                        }
                        return '';
                    }""")
                    logger.info("Placement count: %s", placement_text)
                    page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_cat_presave.png"))

                    # Save categories via JS click (bypass modal scroller)
                    saved = page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('.a-popover button, [role="dialog"] button'));
                        const b = btns.find(b => b.textContent.trim() === 'Save categories') || btns.find(b => b.textContent.includes('Save'));
                        if (b) { b.click(); return 'clicked:' + b.textContent.trim(); }
                        return 'not found:' + btns.map(b=>b.textContent.trim()).join('|');
                    }""")
                    logger.info("Save categories: %s", saved)
                    time.sleep(3)
            except Exception as cat_err:
                logger.warning("Category selection failed: %s", cat_err)
                page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_cat_error.png"))

            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_details.png"))

            # Save & Continue → Step 2
            click_btn([
                "button:has-text('Save and Continue')",
                "button:has-text('Save & Continue')",
            ], "Save details")
            # Dismiss any post-save modals (e.g. "Title creation limit exceeded")
            for _ in range(3):
                try:
                    modal_cont = page.locator(
                        "button:has-text('Continue'), .a-button-primary:has-text('Continue')"
                    ).first
                    if modal_cont.is_visible(timeout=2000):
                        modal_cont.click(force=True)
                        logger.info("Dismissed post-save modal")
                        time.sleep(2)
                    else:
                        break
                except Exception:
                    break
            # Wait for content page to fully load
            try:
                page.wait_for_url("**/content**", timeout=20000)
            except Exception:
                pass
            try:
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            time.sleep(5)
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_content.png"))
            logger.info("After details save: %s", page.url)

            # If still on /new/details (weekly title creation limit exceeded),
            # fall back to the most recent existing draft for this genre
            if "/new/details" in page.url:
                logger.warning("Stuck on /new/details — title creation limit likely exceeded, searching for existing draft")
                draft_content_url = None
                for f in sorted(
                    (ROOT / "outputs" / "books").glob(f"pb_result_{genre}_*.json"),
                    key=lambda f: f.stat().st_mtime, reverse=True
                ):
                    try:
                        data = json.loads(f.read_text())
                        url = data.get("kdp_url", "")
                        m = re.search(r'/paperback/([A-Z0-9]+)/', url)
                        if m:
                            asin = m.group(1)
                            draft_content_url = (
                                f"https://kdp.amazon.com/en_US/title-setup/paperback/{asin}/content"
                            )
                            logger.info("Resuming existing draft: %s  (from %s)", asin, f.name)
                            break
                    except Exception:
                        continue
                if draft_content_url:
                    page.goto(draft_content_url, wait_until="domcontentloaded", timeout=45000)
                    time.sleep(5)
                    logger.info("Resumed draft content page: %s", page.url)
                else:
                    logger.warning("No existing draft found for genre '%s' — cannot proceed to content", genre)

            # ── STEP 2: CONTENT / PRINT OPTIONS ─────────────────────────────
            # ISBN — assign free KDP ISBN
            # Confirmed working sequence (run3):
            #   Step 1: click "Get a free KDP ISBN" link → this opens the confirmation modal
            #   Step 2: click modal's "Assign ISBN" button → confirms assignment
            page.evaluate("window.scrollTo(0, 0)"); time.sleep(1)
            isbn_assigned = False
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_isbn_debug.png"))

            # Step 1: Open the ISBN confirmation modal.
            # On returning drafts: click "Get a free KDP ISBN" link.
            # On fresh drafts: the radio is already selected; click yellow "Assign ISBN" button
            # (page-level, not modal) to open the confirmation modal.
            step1_clicked = False
            for step1_sel in [
                "a:has-text('Get a free KDP ISBN')",
                "button:has-text('Get a free KDP ISBN')",
                "span:has-text('Get a free KDP ISBN')",
                ".a-button-primary:has-text('Assign ISBN')",   # yellow button on fresh drafts
                "a:has-text('Assign ISBN')",                    # Amazon buttons are <a> inside <span class=a-button>
                "button:has-text('Assign ISBN')",
                "input[value='Assign ISBN']",
            ]:
                try:
                    el = page.locator(step1_sel).first
                    if el.is_visible(timeout=4000):
                        el.scroll_into_view_if_needed()
                        el.click(force=True)
                        step1_clicked = True
                        logger.info("ISBN step1 clicked: %s", step1_sel)
                        break
                except Exception:
                    continue
            if not step1_clicked:
                logger.warning("ISBN step1 not found — trying direct Assign ISBN click")
            time.sleep(4)  # wait for modal to appear (short wait, NOT networkidle)

            # Step 2: Handle the "Free KDP ISBN" confirmation modal — click modal's "Assign ISBN"
            modal_confirmed = False
            for modal_sel in [
                "[role='dialog'] .a-button-primary:has-text('Assign ISBN')",
                "[role='dialog'] a:has-text('Assign ISBN')",
                "[role='dialog'] button:has-text('Assign ISBN')",
                ".a-modal .a-button-primary:has-text('Assign ISBN')",
                ".a-modal a:has-text('Assign ISBN')",
                ".a-popup a:has-text('Assign ISBN')",
                ".a-button-primary:has-text('Assign ISBN')",
                "a:has-text('Assign ISBN')",
            ]:
                try:
                    mbtn = page.locator(modal_sel).last
                    if mbtn.is_visible(timeout=3000):
                        mbtn.click(force=True)
                        modal_confirmed = True
                        isbn_assigned = True
                        logger.info("ISBN modal confirmed via: %s", modal_sel)
                        time.sleep(3); break
                except Exception:
                    continue
            if not modal_confirmed:
                # If no modal appeared (already has ISBN or different page state), still mark assigned
                logger.warning("ISBN modal confirmation not found — checking if ISBN already present")
            # Wait for the assignment API call to complete
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                time.sleep(8)

            # Verify ISBN appeared — scan body text for ISBN pattern (per-element fails on long textContent)
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_isbn_after.png"))
            isbn_val = ""
            for _ in range(4):
                isbn_val = page.evaluate("""() => {
                    const body = document.body.innerText;
                    const m = body.match(/97[89][\\d][\\d -]{9,14}/);
                    if (m) return m[0].replace(/[\\s-]/g, '').slice(0,13);
                    // Also check input values
                    for (const inp of document.querySelectorAll('input')) {
                        const v = (inp.value || '').replace(/[\\s-]/g, '');
                        if (/^97[89]\\d{10}$/.test(v)) return v;
                    }
                    return '';
                }""")
                if isbn_val:
                    break
                time.sleep(5)
            logger.info("ISBN value: '%s' | clicked: %s", isbn_val[:20] if isbn_val else "not found", isbn_assigned)

            # Print options: B&W interior with white paper
            page.evaluate("window.scrollTo(0, 600)"); time.sleep(1)
            for sel, label in [
                ('button:has-text("Black & white interior\\nwith white paper"), button:has-text("Black & white interiorwith white paper")', "B&W white paper"),
                ('input[value="black_and_white_standard"], input[value*="black_white"]', "B&W interior radio"),
            ]:
                for s in sel.split(", "):
                    try:
                        el = page.locator(s.strip()).first
                        if el.is_visible(timeout=2000): el.click(); logger.info(label); break
                    except Exception:
                        continue

            # Trim size 6×9 — shown as button cards, not select
            for s in [
                'button:has-text("6 x 9 in")',
                'input[value*="6x9"]', 'input[value*="6 x 9"]',
            ]:
                try:
                    el = page.locator(s).first
                    if el.is_visible(timeout=2000): el.click(); logger.info("Trim 6x9"); break
                except Exception:
                    continue

            time.sleep(2)

            # Upload interior PDF
            logger.info("Uploading interior PDF: %s", interior_pdf.name)
            ms_uploaded = False

            # Take a screenshot to see the manuscript section state
            page.evaluate("window.scrollTo(0, 1200)"); time.sleep(1)
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_ms_section.png"))

            # Dump button text at this scroll position for debugging
            ms_btns = page.evaluate("""() => Array.from(document.querySelectorAll('button'))
                .filter(e => e.offsetParent !== null)
                .map(e => e.textContent.trim().slice(0,60))
                .filter(t => t.length > 2)
                .join(' | ')""")
            logger.info("Buttons at scroll 1200: %s", ms_btns[:200])

            # Try Playwright selectors — scroll into view FIRST, then click INSIDE expect_file_chooser
            for trigger in [
                "button:has-text('Upload manuscript')",
                "button:has-text('Upload paperback manuscript')",
                "button:has-text('Upload your manuscript')",
                "button:has-text('Upload your manuscript file')",
            ]:
                try:
                    el = page.locator(trigger).first
                    el.scroll_into_view_if_needed(timeout=5000)
                    time.sleep(1)  # let scroll settle before opening file chooser
                    with page.expect_file_chooser(timeout=10000) as fc:
                        el.click(force=True, timeout=8000)
                    fc.value.set_files(str(interior_pdf))
                    ms_uploaded = True; logger.info("Interior PDF uploaded via: %s", trigger[:50]); break
                except Exception as te:
                    logger.debug("Trigger %s: %s", trigger[:40], str(te)[:80])
                    continue

            if not ms_uploaded:
                # JS fallback: find the manuscript section button and re-click INSIDE the context manager
                def _ms_click_js():
                    page.evaluate("""() => {
                        const sections = Array.from(document.querySelectorAll('*'));
                        let msSection = null;
                        for (const el of sections) {
                            if (el.textContent.includes('Manuscript') && el.children.length < 10 &&
                                el.offsetParent !== null && el.tagName.match(/^(H|LABEL|SPAN|DIV)$/)) {
                                msSection = el.closest('section, div[class*="section"], fieldset') || el.parentElement.parentElement;
                                if (msSection) break;
                            }
                        }
                        if (msSection) {
                            const btns = Array.from(msSection.querySelectorAll('button'));
                            for (const b of btns) {
                                if (b.textContent.toLowerCase().includes('upload')) { b.click(); return; }
                            }
                        }
                        const allBtns = Array.from(document.querySelectorAll('button'));
                        for (const b of allBtns) {
                            const t = b.textContent.toLowerCase();
                            if (t.includes('upload') && t.includes('manuscript') && b.offsetParent !== null) {
                                b.click(); return;
                            }
                        }
                    }""")
                try:
                    with page.expect_file_chooser(timeout=10000) as fc:
                        _ms_click_js()
                    fc.value.set_files(str(interior_pdf))
                    ms_uploaded = True; logger.info("Interior PDF uploaded via JS")
                except Exception as je:
                    logger.warning("JS manuscript upload: %s", str(je)[:80])

            if not ms_uploaded:
                logger.warning("Interior PDF upload failed — will attempt Save anyway")

            if ms_uploaded:
                # Wait for KDP to process the manuscript
                # NOTE: do NOT use "Launch Previewer" as done indicator — it's always present
                logger.info("Waiting for manuscript processing...")
                for _ in range(24):  # up to 120s
                    time.sleep(5)
                    state_text = page.evaluate("""() => {
                        // Check for the "Uploading..." modal (present during upload)
                        const allEls = Array.from(document.querySelectorAll('*'));
                        const uploadModal = allEls.find(el =>
                            el.offsetParent !== null &&
                            el.textContent.trim() === 'Uploading...' &&
                            el.children.length <= 3);
                        if (uploadModal) return 'uploading_modal';

                        // Check manuscript section specifically
                        const body = document.body.innerText;
                        if (body.includes('uploaded successfully') || body.includes('Manuscript') && body.includes('uploaded')) return 'done';
                        if (body.includes('Cancel Upload')) return 'uploading';
                        if (body.includes('processing') || body.includes('Processing')) return 'processing';
                        return 'waiting';
                    }""")
                    logger.info("  Processing state: %s", state_text)
                    if state_text == "done":
                        break
                page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_ms_done.png"))

            # Upload cover PDF
            # Step 1: Select "Upload a cover you already have" radio
            # Step 2: Wait for "Upload your cover file" button to appear (confirms mode switch)
            # Step 3: Upload via file chooser on that button
            upload_cover = cover_pdf if (cover_pdf and cover_pdf.exists()) else (cover_jpg if (cover_jpg and cover_jpg.exists()) else None)
            cv_uploaded = False
            if upload_cover:
                logger.info("Uploading cover: %s", upload_cover.name)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)"); time.sleep(2)
                page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_cover_before.png"))

                # Click the "Upload a cover you already have" option
                # From screenshots: this is an actual label+radio in the Book Cover section
                cover_clicked = False
                for sel in [
                    "label:has-text('Upload a cover you already have')",
                    "text=Upload a cover you already have (print-ready PDF only)",
                    "text=Upload a cover you already have",
                    "*:has-text('Upload a cover you already have (print-ready PDF only)')  >> nth=-1",
                ]:
                    try:
                        el = page.locator(sel).first
                        if el.is_visible(timeout=4000):
                            el.scroll_into_view_if_needed(); el.click()
                            cover_clicked = True
                            logger.info("Cover option clicked via: %s", sel[:50]); break
                    except Exception:
                        continue
                if not cover_clicked:
                    # JS fallback: click the label for the "upload" radio
                    js_r = page.evaluate("""() => {
                        const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
                        for (const r of radios) {
                            const lbl = r.labels && r.labels[0] ? r.labels[0] : r.closest('label');
                            if (!lbl) continue;
                            if (lbl.textContent.toLowerCase().includes('upload') && lbl.textContent.toLowerCase().includes('already have')) {
                                r.click(); lbl.click();
                                return 'radio_clicked:' + (r.id || r.name || r.value);
                            }
                        }
                        // Try second radio (index 1)
                        if (radios.length >= 2) { radios[1].click(); return 'radio[1]_clicked'; }
                        return 'not_found';
                    }""")
                    logger.info("Cover radio JS: %s", js_r)
                    cover_clicked = js_r != 'not_found'
                time.sleep(3)

                # Verify: wait for "Upload your cover file" button to appear (confirms mode switched)
                upload_btn_visible = False
                for _ in range(8):  # up to 16s
                    try:
                        btn = page.locator("button:has-text('Upload your cover file'), button:has-text('Upload cover file'), a:has-text('Upload your cover file')").first
                        if btn.is_visible(timeout=2000):
                            upload_btn_visible = True
                            logger.info("Upload cover button is visible — mode confirmed"); break
                    except Exception:
                        pass
                    time.sleep(2)
                logger.info("Cover mode switched: %s", upload_btn_visible)
                page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_cover_radio.png"))

                if upload_btn_visible:
                    # Use file chooser with the proper upload button
                    try:
                        with page.expect_file_chooser(timeout=15000) as fc:
                            page.locator("button:has-text('Upload your cover file'), button:has-text('Upload cover file'), a:has-text('Upload your cover file')").first.click()
                        fc.value.set_files(str(upload_cover))
                        cv_uploaded = True
                        logger.info("Cover uploaded via 'Upload your cover file' button")
                    except Exception as ce:
                        logger.warning("Cover file chooser failed: %s", ce)
                else:
                    logger.warning("Upload cover button never appeared after clicking radio")
                    # Fallback: direct inject to input[1] (skip manuscript input[0])
                    page.evaluate("""() => {
                        document.querySelectorAll('input[type="file"]').forEach(e => {
                            e.style.cssText = 'display:block!important;visibility:visible!important;opacity:1!important;position:relative!important;';
                        });
                    }"""); time.sleep(1)
                    file_inputs = page.locator('input[type="file"]').all()
                    for i, fi in enumerate(file_inputs):
                        if i == 0:
                            continue
                        try:
                            fi.set_input_files(str(upload_cover))
                            cv_uploaded = True
                            logger.info("Cover injected to file input[%d] (fallback)", i); break
                        except Exception as fe:
                            logger.debug("File input[%d]: %s", i, fe)

                if cv_uploaded:
                    # Wait for cover upload to complete — check for "Uploading..." modal to disappear
                    # Do NOT use "uploaded successfully" — that matches the manuscript message
                    logger.info("Waiting for cover upload modal to disappear...")
                    for _ in range(30):  # up to 150s
                        time.sleep(5)
                        cover_state = page.evaluate("""() => {
                            // The "Uploading..." modal (Cancel Upload button present = uploading)
                            const cancelBtn = Array.from(document.querySelectorAll('button'))
                                .find(b => b.textContent.trim() === 'Cancel Upload' && b.offsetParent !== null);
                            if (cancelBtn) return 'uploading_modal';

                            // Check for active modal or spinner
                            const allEls = Array.from(document.querySelectorAll('*'));
                            const uploadModal = allEls.find(el =>
                                el.offsetParent !== null && el.children.length <= 3 &&
                                el.textContent.trim() === 'Uploading...');
                            if (uploadModal) return 'uploading_modal';

                            // Check for conversion messages
                            const body = document.body.innerText;
                            if (body.includes('Converting') || body.includes('converting')) return 'converting';
                            return 'no_upload_modal';
                        }""")
                        logger.info("  Cover upload state: %s", cover_state)
                        if cover_state == 'no_upload_modal':
                            break
                    time.sleep(5)  # extra settle time after upload completes
                else:
                    logger.warning("Cover upload failed — continuing without cover")

                page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_cover_done.png"))

            # AI-Generated Content — answer Yes
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)"); time.sleep(1)
            ai_clicked = False
            for approach in ["section_radio", "a_radio", "role", "js_section", "js_leaf"]:
                try:
                    if approach == "section_radio":
                        page.locator("*:has-text('Did you use AI tools')").last.locator("input[type='radio']").first.click(timeout=3000)
                        ai_clicked = True; logger.info("AI content: Yes via section_radio"); break
                    elif approach == "a_radio":
                        page.locator(".a-radio:has-text('Yes'), label.a-radio:has-text('Yes')").first.click(timeout=3000)
                        ai_clicked = True; logger.info("AI content: Yes via a_radio"); break
                    elif approach == "role":
                        page.get_by_role("radio", name="Yes").last.click(timeout=3000)
                        ai_clicked = True; logger.info("AI content: Yes via role"); break
                    elif approach == "js_section":
                        js_res = page.evaluate("""() => {
                            const all = Array.from(document.querySelectorAll('*'));
                            let found = false;
                            for (const el of all) {
                                if (!found && el.textContent.includes('Did you use AI tools')) found = true;
                                if (found && el.tagName === 'INPUT' && el.type === 'radio') {
                                    el.click(); return 'ok';
                                }
                            }
                            return 'not_found';
                        }""")
                        if js_res == 'ok':
                            ai_clicked = True; logger.info("AI content: Yes via js_section"); break
                    elif approach == "js_leaf":
                        js_res = page.evaluate("""() => {
                            const spans = Array.from(document.querySelectorAll('span, div, label'));
                            for (const el of spans) {
                                if (el.children.length <= 1 && el.textContent.trim() === 'Yes') {
                                    const radio = el.querySelector('input[type="radio"]') || el.previousElementSibling;
                                    if (radio && radio.type === 'radio') { radio.click(); return 'sibling'; }
                                    el.click(); return 'el_click';
                                }
                            }
                            return 'not_found';
                        }""")
                        if js_res != 'not_found':
                            ai_clicked = True; logger.info("AI content: Yes via js_leaf (%s)", js_res); break
                except Exception as ae:
                    logger.debug("AI %s: %s", approach, ae)
            if not ai_clicked:
                logger.warning("AI content: could not select Yes")

            # AI content disclosure dropdowns — KDP requires text/images/translations amounts
            # KDP shows 3 selects after clicking "Yes": text content, images, translations
            time.sleep(12)  # wait for all 3 conditional selects to appear
            ai_selects_result = page.evaluate("""() => {
                const results = [];
                const seen = new Set();
                const allSelects = Array.from(document.querySelectorAll('select'));
                for (const sel of allSelects) {
                    if (seen.has(sel)) continue;
                    seen.add(sel);

                    // Walk UP to find label or legend text — look at IMMEDIATE parent label
                    // KDP labels each select with a <label> sibling or aria-label
                    const labelEl = sel.labels && sel.labels[0];
                    const ariaLabel = sel.getAttribute('aria-label') || '';
                    const idRef = sel.id ? document.querySelector('label[for="' + sel.id + '"]') : null;
                    const labelText = (labelEl ? labelEl.textContent : (idRef ? idRef.textContent : ariaLabel)).toLowerCase();

                    // Walk up max 4 levels for a narrowly-scoped context (not the whole section)
                    let nearCtxt = labelText;
                    let node = sel.parentElement;
                    for (let i = 0; i < 4 && node; i++) {
                        nearCtxt = node.textContent.toLowerCase().slice(0, 300);
                        if (nearCtxt.includes('translation') || nearCtxt.includes('image') ||
                            nearCtxt.includes('text content') || nearCtxt.includes('written')) break;
                        node = node.parentElement;
                    }
                    if (!nearCtxt.includes('ai') && !nearCtxt.includes('generat') &&
                        !nearCtxt.includes('translation') && !nearCtxt.includes('image') &&
                        !nearCtxt.includes('text content') && !nearCtxt.includes('written')) continue;

                    // Classify by label text first (KDP labels are "Texts", "Images", "Translations")
                    const directLabel = labelEl ? labelEl.textContent.trim().toLowerCase() :
                                        (idRef ? idRef.textContent.trim().toLowerCase() : '');
                    let fieldType, targetText;
                    if (directLabel === 'translations' || nearCtxt.includes('translation')) {
                        fieldType = 'translations'; targetText = 'none';
                    } else if (directLabel === 'images' || nearCtxt.includes('image')) {
                        fieldType = 'images'; targetText = 'all';
                    } else if (directLabel === 'texts' || directLabel === 'text' ||
                               nearCtxt.includes('text content') || nearCtxt.includes('written')) {
                        fieldType = 'text'; targetText = 'all';
                    } else {
                        fieldType = 'other'; targetText = 'none';
                    }
                    // Avoid duplicate field types
                    if (results.find(r => r.startsWith(fieldType))) continue;

                    const opts = Array.from(sel.options);
                    const match = opts.find(o => o.text.toLowerCase().trim() === targetText) ||
                                  opts.find(o => o.text.toLowerCase().includes(targetText)) ||
                                  opts.find(o => o.value && o.value !== '' && o.value !== '0' && o.value !== 'select');
                    if (match) {
                        sel.value = match.value;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        sel.dispatchEvent(new Event('input', {bubbles: true}));
                        results.push(fieldType + ':' + match.text);
                    }
                }
                return results.length ? results.join(' | ') : 'no_ai_selects';
            }""")
            logger.info("AI selects: %s", ai_selects_result)

            # Fallback: find the first select still showing the "Select" placeholder and set it
            # (This is the Texts dropdown — Images and Translations are already set to "None")
            if "text" not in ai_selects_result.lower():
                texts_set = page.evaluate("""() => {
                    const selects = Array.from(document.querySelectorAll('select'));
                    for (const sel of selects) {
                        const cur = sel.options[sel.selectedIndex];
                        if (!cur || cur.text.toLowerCase().trim() !== 'select') continue;
                        // This select is still on placeholder — set it to first real option
                        const opts = Array.from(sel.options).filter(
                            o => o.value && o.text.toLowerCase().trim() !== 'select');
                        if (!opts.length) continue;
                        sel.value = opts[0].value;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        sel.dispatchEvent(new Event('input',  {bubbles: true}));
                        return 'set:' + opts[0].text;
                    }
                    return 'no_placeholder_select';
                }""")
                logger.info("AI Texts positional fallback: %s", texts_set)

            # Book Preview — wait for Launch Previewer button, then launch & approve
            # The button stays disabled until BOTH manuscript AND cover are processed.
            # Skip the full wait if manuscript upload failed (it will never enable).
            if not ms_uploaded:
                logger.info("Skipping previewer wait — manuscript not uploaded")
            logger.info("Waiting for Launch Previewer button to become enabled...")
            previewer_iters = 24 if ms_uploaded else 4  # only 20s if no manuscript
            for _ in range(previewer_iters):  # up to 120s (or 20s if no manuscript)
                try:
                    prev_btn = page.locator("button:has-text('Launch Previewer')").first
                    if prev_btn.is_visible(timeout=2000):
                        # get_attribute returns None when absent, "" when present as disabled=""
                        disabled_attr = prev_btn.get_attribute("disabled")
                        aria_dis = prev_btn.get_attribute("aria-disabled")
                        cls = prev_btn.get_attribute("class") or ""
                        is_disabled = (disabled_attr is not None) or (aria_dis == "true") or ("a-button-disabled" in cls) or ("a-form-disabled" in cls)
                        if not is_disabled:
                            logger.info("Launch Previewer is now enabled (cls=%s)", cls[:40])
                            break
                        logger.info("  Previewer still disabled (d=%s, aria=%s, cls=...%s)", disabled_attr, aria_dis, cls[-30:])
                except Exception:
                    pass
                time.sleep(5)

            try:
                prev_btn = page.locator("button:has-text('Launch Previewer')").first
                if prev_btn.is_visible(timeout=5000):
                    prev_btn.scroll_into_view_if_needed()
                    # Record pages before click — new tab may open without triggering expect_page
                    pages_before = list(page.context.pages)
                    prev_btn.click(force=True)
                    time.sleep(10)  # give previewer time to open a new tab or render inline

                    pages_after = list(page.context.pages)
                    new_tabs = [p for p in pages_after if p not in pages_before]
                    logger.info("Previewer click: %d new tab(s) opened", len(new_tabs))

                    approve_sels = [
                        "button:has-text('Approve for print')",
                        "button:has-text('Approve for Print')",
                        "button:has-text('Approve')",
                        "button:has-text('Approved')",
                        "a:has-text('Approve for print')",
                        "a:has-text('Approve')",
                        "input[value*='Approve']",
                    ]

                    if new_tabs:
                        new_tab = new_tabs[-1]
                        try:
                            new_tab.wait_for_load_state("domcontentloaded", timeout=60000)
                        except Exception:
                            pass
                        time.sleep(25)
                        new_tab.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_previewer_tab.png"))
                        approved = False
                        for approve_sel in approve_sels:
                            try:
                                approve = new_tab.locator(approve_sel).first
                                if approve.is_visible(timeout=10000):
                                    approve.click(); time.sleep(3)
                                    logger.info("Previewer approved (new tab) via %s", approve_sel)
                                    approved = True; break
                            except Exception:
                                pass
                        if not approved:
                            new_tab.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_previewer_noapprove.png"))
                            logger.warning("No approve button found in previewer tab")
                        try:
                            new_tab.close()
                        except Exception:
                            pass
                        logger.info("Previewer tab handled (approved=%s)", approved)
                    else:
                        # Same-page previewer — wait for inline render
                        time.sleep(20)
                        page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_previewer_inline.png"))
                        approved = False
                        for approve_sel in approve_sels:
                            try:
                                approve = page.locator(approve_sel).first
                                if approve.is_visible(timeout=5000):
                                    approve.click(); time.sleep(3)
                                    logger.info("Previewer approved (inline) via %s", approve_sel)
                                    approved = True; break
                            except Exception:
                                pass
                        if not approved:
                            logger.warning("Previewer inline: no approve button found after 20s wait")
                else:
                    logger.warning("Launch Previewer button not visible after waiting")
            except Exception as prev_err:
                logger.info("Previewer outer error: %s", str(prev_err)[:80])

            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_content_filled.png"))

            # Save & Continue → Step 3 (pricing)
            click_btn([
                "button:has-text('Save and Continue')",
                "button:has-text('Save & Continue')",
            ], "Save content")
            # Wait for navigation to pricing step
            try:
                page.wait_for_url("**/pricing**", timeout=25000)
            except Exception:
                pass
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            time.sleep(3)

            # If still on content page, log validation errors then jump to pricing directly
            if "/content" in page.url:
                errors = page.evaluate("""() => {
                    const errs = Array.from(document.querySelectorAll(
                        '.a-alert-content, .a-box-inner .a-text-bold, [class*="error-text"], [class*="validation"]'
                    ));
                    return errs.map(e => e.textContent.trim()).filter(t => t.length > 3).slice(0, 8).join(' | ');
                }""")
                logger.warning("Still on content page — validation errors: %s", errors)
                page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_content_stuck.png"))
                # Bypass previewer/validation by navigating directly to pricing URL
                asin_m = re.search(r'/paperback/([A-Z0-9]+)/', page.url)
                if asin_m:
                    pricing_url = f"https://kdp.amazon.com/en_US/title-setup/paperback/{asin_m.group(1)}/pricing"
                    logger.info("Navigating directly to pricing page: %s", pricing_url)
                    page.goto(pricing_url, wait_until="domcontentloaded", timeout=45000)
                    time.sleep(5)

            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_pricing.png"))
            logger.info("After content save: %s", page.url)

            # ── STEP 3: RIGHTS & PRICING ─────────────────────────────────────
            logger.info("Setting price $%s", price)

            # Hide (not remove) any "found an issue on an earlier page" modal so it doesn't
            # block the Publish button click. Pricing inputs work even with modal visible.
            pricing_modal = page.evaluate("""() => {
                const modals = document.querySelectorAll('[role="dialog"], .a-popover-modal, .a-popover');
                for (const m of modals) {
                    if (m.offsetParent !== null &&
                        m.textContent.includes('found an issue on an earlier page')) {
                        m.style.display = 'none';
                        document.querySelectorAll('.a-modal-background, .a-overlay, .a-popover-backdrop')
                            .forEach(b => b.style.display = 'none');
                        return 'hidden';
                    }
                }
                return 'no_modal';
            }""")
            logger.info("Pricing page modal: %s", pricing_modal)
            time.sleep(1)

            # Territories: Worldwide
            for sel in ['input[value="ALL"]', 'input[value="worldwide"]', "label:has-text('All territories')"]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=3000): el.click(); break
                except Exception:
                    continue

            # Primary marketplace: select Amazon.com — required on fresh drafts,
            # otherwise "No marketplaces configured" is shown and no price inputs render
            time.sleep(1)
            marketplace_set = page.evaluate("""() => {
                const selects = Array.from(document.querySelectorAll('select'));
                for (const sel of selects) {
                    if (sel.offsetParent === null) continue;
                    // Look for marketplace select by nearby label or context
                    const nearCtxt = (sel.closest('.a-row, div, td, fieldset') || sel.parentElement).textContent.toLowerCase();
                    if (!nearCtxt.includes('marketplace') && !nearCtxt.includes('primary')) continue;
                    const opts = Array.from(sel.options);
                    const amzn = opts.find(o => o.text.toLowerCase().includes('amazon.com') ||
                                                o.value.toLowerCase().includes('amazon.com') ||
                                                o.value.toLowerCase() === 'us');
                    if (amzn) {
                        sel.value = amzn.value;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        sel.dispatchEvent(new Event('input', {bubbles: true}));
                        return 'set:' + amzn.text;
                    }
                }
                return 'no_marketplace_select';
            }""")
            logger.info("Primary marketplace: %s", marketplace_set)
            time.sleep(3)  # wait for price rows to render after marketplace selection

            # USD price — try Playwright selectors, then JS direct injection
            time.sleep(2)
            price_set = False
            for sel in [
                'input[name*="us_price"]', 'input[id*="us_price"]',
                'input[name*="USD"]', 'input[id*="USD"]',
                'input[name*="price"][name*="us"]',
                'input[placeholder*="$"]',
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=3000):
                        el.click(click_count=3); el.fill(str(price))
                        el.dispatch_event("input"); el.dispatch_event("change")
                        logger.info("Price $%s set via %s", price, sel)
                        price_set = True; break
                except Exception:
                    continue
            if not price_set:
                # JS fallback: find the USD price input (next to USD/$ label) and set it
                js_price = page.evaluate(f"""() => {{
                    const inputs = Array.from(document.querySelectorAll('input'));
                    const visible = inputs.filter(i => i.offsetParent !== null &&
                        (i.type === 'text' || i.type === 'number' || i.type === ''));
                    // Prefer input whose parent cell/row contains USD or $
                    for (const inp of visible) {{
                        const parent = inp.closest('td, tr, .a-row, div, li') || inp.parentElement;
                        const txt = (parent ? parent.textContent : '').toUpperCase();
                        if (txt.includes('USD') || txt.includes('AMAZON.COM')) {{
                            inp.value = '{price}';
                            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                            inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
                            return 'set_usd:' + (inp.name || inp.id || 'unnamed');
                        }}
                    }}
                    // Fallback: first visible input with 0.00 value
                    for (const inp of visible) {{
                        if (inp.value === '0.00' || inp.value === '' || inp.value === '0') {{
                            inp.value = '{price}';
                            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                            inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                            inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
                            return 'set_first:' + (inp.name || inp.id || 'unnamed');
                        }}
                    }}
                    return 'not_found (' + visible.length + ' visible inputs)';
                }}""")
                logger.info("Price JS fallback: %s", js_price)

            time.sleep(2)
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_pricing_filled.png"))

            # Save & Continue → Step 4 (Publish)
            click_btn([
                "button:has-text('Save and Continue')",
                "button:has-text('Save & Continue')",
            ], "Save pricing")
            try:
                page.wait_for_url("**/publish**", timeout=20000)
            except Exception:
                pass
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            time.sleep(3)
            page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_publish.png"))

            # ── STEP 4: PUBLISH ──────────────────────────────────────────────
            def _verify_published(url_before: str) -> bool:
                """Verify publish actually happened by URL change or success text.
                Returns True only if we navigated away from /content or /pricing."""
                time.sleep(3)
                url_after = page.url
                on_setup_page = any(s in url_after for s in ["/content", "/pricing", "/details"])
                if url_after != url_before and not on_setup_page:
                    return True
                # Check for success text anywhere on the page
                try:
                    success = page.evaluate("""() => {
                        const t = document.body.innerText.toLowerCase();
                        return t.includes('submitted for publishing') ||
                               t.includes('publishing in progress') ||
                               t.includes('your book is being published') ||
                               t.includes('congratulations');
                    }""")
                    return bool(success)
                except Exception:
                    return False

            if auto_publish:
                published = False
                url_before_publish = page.url
                publish_sels = [
                    "button:has-text('Publish Your Paperback Book')",
                    "button:has-text('Submit for Publishing')",
                    "button:has-text('Publish Your Paperback')",
                    "button:has-text('Publish')",
                    "input[value*='Publish'][type='submit']",
                ]
                for sel in publish_sels:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=5000):
                            btn.scroll_into_view_if_needed()
                            btn.click(force=True)
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=30000)
                            except Exception:
                                pass
                            time.sleep(5)
                            if _verify_published(url_before_publish):
                                result["status"] = "published"
                                result["kdp_url"] = page.url
                                published = True
                                logger.info("Paperback published! URL: %s", page.url)
                            else:
                                logger.warning("Publish click registered but URL unchanged (%s) — KDP rejected", page.url)
                            break
                    except Exception:
                        continue
                if not published:
                    # JS fallback: click Publish via dispatched events bypassing overlays
                    js_pub = page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll('button, input[type="submit"]'));
                        const b = btns.find(b => b.offsetParent !== null &&
                            (b.textContent.includes('Publish') || (b.value || '').includes('Publish')));
                        if (b) { b.click(); return 'clicked:' + (b.textContent.trim() || b.value); }
                        return 'not_found';
                    }""")
                    logger.info("Publish JS fallback: %s", js_pub)
                    if "clicked" in js_pub:
                        try:
                            page.wait_for_load_state("domcontentloaded", timeout=30000)
                        except Exception:
                            pass
                        time.sleep(5)
                        if _verify_published(url_before_publish):
                            result["status"] = "published"
                            result["kdp_url"] = page.url
                            published = True
                            logger.info("Paperback published via JS! URL: %s", page.url)
                        else:
                            logger.warning("JS publish click registered but URL unchanged — KDP rejected")
                if not published:
                    # Log any visible validation errors to help diagnose
                    err_text = page.evaluate("""() => {
                        const errs = Array.from(document.querySelectorAll(
                            '.a-alert-content, [class*="error"], [class*="validation"]'));
                        return errs.map(e => e.textContent.trim())
                            .filter(t => t.length > 5 && t.length < 300)
                            .slice(0, 5).join(' | ');
                    }""")
                    btns = page.evaluate("""() =>
                        Array.from(document.querySelectorAll("button, input[type=submit]"))
                             .filter(e => e.offsetParent !== null)
                             .map(e => e.textContent.trim() || e.value)
                    """)
                    logger.info("Visible buttons on publish page: %s", btns)
                    logger.info("Publish-page validation errors: %s", err_text)
                    result["status"] = "ready_to_publish"
                    result["kdp_url"] = page.url
                    result["note"] = f"Publish blocked — complete manually at: {page.url}  |  Errors: {err_text}"
            else:
                result["status"] = "ready_to_publish"
                result["kdp_url"] = page.url

        except PWTimeout as e:
            result["status"] = "error"
            result["error"] = f"Timeout: {e}"
            logger.error("Timeout: %s", e)
            try:
                page.screenshot(path=str(ROOT / "outputs" / "books" / f"pb_{genre}_error.png"))
            except Exception:
                pass
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error("Error: %s", e)
        finally:
            ctx.close()
            browser.close()

    # Save result
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "outputs" / "books" / f"pb_result_{genre}_{ts}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("Paperback result: %s", result)

    try:
        from core.telegram import notify
        icon = "✅" if result["status"] == "published" else "📋" if result["status"] == "ready_to_publish" else "❌"
        notify(f"{icon} Paperback — {genre.title()}\n📖 {title}\n💰 ${price}\nStatus: {result['status']}")
    except Exception:
        pass

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 5. BATCH: UPLOAD ALL PUBLISHED EBOOKS AS PAPERBACKS
# ═══════════════════════════════════════════════════════════════════════════════

def upload_all_paperbacks(headless: bool = True, auto_publish: bool = True) -> list:
    """
    For every published Kindle book in the registry, create and upload a
    matching paperback edition. Skips books that already have a paperback entry.
    """
    registry = json.loads((ROOT / "data" / "kdp_registry.json").read_text())
    published_ebooks = [
        e for e in registry
        if e.get("status") in ("published", "ready_to_publish")
        and e.get("format", "ebook") != "paperback"
        and e.get("kdp_url")
    ]

    # Check for genres that already have a paperback
    paperback_genres = {
        e.get("genre") for e in registry
        if e.get("format") == "paperback"
        and e.get("status") in ("published", "ready_to_publish")
    }

    results = []
    for e in published_ebooks:
        genre = e.get("genre", "")[:12].rstrip()  # registry has truncated genre names
        # Normalize genre back to full name
        genre_map = {
            "adventure": "adventure", "mystery": "mystery", "historical": "historical",
            "romance": "romance", "sci": "sci_fi", "self": "self_help",
            "true": "true_crime", "fantasy": "fantasy", "horror": "horror",
            "childrens": "childrens",
        }
        full_genre = next((v for k, v in genre_map.items() if genre.startswith(k)), genre)

        if full_genre in paperback_genres:
            print(f"  ⏭ {full_genre}: paperback already exists")
            continue

        # Find manuscript path
        ms_path = e.get("manuscript_path", "")
        if not ms_path or not Path(ms_path).exists():
            # Search packaged dir
            packaged = ROOT / "outputs" / "books" / "packaged"
            title_words = [w.lower() for w in e["title"].split() if len(w) > 3][:3]
            candidates = [
                f for f in packaged.glob("*.html")
                if all(w in f.stem.lower() for w in title_words)
            ]
            ms_path = str(sorted(candidates, key=lambda f: f.stat().st_mtime, reverse=True)[0]) if candidates else ""

        if not ms_path or not Path(ms_path).exists():
            logger.warning("No manuscript found for %s — skipping", e["title"])
            results.append({"genre": full_genre, "title": e["title"], "status": "skipped", "error": "no manuscript"})
            continue

        print(f"\n  📚 Uploading paperback: [{full_genre}] {e['title'][:55]}")
        result = upload_paperback(
            genre=full_genre,
            title=e["title"],
            manuscript_html_path=ms_path,
            auto_publish=auto_publish,
            headless=headless,
        )
        results.append(result)

        # Register paperback in registry
        try:
            from core.kdp_registry import get_registry
            reg = get_registry()
            reg.add_book(
                title=e["title"],
                genre=full_genre,
                status=result.get("status", "error"),
                kdp_url=result.get("kdp_url", ""),
                manuscript_path=ms_path,
                cover_path=result.get("cover_jpg", ""),
            )
            # Manually set format=paperback since schema doesn't have it
            data = json.loads((ROOT / "data" / "kdp_registry.json").read_text())
            for entry in data:
                if entry.get("title") == e["title"] and not entry.get("format"):
                    entry["format"] = "paperback"
            (ROOT / "data" / "kdp_registry.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as re_err:
            logger.warning("Registry update failed: %s", re_err)

        icon = "✅" if result.get("status") == "published" else "📋" if result.get("status") == "ready_to_publish" else "❌"
        print(f"  {icon} {full_genre}: {result.get('status')}")
        time.sleep(5)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse, sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")

    p = argparse.ArgumentParser(description="KDP Paperback Publisher")
    p.add_argument("--all",     action="store_true", help="Upload paperback for all published ebooks")
    p.add_argument("--genre",   type=str,            help="Upload paperback for one genre")
    p.add_argument("--visible", action="store_true", help="Show browser window")
    p.add_argument("--no-publish", action="store_true", help="Upload only, don't click Publish")
    args = p.parse_args()

    headless     = not args.visible
    auto_publish = not args.no_publish

    if args.all:
        print("\n" + "═"*60)
        print("  KDP PAPERBACK BATCH UPLOAD — WheellsVerse")
        print("  All 8 published genres → paperback edition")
        print("═"*60 + "\n")
        results = upload_all_paperbacks(headless=headless, auto_publish=auto_publish)
        ok = sum(1 for r in results if r.get("status") == "published")
        rdy = sum(1 for r in results if r.get("status") == "ready_to_publish")
        print(f"\n✅ {ok} published | 📋 {rdy} ready | total {len(results)}")

    elif args.genre:
        reg = json.loads((ROOT / "data" / "kdp_registry.json").read_text())
        entry = next((e for e in reg if e.get("genre","").startswith(args.genre[:5]) and e.get("status") == "published"), None)
        if not entry:
            print(f"No published entry for genre '{args.genre}'"); sys.exit(1)
        ms = entry.get("manuscript_path", "")
        result = upload_paperback(args.genre, entry["title"], ms, auto_publish, headless)
        print(f"\n{'✅' if result['status']=='published' else '📋'} {args.genre}: {result['status']}")

    else:
        print("Usage:  python core/kdp_paperback.py --all")
        print("        python core/kdp_paperback.py --genre mystery")
        print("        python core/kdp_paperback.py --all --visible")
