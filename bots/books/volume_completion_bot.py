#!/usr/bin/env python3
"""
bots/books/volume_completion_bot.py
─────────────────────────────────────────────────────────────────────────────
VolumeCompletionBot — scan all manuscripts, detect incomplete ones,
write proper sequels using ContinuityEngine (reads real characters),
run LiteraryQC, then publish to Amazon KDP.

Usage:
  python volume_completion_bot.py --action scan
  python volume_completion_bot.py --action complete_all
  python volume_completion_bot.py --action complete_one --file outputs/books/mystery/book_X.md
  python volume_completion_bot.py --action check_series
─────────────────────────────────────────────────────────────────────────────
"""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from core.base_bot import BaseBot  # noqa: E402

OUTPUTS_DIR = ROOT / "outputs" / "books"
SCAN_FILE = ROOT / "data" / "volume_scan_results.json"

GENRES = [
    "childrens", "mystery", "adventure", "historical",
    "self_help", "romance", "sci_fi", "fantasy", "horror", "true_crime",
]

# Files to skip during scan (not primary manuscripts)
SKIP_PREFIXES = ("outline_", "cover_", "kdp_", "series_", "book_promo_",
                 "pe_",  # publisher engine outputs
                 "the_memory_thief_vol2_",  # handled separately
                 )


