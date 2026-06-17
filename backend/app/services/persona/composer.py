"""Composer — format KAI's active persona traits into a prompt block."""
from __future__ import annotations

from app.services.persona import storage


def compose_persona(entries: list[storage.Entry]) -> str:
    """Group active traits by section into a compact block. Pure (no I/O)."""
    if not entries:
        return ""
    by_section: dict[str, list[str]] = {}
    for e in entries:
        by_section.setdefault(e.section, []).append(e.text)
    lines: list[str] = []
    for section in storage.SECTIONS:  # stable, meaningful order
        items = by_section.get(section)
        if not items:
            continue
        lines.append(f"[{section}]")
        for text in items:
            lines.append(f"- {text}")
    return "\n".join(lines)
