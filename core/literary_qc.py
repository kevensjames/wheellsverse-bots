#!/usr/bin/env python3
"""
core/literary_qc.py
─────────────────────────────────────────────────────────────────────────────
LiteraryQCAgent — 7-pass literary quality control for book manuscripts.

Passes:
  1. completion          — real ending, all arcs closed, THE END marker
  2. character_consistency — same names/abilities/personality throughout
  3. plot_threads        — every mystery/question raised gets answered
  4. pacing              — no dead chapters, no rushed endings
  5. series_continuity   — if vol1_bible provided: names match, no changes
  6. market_readiness    — would readers enjoy this? comparable to published works?
  7. publication_ready   — word count OK, no placeholder text, properly formatted

Approval: score >= 75 overall, no single pass < 40.
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
QC_RESULTS_FILE = ROOT / "data" / "literary_qc_results.json"

PASS_THRESHOLD = 75    # overall score to approve
FAIL_FLOOR = 40    # any single pass below this = rejection
MAX_RESULTS = 200   # keep last N results in JSON


class LiteraryQCAgent(BaseBot):
    """
    7-pass literary quality control. Extends the existing QC system
    (market_intelligence.py) with book-specific narrative passes.
    """

    def __init__(self):
        super().__init__("literary_qc", "core")

    def run(self, action: str = "review", **kwargs):
        if action == "review":
            return self.review_manuscript(
                manuscript=kwargs.get("manuscript", ""),
                title=kwargs.get("title", "untitled"),
                vol1_bible=kwargs.get("vol1_bible"),
                genre=kwargs.get("genre", "mystery"),
            )
        elif action == "full_analysis":
            return self.full_book_analysis(
                manuscript=kwargs.get("manuscript", ""),
                title=kwargs.get("title", "untitled"),
                genre=kwargs.get("genre", "mystery"),
                vol1_bible=kwargs.get("vol1_bible"),
                manuscript_path=kwargs.get("manuscript_path", ""),
            )
        elif action == "results":
            return {"results": self._load_results()}
        return {}

    # ── Main Review ──────────────────────────────────────────────────────────

    def review_manuscript(
        self,
        manuscript: str,
        title: str,
        vol1_bible: Optional[dict] = None,
        genre: str = "mystery",
        series_name: str = "",
        check_registry: bool = True,
    ) -> dict:
        """
        Run all 8 literary QC passes on a manuscript.
        Returns full structured result with scores, issues, verdict.
        """
        self.logger.info("Starting literary QC: %s (%d words)", title, len(manuscript.split()))

        # Truncate for each pass — use representative sample
        words = manuscript.split()
        wc = len(words)
        if wc > 15000:
            opening = " ".join(words[:5000])
            middle = " ".join(words[wc // 2 - 1500: wc // 2 + 1500])
            ending = " ".join(words[-5000:])
            sample = f"{opening}\n\n[...middle section...]\n\n{middle}\n\n[...ending...]\n\n{ending}"
        else:
            sample = manuscript

        passes = {}

        # ── Pass 1: Completion ────────────────────────────────────────────────
        passes["completion"] = self._pass_completion(sample, title, wc)

        # ── Pass 2: Character Consistency ────────────────────────────────────
        passes["character_consistency"] = self._pass_character_consistency(sample, title)

        # ── Pass 3: Plot Threads ──────────────────────────────────────────────
        passes["plot_threads"] = self._pass_plot_threads(sample, title, genre)

        # ── Pass 4: Pacing ────────────────────────────────────────────────────
        passes["pacing"] = self._pass_pacing(sample, title, genre)

        # ── Pass 5: Series Continuity (only if vol1_bible provided) ──────────
        if vol1_bible:
            passes["series_continuity"] = self._pass_series_continuity(sample, title, vol1_bible)
        else:
            passes["series_continuity"] = {"score": 100, "issues": [], "skipped": True,
                                            "note": "No Vol 1 bible provided — standalone book"}

        # ── Pass 6: Market Readiness ──────────────────────────────────────────
        passes["market_readiness"] = self._pass_market_readiness(sample, title, genre)

        # ── Pass 7: Publication Ready ─────────────────────────────────────────
        passes["publication_ready"] = self._pass_publication_ready(manuscript, title, wc)

        # ── Pass 8: Cross-book Name Uniqueness ───────────────────────────────
        if check_registry:
            passes["name_uniqueness"] = self._pass_name_uniqueness(sample, title, series_name)
        else:
            passes["name_uniqueness"] = {"score": 100, "issues": [], "skipped": True,
                                           "note": "Registry check skipped"}

        # ── Aggregate score ───────────────────────────────────────────────────
        scores = [p["score"] for p in passes.values() if not p.get("skipped")]
        overall = round(sum(scores) / len(scores)) if scores else 0
        min_score = min(scores) if scores else 0
        approved = (overall >= PASS_THRESHOLD) and (min_score >= FAIL_FLOOR)

        # Collect all issues
        all_issues = []
        for pass_name, data in passes.items():
            for issue in data.get("issues", []):
                all_issues.append(f"[{pass_name}] {issue}")

        # Revision notes
        revision_notes = self._generate_revision_notes(passes, overall, approved) if not approved else ""

        result = {
            "title": title,
            "genre": genre,
            "word_count": wc,
            "score": overall,
            "approved": approved,
            "verdict": "APPROVED" if approved else "REJECTED",
            "passes": passes,
            "issues": all_issues,
            "revision_notes": revision_notes,
            "reviewed_at": datetime.now().isoformat(),
        }

        self._save_result(result)
        self.logger.info("QC complete: %s — %s (score: %d)", title,
                         result["verdict"], overall)

        # Register characters in global registry after approval
        if approved and check_registry:
            try:
                from core.character_registry import get_character_registry
                get_character_registry().extract_and_register(
                    manuscript, title, genre, series_name or title, self
                )
            except Exception as _reg_err:
                self.logger.debug("Character registration skipped: %s", _reg_err)

        return result

    # ── Pass implementations ──────────────────────────────────────────────────

    def _pass_completion(self, sample: str, title: str, word_count: int) -> dict:
        """Does the story have a real, satisfying ending?"""
        # Quick checks first
        tail = sample[-500:].lower() if len(sample) > 500 else sample.lower()
        has_end_marker = any(e in tail for e in ["the end", "**the end**", "— end —", "epilogue"])
        ends_mid = not tail.rstrip().endswith((".", "!", "?", '"', "'", "…"))
        too_short = word_count < 8000

        if too_short:
            return {"score": 20, "issues": [f"Manuscript only {word_count} words — too short for KDP (min 10,000)"],
                    "has_end_marker": False, "ends_mid_sentence": True}
        if ends_mid:
            return {"score": 10, "issues": ["Manuscript ends mid-sentence — story is incomplete"],
                    "has_end_marker": False, "ends_mid_sentence": True}

        prompt = f"""Evaluate whether this story has a complete, satisfying ending.

