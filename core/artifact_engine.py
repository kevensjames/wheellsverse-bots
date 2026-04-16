#!/usr/bin/env python3
"""
core/artifact_engine.py
─────────────────────────────────────────────────────────────────────────────
Detects renderable content in NarAI responses.
Types: html, react, svg, mermaid, markdown, table, math, code
─────────────────────────────────────────────────────────────────────────────
"""

import re
from typing import Optional

# ─── Regex patterns ───────────────────────────────────────────────────────────

_HTML_RE = re.compile(r'```html\s*\n(.*?)```', re.S | re.I)
_REACT_RE = re.compile(r'```(?:jsx?|tsx?|react)\s*\n(.*?)```', re.S | re.I)
_SVG_RE = re.compile(r'(<svg[\s\S]*?</svg>)', re.I)
_MERMAID_RE = re.compile(r'```mermaid\s*\n(.*?)```', re.S | re.I)
_MATH_RE = re.compile(r'\$\$(.+?)\$\$', re.S)
_TABLE_RE = re.compile(r'(\|.+\|[\r\n]+\|[-:| ]+\|[\r\n]+(?:\|.+\|[\r\n]*)+)', re.M)
_CODE_RE = re.compile(r'```(\w+)\s*\n(.*?)```', re.S)


def detect_artifact(content: str) -> Optional[dict]:
    """
    Scan an AI response for renderable content.
    Returns {type, content, language?} or None.
    Priority: html > react > mermaid > svg > math > table > code
    """
    # HTML block
    m = _HTML_RE.search(content)
    if m:
        return {"type": "html", "content": m.group(1).strip()}

    # React/JSX
    m = _REACT_RE.search(content)
    if m:
        return {"type": "react", "content": m.group(1).strip()}

    # Mermaid diagram
    m = _MERMAID_RE.search(content)
    if m:
        return {"type": "mermaid", "content": m.group(1).strip()}

    # SVG inline
    m = _SVG_RE.search(content)
    if m:
        return {"type": "svg", "content": m.group(1).strip()}

    # LaTeX math
    m = _MATH_RE.search(content)
    if m:
        return {"type": "math", "content": m.group(1).strip()}

    # Markdown table
    m = _TABLE_RE.search(content)
    if m:
        return {"type": "table", "content": m.group(1).strip()}

    # Generic code block (only if it's standalone large code)
    m = _CODE_RE.search(content)
    if m and len(m.group(2)) > 200:
        return {"type": "code", "language": m.group(1), "content": m.group(2).strip()}

    return None


def get_artifact_meta(artifact: dict) -> dict:
    """Return display metadata for an artifact type."""
    meta = {
        "html": {"label": "HTML Preview", "icon": "🌐", "runnable": False},
        "react": {"label": "React Preview", "icon": "⚛️", "runnable": False},
        "mermaid": {"label": "Diagram", "icon": "📊", "runnable": False},
        "svg": {"label": "SVG Graphic", "icon": "🎨", "runnable": False},
        "math": {"label": "Math", "icon": "∑", "runnable": False},
        "table": {"label": "Table", "icon": "📋", "runnable": False},
        "code": {"label": "Code", "icon": "💻", "runnable": True},
    }
    t = artifact.get("type", "code")
    return {**meta.get(t, {"label": t, "icon": "💻", "runnable": False}), "type": t}
