#!/usr/bin/env python3
"""
scripts/build_blueprint_pdf.py
─────────────────────────────────────────────────────────────────────────────
Convert marketing/ai_entrepreneur_blueprint.md into a 2-page PDF deliverable.

Page 1 — full-bleed cover image (Higgsfield-generated, fetched from URL)
Page 2 — typeset body content (parsed from the markdown between the title
         heading and the production-notes HTML comment)

Outputs:
  data/store/digital/ai_entrepreneur_blueprint.pdf   ← canonical product asset
  frontend/blueprint.pdf                              ← Cloudflare Pages serves /blueprint.pdf
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.request import urlopen

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "marketing" / "ai_entrepreneur_blueprint.md"
PRIMARY_OUT = ROOT / "data" / "store" / "digital" / "ai_entrepreneur_blueprint.pdf"
FRONTEND_OUT = ROOT / "frontend" / "blueprint.pdf"
DEFAULT_COVER = ROOT / "assets" / "ai_entrepreneur_blueprint_cover.png"

PAGE_W, PAGE_H = LETTER  # 8.5 x 11 in


def fetch_cover(source: str, dest: Path) -> Path:
    """Accept either a URL or a local path; cache to dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.startswith(("http://", "https://")):
        with urlopen(source, timeout=60) as r:
            dest.write_bytes(r.read())
    else:
        src = Path(source)
        if not src.exists():
            raise FileNotFoundError(f"cover not found: {src}")
        if src.resolve() != dest.resolve():
            dest.write_bytes(src.read_bytes())
    return dest


def parse_body(md_text: str) -> list[str]:
    """Strip YAML frontmatter and everything after the production-notes marker."""
    # Drop YAML frontmatter
    if md_text.startswith("---"):
        end = md_text.find("\n---", 3)
        if end != -1:
            md_text = md_text[end + 4:]

    # Drop everything from the production-notes HTML comment onward
    cut = md_text.find("<!--")
    if cut != -1:
        md_text = md_text[:cut]

    return [ln.rstrip() for ln in md_text.splitlines()]


def escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Inline **bold** → <b>...</b>  (after HTML-escaping)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def render_inline(s: str) -> str:
    return _BOLD_RE.sub(r"<b>\1</b>", escape(s))


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=base["Heading1"], fontSize=24, leading=28,
            textColor=colors.HexColor("#0b1e3a"), alignment=1, spaceAfter=2),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["BodyText"], fontSize=13, leading=16,
            textColor=colors.HexColor("#06b6d4"), alignment=1, spaceAfter=12,
            fontName="Helvetica-Oblique"),
        "h2": ParagraphStyle(
            "H2", parent=base["Heading2"], fontSize=13, leading=17,
            textColor=colors.HexColor("#06b6d4"), spaceBefore=8, spaceAfter=4,
            fontName="Helvetica-Bold"),
        "body": ParagraphStyle(
            "Body", parent=base["BodyText"], fontSize=10, leading=13.5,
            textColor=colors.HexColor("#1f2937"), spaceAfter=2),
        "list": ParagraphStyle(
            "List", parent=base["BodyText"], fontSize=10, leading=13.5,
            textColor=colors.HexColor("#1f2937"), spaceAfter=3,
            leftIndent=16, firstLineIndent=-16),
        "signoff": ParagraphStyle(
            "Signoff", parent=base["BodyText"], fontSize=10, leading=13.5,
            textColor=colors.HexColor("#1f2937"), spaceBefore=8,
            fontName="Helvetica-Bold"),
        "ps": ParagraphStyle(
            "PS", parent=base["BodyText"], fontSize=9, leading=13,
            textColor=colors.HexColor("#6b7280"), spaceBefore=6,
            fontName="Helvetica-Oblique"),
    }


def build_story(lines: list[str], cover_path: Path, s: dict,
                frame_w: float, frame_h: float) -> list:
    story: list = []

    # ── Page 1: cover image, contained inside the frame ──────────────────────
    img = Image(str(cover_path))
    aspect = img.imageWidth / img.imageHeight  # width / height

    # Contain inside the frame, leaving a 2% buffer so a fractional pixel
    # rounding error can't trip reportlab's "too large" guard.
    max_w = frame_w * 0.98
    max_h = frame_h * 0.98

    # Try height-bound first (cover is portrait so that's usually tighter).
    img.drawHeight = max_h
    img.drawWidth = max_h * aspect
    if img.drawWidth > max_w:
        img.drawWidth = max_w
        img.drawHeight = max_w / aspect
    img.hAlign = "CENTER"
    story.append(img)
    story.append(PageBreak())

    # ── Page 2: typeset body ─────────────────────────────────────────────────
    title_seen = False
    subtitle_seen = False
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1

        if not line:
            # Skip blank lines — paragraph styles already carry spaceAfter
            # for visual rhythm; doubling adds ~1" over a 1-page body.
            continue

        # H1 — title (only first one)
        if line.startswith("# ") and not title_seen:
            story.append(Paragraph(render_inline(line[2:]), s["title"]))
            title_seen = True
            continue

        # Subtitle line: **The Stack & The Method** right after title
        if (not subtitle_seen and title_seen
                and line.startswith("**") and line.endswith("**")):
            inner = line[2:-2]
            story.append(Paragraph(escape(inner), s["subtitle"]))
            subtitle_seen = True
            continue

        # H2 sections — THE STACK / THE METHOD / THAT'S IT.
        if line.startswith("## "):
            story.append(Paragraph(render_inline(line[3:]), s["h2"]))
            continue

        # Horizontal rule → small visual gap
        if line == "---":
            story.append(Spacer(1, 6))
            continue

        # Numbered list item
        if re.match(r"^\d+\.\s", line):
            num, rest = line.split(".", 1)
            story.append(Paragraph(
                f"<b>{escape(num)}.</b> {render_inline(rest.strip())}",
                s["list"]))
            continue

        # Signoff / P.S.
        if line.startswith("— "):
            story.append(Paragraph(render_inline(line), s["signoff"]))
            continue
        if line.lower().startswith("**p.s.**") or line.startswith("**P.S.**"):
            story.append(Paragraph(render_inline(line), s["ps"]))
            continue

        # Default — body paragraph
        story.append(Paragraph(render_inline(line), s["body"]))

    return story


def build(cover_path: Path) -> None:
    lines = parse_body(SRC.read_text(encoding="utf-8"))
    s = styles()

    top_m = 0.6 * inch
    bot_m = 0.6 * inch
    left_m = 0.8 * inch
    right_m = 0.8 * inch
    frame_w = PAGE_W - left_m - right_m
    frame_h = PAGE_H - top_m - bot_m

    for out_path in (PRIMARY_OUT, FRONTEND_OUT):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(
            str(out_path), pagesize=LETTER,
            topMargin=top_m, bottomMargin=bot_m,
            leftMargin=left_m, rightMargin=right_m,
            title="The AI Entrepreneur Blueprint",
            author="J.K. Blaze",
            subject="The Stack & The Method",
            keywords="AI, entrepreneurship, blueprint, WheellsVerse, J.K. Blaze",
        )
        # Rebuild the story per-doc because flowables can be consumed on build()
        doc.build(build_story(lines, cover_path, s, frame_w, frame_h))
        kb = out_path.stat().st_size / 1024
        print(f"wrote {out_path.relative_to(ROOT)}  ({kb:.1f} KB)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--cover", required=True,
                   help="Path to local cover image OR https URL.")
    args = p.parse_args()
    try:
        cover = fetch_cover(args.cover, DEFAULT_COVER)
        build(cover)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
