#!/usr/bin/env python3
"""
core/character_registry.py
─────────────────────────────────────────────────────────────────────────────
Global registry of every character name NarAI has used across all books.
Prevents reuse of character names in different, unrelated series.
Persists to data/character_registry.json.
On first init: auto-seeds from data/story_bibles/*.json
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
REGISTRY_FILE = ROOT / "data" / "character_registry.json"
logger = logging.getLogger("character_registry")

_SCHEMA = {
    "id":             "",
    "book_title":     "",
    "series_name":    "",
    "genre":          "",
    "characters":     [],   # [{"name": str, "role": str}]
    "registered_at":  "",
}


class CharacterRegistry:
    """
    Tracks every character name used across all WheellsVerse books.
    Prevents name reuse across different series.
    """

    def __init__(self):
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._auto_seed()

    # ── Persistence ───────────────────────────────────────────────────────────

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

    # ── Auto-seed ─────────────────────────────────────────────────────────────

    def _auto_seed(self):
        """Seed from existing story bibles — runs once (skips if already populated)."""
        entries = self._load()
        if entries:
            return

        imported: list[dict] = []
        bibles_dir = ROOT / "data" / "story_bibles"
        if bibles_dir.exists():
            for f in sorted(bibles_dir.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    title = data.get("source_title") or data.get("title") or f.stem.replace("_", " ").title()
                    characters = data.get("characters", [])
                    if not characters:
                        continue
                    # Normalise: each entry must have "name"
                    chars = []
                    for c in characters:
                        if isinstance(c, dict) and c.get("name"):
                            chars.append({"name": c["name"], "role": c.get("role", "supporting")})
                        elif isinstance(c, str):
                            chars.append({"name": c, "role": "supporting"})
                    if not chars:
                        continue
                    e = {**_SCHEMA}
                    e["id"] = uuid.uuid4().hex
                    e["book_title"] = title
                    e["series_name"] = title  # bibles are per-series
                    e["genre"] = data.get("genre", "unknown")
                    e["characters"] = chars
                    e["registered_at"] = datetime.now().isoformat()
                    imported.append(e)
                except Exception as ex:
                    logger.debug("Auto-seed %s: %s", f.name, ex)

        if imported:
            self._save(imported)
            logger.info("CharacterRegistry seeded: %d entries (%d total names)",
                        len(imported),
                        sum(len(e["characters"]) for e in imported))

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_all_names(self, exclude_series: str = "") -> set:
        """Return every character name used in any book NOT in exclude_series."""
        names: set = set()
        exclude = exclude_series.lower().strip()
        for entry in self._load():
            if exclude and entry.get("series_name", "").lower().strip() == exclude:
                continue
            for ch in entry.get("characters", []):
                n = ch.get("name", "").strip()
                if n:
                    names.add(n.lower())
        return names

    def check_conflicts(self, names: list, series_name: str = "") -> list:
        """
        Return the subset of `names` that are already used in a different series.
        Case-insensitive.
        """
        existing = self.get_all_names(exclude_series=series_name)
        return [n for n in names if n.lower().strip() in existing]

    def get_all(self) -> list:
        return self._load()

    def get_by_genre(self, genre: str) -> list:
        return [e for e in self._load() if e.get("genre") == genre]

    def get_by_series(self, series_name: str) -> list:
        return [e for e in self._load()
                if e.get("series_name", "").lower() == series_name.lower()]

    def find_by_book(self, book_title: str) -> Optional[dict]:
        t = book_title.lower()
        for e in self._load():
            if e.get("book_title", "").lower() == t:
                return e
        return None

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        book_title: str,
        genre: str,
        series_name: str,
        characters: list,
    ) -> dict:
        """
        Upsert a book entry. If book_title already registered, update its characters.
        characters = [{"name": str, "role": str}, ...]
        """
        entries = self._load()
        # Normalise characters list
        chars = []
        for c in characters:
            if isinstance(c, dict) and c.get("name"):
                chars.append({"name": c["name"].strip(), "role": c.get("role", "supporting")})
            elif isinstance(c, str) and c.strip():
                chars.append({"name": c.strip(), "role": "supporting"})

        # Check for existing entry
        for e in entries:
            if e.get("book_title", "").lower() == book_title.lower():
                e["characters"] = chars
                e["series_name"] = series_name or e["series_name"]
                e["genre"] = genre or e["genre"]
                e["registered_at"] = datetime.now().isoformat()
                self._save(entries)
                self._update_book_graph(e, entries)
                logger.info("CharacterRegistry updated: %s (%d chars)", book_title, len(chars))
                return e

        # New entry
        e = {**_SCHEMA}
        e["id"] = uuid.uuid4().hex
        e["book_title"] = book_title
        e["series_name"] = series_name or book_title
        e["genre"] = genre
        e["characters"] = chars
        e["registered_at"] = datetime.now().isoformat()
        entries.append(e)
        self._save(entries)
        self._update_book_graph(e, entries)
        logger.info("CharacterRegistry registered: %s (%d chars)", book_title, len(chars))
        return e

    def add_character(self, name: str, role: str, book_title: str,
                      series_name: str, genre: str) -> dict:
        """
        Manually add a single character to the registry.
        If book_title already exists, appends to its characters list (deduped by name).
        If not, creates a new entry. Returns the updated/created entry.
        """
        entries = self._load()
        existing = next((e for e in entries if e.get("book_title", "").lower() == book_title.lower()), None)
        if existing:
            names_in_entry = {c["name"].lower() for c in existing.get("characters", [])}
            if name.lower().strip() not in names_in_entry:
                existing["characters"].append({"name": name.strip(), "role": role})
                existing["registered_at"] = datetime.now().isoformat()
                self._save(entries)
                self._update_book_graph(existing, entries)
                logger.info("CharacterRegistry manual add: '%s' → '%s'", name, book_title)
            return existing
        else:
            return self.register(
                book_title=book_title,
                genre=genre,
                series_name=series_name or book_title,
                characters=[{"name": name.strip(), "role": role}],
            )

    def extract_and_register(
        self,
        manuscript: str,
        title: str,
        genre: str,
        series_name: str,
        bot,
    ) -> list:
        """
        Extract character names from manuscript via Claude, then register.
        `bot` is any BaseBot instance that has .claude_json().
        Returns list of character dicts.
        """
        # Sample the manuscript for extraction (opening + middle for brevity)
        words = manuscript.split()
        wc = len(words)
        if wc > 8000:
            sample = " ".join(words[:3000]) + "\n\n...\n\n" + " ".join(words[wc // 2 - 1000: wc // 2 + 1000])
        else:
            sample = manuscript

        prompt = f"""Extract ALL named characters from this book manuscript.

