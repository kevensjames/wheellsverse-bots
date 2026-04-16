#!/usr/bin/env python3
"""
bots/books/write_bestseller.py
─────────────────────────────────────────────────────────────────────────────
Best-seller quality single book writer.
Writes a full novel (20 chapters × 2,500+ words = ~50,000 words), runs it
through QC and Publisher Engine, and queues it for KDP autopublish.

Usage:
  python bots/books/write_bestseller.py              # auto-picks genre + idea
  python bots/books/write_bestseller.py --genre mystery
  python bots/books/write_bestseller.py --genre fantasy --title "The Iron Crown"
─────────────────────────────────────────────────────────────────────────────
"""
import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.base_bot import BaseBot

# ── Genre catalogue ───────────────────────────────────────────────────────────
GENRE_IDEAS = {
    "mystery": [
        {"title": "The Last Witness", "logline": "The only witness to a senator's murder is an AI — and someone is trying to erase its memory before trial.", "series": "standalone"},
        {"title": "Cold Case Requiem", "logline": "A retired detective receives a vinyl record containing a confession to a 30-year-old murder — but the confessor died last week.", "series": "standalone"},
        {"title": "The Poisoner's Almanac", "logline": "A botanist inherits her grandmother's apothecary shop and finds a coded ledger listing every unsolved death in the county going back fifty years.", "series": "standalone"},
    ],
    "thriller": [
        {"title": "The Forty-Eight Hour Protocol", "logline": "A crisis negotiator has 48 hours to save hostages inside a sovereign tech campus — before her own agency assassinates everyone to bury a secret.", "series": "standalone"},
        {"title": "Zero Extraction", "logline": "A burned CIA officer must retrieve a defector from a city that no longer exists on any map — guided only by a six-year-old's drawings.", "series": "standalone"},
    ],
    "fantasy": [
        {"title": "The Cartographer of Dying Cities", "logline": "A mapmaker discovers that every city she draws disappears within a year — and someone has been commissioning her maps for decades.", "series": "standalone"},
        {"title": "The Glass King's Bargain", "logline": "A thief steals a cursed crown and must now rule a kingdom she doesn't want while the true heir hunts her across three continents.", "series": "standalone"},
    ],
    "sci_fi": [
        {"title": "After the Signal", "logline": "Humanity receives a mathematically perfect alien message — and inside it is a warning about Earth's government that's already 200 years out of date.", "series": "standalone"},
        {"title": "The Memory Merchants", "logline": "In a future where memories can be bought and sold, a debt collector repossessing stolen memories discovers she's been living someone else's life.", "series": "standalone"},
    ],
    "romance": [
        {"title": "The Architecture of Almost", "logline": "Two rival architects forced to co-design a memorial discover that the building they're fighting over was commissioned by the person they both loved and lost.", "series": "standalone"},
    ],
    "adventure": [
        {"title": "The Undiscovered Country", "logline": "An explorer mapping uncharted territory stumbles upon a civilization that has been deliberately hidden from the modern world — and will kill to stay that way.", "series": "standalone"},
    ],
    "horror": [
        {"title": "The Tenant in Room Zero", "logline": "A property manager discovers that every building she's ever managed has a room that doesn't appear on the blueprints — and something lives in each one.", "series": "standalone"},
    ],
    "historical": [
        {"title": "The Code Breaker's Daughter", "logline": "During WWII, a woman working in secret intelligence discovers that the enemy cipher she's been cracking was written by her missing father.", "series": "standalone"},
    ],
    "true_crime": [
        {"title": "The Gentleman Arsonist", "logline": "A journalist investigating a series of historic building fires realizes the arsonist is methodically erasing evidence of a real estate conspiracy that goes back to the founding of the city.", "series": "standalone"},
    ],
    "self_help": [
        {"title": "The Clarity Protocol", "logline": "A performance scientist distills seven years of research on high-achievers into a simple daily system for deciding what matters — and eliminating everything that doesn't.", "series": "standalone"},
    ],
}