Title: "{title}"

Story ending (last ~1000 words):
{sample[-4000:]}

Return JSON only:
{{
  "score": 85,
  "has_satisfying_ending": true,
  "all_main_arcs_closed": true,
  "ending_quality": "strong|adequate|weak|none",
  "issues": ["list of specific completion problems, or empty if none"],
  "verdict": "The ending..."
}}
score is 0-100. Issues list must be specific, not generic."""

        try:
            r = self.claude_json(prompt)
            r.setdefault("score", 50)
            r.setdefault("issues", [])
            if has_end_marker:
                r["score"] = min(100, r["score"] + 10)
            return r
        except Exception as e:
            score = 70 if has_end_marker else 40
            return {"score": score, "issues": [f"QC check error: {e}"], "has_end_marker": has_end_marker}

    def _pass_character_consistency(self, sample: str, title: str) -> dict:
        """Do character names, abilities, and personalities stay consistent?"""
        prompt = f"""Check character consistency throughout this manuscript.

Title: "{title}"

Text (opening + ending):
{sample[:6000]}
...
{sample[-3000:]}

Return JSON only:
{{
  "score": 90,
  "characters_found": ["Sara Chen", "Mike Rodriguez"],
  "name_inconsistencies": ["character referred to as 'Sara' then 'Detective Lee'"],
  "ability_inconsistencies": ["ability described differently in ch1 vs ch12"],
  "personality_inconsistencies": ["character acts against established traits"],
  "issues": ["specific consistency problems"],
  "verdict": "Characters are consistent / inconsistent because..."
}}
score is 0-100. Be specific about any inconsistencies found."""

        try:
            r = self.claude_json(prompt)
            r.setdefault("score", 75)
            r.setdefault("issues", [])
            return r
        except Exception as e:
            return {"score": 60, "issues": [f"QC check error: {e}"]}

    def _pass_plot_threads(self, sample: str, title: str, genre: str) -> dict:
        """Are all plot threads and mysteries properly resolved?"""
        prompt = f"""Analyze plot thread resolution in this {genre} manuscript.

