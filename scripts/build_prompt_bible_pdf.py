#!/usr/bin/env python3
"""Convert data/store/prompt_bible/prompt_bible.md to a polished PDF via reportlab."""
import re
from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, ListFlowable, ListItem
)

ROOT = Path(__file__).parent.parent
SRC = ROOT / "data" / "store" / "prompt_bible" / "prompt_bible.md"
OUT = ROOT / "data" / "store" / "prompt_bible" / "prompt_bible.pdf"


def _escape(text: str) -> str:
    """Reportlab Paragraph uses limited HTML-like tags; escape ampersands/brackets."""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


def build():
    md = SRC.read_text(encoding="utf-8").splitlines()

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=22,
                        textColor=colors.HexColor("#1a2035"), spaceAfter=18)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=15,
                        textColor=colors.HexColor("#7c3aed"), spaceBefore=14, spaceAfter=8)
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10.5, leading=15,
                          textColor=colors.HexColor("#222"))
    small = ParagraphStyle("Small", parent=body, fontSize=9,
                           textColor=colors.HexColor("#666"))
    prompt_num = ParagraphStyle("PNum", parent=body, fontSize=10.5,
                                leftIndent=18, firstLineIndent=-18, spaceAfter=6)

    doc = SimpleDocTemplate(
        str(OUT), pagesize=LETTER,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        leftMargin=0.8 * inch, rightMargin=0.8 * inch,
        title="The Prompt Bible — WheellsVerse",
        author="J.K. Blaze",
    )

    story = []
    current_num = 0  # tracks the 1..10 prompt number inside a category
    for raw in md:
        line = raw.rstrip()
        if not line:
            story.append(Spacer(1, 4))
            continue
        if line.startswith("# "):
            story.append(Paragraph(_escape(line[2:]), h1))
        elif line.startswith("## "):
            story.append(Paragraph(_escape(line[3:]), h2))
            current_num = 0
        elif line.strip() == "---":
            story.append(Spacer(1, 8))
        elif line.startswith("**") and line.endswith("**"):
            story.append(Paragraph(f"<b>{_escape(line[2:-2])}</b>", small))
        elif re.match(r"^\d+\.\s", line):
            current_num += 1
            # strip the leading "N. " since we'll render our own number
            text = re.sub(r"^\d+\.\s+", "", line)
            story.append(Paragraph(f"<b>{current_num}.</b> {_escape(text)}", prompt_num))
        else:
            story.append(Paragraph(_escape(line), body))

    doc.build(story)
    size_kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    build()