Title: "{title}"
Genre: {genre}

Manuscript excerpt:
{sample[:6000]}

Return JSON only:
{{
  "characters": [
    {{"name": "Full Name", "role": "protagonist|antagonist|supporting|minor"}},
    ...
  ]
}}
Include every named person. Use their full name as it appears most often. No duplicates."""

        try:
            result = bot.claude_json(prompt)
            characters = result.get("characters", [])
            if not characters:
                # Fallback: simple regex extraction
                raw = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', manuscript[:8000])
                seen: dict = {}
                for name in raw:
                    if name not in seen:
                        seen[name] = {"name": name, "role": "supporting"}
                characters = list(seen.values())[:20]
        except Exception as ex:
            logger.warning("Character extraction failed for '%s': %s — using regex fallback", title, ex)
            raw = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', manuscript[:8000])
            seen = {}
            for name in raw:
                if name not in seen:
                    seen[name] = {"name": name, "role": "supporting"}
            characters = list(seen.values())[:20]

        if characters:
            self.register(book_title=title, genre=genre, series_name=series_name, characters=characters)
        return characters

    # ── Book graph (for /graphify) ─────────────────────────────────────────────

    def _update_book_graph(self, entry: dict, all_entries: list):
        """Write/update data/book_graph/nodes.json + edges.json for graphify."""
        try:
            graph_dir = ROOT / "data" / "book_graph"
            graph_dir.mkdir(exist_ok=True)

            # ── Nodes ──────────────────────────────────────────────────────────
            nodes_file = graph_dir / "nodes.json"
            nodes: list = json.loads(nodes_file.read_text(encoding="utf-8")) if nodes_file.exists() else []

            # Replace existing book node
            nodes = [n for n in nodes if n.get("id") != entry["id"]]
            nodes.append({
                "id":     entry["id"],
                "label":  entry["book_title"],
                "type":   "book",
                "genre":  entry.get("genre", ""),
                "series": entry.get("series_name", ""),
            })
            # Add character nodes (deduplicated by id)
            existing_ids = {n["id"] for n in nodes}
            for ch in entry.get("characters", []):
                ch_id = "char_" + re.sub(r'\W+', '_', ch["name"].lower())
                if ch_id not in existing_ids:
                    nodes.append({
                        "id":    ch_id,
                        "label": ch["name"],
                        "type":  "character",
                        "role":  ch.get("role", "supporting"),
                    })
                    existing_ids.add(ch_id)
            nodes_file.write_text(json.dumps(nodes, indent=2, ensure_ascii=False), encoding="utf-8")

            # ── Edges ──────────────────────────────────────────────────────────
            edges_file = graph_dir / "edges.json"
            edges: list = json.loads(edges_file.read_text(encoding="utf-8")) if edges_file.exists() else []
            existing_edge_ids = {e["id"] for e in edges}

            for ch in entry.get("characters", []):
                ch_id = "char_" + re.sub(r'\W+', '_', ch["name"].lower())
                eid = f"{entry['id']}_{ch_id}"
                if eid not in existing_edge_ids:
                    edges.append({
                        "id":     eid,
                        "source": entry["id"],
                        "target": ch_id,
                        "type":   "has_character",
                    })
                    existing_edge_ids.add(eid)

            # Series sequel edge (Vol N → Vol N-1)
            series = entry.get("series_name", "")
            vol_m = re.search(r'\b(?:Volume|Vol\.?|Book)\s*(\d+)', entry.get("book_title", ""), re.IGNORECASE)
            if series and vol_m and int(vol_m.group(1)) > 1:
                vol_num = int(vol_m.group(1))
                prior = [
                    e for e in all_entries
                    if e.get("series_name", "").lower() == series.lower()
                    and re.search(r'\b(?:Volume|Vol\.?|Book)\s*' + str(vol_num - 1) + r'\b',
                                  e.get("book_title", ""), re.IGNORECASE)
                ]
                if prior:
                    eid = f"{prior[0]['id']}_sequel_{entry['id']}"
                    if eid not in existing_edge_ids:
                        edges.append({
                            "id":     eid,
                            "source": prior[0]["id"],
                            "target": entry["id"],
                            "type":   "sequel",
                        })

            edges_file.write_text(json.dumps(edges, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.debug("Book graph updated: %s", entry["book_title"])

        except Exception as ex:
            logger.warning("Book graph update failed (non-fatal): %s", ex)


# ── Module-level singleton ────────────────────────────────────────────────────

_registry: Optional[CharacterRegistry] = None


def get_character_registry() -> CharacterRegistry:
    global _registry
    if _registry is None:
        _registry = CharacterRegistry()
    return _registry