Title: "{title}"

Opening (introduces threads):
{sample[:5000]}

Ending (resolves threads):
{sample[-5000:]}

Return JSON only:
{{
  "score": 80,
  "threads_introduced": ["the mystery of X", "who killed Y"],
  "threads_resolved": ["mystery of X revealed in ch12"],
  "threads_unresolved": ["who killed Y never answered"],
  "dangling_questions": ["questions raised but never answered"],
  "issues": ["specific unresolved thread problems"],
  "verdict": "Plot threads are well-resolved / have gaps because..."
}}
score is 0-100. A {genre} MUST resolve its central mystery."""

        try:
            r = self.claude_json(prompt)
            r.setdefault("score", 70)
            r.setdefault("issues", [])
            return r
        except Exception as e:
            return {"score": 55, "issues": [f"QC check error: {e}"]}

    def _pass_pacing(self, sample: str, title: str, genre: str) -> dict:
        """Is the story well-paced? No dead chapters, no rushed ending?"""
        prompt = f"""Evaluate the pacing of this {genre} manuscript.

Title: "{title}"

Sample (opening + middle + ending):
{sample[:8000]}

Return JSON only:
{{
  "score": 75,
  "opening_hook": "strong|adequate|weak",
  "middle_sag": false,
  "rushed_ending": false,
  "chapter_endings": "hooks readers forward / too weak",
  "tension_curve": "builds steadily / drops mid-book / inconsistent",
  "issues": ["specific pacing problems"],
  "verdict": "Pacing is strong/adequate/weak because..."
}}
score is 0-100."""

        try:
            r = self.claude_json(prompt)
            r.setdefault("score", 70)
            r.setdefault("issues", [])
            return r
        except Exception as e:
            return {"score": 60, "issues": [f"QC check error: {e}"]}

    def _pass_series_continuity(self, sample: str, title: str, vol1_bible: dict) -> dict:
        """
        Does Vol 2 correctly continue Vol 1?
        Checks names, abilities, world rules, no unauthorized additions.
        """
        vol1_chars = [c["name"] for c in vol1_bible.get("characters", [])]
        vol1_rules = vol1_bible.get("world_rules", [])
        vol1_cliffhanger = vol1_bible.get("cliffhanger", "none")

        prompt = f"""Check series continuity between Volume 1 and this Volume 2.

VOLUME 1 FACTS:
- Characters: {json.dumps(vol1_chars)}
- World rules: {json.dumps(vol1_rules)}
- Vol 1 ended on: {vol1_cliffhanger}

VOLUME 2 OPENING (must pick up from cliffhanger):
{sample[:6000]}

VOLUME 2 ENDING:
{sample[-3000:]}

