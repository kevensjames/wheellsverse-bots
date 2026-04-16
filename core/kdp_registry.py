#!/usr/bin/env python3
"""
core/kdp_registry.py
─────────────────────────────────────────────────────────────────────────────
Persistent registry of every book NarAI has published (or attempted) on KDP.
Persists to data/kdp_registry.json.
On first init: auto-seeds from data/kdp_results.json + outputs/books/published/*.md
─────────────────────────────────────────────────────────────────────────────
"""
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_FILE = ROOT / "data" / "kdp_registry.json"
logger = logging.getLogger("kdp_registry")

_SCHEMA = {
    "id": "",
    "title": "",
    "genre": "",
    "volume_number": None,   # int or None
    "series_name": "",
    "asin": "",
    "kdp_url": "",
    "status": "draft",  # draft | live | review_required | rejected | published
    "word_count": 0,
    "publish_date": "",
    "manuscript_path": "",
    "cover_path": "",
    "qc_score": 0,
    "added_at": "",
    "updated_at": "",
}


def _vol_from_title(title: str) -> Optional[int]:
    """Extract volume number from title string."""
    m = re.search(r'\b(?:Volume|Vol\.?|Book)\s*(\d+)', title, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _series_from_title(title: str) -> str:
    """Try to extract series name — everything before 'Volume/Vol/Book N'."""
    m = re.search(r'^(.*?)\s*(?:Volume|Vol\.?|Book)\s*\d+', title, re.IGNORECASE)
    return m.group(1).strip(': -').strip() if m else ""


class KDPRegistry:

    def __init__(self):
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._auto_seed()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> list:
        if not REGISTRY_FILE.exists():
            return []
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, entries: list):
        REGISTRY_FILE.write_text(
            json.dumps(entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── seed ─────────────────────────────────────────────────────────────────

    def _auto_seed(self):
        """Seed registry from existing KDP data — runs once (skips if already populated)."""
        entries = self._load()
        if entries:
            return

        imported: list[dict] = []

        # Source 1: data/kdp_results.json  {genre: {title, asin, status, …}}
        results_file = ROOT / "data" / "kdp_results.json"
        if results_file.exists():
            try:
                results = json.loads(results_file.read_text(encoding="utf-8"))
                for genre, info in results.items():
                    if not isinstance(info, dict) or not info.get("title"):
                        continue
                    e = {**_SCHEMA}
                    e["id"] = uuid.uuid4().hex
                    e["title"] = info.get("title", "")
                    e["genre"] = genre
                    e["asin"] = info.get("asin", "")
                    e["status"] = info.get("status", "draft")
                    e["added_at"] = datetime.now().isoformat()
                    e["updated_at"] = datetime.now().isoformat()
                    # Try to detect series/volume from title
                    e["volume_number"] = _vol_from_title(e["title"])
                    e["series_name"] = _series_from_title(e["title"]) if e["volume_number"] else ""
                    imported.append(e)
            except Exception as ex:
                logger.warning("Auto-seed kdp_results.json: %s", ex)

        # Source 2: outputs/books/published/*.md packages
        pub_dir = ROOT / "outputs" / "books" / "published"
        if pub_dir.exists():
            for f in sorted(pub_dir.glob("*.md")):
                try:
                    content = f.read_text(errors="replace")
                    title = ""
                    for line in content.splitlines():
                        if "BOOK TITLE" in line.upper() or "**Book Title:**" in line:
                            title = line.split(":", 1)[-1].strip().strip("*").strip()
                            break
                    if not title:
                        # Derive from filename: genre_safe_title_ts_kdp_package
                        parts = f.stem.replace("_kdp_package", "").split("_")
                        genre_guess = parts[0] if parts else "unknown"
                        title = " ".join(parts[1:-2]).replace("-", " ").title()
                    else:
                        genre_guess = f.stem.split("_")[0]

                    # Avoid duplicating entries already seeded from kdp_results
                    if any(e["title"].lower() == title.lower() for e in imported):
                        continue

                    e = {**_SCHEMA}
                    e["id"] = uuid.uuid4().hex
                    e["title"] = title
                    e["genre"] = genre_guess
                    e["status"] = "live"
                    e["manuscript_path"] = str(f)
                    e["word_count"] = len(content.split())
                    e["added_at"] = datetime.now().isoformat()
                    e["updated_at"] = datetime.now().isoformat()
                    e["volume_number"] = _vol_from_title(title)
                    e["series_name"] = _series_from_title(title) if e["volume_number"] else ""
                    imported.append(e)
                except Exception as ex:
                    logger.debug("Auto-seed %s: %s", f.name, ex)

        # Source 3: complete_and_publish_progress.json
        progress_file = ROOT / "data" / "complete_and_publish_progress.json"
        if progress_file.exists():
            try:
                prog = json.loads(progress_file.read_text(encoding="utf-8"))
                for pub in prog.get("published", []):
                    title = pub.get("title", "")
                    if not title or any(e["title"].lower() == title.lower() for e in imported):
                        continue
                    e = {**_SCHEMA}
                    e["id"] = uuid.uuid4().hex
                    e["title"] = title
                    e["genre"] = pub.get("genre", "unknown")
                    e["status"] = "live" if pub.get("kdp_status") == "published" else "draft"
                    e["kdp_url"] = pub.get("kdp_url", "")
                    e["added_at"] = datetime.now().isoformat()
                    e["updated_at"] = datetime.now().isoformat()
                    e["volume_number"] = _vol_from_title(title)
                    e["series_name"] = _series_from_title(title) if e["volume_number"] else ""
                    imported.append(e)
            except Exception as ex:
                logger.warning("Auto-seed progress file: %s", ex)

        if imported:
            self._save(imported)
            logger.info("KDPRegistry seeded: %d entries", len(imported))

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def add_book(self, title: str, genre: str, **kwargs) -> dict:
        entries = self._load()
        e = {**_SCHEMA}
        e["id"] = uuid.uuid4().hex
        e["title"] = title
        e["genre"] = genre
        e["added_at"] = datetime.now().isoformat()
        e["updated_at"] = datetime.now().isoformat()
        if not e.get("volume_number"):
            e["volume_number"] = _vol_from_title(title)
        if not e.get("series_name") and e["volume_number"]:
            e["series_name"] = _series_from_title(title)
        for k, v in kwargs.items():
            if k in _SCHEMA:
                e[k] = v
        entries.append(e)
        self._save(entries)
        logger.info("KDPRegistry add_book: %s [%s]", title, genre)
        return e

    def get_all(self) -> list:
        return self._load()

    def get_by_genre(self, genre: str) -> list:
        return [e for e in self._load() if e.get("genre") == genre]

    def get_series(self, series_name: str) -> list:
        return sorted(
            [e for e in self._load()
             if e.get("series_name", "").lower() == series_name.lower()],
            key=lambda e: e.get("volume_number") or 0,
        )

    def find_by_title(self, title: str) -> Optional[dict]:
        t = title.lower()
        for e in self._load():
            if e.get("title", "").lower() == t:
                return e
        return None

    def find_by_id(self, entry_id: str) -> Optional[dict]:
        for e in self._load():
            if e.get("id") == entry_id:
                return e
        return None

    def update_entry(self, entry_id: str, **kwargs) -> bool:
        entries = self._load()
        for e in entries:
            if e["id"] == entry_id:
                for k, v in kwargs.items():
                    if k in _SCHEMA:
                        e[k] = v
                e["updated_at"] = datetime.now().isoformat()
                self._save(entries)
                return True
        return False

    def update_status(self, entry_id: str, status: str, **kwargs) -> bool:
        return self.update_entry(entry_id, status=status, **kwargs)

    def delete_entry(self, entry_id: str) -> bool:
        entries = self._load()
        new = [e for e in entries if e["id"] != entry_id]
        if len(new) == len(entries):
            return False
        self._save(new)
        return True

    def series_exists_on_kdp(self, series_name: str, vol_num: int) -> bool:
        """True if the given series+volume is live/published in the registry."""
        live_statuses = {"live", "published", "review_required"}
        for e in self._load():
            if (e.get("series_name", "").lower() == series_name.lower()
                    and e.get("volume_number") == vol_num
                    and e.get("status", "") in live_statuses):
                return True
        return False


# ── Module-level singleton ────────────────────────────────────────────────────

_registry: Optional[KDPRegistry] = None


def get_registry() -> KDPRegistry:
    global _registry
    if _registry is None:
        _registry = KDPRegistry()
    return _registry