SYSTEM_PROMPTS = {
    "mystery":    "You are a bestselling mystery novelist in the tradition of Tana French and Gillian Flynn. Your prose is atmospheric, your characters psychologically complex, your plots airtight.",
    "thriller":   "You are a bestselling thriller writer in the tradition of Lee Child and Jason Bourne. Relentless pacing, credible tradecraft, visceral action, moral ambiguity.",
    "fantasy":    "You are a bestselling fantasy author in the tradition of Brandon Sanderson and Patrick Rothfuss. Rich world-building, intricate magic systems, epic scope, emotional depth.",
    "sci_fi":     "You are a bestselling sci-fi author in the tradition of Andy Weir and N.K. Jemisin. Hard concepts made human, diverse characters, ideas that change how readers see the world.",
    "romance":    "You are a bestselling romance author in the tradition of Nora Roberts and Emily Henry. Emotionally intelligent, witty, deeply satisfying arcs with real stakes beyond the central relationship.",
    "adventure":  "You are a bestselling adventure novelist in the tradition of Michael Crichton and Andy Weir. Immersive settings, expert knowledge worn lightly, relentless forward momentum.",
    "horror":     "You are a bestselling horror author in the tradition of Stephen King and Shirley Jackson. Psychological dread, deeply human characters, terror that comes from the real as much as the supernatural.",
    "historical": "You are a bestselling historical novelist in the tradition of Ken Follett and Hilary Mantel. Impeccably researched, immersive period voice, characters who feel entirely real.",
    "true_crime": "You are a bestselling true crime writer in the tradition of Erik Larson. Narrative nonfiction that reads like a thriller, meticulous research, moral clarity.",
    "self_help":  "You are a bestselling self-help author in the tradition of James Clear and Cal Newport. Evidence-based, practical, transformative. No fluff. Every page earns its place.",
}