Return JSON only:
{{
  "score": 90,
  "correct_protagonist": true,
  "protagonist_name_matches": true,
  "cliffhanger_resolved": true,
  "unauthorized_name_changes": ["Vol 1 name X appears as Y in Vol 2"],
  "unauthorized_new_characters": ["character not in Vol 1 added without justification"],
  "ability_changes": ["ability worked differently than Vol 1 established"],
  "world_rule_violations": ["rule broken"],
  "issues": ["specific continuity failures"],
  "verdict": "Continuity is maintained / broken because..."
}}
score 0-100. Critical: protagonist name MUST match Vol 1. Zero tolerance for unauthorized renames."""

        try:
            r = self.claude_json(prompt)
            r.setdefault("score", 50)
            r.setdefault("issues", [])
            # Hard penalize protagonist name mismatch
            if not r.get("protagonist_name_matches", True):
                r["score"] = min(r["score"], 30)
                r["issues"].append("CRITICAL: Protagonist name does not match Vol 1")
            return r
        except Exception as e:
            return {"score": 30, "issues": [f"Series continuity check error: {e}"]}

    def _pass_market_readiness(self, sample: str, title: str, genre: str) -> dict:
        """Would readers enjoy this? Is it comparable to published works?"""
        prompt = f"""Evaluate the market readiness of this {genre} manuscript.

Title: "{title}"

Sample:
{sample[:6000]}

