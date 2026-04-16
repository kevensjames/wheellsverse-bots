#!/usr/bin/env python3
"""
core/file_handler.py
─────────────────────────────────────────────────────────────────────────────
File upload processing for NarAI chat.
Converts uploaded files into Claude API content blocks.
Supported: PDF, images, CSV, TXT/MD/code files, DOCX
─────────────────────────────────────────────────────────────────────────────
"""

import base64
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("file_handler")

ROOT = Path(__file__).parent.parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_PATH", str(ROOT / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_TEXT_CHARS = 40_000   # max chars to include from text files
MAX_CSV_ROWS = 200      # max rows to convert for CSV

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json",
    ".yaml", ".yml", ".sh", ".bash", ".sql", ".rb", ".go", ".rs",
    ".java", ".cpp", ".c", ".h", ".php", ".swift", ".kt",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
}


# ─── Save upload ─────────────────────────────────────────────────────────────

def save_upload(filename: str, data: bytes, conversation_id: str) -> Path:
    """Save raw bytes to uploads/{conversation_id}/filename. Returns path."""
    conv_dir = UPLOAD_DIR / conversation_id
    conv_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in filename).strip()
    if not safe_name:
        safe_name = "upload"

    dest = conv_dir / safe_name
    # Avoid overwrite
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        i = 1
        while dest.exists():
            dest = conv_dir / f"{stem}_{i}{suffix}"
            i += 1

    dest.write_bytes(data)
    logger.info(f"[file_handler] Saved upload: {dest} ({len(data)} bytes)")
    return dest


# ─── Process file into Claude content block ───────────────────────────────────

def process_file(filepath: str) -> Optional[Dict[str, Any]]:
    """
    Convert a file to a Claude API content block.
    Returns a content block dict or None if unsupported.
    """
    p = Path(filepath)
    if not p.exists():
        return None

    ext = p.suffix.lower()

    # ── Images ──────────────────────────────────────────────────────────────
    if ext in IMAGE_EXTENSIONS:
        return _process_image(p)

    # ── PDF ─────────────────────────────────────────────────────────────────
    if ext == ".pdf":
        return _process_pdf(p)

    # ── DOCX ────────────────────────────────────────────────────────────────
    if ext == ".docx":
        return _process_docx(p)

    # ── CSV ─────────────────────────────────────────────────────────────────
    if ext == ".csv":
        return _process_csv(p)

    # ── Code / text files ───────────────────────────────────────────────────
    if ext in CODE_EXTENSIONS or ext in {".txt", ".md", ".rst"}:
        return _process_text(p)

    # ── Generic fallback — try reading as text ───────────────────────────────
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARS]
        return {
            "type": "text",
            "text": f"[File: {p.name}]\n{text}",
        }
    except Exception:
        return None


def _process_image(p: Path) -> Dict:
    ext = p.suffix.lower()
    media_type = MEDIA_TYPES.get(ext, "image/jpeg")
    data = base64.standard_b64encode(p.read_bytes()).decode("utf-8")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": data,
        },
    }


def _process_pdf(p: Path) -> Dict:
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(str(p))
        pages = []
        for i, page in enumerate(reader.pages[:50]):
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pass
        text = "\n\n".join(pages)[:MAX_TEXT_CHARS]
        return {
            "type": "text",
            "text": f"[PDF: {p.name} — {len(reader.pages)} pages]\n\n{text}",
        }
    except ImportError:
        return {"type": "text", "text": f"[PDF: {p.name} — PyPDF2 not installed]"}
    except Exception as e:
        return {"type": "text", "text": f"[PDF: {p.name} — Error reading: {e}]"}


def _process_docx(p: Path) -> Dict:
    try:
        from docx import Document
        doc = Document(str(p))
        text = "\n".join(para.text for para in doc.paragraphs)[:MAX_TEXT_CHARS]
        return {
            "type": "text",
            "text": f"[DOCX: {p.name}]\n\n{text}",
        }
    except ImportError:
        return {"type": "text", "text": f"[DOCX: {p.name} — python-docx not installed]"}
    except Exception as e:
        return {"type": "text", "text": f"[DOCX: {p.name} — Error: {e}]"}


def _process_csv(p: Path) -> Dict:
    try:
        import pandas as pd
        df = pd.read_csv(str(p), nrows=MAX_CSV_ROWS)
        md_table = df.to_markdown(index=False)
        rows_note = f" (showing first {MAX_CSV_ROWS} rows)" if len(df) >= MAX_CSV_ROWS else ""
        return {
            "type": "text",
            "text": f"[CSV: {p.name}{rows_note} — {len(df)} rows × {len(df.columns)} columns]\n\n{md_table}",
        }
    except ImportError:
        raw = p.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARS]
        return {"type": "text", "text": f"[CSV: {p.name}]\n\n{raw}"}
    except Exception as e:
        return {"type": "text", "text": f"[CSV: {p.name} — Error: {e}]"}


def _process_text(p: Path) -> Dict:
    ext = p.suffix.lower().lstrip(".")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_CHARS]
        lang = ext if ext else "text"
        return {
            "type": "text",
            "text": f"[File: {p.name}]\n```{lang}\n{text}\n```",
        }
    except Exception as e:
        return {"type": "text", "text": f"[File: {p.name} — Error reading: {e}]"}


# ─── File info ────────────────────────────────────────────────────────────────

def get_file_info(filepath: str) -> Dict:
    p = Path(filepath)
    if not p.exists():
        return {}
    stat = p.stat()
    ext = p.suffix.lower()
    ftype = (
        "image" if ext in IMAGE_EXTENSIONS else
        "pdf" if ext == ".pdf" else
        "docx" if ext == ".docx" else
        "csv" if ext == ".csv" else
        "code" if ext in CODE_EXTENSIONS else
        "text"
    )
    # Small text preview
    preview = ""
    if ftype in ("text", "code") and stat.st_size < 50_000:
        try:
            preview = p.read_text(encoding="utf-8", errors="replace")[:200]
        except Exception:
            pass

    return {
        "name": p.name,
        "path": str(p),
        "type": ftype,
        "ext": ext,
        "size": stat.st_size,
        "preview": preview,
    }
