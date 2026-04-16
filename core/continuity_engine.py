#!/usr/bin/env python3
"""
core/continuity_engine.py
─────────────────────────────────────────────────────────────────────────────
ContinuityEngine — Extract story bibles from manuscripts and compare volumes
for character, plot, and world-rule continuity.

Used by:
  - volume_completion_bot.py  (before writing a sequel)
  - literary_qc.py            (series_continuity pass)
  - memory_thief_vol2.py      (loads real Vol 1 characters)
  - /api/continuity/          (API endpoints)
─────────────────────────────────────────────────────────────────────────────
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.base_bot import BaseBot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BIBLES_DIR = ROOT / "data" / "story_bibles"
BIBLES_DIR.mkdir(parents=True, exist_ok=True)


class ContinuityEngine(BaseBot):
    """
    Extracts story bibles from manuscripts and validates continuity
    between volumes of a series.
    """

    def __init__(self):
        super().__init__("continuity_engine", "core")

    def run(self, action: str = "extract", **kwargs):
        if action == "extract":
            text = kwargs.get("manuscript") or kwargs.get("text", "")
            title = kwargs.get("title", "untitled")
            return self.extract_story_bible(text, title)
        elif action == "compare":
            vol1_bible = kwargs.get("vol1_bible", {})
            vol2_text = kwargs.get("vol2_text", "")
            return self.compare_volumes(vol1_bible, vol2_text)
        elif action == "report":
            comparison = kwargs.get("comparison", {})
            return {"report": self.generate_continuity_report(comparison)}
        return {}

    # ── Story Bible Extraction ────────────────────────────────────────────────

    def extract_story_bible(self, manuscript_text: str, title: str = "untitled") -> dict:
        """
        Extract a structured story bible from a manuscript.
        Saves to data/story_bibles/{safe_title}.json for reuse.
        """
        safe_title = re.sub(r"[^\w]+", "_", title.lower())[:50]
        cache_path = BIBLES_DIR / f"{safe_title}.json"

        # Return cached bible if exists and fresh (< 7 days)
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                age_days = (datetime.now() - datetime.fromisoformat(
                    cached.get("extracted_at", "2000-01-01")
                )).days
                if age_days < 7:
                    self.logger.info("Story bible loaded from cache: %s", cache_path.name)
                    return cached
            except Exception:
                pass

        self.logger.info("Extracting story bible from: %s (%d words)", title, len(manuscript_text.split()))

        # Truncate for API — use first 12K + last 3K words to capture setup and ending
        words = manuscript_text.split()
        if len(words) > 15000:
            sample = " ".join(words[:12000]) + "\n\n[...middle sections...]\n\n" + " ".join(words[-3000:])
        else:
            sample = manuscript_text

        prompt = f"""You are a literary analyst extracting a structured story bible from a manuscript.

MANUSCRIPT (title: "{title}"):
{sample[:20000]}

Extract the following as a JSON object ONLY (no extra text):
{{
  "title": "exact title",
  "characters": [
    {{
      "name": "full name as used in text",
      "role": "protagonist|antagonist|supporting|minor",
      "description": "brief physical/personality description",
      "abilities": "any special skills or supernatural abilities",
      "relationships": "key relationships to other characters",
      "arc": "how character changes through the story"
    }}
  ],
  "plot_threads": [
    {{
      "thread": "description of the plot thread",
      "introduced": "chapter/scene where introduced",
      "status": "resolved|unresolved|partially_resolved"
    }}
  ],
  "world_rules": [
    "rule 1 about how the world/abilities work",
    "rule 2..."
  ],
  "setting": "time period, location, atmosphere",
  "tone": "genre tone (dark/light/humorous/serious etc)",
  "cliffhanger": "exact description of unresolved ending, or 'none' if complete",
  "last_line": "the actual last sentence of the manuscript",
  "ending_status": "complete|incomplete|mid_sentence",
  "major_mysteries": ["unresolved question 1", "unresolved question 2"],
  "resolved_mysteries": ["resolved question 1", "resolved question 2"],
  "series_setup": "how this book sets up a potential sequel"
}}