class BestsellerWriter(BaseBot):
    """Writes a full-length, best-seller quality novel in a single run."""

    def __init__(self, genre: str = "mystery"):
        super().__init__("bestseller_writer", "books")
        self.genre = genre
        self.sys_prompt = SYSTEM_PROMPTS.get(genre, SYSTEM_PROMPTS["mystery"])
        self.output_dir = ROOT / "outputs" / "books" / genre
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────

    def run(self, action: str = "write", **kwargs) -> dict:
        return self.write(
            title=kwargs.get("title", ""),
            logline=kwargs.get("logline", ""),
            num_chapters=kwargs.get("num_chapters", 20),
        )

    def write(self, title: str = "", logline: str = "", num_chapters: int = 20) -> dict:
        # Pick idea if not provided
        ideas = GENRE_IDEAS.get(self.genre, GENRE_IDEAS["mystery"])
        idea = ideas[datetime.now().day % len(ideas)]
        title   = title   or idea["title"]
        logline = logline or idea["logline"]
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.logger.info("=" * 60)
        self.logger.info("BESTSELLER WRITER — '%s' (%s)", title, self.genre)
        self.logger.info("Logline: %s", logline)
        self.logger.info("Target: %d chapters × 2,500+ words ≈ 50,000 words", num_chapters)
        self.logger.info("=" * 60)

        # ── Phase 1: Deep outline ─────────────────────────────────────────────
        self.logger.info("[1/4] Generating deep outline…")
        outline_raw = self._build_outline(title, logline, num_chapters)

        # ── Phase 1b: Character conflict check ────────────────────────────────
        try:
            from core.character_registry import get_character_registry
            cr = get_character_registry()
            proposed = re.findall(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', outline_raw)
            expanded = set()
            for ph in proposed:
                parts = ph.split()
                for i in range(len(parts) - 1):
                    expanded.add(parts[i] + " " + parts[i+1])
                expanded.add(ph)
            conflicts = cr.check_conflicts(list(expanded), series_name=title)
            if conflicts:
                self.logger.warning("Character conflicts: %s — regenerating outline", conflicts)
                outline_raw = self._build_outline(
                    title, logline, num_chapters,
                    avoid_names=conflicts
                )
        except Exception as e:
            self.logger.debug("Registry check skipped: %s", e)

        # Parse chapter plan from outline
        chapters_plan = self._parse_chapters(outline_raw, num_chapters, title)
        self.logger.info("Outline ready: %d chapters planned", len(chapters_plan))

        # ── Phase 2: Write every chapter ─────────────────────────────────────
        self.logger.info("[2/4] Writing %d chapters…", len(chapters_plan))
        manuscript_parts = [
            f"# {title}\n\n*By J.K. Blaze*\n\n---\n\n"
            f"*Copyright © {datetime.now().year} WheellsVerse Publishing. All rights reserved.*\n\n---\n\n"
        ]

        story_so_far = logline
        total_words  = 0

        for idx, ch in enumerate(chapters_plan):
            ch_num   = ch["num"]
            ch_title = ch["title"]
            is_first = idx == 0
            is_last  = idx == len(chapters_plan) - 1

            self.logger.info("  Writing ch %02d/%d: %s", ch_num, len(chapters_plan), ch_title)
            t0 = time.time()

            ch_text = self._write_chapter(
                title, ch_num, ch_title, ch.get("beats", ""),
                story_so_far, is_first, is_last,
            )
            elapsed = round(time.time() - t0, 1)

            wc = len(ch_text.split())
            total_words += wc
            self.logger.info("    ch %02d done: %d words in %.1fs", ch_num, wc, elapsed)

            manuscript_parts.append(ch_text)
            # Rolling context: last chapter summary for continuity
            story_so_far = story_so_far[-800:] + f" [Ch{ch_num}: {ch_text[:300]}]"

        # ── Phase 3: Verify & close ───────────────────────────────────────────
        self.logger.info("[3/4] Assembling and verifying manuscript…")
        manuscript = "\n\n".join(manuscript_parts)

        # Ensure proper ending
        if not self._has_proper_ending(manuscript):
            self.logger.warning("No ending marker — writing closing + THE END")
            closing = self.claude(
                f"Write a final closing paragraph (200 words) for '{title}' ({self.genre}) "
                f"that brings emotional resolution, then end with:\n\n**THE END**\n\nAbout the Author\n\nJ.K. Blaze is a prolific fiction author published by WheellsVerse.\n\n"
                f"Last 800 words of the story:\n{manuscript[-3200:]}",
                system=self.sys_prompt, max_tokens=500,
            )
            manuscript = manuscript.rstrip() + "\n\n" + closing.strip()
        else:
            manuscript = manuscript.rstrip() + "\n\n---\n\n### About the Author\n\nJ.K. Blaze is a prolific author of " + self.genre + " fiction published by WheellsVerse. To discover more books, visit wheellsverse.blog.\n"

        final_wc = len(manuscript.split())
        self.logger.info("Final manuscript: %d words", final_wc)

        # Save
        safe = title.lower().replace(" ", "_").replace("'", "")[:40]
        ms_path = self.output_dir / f"bs_{safe}_{ts}.md"
        ms_path.write_text(manuscript, encoding="utf-8")
        self.logger.info("Manuscript saved: %s", ms_path.name)

        # ── Phase 4: Full pipeline — QC → Publisher Engine → KDP queue ────────
        self.logger.info("[4/4] Running QC → Publisher Engine → KDP queue…")
        pipeline_result = self._run_pipeline(manuscript, title, ms_path, ts)

        result = {
            "title":           title,
            "genre":           self.genre,
            "word_count":      final_wc,
            "chapters":        len(chapters_plan),
            "manuscript_path": str(ms_path),
            "ts":              ts,
            **pipeline_result,
        }

        # Telegram
        try:
            from core.telegram import notify
            qc_score = pipeline_result.get("qc_result", {}).get("overall_score") or pipeline_result.get("qc_result", {}).get("score", "?")
            queued   = pipeline_result.get("autopilot_queued", False)
            notify(
                f"📚 Best-Seller Written!\n"
                f"📖 {title}\n"
                f"📊 {final_wc:,} words · {len(chapters_plan)} chapters\n"
                f"🔬 QC score: {qc_score}/100\n"
                f"{'✅ Queued for KDP autopublish' if queued else '⚠️ Sent to rewrite queue'}"
            )
        except Exception:
            pass

        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_outline(self, title: str, logline: str, num_chapters: int,
                       avoid_names: list = None) -> str:
        avoid = ""
        if avoid_names:
            avoid = f"\n\nCRITICAL — DO NOT use these character names (already used in other books): {', '.join(avoid_names)}. Invent completely different names."

        prompt = (
            f"You are outlining a full-length {self.genre} novel.\n\n"
            f"Title: {title}\n"
            f"Logline: {logline}\n"
            f"Target: {num_chapters} chapters, ~50,000 words total{avoid}\n\n"
            "Deliver a COMPLETE novel blueprint:\n\n"
            "1. CAST OF CHARACTERS (5-8 people)\n"
            "   For each: Full name · Role · Age · Core trait · Fatal flaw · Arc summary\n\n"
            "2. THREE-ACT STRUCTURE\n"
            "   Act 1 (ch 1-5): Setup + Inciting Incident\n"
            "   Act 2A (ch 6-12): Rising complications + Midpoint reversal\n"
            "   Act 2B (ch 13-17): Dark night of the soul + All is lost\n"
            "   Act 3 (ch 18-20): Climax + Resolution + Denouement\n\n"
            "3. CHAPTER-BY-CHAPTER BREAKDOWN\n"
            f"   For EACH of the {num_chapters} chapters:\n"
            "   CHAPTER N: [Title] | POV: [Character]\n"
            "   BEATS: [3-4 specific things that happen]\n"
            "   ENDS ON: [exact hook/revelation/cliffhanger]\n"
            "   TARGET: 2,500 words\n\n"
            "4. CENTRAL MYSTERY/CONFLICT (one paragraph — what is the reader desperate to know?)\n"
            "5. EMOTIONAL THROUGHLINE (what does the protagonist learn about themselves?)\n"
        )
        return self.claude(prompt, system=self.sys_prompt, max_tokens=6000)

    def _parse_chapters(self, outline: str, num_chapters: int, title: str) -> list:
        chapters = []
        lines = outline.splitlines()
        current = None
        for line in lines:
            m = re.match(r'CHAPTER\s+(\d+):\s*(.+?)(?:\s*\|\s*POV.*)?$', line, re.IGNORECASE)
            if m:
                if current:
                    chapters.append(current)
                current = {"num": int(m.group(1)), "title": m.group(2).strip(), "beats": ""}
            elif current and line.strip().startswith("BEATS:"):
                current["beats"] = line.split("BEATS:", 1)[-1].strip()
            elif current and line.strip().startswith("ENDS ON:"):
                current["beats"] += " ENDS: " + line.split("ENDS ON:", 1)[-1].strip()
        if current:
            chapters.append(current)

        # Fallback if parsing found nothing
        if not chapters:
            chapters = [{"num": i+1, "title": f"Chapter {i+1}", "beats": ""} for i in range(num_chapters)]

        return chapters[:num_chapters]

    def _write_chapter(self, title: str, ch_num: int, ch_title: str, beats: str,
                       story_so_far: str, is_first: bool, is_last: bool) -> str:
        position_note = ""
        if is_first:
            position_note = (
                "OPENING CHAPTER RULES:\n"
                "- First sentence must hook the reader immediately — no throat-clearing\n"
                "- Drop the reader into a scene already in motion\n"
                "- Establish voice, tone, and stakes within the first paragraph\n"
            )
        elif is_last:
            position_note = (
                "FINAL CHAPTER RULES:\n"
                "- Resolve every major plot thread and character arc\n"
                "- Deliver the emotional payoff the reader has been waiting for\n"
                "- End with a final line that resonates and closes the book with weight\n"
                "- After the final scene, write '**THE END**' on its own line\n"
            )
        else:
            position_note = (
                "MID-STORY RULES:\n"
                "- Begin in motion — reference the previous chapter's tension\n"
                "- Raise the stakes OR deepen character by the end\n"
                "- Final line must create urgency to read the next chapter\n"
            )

        prompt = (
            f"Write Chapter {ch_num} of '{title}' — a {self.genre} novel.\n\n"
            f"Chapter title: {ch_title}\n"
            f"Chapter beats: {beats or 'Follow naturally from the story so far'}\n\n"
            f"Story context (what has happened so far):\n{story_so_far[-1200:]}\n\n"
            f"{position_note}\n"
            "WRITING STANDARDS:\n"
            "- MINIMUM 2,500 words — write a COMPLETE, full chapter, not a summary\n"
            "- Show don't tell: concrete sensory detail over abstract description\n"
            "- Dialogue must reveal character AND advance plot simultaneously\n"
            "- Vary sentence rhythm — short punchy sentences for action/tension, longer for reflection\n"
            "- Every scene must change something: a relationship, a belief, a situation\n"
            "- No filler sentences. Every word earns its place.\n\n"
            "FORMAT:\n"
            f"## Chapter {ch_num}: {ch_title}\n\n"
            "[chapter content — minimum 2,500 words]"
        )
        return self.claude(prompt, system=self.sys_prompt, max_tokens=5000)

    def _has_proper_ending(self, text: str) -> bool:
        tail = text[-600:].lower()
        markers = ["the end", "**the end**", "about the author", "epilogue", "acknowledgment"]
        if any(m in tail for m in markers):
            return True
        stripped = text.rstrip()
        return bool(stripped) and stripped[-1] in ".!?\"'"

    def _run_pipeline(self, manuscript: str, title: str, ms_path: Path, ts: str) -> dict:
        result = {}
        # QC
        try:
            from core.literary_qc import LiteraryQCAgent
            self.logger.info("  Running Literary QC…")
            qc = LiteraryQCAgent()
            qc_result = qc.full_book_analysis(
                manuscript, title,
                genre=self.genre,
                manuscript_path=str(ms_path),
            )
            result["qc_result"]        = qc_result
            result["autopilot_queued"] = qc_result.get("autopilot_queued", False)
            result["rewrite_queued"]   = qc_result.get("rewrite_needed", False)
            self.logger.info(
                "  QC: %s (score %s) | approved=%s",
                qc_result.get("verdict", "?"),
                qc_result.get("overall_score", "?"),
                qc_result.get("approved", False),
            )
        except Exception as e:
            self.logger.warning("QC failed (non-fatal): %s", e)
            result["qc_result"] = {}

        # Publisher Engine (only if approved)
        if result.get("qc_result", {}).get("approved", False):
            try:
                from bots.books.publisher_engine.pipeline import PublisherEnginePipeline
                self.logger.info("  Running Publisher Engine (7 agents)…")
                pe = PublisherEnginePipeline()
                pe_result = pe.process(manuscript, title, self.genre)
                result["publisher_engine_result"] = {
                    k: v for k, v in pe_result.items()
                    if k not in ("agents",) and not (isinstance(v, str) and len(v) > 500)
                }
                self.logger.info(
                    "  Publisher Engine: ready_to_publish=%s",
                    pe_result.get("ready_to_publish", False),
                )
            except Exception as e:
                self.logger.warning("Publisher Engine failed (non-fatal): %s", e)
        else:
            self.logger.info("  QC not approved — skipping Publisher Engine")

        return result


# ── Daily scheduler integration ───────────────────────────────────────────────

def run_daily_bestseller(genre: str = None):
    """Write one best-seller quality book per day, rotating genres."""
    genres = list(GENRE_IDEAS.keys())
    # Pick today's genre based on day-of-year rotation
    if not genre:
        genre = genres[datetime.now().timetuple().tm_yday % len(genres)]

    print(f"\n📚 Daily Best-Seller — {datetime.now().strftime('%A, %B %d, %Y')}")
    print(f"Genre today: {genre.upper()}\n")

    writer = BestsellerWriter(genre=genre)
    result = writer.write()

    print(f"\n{'='*60}")
    print(f"  COMPLETE: {result['title']}")
    print(f"  Words:    {result['word_count']:,}")
    print(f"  Chapters: {result['chapters']}")
    qc = result.get("qc_result", {})
    print(f"  QC:       {qc.get('verdict','?')} (score {qc.get('overall_score') or qc.get('score','?')})")
    print(f"  Queued:   {'✅ KDP autopublish' if result.get('autopilot_queued') else '⚠️ rewrite queue'}")
    print(f"  Path:     {result['manuscript_path']}")
    print(f"{'='*60}\n")

    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Write one best-seller quality book and publish")
    p.add_argument("--genre",    default="", help="Genre (default: auto-rotate by day)")
    p.add_argument("--title",    default="", help="Override book title")
    p.add_argument("--chapters", type=int, default=20, help="Number of chapters (default: 20)")
    args = p.parse_args()

    if args.title or args.genre:
        genre  = args.genre or "mystery"
        writer = BestsellerWriter(genre=genre)
        result = writer.write(title=args.title, num_chapters=args.chapters)
        qc = result.get("qc_result", {})
        print(f"\n✅ {result['title']} — {result['word_count']:,} words")
        print(f"   QC: {qc.get('verdict','?')} ({qc.get('overall_score') or qc.get('score','?')}/100)")
        print(f"   {'✅ Queued for KDP' if result.get('autopilot_queued') else '⚠️ Sent to rewrite queue'}")
    else:
        run_daily_bestseller()