class VolumeCompletionBot(BaseBot):
    """
    Scans all manuscript outputs, identifies incomplete stories,
    and writes proper sequel volumes using the real story bible.
    """

    def __init__(self):
        super().__init__("volume_completion_bot", "books")

    def run(self, action: str = "scan", **kwargs):
        actions = {
            "scan": self.scan_all_manuscripts,
            "complete_one": lambda: self.complete_volume(
                kwargs.get("file", ""), kwargs.get("genre", "mystery")
            ),
            "complete_all": self.complete_all_incomplete,
            "check_series": self.check_all_series_continuity,
        }
        fn = actions.get(action, self.scan_all_manuscripts)
        return fn()

    # ── Scan ──────────────────────────────────────────────────────────────────

    def scan_all_manuscripts(self) -> dict:
        """
        Walk all genre output directories and assess each manuscript.
        Returns categorized list: complete, incomplete, unknown.
        """
        self.logger.info("Scanning all manuscripts for completion status...")
        results = {"complete": [], "incomplete": [], "unknown": []}

        for genre in GENRES:
            genre_dir = OUTPUTS_DIR / genre
            if not genre_dir.exists():
                continue

            mds = sorted(
                [f for f in genre_dir.glob("*.md")
                 if not any(f.name.startswith(p) for p in SKIP_PREFIXES)],
                key=lambda f: f.stat().st_mtime, reverse=True
            )

            for md in mds:
                status = self._assess_completion(md)
                status["genre"] = genre
                results[status["status"]].append(status)

        total = sum(len(v) for v in results.values())
        self.logger.info(
            "Scan complete: %d total | %d complete | %d incomplete | %d unknown",
            total, len(results["complete"]), len(results["incomplete"]), len(results["unknown"])
        )

        # Save scan results
        SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCAN_FILE.write_text(json.dumps({
            "scanned_at": datetime.now().isoformat(),
            "total": total,
            **results
        }, indent=2, default=str), encoding="utf-8")

        # Print summary
        print(f"\n{'=' * 60}")
        print("  Volume Scan Results")
        print(f"{'=' * 60}")
        print(f"  ✅ Complete:   {len(results['complete'])}")
        print(f"  ❌ Incomplete: {len(results['incomplete'])}")
        print(f"  ❓ Unknown:    {len(results['unknown'])}")
        print(f"{'=' * 60}")
        if results["incomplete"]:
            print("\n  Incomplete manuscripts:")
            for r in results["incomplete"]:
                print(f"  • [{r['genre']}] {r['title']} ({r['word_count']:,} words) — {r['reason']}")
        print()

        return results

    def _assess_completion(self, path: Path) -> dict:
        """Assess whether a manuscript is complete."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"file": str(path), "title": path.stem, "status": "unknown",
                    "word_count": 0, "reason": f"Read error: {e}"}

        words = text.split()
        wc = len(words)
        title = path.stem.replace("_", " ").replace("-", " ")
        # Clean up timestamped filename
        title = re.sub(r"\s+\d{8}(?:_\d{6})?$", "", title).strip().title()

        tail = " ".join(words[-200:]) if wc > 200 else text
        tail_lower = tail.lower()

        # Definitive incomplete: ends mid-sentence
        if wc > 0 and not tail.rstrip().endswith((".", "!", "?", '"', "'", "…", "*")):
            return {"file": str(path), "title": title, "status": "incomplete",
                    "word_count": wc, "reason": "Ends mid-sentence",
                    "last_line": " ".join(words[-15:])}

        # Too short
        if wc < 5000:
            return {"file": str(path), "title": title, "status": "incomplete",
                    "word_count": wc, "reason": f"Only {wc} words — too short",
                    "last_line": " ".join(words[-15:])}

        # Has proper ending marker
        end_markers = ["the end", "**the end**", "— end —", "epilogue",
                       "about the author", "acknowledgment"]
        if any(m in tail_lower for m in end_markers):
            return {"file": str(path), "title": title, "status": "complete",
                    "word_count": wc, "reason": "Has ending marker",
                    "last_line": " ".join(words[-10:])}

        # Borderline — ask Claude for assessment if text is meaningful
        if wc >= 5000:
            return {"file": str(path), "title": title, "status": "unknown",
                    "word_count": wc, "reason": "No clear ending marker — manual review needed",
                    "last_line": " ".join(words[-15:])}

        return {"file": str(path), "title": title, "status": "unknown",
                "word_count": wc, "reason": "Unclear", "last_line": " ".join(words[-15:])}

    # ── Complete a single volume ───────────────────────────────────────────────

    def complete_volume(self, source_path: str, genre: str) -> dict:
        """
        Write a proper sequel for an incomplete manuscript:
        1. Extract story bible from Vol 1 (real characters)
        2. Write the completion using those characters
        3. Run Literary QC
        4. If passes: package + publish
        """
        from core.continuity_engine import ContinuityEngine
        from core.literary_qc import LiteraryQCAgent

        path = Path(source_path)
        if not path.exists():
            self.logger.error("File not found: %s", source_path)
            return {"error": f"File not found: {source_path}"}

        vol1_text = path.read_text(encoding="utf-8", errors="replace")
        title = path.stem.replace("_", " ").title()
        title = re.sub(r"\s+\d{8}(?:_\d{6})?$", "", title).strip()

        self.logger.info("Completing volume: %s (%s)", title, genre)

        # Step 1: Extract story bible
        self.logger.info("Step 1/4 — Extracting story bible from Vol 1...")
        engine = ContinuityEngine()
        bible = engine.extract_story_bible(vol1_text, title)

        cliffhanger = bible.get("cliffhanger", "The story ended abruptly")
        characters = bible.get("characters", [])
        char_names = [c["name"] for c in characters if c.get("role") in ("protagonist", "antagonist", "supporting")]
        world_rules = bible.get("world_rules", [])
        threads = [t["thread"] for t in bible.get("plot_threads", [])
                       if t.get("status") == "unresolved"]

        self.logger.info("Story bible extracted: %d characters, %d unresolved threads",
                         len(characters), len(threads))

        # Step 2: Write the completion
        self.logger.info("Step 2/4 — Writing completion sequel...")
        sequel = self._write_sequel(
            title=title, genre=genre,
            cliffhanger=cliffhanger,
            char_names=char_names,
            world_rules=world_rules,
            unresolved_threads=threads,
            bible=bible,
        )
        sequel_wc = len(sequel.split())
        self.logger.info("Sequel written: %d words", sequel_wc)

        # Step 3: Literary QC — up to 3 rounds, full book analysis each time
        MAX_QC_ROUNDS = 3
        self.logger.info("Step 3/4 — Running full book analysis QC (up to %d rounds)...", MAX_QC_ROUNDS)
        sequel_title = f"{title}: The Complete Story"
        qc_agent = LiteraryQCAgent()

        # Save to temp path for dispatch references
        ts_tmp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_tmp = re.sub(r"[^\w]+", "_", sequel_title.lower())[:40]
        tmp_path = OUTPUTS_DIR / genre / f"{safe_tmp}_{ts_tmp}_draft.md"
        tmp_path.parent.mkdir(parents=True, exist_ok=True)

        qc_result = {}
        for round_num in range(1, MAX_QC_ROUNDS + 1):
            # Save current draft for dispatch file reference
            tmp_path.write_text(sequel, encoding="utf-8")

            qc_result = qc_agent.full_book_analysis(
                manuscript=sequel,
                title=sequel_title,
                genre=genre,
                vol1_bible=bible,
                manuscript_path=str(tmp_path),
            )
            self.logger.info(
                "QC round %d/%d: %s (score: %d, rewrite_needed: %s)",
                round_num, MAX_QC_ROUNDS,
                qc_result["verdict"], qc_result["overall_score"],
                qc_result["rewrite_needed"],
            )

            if qc_result["approved"]:
                self.logger.info("QC passed on round %d", round_num)
                break

            if round_num == MAX_QC_ROUNDS:
                # Final round failed — already dispatched to rewrite queue by full_book_analysis
                self.logger.warning(
                    "QC failed after %d rounds — '%s' dispatched to NarAI rewrite queue",
                    MAX_QC_ROUNDS, sequel_title,
                )
                break

            # Revise for next round
            directive = qc_result.get("rewrite_directive") or qc_result.get("revision_notes", "")
            if directive:
                self.logger.info("Revising for round %d...", round_num + 1)
                sequel = self._revise_sequel(sequel, directive, genre, sequel_title)

        # Clean up draft temp file if it exists
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

        # Normalise qc_result keys (full_book_analysis uses overall_score, review_manuscript uses score)
        if "overall_score" in qc_result and "score" not in qc_result:
            qc_result["score"] = qc_result["overall_score"]

        # Step 4: Save + package
        self.logger.info("Step 4/4 — Packaging...")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = re.sub(r"[^\w]+", "_", sequel_title.lower())[:40]
        out_dir = OUTPUTS_DIR / genre
        out_dir.mkdir(parents=True, exist_ok=True)
        ms_path = out_dir / f"{safe_title}_{ts}.md"
        ms_path.write_text(sequel, encoding="utf-8")

        result = {
            "original_file": source_path,
            "sequel_file": str(ms_path),
            "title": sequel_title,
            "genre": genre,
            "word_count": sequel_wc,
            "qc_score": qc_result["score"],
            "qc_verdict": qc_result["verdict"],
            "characters_used": char_names,
            "cliffhanger_resolved": cliffhanger,
            "ts": ts,
        }

        # Notify
        try:
            from core.telegram import notify
            notify(
                f"📚 Volume Completed!\n"
                f"📖 {sequel_title}\n"
                f"📊 {sequel_wc:,} words\n"
                f"QC: {qc_result['verdict']} ({qc_result['score']}/100)\n"
                f"Characters: {', '.join(char_names[:3])}"
            )
        except Exception:
            pass

        return result

    def _write_sequel(self, title: str, genre: str, cliffhanger: str,
                      char_names: list, world_rules: list,
                      unresolved_threads: list, bible: dict) -> str:
        """Write a complete sequel that resolves the Vol 1 cliffhanger."""
        protagonist = char_names[0] if char_names else "the protagonist"

        # Build chapter outline based on unresolved threads
        num_chapters = max(10, min(16, len(unresolved_threads) * 2 + 4))

        outline_prompt = (
            f"You are writing the COMPLETE sequel to '{title}' ({genre}).\n\n"
            f"PROTAGONIST: {protagonist}\n"
            f"ALL CHARACTERS: {', '.join(char_names)}\n"
            f"VOL 1 ENDED ON: {cliffhanger}\n"
            f"MUST RESOLVE: {json.dumps(unresolved_threads[:8])}\n"
            f"WORLD RULES: {json.dumps(world_rules[:5])}\n\n"
            f"Create a {num_chapters}-chapter outline for the COMPLETE sequel.\n"
            f"Chapter 1 must pick up EXACTLY where Vol 1 ended.\n"
            f"Final chapter must resolve EVERYTHING and end satisfyingly.\n"
            f"Format:\nCHAPTER N: [Title] | [word count]\n"
            f"What happens: [3 sentences]\nEnds on: [hook or resolution]\n"
        )

        outline_raw = self.claude(outline_prompt, max_tokens=3000)

        # Parse chapters
        chapter_lines = re.findall(r"CHAPTER\s+(\d+):\s*([^\n|]+)", outline_raw, re.IGNORECASE)
        if not chapter_lines:
            chapter_lines = [(str(i), f"Chapter {i}") for i in range(1, num_chapters + 1)]

        # Front matter
        year = datetime.now().year
        front = (
            f"# {title}: The Complete Story\n\n"
            f"*By J.K. Blaze*\n\n"
            f"---\n\n"
            f"*Book 2 — The Complete Resolution*\n\n"
            f"*Copyright © {year} WheellsVerse Publishing. All rights reserved.*\n\n"
            f"---\n\n"
            f"## Previously...\n\n"
            f"*{cliffhanger}*\n\n"
            f"*Volume 2 begins where the darkness ended.*\n\n"
            f"---\n\n"
        )

        chapters = [front]
        story_context = f"Vol 1 ended: {cliffhanger}. Characters: {', '.join(char_names)}."

        for idx, (ch_num, ch_title) in enumerate(chapter_lines):
            ch_title = ch_title.strip()
            is_last = (idx == len(chapter_lines) - 1)

            if is_last:
                special = (
                    "FINAL CHAPTER — write THE END explicitly at the close. "
                    "Resolve every remaining thread. Give the reader catharsis. "
                    "End with a quiet, earned moment that resonates emotionally."
                )
            elif idx == len(chapter_lines) - 2:
                special = "PENULTIMATE CHAPTER — the climax. Maximum tension. Set up the finale."
            else:
                special = "End on a hook that makes it impossible not to read the next chapter."

            ch_prompt = (
                f"Write Chapter {ch_num}: '{ch_title}' of '{title}: The Complete Story' ({genre}).\n\n"
                f"PROTAGONIST: {protagonist} (DO NOT change this name)\n"
                f"ALL CHARACTERS: {', '.join(char_names)}\n"
                f"WORLD RULES: {json.dumps(world_rules[:3])}\n"
                f"Story so far: {story_context[-800:]}\n\n"
                f"INSTRUCTIONS: {special}\n\n"
                f"Rules:\n"
                f"- Minimum 1,200 words. Write the FULL chapter.\n"
                f"- Use ONLY the character names listed above — do NOT invent new characters.\n"
                f"- Show don't tell. Strong verbs. Natural dialogue.\n\n"
                f"Format:\n## Chapter {ch_num}: {ch_title}\n\n[full chapter]\n\n---\n"
            )

            chapter_text = self.claude(ch_prompt, max_tokens=4000)
            chapters.append(chapter_text)
            story_context += f" Ch{ch_num}: " + chapter_text[:250]
            time.sleep(0.3)

        # Back matter
        back = (
            "\n\n---\n\n**THE END**\n\n"
            f"---\n\n"
            f"### About the Author\n\n"
            f"J.K. Blaze is a {genre} fiction author published by WheellsVerse. "
            f"Discover more at wheellsverse.blog.\n"
        )
        chapters.append(back)

        return "\n\n".join(chapters)

    def _revise_sequel(self, manuscript: str, revision_notes: str, genre: str, title: str) -> str:
        """Apply revision notes to improve a rejected manuscript."""
        words = manuscript.split()
        # Focus on the areas most likely to need revision (ending)
        ending = " ".join(words[-5000:]) if len(words) > 5000 else manuscript

        prompt = (
            f"Revise the ending of this {genre} manuscript based on the QC feedback.\n\n"
            f"Title: {title}\n\n"
            f"QC REVISION NOTES:\n{revision_notes[:2000]}\n\n"
            f"CURRENT ENDING (last ~5000 words):\n{ending}\n\n"
            f"Rewrite ONLY the ending to address the specific issues above.\n"
            f"Keep all character names exactly as they are.\n"
            f"Return the revised ending only (not the whole book)."
        )
        try:
            revised_ending = self.claude(prompt, max_tokens=6000)
            # Replace the last portion
            if revised_ending and len(revised_ending.split()) > 500:
                return " ".join(words[:-4000]) + "\n\n" + revised_ending
        except Exception as e:
            self.logger.warning("Revision failed: %s", e)
        return manuscript

    # ── Complete all incomplete volumes ───────────────────────────────────────

    def complete_all_incomplete(self) -> dict:
        """Scan and complete all incomplete manuscripts."""
        scan = self.scan_all_manuscripts()
        incomplete = scan.get("incomplete", [])

        if not incomplete:
            self.logger.info("No incomplete manuscripts found.")
            return {"completed": [], "message": "No incomplete manuscripts found"}

        self.logger.info("Found %d incomplete manuscripts to complete", len(incomplete))
        completed = []
        failed = []

        for item in incomplete:
            self.logger.info("Completing: %s (%s)", item["title"], item["genre"])
            try:
                result = self.complete_volume(item["file"], item["genre"])
                completed.append(result)
                self.logger.info("✅ Completed: %s", item["title"])
                time.sleep(2)  # Brief pause between books
            except Exception as e:
                self.logger.error("❌ Failed to complete %s: %s", item["title"], e)
                failed.append({"title": item["title"], "error": str(e)})

        return {"completed": completed, "failed": failed,
                "total_completed": len(completed), "total_failed": len(failed)}

    # ── Check all series continuity ───────────────────────────────────────────

    def check_all_series_continuity(self) -> dict:
        """
        Find all multi-volume series and run continuity checks on each.
        """
        from core.continuity_engine import ContinuityEngine
        engine = ContinuityEngine()
        results = []

        # Look for vol2 files that correspond to vol1 files
        for genre in GENRES:
            genre_dir = OUTPUTS_DIR / genre
            if not genre_dir.exists():
                continue

            all_mds = list(genre_dir.glob("*.md"))
            # Find files with vol2/volume_2 in name
            vol2_files = [f for f in all_mds if re.search(r"vol2|volume_2|_v2_", f.name, re.I)]

            for vol2_path in vol2_files:
                # Try to find corresponding vol1
                base_name = re.sub(r"_vol2.*|_volume_2.*|_v2_.*", "", vol2_path.stem)
                vol1_candidates = [f for f in all_mds
                                   if base_name.lower() in f.name.lower()
                                   and f != vol2_path
                                   and not re.search(r"vol2|volume_2|_v2_", f.name, re.I)]

                if not vol1_candidates:
                    continue

                vol1_path = max(vol1_candidates, key=lambda f: f.stat().st_mtime)
                self.logger.info("Checking continuity: %s → %s", vol1_path.name, vol2_path.name)

                try:
                    vol1_text = vol1_path.read_text(encoding="utf-8", errors="replace")
                    vol2_text = vol2_path.read_text(encoding="utf-8", errors="replace")

                    bible = engine.extract_story_bible(vol1_text, vol1_path.stem)
                    comparison = engine.compare_volumes(bible, vol2_text)
                    report = engine.generate_continuity_report(comparison)

                    results.append({
                        "genre": genre,
                        "vol1": vol1_path.name,
                        "vol2": vol2_path.name,
                        "continuity_score": comparison.get("continuity_score", 0),
                        "passed": comparison.get("passed", False),
                        "verdict": comparison.get("verdict", "FAIL"),
                        "issues": comparison.get("issues", []),
                        "report": report,
                    })

                    status = "✅" if comparison.get("passed") else "❌"
                    print(f"  {status} [{genre}] {vol1_path.name} → {vol2_path.name}")
                    print(f"     Score: {comparison.get('continuity_score', 0)}/100")
                    if comparison.get("issues"):
                        for issue in comparison["issues"][:3]:
                            print(f"     • {issue}")

                except Exception as e:
                    self.logger.error("Continuity check failed for %s: %s", vol2_path.name, e)
                    results.append({"genre": genre, "vol1": vol1_path.name,
                                    "vol2": vol2_path.name, "error": str(e)})

        if not results:
            print("No multi-volume series found in outputs/books/")

        return {"series_checked": len(results), "results": results}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="VolumeCompletionBot — find and complete incomplete stories")
    p.add_argument("--action", default="scan",
                   choices=["scan", "complete_one", "complete_all", "check_series"])
    p.add_argument("--file", help="Path to manuscript (for complete_one)")
    p.add_argument("--genre", default="mystery", help="Genre (for complete_one)")
    args = p.parse_args()

    bot = VolumeCompletionBot()
    result = bot.run(action=args.action, file=args.file, genre=args.genre)

    if args.action == "scan":
        pass  # Already printed
    else:
        print(json.dumps(result, indent=2, default=str))
