#!/usr/bin/env python3
"""
Bot #47 — Book Chapter Writer & Outline Builder
Category: Writing
Purpose: Write complete book chapters or full chapter outlines with section breakdowns,
         scene descriptions, and voice-consistent prose for non-fiction and fiction.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

BOOK_GENRES = {
    "nonfiction_business": "Business/entrepreneurship non-fiction -- practical, data-backed, story-driven",
    "nonfiction_self_help": "Self-help/personal development -- motivational, actionable, relatable",
    "how_to_guide": "How-to/instructional -- step-by-step, practical, outcome-focused",
    "memoir": "Memoir/personal story -- narrative, reflective, emotionally resonant",
    "fiction_thriller": "Thriller fiction -- tension-driven, fast-paced, cliffhangers",
    "fiction_scifi": "Science fiction -- world-building, conceptual, character-driven",
}

OUTPUT_MODES = {
    "chapter_outline": "Detailed chapter outline with section headings and key points",
    "full_chapter": "Complete written chapter with full prose",
    "book_outline": "Full book outline with all chapters and chapter summaries",
    "opening_hook": "First 3-5 paragraphs optimized to hook the reader",
    "chapter_summary": "Summary + key takeaways from an existing chapter",
}


class BookWriterBot(BaseBot):

    def __init__(self):
        super().__init__("47_book_writer", "writing")

    def run(self, book_title: str = None, chapter_title: str = None,
            genre: str = None, target_audience: str = None,
            output_mode: str = None, **kwargs):

        cfg = self.config
        book_title = book_title or cfg.get("book_title", "The AI Entrepreneur: Building Automated Businesses")
        chapter_title = chapter_title or cfg.get("chapter_title", "Chapter 1: Why Automation Changes Everything")
        genre = genre or cfg.get("genre", "nonfiction_business")
        target_audience = target_audience or cfg.get("target_audience",
            "entrepreneurs and business owners who want to automate their operations")
        output_mode = output_mode or cfg.get("output_mode", "full_chapter")

        genre_desc = BOOK_GENRES.get(genre, genre)
        mode_desc = OUTPUT_MODES.get(output_mode, output_mode)

        self.logger.info(f"Writing book content: {output_mode} for '{chapter_title}'")

        system = (
            "You are a professional ghostwriter and published author who has written bestselling "
            "books across business, self-help, and fiction genres. You write with a distinct voice "
            "that matches the genre -- business books have authority and insight, self-help has "
            "warmth and stories, fiction has momentum and vivid scenes. You understand narrative "
            "arc, chapter structure, and pacing. You know that every chapter needs a hook, "
            "a promise, developed content, and a satisfying close that propels the reader forward. "
            "You never write filler -- every sentence earns its place."
        )

        # Pre-compute the content sections to avoid nested triple-quoted f-strings (Python 3.11)
        book_context_header = (
            "## BOOK CONTEXT (if full chapter or outline)"
            if output_mode in ("book_outline", "chapter_outline") else ""
        )

        if output_mode == "book_outline":
            mode_section = "## FULL BOOK OUTLINE"
        else:
            chapter_header = f"## {output_mode.upper().replace('_', ' ')}\n\n"
            meta = (
                "### Chapter Metadata\n"
                "- **Chapter number:** [N of estimated total]\n"
                "- **Chapter purpose:** [What this chapter accomplishes in the book's arc]\n"
                "- **Core promise:** [What the reader will know/feel/be able to do after reading]\n"
                "- **Key tension:** [The problem or question this chapter sets up and resolves]\n"
                "- **Estimated read time:** [X minutes]\n\n"
                "---\n\n"
            )
            if output_mode == "chapter_outline":
                body = (
                    "### CHAPTER OUTLINE\n\n"
                    "[Detailed section-by-section breakdown with H2/H3 headings, key points per "
                    "section, and brief notes on examples or stories to include. Include: opening "
                    "hook, 4-6 main sections, closing and transition to next chapter.]"
                )
            else:
                body = (
                    "### FULL CHAPTER\n\n"
                    f'[Write the complete chapter for "{chapter_title}" from the book "{book_title}".\n\n'
                    "Guidelines:\n"
                    "- Open with a story, quote, surprising fact, or bold claim\n"
                    "- Develop the core idea with examples, data, and real scenarios\n"
                    f"- Write for {target_audience} - at their level, using their language\n"
                    f"- Genre tone: {genre_desc}\n"
                    "- Target: 2,500-4,000 words\n"
                    "- End with a clear takeaway, summary, and bridge to the next chapter\n"
                    "- Use subheadings (H2/H3) to organize content\n"
                    "- Include call-out boxes, key quotes, or action steps where appropriate\n\n"
                    "Write the full chapter now:]"
                )
            end_matter = (
                "\n\n---\n\n"
                "### END MATTER\n\n"
                "**Chapter Summary (100 words):** [Condensed takeaways]\n"
                "**Key Quotes from this Chapter:**\n"
                '1. "[Quote 1]"\n'
                '2. "[Quote 2]"\n'
                '3. "[Quote 3]"\n\n'
                "**Action Steps for Readers:**\n"
                "1. [Step 1]\n"
                "2. [Step 2]\n"
                "3. [Step 3]\n\n"
                "**Bridge to Next Chapter:**\n"
                "[Last 2-3 sentences that create anticipation for what comes next]"
            )
            mode_section = chapter_header + meta + body + end_matter

        prompt = f"""Write {output_mode} for:

BOOK TITLE: {book_title}
CHAPTER: {chapter_title}
GENRE: {genre} -- {genre_desc}
TARGET AUDIENCE: {target_audience}
OUTPUT: {output_mode} -- {mode_desc}
BRAND VOICE: WheellsVerse -- practical, direct, entrepreneurial, optimistic about AI's potential

---

{book_context_header}

{mode_section}"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3500)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_chapter = self.slugify(chapter_title, 25)

        output = f"""# Book Writing: {chapter_title}
**Book:** {book_title}
**Genre:** {genre}
**Output Mode:** {output_mode}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Book Writer Bot*
"""
        path = self.save_output(output, f"book_{safe_chapter}_{ts}.md", ext="md")
        self.logger.info(f"Book content saved -> {path}")
        return {"file": str(path), "book": book_title, "chapter": chapter_title}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Book Chapter Writer & Outline Builder")
    parser.add_argument("--book", type=str, default=None)
    parser.add_argument("--chapter", type=str, default=None)
    parser.add_argument("--genre", type=str, default="nonfiction_business",
                        choices=list(BOOK_GENRES.keys()))
    parser.add_argument("--audience", type=str, default=None)
    parser.add_argument("--mode", type=str, default="full_chapter",
                        choices=list(OUTPUT_MODES.keys()))
    args = parser.parse_args()
    bot = BookWriterBot()
    result = bot.execute(book_title=args.book, chapter_title=args.chapter,
                         genre=args.genre, target_audience=args.audience,
                         output_mode=args.mode)
    print(f"\n✅ Book Content: {result['file']}")