Return JSON only:
{{
  "score": 75,
  "comparable_authors": ["author 1", "author 2"],
  "target_audience": "description",
  "unique_hook": "what makes this stand out",
  "reader_engagement": "high/medium/low",
  "commercial_viability": "high/medium/low",
  "kdp_category_fit": "strong/adequate/weak",
  "issues": ["specific market problems"],
  "verdict": "This book is/isn't commercially viable because..."
}}
score 0-100. Compare against actual published {genre} books."""

        try:
            r = self.claude_json(prompt)
            r.setdefault("score", 65)
            r.setdefault("issues", [])
            return r
        except Exception as e:
            return {"score": 60, "issues": [f"QC check error: {e}"]}

    def _pass_publication_ready(self, full_manuscript: str, title: str, word_count: int) -> dict:
        """Is the manuscript properly formatted and ready to upload to KDP?"""
        issues = []
        score = 100

        # Word count check
        if word_count < 10000:
            issues.append(f"Word count {word_count} is below KDP minimum (10,000)")
            score -= 40
        elif word_count < 15000:
            issues.append(f"Word count {word_count} is low — aim for 20,000+ for better perceived value")
            score -= 10

        # Check for placeholder text
        placeholders = ["[PLACEHOLDER]", "[TODO]", "[INSERT", "XXXX", "Lorem ipsum",
                        "[chapter title]", "[author name]", "[finish this"]
        for ph in placeholders:
            if ph.lower() in full_manuscript.lower():
                issues.append(f"Placeholder text found: '{ph}'")
                score -= 15

        # Check for proper structure markers
        has_chapters = bool(re.search(r"##\s*Chapter\s+\d+", full_manuscript, re.IGNORECASE))
        has_title = full_manuscript.strip().startswith("#")
        has_ending = any(e in full_manuscript[-500:].lower() for e in
                         ["the end", "**the end**", "about the author", "acknowledgment"])

        if not has_chapters:
            issues.append("No chapter headings found (## Chapter N format)")
            score -= 10
        if not has_title:
            issues.append("Missing title heading at start of manuscript")
            score -= 5
        if not has_ending:
            issues.append("No ending marker (THE END, About the Author) found")
            score -= 15

        score = max(0, min(100, score))
        return {
            "score": score,
            "word_count": word_count,
            "has_chapters": has_chapters,
            "has_title_heading": has_title,
            "has_ending_marker": has_ending,
            "issues": issues,
        }

    def _pass_name_uniqueness(self, sample: str, title: str, series_name: str = "") -> dict:
        """Pass 8: Check that no character names are reused from different series."""
        try:
            from core.character_registry import get_character_registry
            cr = get_character_registry()
            # Extract capitalised name pairs from the sample
            raw = re.findall(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', sample)
            # Also generate 2-word sub-pairs (e.g. 'Detective Sara Chen' → 'Sara Chen')
            expanded = set()
            for phrase in raw:
                parts = phrase.split()
                for i in range(len(parts) - 1):
                    expanded.add(parts[i] + " " + parts[i + 1])
                expanded.add(phrase)
            names = list(expanded)[:60]
            if not names:
                return {"score": 100, "issues": [], "conflicts": [], "names_checked": 0}
            conflicts = cr.check_conflicts(names, series_name=series_name)
            score = max(0, 100 - len(conflicts) * 20)
            issues = [f"'{n}' already used in a different WheellsVerse series" for n in conflicts]
            return {
                "score":         score,
                "issues":        issues,
                "conflicts":     conflicts,
                "names_checked": len(names),
            }
        except Exception as ex:
            return {"score": 100, "issues": [], "conflicts": [], "error": str(ex), "skipped": True}

    # ── Full Book Analysis (chapter-by-chapter deep scan) ────────────────────

    def full_book_analysis(
        self,
        manuscript: str,
        title: str,
        genre: str = "mystery",
        vol1_bible: Optional[dict] = None,
        manuscript_path: str = "",
    ) -> dict:
        """
        Deep chapter-by-chapter analysis of the full manuscript.
        Flags incomplete chapters, stub chapters, and missing endings.
        If the book needs a full rewrite, dispatches to the NarAI rewrite queue.
        """
        self.logger.info("Full book analysis: %s (%d words)", title, len(manuscript.split()))

        # ── Chapter parsing ───────────────────────────────────────────────────
        chapter_pattern = re.compile(
            r'^#{1,2}\s*(?:Chapter|Ch\.?|CHAPTER|PART)\s*\d+', re.MULTILINE
        )
        splits = list(chapter_pattern.finditer(manuscript))

        chapters = []
        for i, m in enumerate(splits):
            start = m.start()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(manuscript)
            body = manuscript[start:end].strip()
            ch_title = m.group(0).strip().lstrip("#").strip()
            chapters.append({"num": i + 1, "title": ch_title, "body": body})

        chapter_count = len(chapters)

        # ── Per-chapter checks ────────────────────────────────────────────────
        incomplete_chapters = []
        stub_chapters = []
        SENTENCE_FINAL = {'.', '!', '?', '"', "'", '\u2026', '*', '\u201d', '\u2019'}

        for ch in chapters:
            words = ch["body"].split()
            wc = len(words)

            # Stub: fewer than 300 words
            if wc < 300:
                stub_chapters.append({"num": ch["num"], "title": ch["title"], "word_count": wc})

            # Incomplete: last meaningful word doesn't end a sentence
            # Strip markdown separators (---, ***, ___) before checking
            body_stripped = re.sub(r'\n[-*_]{3,}\s*$', '', ch["body"].rstrip())
            words_clean = body_stripped.split()
            last_words = " ".join(words_clean[-50:]) if len(words_clean) >= 50 else body_stripped
            stripped = last_words.rstrip()
            if stripped and stripped[-1] not in SENTENCE_FINAL:
                incomplete_chapters.append({
                    "num": ch["num"],
                    "title": ch["title"],
                    "last_words": " ".join(words[-15:]),
                })

        # ── Ending detection ──────────────────────────────────────────────────
        last_2000 = manuscript[-2000:].lower()
        END_MARKERS = ("the end", "**the end**", "— end —", "epilogue",
                       "about the author", "acknowledgment", "acknowledgement")
        has_proper_ending = any(m in last_2000 for m in END_MARKERS)

        # Also check final chapter last line
        final_ending_ok = has_proper_ending
        if chapters:
            final_words = chapters[-1]["body"].split()
            if final_words and final_words[-1].rstrip()[-1] not in SENTENCE_FINAL:
                final_ending_ok = False

        # ── Run standard 7-pass QC ────────────────────────────────────────────
        qc = self.review_manuscript(manuscript, title, vol1_bible, genre)

        # ── Rewrite conditions ────────────────────────────────────────────────
        rewrite_needed = (
            len(incomplete_chapters) > 0
            or (not final_ending_ok and not has_proper_ending)
            or qc["score"] < 50
            or len(stub_chapters) > 2
        )

        # Build human-readable fail reason
        reasons = []
        if incomplete_chapters:
            nums = ", ".join(str(c["num"]) for c in incomplete_chapters)
            reasons.append(f"Chapter(s) {nums} end mid-sentence")
        if not has_proper_ending and not final_ending_ok:
            reasons.append("No proper ending / THE END marker found")
        if qc["score"] < 50:
            reasons.append(f"QC score too low ({qc['score']}/100) for revision to fix")
        if len(stub_chapters) > 2:
            nums = ", ".join(str(c["num"]) for c in stub_chapters)
            reasons.append(f"Stub chapters (< 300 words): {nums}")
        fail_reason = "; ".join(reasons) if reasons else ""

        # Build rewrite directive
        rewrite_directive = ""
        if rewrite_needed:
            parts = [f"Full rewrite needed for '{title}' ({genre})."]
            if incomplete_chapters:
                for c in incomplete_chapters:
                    parts.append(
                        f"Chapter {c['num']} ({c['title']}) ends mid-sentence: "
                        f"\"...{c['last_words']}\". Complete this chapter properly."
                    )
            if not has_proper_ending:
                parts.append(
                    "The book has no proper ending. Add a final chapter that resolves all "
                    "plot threads and ends with 'THE END'."
                )
            if qc.get("revision_notes"):
                parts.append(qc["revision_notes"])
            rewrite_directive = "\n\n".join(parts)

        result = {
            "title": title,
            "genre": genre,
            "word_count": len(manuscript.split()),
            "chapter_count": chapter_count,
            "incomplete_chapters": incomplete_chapters,
            "stub_chapters": stub_chapters,
            "has_proper_ending": has_proper_ending,
            "overall_score": qc["score"],
            "approved": qc["approved"] and not rewrite_needed,
            "verdict": "APPROVED" if (qc["approved"] and not rewrite_needed) else "REJECTED",
            "fail_reason": fail_reason,
            "rewrite_needed": rewrite_needed,
            "rewrite_directive": rewrite_directive,
            "passes": qc.get("passes", {}),
            "analyzed_at": datetime.now().isoformat(),
        }

        # ── Dispatch to NarAI rewrite queue if needed ─────────────────────────
        if rewrite_needed:
            self._dispatch_rewrite(result, manuscript_path)

        return result

    def _dispatch_rewrite(self, analysis: dict, manuscript_path: str):
        """Append a failed book to the NarAI rewrite queue."""
        queue_file = ROOT / "data" / "narai_rewrite_queue.json"
        try:
            queue = []
            if queue_file.exists():
                try:
                    queue = json.loads(queue_file.read_text(encoding="utf-8"))
                except Exception:
                    queue = []

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            entry = {
                "id": f"rewrite_{ts}",
                "title": analysis["title"],
                "genre": analysis["genre"],
                "manuscript_path": manuscript_path,
                "fail_reason": analysis["fail_reason"],
                "rewrite_directive": analysis["rewrite_directive"],
                "qc_score": analysis["overall_score"],
                "chapter_count": analysis["chapter_count"],
                "incomplete_chapters": len(analysis["incomplete_chapters"]),
                "queued_at": datetime.now().isoformat(),
                "status": "pending",
            }
            # Avoid duplicate entries for the same manuscript
            queue = [q for q in queue if q.get("manuscript_path") != manuscript_path]
            queue.append(entry)
            queue_file.parent.mkdir(parents=True, exist_ok=True)
            queue_file.write_text(json.dumps(queue, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
            self.logger.warning("Dispatched to NarAI rewrite queue: %s (score %d)",
                                 analysis["title"], analysis["overall_score"])

            # Telegram alert
            try:
                from core.telegram import notify
                notify(
                    f"⚠️ Book failed QC — queued for NarAI rewrite\n"
                    f"📖 {analysis['title']}\n"
                    f"📊 Score: {analysis['overall_score']}/100\n"
                    f"❌ {analysis['fail_reason']}"
                )
            except Exception:
                pass
        except Exception as e:
            self.logger.error("Failed to dispatch rewrite: %s", e)

    # ── Revision Notes ────────────────────────────────────────────────────────

    def _generate_revision_notes(self, passes: dict, overall: int, approved: bool) -> str:
        """Generate actionable revision instructions for rejected manuscripts."""
        failed = [(name, data) for name, data in passes.items()
                  if data.get("score", 100) < FAIL_FLOOR and not data.get("skipped")]
        weak = [(name, data) for name, data in passes.items()
                  if FAIL_FLOOR <= data.get("score", 100) < PASS_THRESHOLD and not data.get("skipped")]

        lines = ["# Revision Instructions\n"]
        lines.append(f"Overall score: {overall}/100. Target: {PASS_THRESHOLD}+\n")

        if failed:
            lines.append("## Critical Issues (must fix):")
            for name, data in failed:
                lines.append(f"\n### {name.replace('_', ' ').title()} (score: {data['score']})")
                for issue in data.get("issues", []):
                    lines.append(f"- {issue}")
                if data.get("verdict"):
                    lines.append(f"\n  {data['verdict']}")

        if weak:
            lines.append("\n## Improvements Needed:")
            for name, data in weak:
                lines.append(f"\n### {name.replace('_', ' ').title()} (score: {data['score']})")
                for issue in data.get("issues", []):
                    lines.append(f"- {issue}")

        return "\n".join(lines)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_result(self, result: dict):
        try:
            results = []
            if QC_RESULTS_FILE.exists():
                try:
                    results = json.loads(QC_RESULTS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    results = []
            results.append({k: v for k, v in result.items() if k != "passes"})
            results = results[-MAX_RESULTS:]
            QC_RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
        except Exception as e:
            self.logger.warning("Failed to save QC result: %s", e)

    def _load_results(self, limit: int = 50) -> list:
        try:
            if QC_RESULTS_FILE.exists():
                results = json.loads(QC_RESULTS_FILE.read_text(encoding="utf-8"))
                return results[-limit:]
        except Exception:
            pass
        return []


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="LiteraryQCAgent — review a manuscript")
    p.add_argument("manuscript", help="Path to manuscript .md file")
    p.add_argument("--title", default="", help="Book title")
    p.add_argument("--genre", default="mystery", help="Genre")
    p.add_argument("--vol1-bible", help="Path to Vol 1 story bible JSON")
    args = p.parse_args()

    text = Path(args.manuscript).read_text(encoding="utf-8")
    title = args.title or Path(args.manuscript).stem.replace("_", " ").title()
    bible = None
    if args.vol1_bible:
        bible = json.loads(Path(args.vol1_bible).read_text(encoding="utf-8"))

    agent = LiteraryQCAgent()
    result = agent.review_manuscript(text, title, bible, args.genre)

    print(f"\n{'=' * 60}")
    print(f"  QC Result: {result['verdict']}  (score: {result['score']}/100)")
    print(f"{'=' * 60}")
    for pass_name, data in result["passes"].items():
        status = "✅" if data.get("score", 0) >= PASS_THRESHOLD else ("⚠️" if data.get("score", 0) >= FAIL_FLOOR else "❌")
        skipped = " (skipped)" if data.get("skipped") else ""
        print(f"  {status} {pass_name:25s} {data.get('score', 0):3d}/100{skipped}")
    if result.get("revision_notes"):
        print(f"\n{result['revision_notes']}")