Be precise about character names — use the exact names as they appear in the text.
If ending_status is incomplete or mid_sentence, the cliffhanger field must describe exactly what was happening."""

        try:
            result = self.claude_json(prompt)
        except Exception as e:
            self.logger.error("Story bible extraction failed: %s", e)
            result = self._fallback_extract(manuscript_text, title)

        result["title"] = result.get("title") or title
        result["extracted_at"] = datetime.now().isoformat()
        result["word_count"] = len(manuscript_text.split())
        result["source_title"] = title

        # Cache to disk
        cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        self.logger.info("Story bible saved: %s", cache_path.name)
        return result

    def _fallback_extract(self, text: str, title: str) -> dict:
        """Simple regex-based fallback if Claude fails."""
        # Find character names (words before dialogue or description patterns)
        words = text.split()
        last_200 = " ".join(words[-200:]) if len(words) > 200 else text
        ends_mid = not last_200.rstrip().endswith((".", "!", "?", '"', "'"))

        return {
            "title": title,
            "characters": [],
            "plot_threads": [],
            "world_rules": [],
            "setting": "unknown",
            "tone": "unknown",
            "cliffhanger": "unknown — extraction failed",
            "last_line": " ".join(words[-20:]) if words else "",
            "ending_status": "mid_sentence" if ends_mid else "unknown",
            "major_mysteries": [],
            "resolved_mysteries": [],
            "series_setup": "",
        }

    # ── Volume Comparison ─────────────────────────────────────────────────────

    def compare_volumes(self, vol1_bible: dict, vol2_text: str) -> dict:
        """
        Compare a Vol 1 story bible against a Vol 2 manuscript.
        Returns detailed continuity analysis.
        """
        self.logger.info("Comparing Vol 2 against story bible: %s", vol1_bible.get("title", "?"))

        # Extract character names from Vol 1
        vol1_chars = {c["name"]: c for c in vol1_bible.get("characters", [])}
        vol1_char_names = list(vol1_chars.keys())
        vol1_threads = vol1_bible.get("plot_threads", [])
        vol1_unresolved = [t["thread"] for t in vol1_threads if t.get("status") == "unresolved"]

        # Truncate Vol 2 for API
        words = vol2_text.split()
        if len(words) > 15000:
            sample = " ".join(words[:10000]) + "\n\n[...]\n\n" + " ".join(words[-3000:])
        else:
            sample = vol2_text

        prompt = f"""You are a literary continuity editor. Check if Volume 2 correctly continues Volume 1.

VOLUME 1 STORY BIBLE:
Characters: {json.dumps(vol1_char_names, indent=2)}
Unresolved plot threads from Vol 1: {json.dumps(vol1_unresolved, indent=2)}
Vol 1 cliffhanger: {vol1_bible.get('cliffhanger', 'none')}
World rules: {json.dumps(vol1_bible.get('world_rules', []), indent=2)}

VOLUME 2 TEXT (sample):
{sample[:18000]}

Return ONLY a JSON object:
{{
  "character_mismatches": [
    {{
      "vol1_name": "Sara Chen",
      "vol2_name": "Elara Voss",
      "severity": "critical|major|minor",
      "occurrences": 5,
      "note": "protagonist renamed"
    }}
  ],
  "missing_threads": [
    "plot thread from vol1 not resolved in vol2"
  ],
  "resolved_threads": [
    "plot thread from vol1 properly resolved"
  ],
  "added_characters": [
    {{
      "name": "character in vol2 not in vol1",
      "role": "their role",
      "severity": "critical|acceptable"
    }}
  ],
  "world_rule_violations": [
    "rule from vol1 that is violated in vol2"
  ],
  "continuity_score": 85,
  "passed": true,
  "issues": [
    "summary of each critical issue"
  ],
  "verdict": "PASS|FAIL",
  "summary": "one paragraph summary of continuity quality"
}}

continuity_score is 0-100. passed is true only if score >= 70 and no critical character mismatches."""

        try:
            result = self.claude_json(prompt)
        except Exception as e:
            self.logger.error("Volume comparison failed: %s", e)
            # Fallback: check character names manually
            result = self._fallback_compare(vol1_char_names, vol2_text)

        result.setdefault("continuity_score", 0)
        result.setdefault("passed", False)
        result.setdefault("verdict", "FAIL")
        return result

    def _fallback_compare(self, vol1_char_names: list, vol2_text: str) -> dict:
        """Fallback: check character names by simple string search."""
        mismatches = []
        for name in vol1_char_names:
            if name and name.lower() not in vol2_text.lower():
                mismatches.append({
                    "vol1_name": name,
                    "vol2_name": "not found",
                    "severity": "critical",
                    "occurrences": 0,
                    "note": f"'{name}' from Vol 1 not found in Vol 2",
                })
        score = max(0, 100 - len(mismatches) * 20)
        return {
            "character_mismatches": mismatches,
            "missing_threads": [],
            "resolved_threads": [],
            "added_characters": [],
            "world_rule_violations": [],
            "continuity_score": score,
            "passed": score >= 70,
            "issues": [m["note"] for m in mismatches],
            "verdict": "PASS" if score >= 70 else "FAIL",
            "summary": f"Fallback check: {len(mismatches)} character(s) from Vol 1 missing in Vol 2.",
        }

    # ── Report Generation ─────────────────────────────────────────────────────

    def generate_continuity_report(self, comparison: dict) -> str:
        """Generate a human-readable continuity report from comparison results."""
        score = comparison.get("continuity_score", 0)
        verdict = comparison.get("verdict", "FAIL")
        mismatches = comparison.get("character_mismatches", [])
        missing = comparison.get("missing_threads", [])
        added = comparison.get("added_characters", [])
        violations = comparison.get("world_rule_violations", [])

        lines = [
            "# Continuity Report",
            f"**Verdict:** {verdict}  |  **Score:** {score}/100",
            "",
        ]

        if mismatches:
            lines.append("## Character Mismatches (CRITICAL)")
            for m in mismatches:
                lines.append(f"- Vol 1: `{m['vol1_name']}` → Vol 2: `{m['vol2_name']}` ({m['severity']}) — {m.get('note', '')}")
            lines.append("")

        if missing:
            lines.append("## Unresolved Plot Threads")
            for t in missing:
                lines.append(f"- {t}")
            lines.append("")

        if added:
            critical_added = [a for a in added if a.get("severity") == "critical"]
            if critical_added:
                lines.append("## Unauthorized New Characters")
                for a in critical_added:
                    lines.append(f"- `{a['name']}` ({a['role']}) — not in Vol 1")
                lines.append("")

        if violations:
            lines.append("## World Rule Violations")
            for v in violations:
                lines.append(f"- {v}")
            lines.append("")

        summary = comparison.get("summary", "")
        if summary:
            lines.append("## Summary")
            lines.append(summary)

        return "\n".join(lines)

    # ── Convenience: Load bible from file ────────────────────────────────────

    def extract_from_file(self, manuscript_path: str) -> dict:
        """Read a manuscript file and extract its story bible."""
        path = Path(manuscript_path)
        if not path.exists():
            raise FileNotFoundError(f"Manuscript not found: {manuscript_path}")
        text = path.read_text(encoding="utf-8")
        title = path.stem.replace("_", " ").replace("-", " ").title()
        return self.extract_story_bible(text, title)

    def get_cached_bible(self, title: str) -> Optional[dict]:
        """Return a cached story bible by title, or None if not found."""
        safe_title = re.sub(r"[^\w]+", "_", title.lower())[:50]
        cache_path = BIBLES_DIR / f"{safe_title}.json"
        if cache_path.exists():
            try:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="ContinuityEngine — extract and compare story bibles")
    p.add_argument("--extract", metavar="FILE", help="Extract story bible from manuscript file")
    p.add_argument("--compare", nargs=2, metavar=("VOL1_BIBLE_JSON", "VOL2_FILE"), help="Compare volumes")
    p.add_argument("--title", default="untitled", help="Title for extraction")
    args = p.parse_args()

    engine = ContinuityEngine()

    if args.extract:
        bible = engine.extract_from_file(args.extract)
        print(json.dumps(bible, indent=2))
    elif args.compare:
        bible = json.loads(Path(args.compare[0]).read_text())
        vol2 = Path(args.compare[1]).read_text(encoding="utf-8")
        result = engine.compare_volumes(bible, vol2)
        print(engine.generate_continuity_report(result))
