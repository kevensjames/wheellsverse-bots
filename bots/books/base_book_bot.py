#!/usr/bin/env python3
"""
Base Book Bot — shared logic for all WheellsVerse book-writing bots.
All genre bots inherit from this class.

Publishing targets:
  - Amazon KDP (Kindle): 70% royalty on $2.99-$9.99 books
  - Gumroad: 97% royalty (direct sales)
  - Payhip: 95% royalty
  - WheellsVerse Store: direct PDF download

Revenue model per book:
  - Children's book: $3.99 KDP / $7 direct → 10 sales/day = $39-$70/day
  - Short story (15K words): $2.99 KDP → 20 sales/day = ~$40/day
  - Full novel (50K words): $4.99-$9.99 → exponential after reviews
  - Series: first book free → hook readers → sell sequels
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.base_bot import BaseBot

GENRE_OUTPUT_MAP = {
    "childrens":   "childrens",
    "mystery":     "mystery",
    "adventure":   "adventure",
    "historical":  "historical",
    "self_help":   "self_help",
    "romance":     "romance",
    "sci_fi":      "sci_fi",
    "fantasy":     "fantasy",
    "horror":      "horror",
    "true_crime":  "true_crime",
}

PRICE_MAP = {
    "childrens": ("$3.99", "$7.00"),   # KDP, direct
    "mystery": ("$2.99", "$5.00"),
    "adventure": ("$2.99", "$5.00"),
    "historical": ("$4.99", "$8.00"),
    "self_help": ("$9.99", "$17.00"),
    "romance": ("$2.99", "$5.00"),
    "sci_fi": ("$3.99", "$7.00"),
    "fantasy": ("$4.99", "$8.00"),
    "horror": ("$2.99", "$5.00"),
    "true_crime": ("$4.99", "$8.00"),
}


class BaseBookBot(BaseBot):
    """Base class for all book-writing bots."""

    GENRE = "general"
    GENRE_SYSTEM = "You are a skilled author."

    def __init__(self, bot_name: str, genre: str):
        super().__init__(bot_name, "books")
        self.genre = genre
        self.kdp_price, self.direct_price = PRICE_MAP.get(genre, ("$2.99", "$5.00"))
        self.gumroad_url = os.getenv("GUMROAD_STORE_URL", "https://gum.co/wheellsverse-store")
        self.output_dir = (
            Path(__file__).resolve().parents[2] / "outputs" / "books" / genre
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, action: str = "write", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "write")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "write":    self._write_book,
            "outline":  self._outline,
            "chapter":  self._write_chapter,
            "cover":    self._cover_brief,
            "listing":  self._kdp_listing,
            "promote":  self._promote,
            "series":   self._plan_series,
        }
        fn = actions.get(action, self._write_book)
        return fn(ts, **kwargs)

    # ── Override these in subclasses ──────────────────────────────────────────

    def _get_book_ideas(self) -> list[dict]:
        """Return list of book ideas for this genre."""
        return [{"title": "Untitled", "logline": "A story waiting to be told."}]

    def _get_system_prompt(self) -> str:
        return self.GENRE_SYSTEM

    # ── Core writing actions ──────────────────────────────────────────────────

    def _is_complete(self, text: str) -> bool:
        """Return True if the manuscript has a proper ending."""
        tail = text[-300:].lower()
        endings = ["the end", "**the end**", "— end —", "—end—", "epilogue", "afterword",
                   "about the author", "acknowledgment", "the beginning of"]
        if any(e in tail for e in endings):
            return True
        # Check that last sentence ends properly
        stripped = text.rstrip()
        return stripped and stripped[-1] in ".!?\"'"

    def _write_book(self, ts: str, **kwargs) -> dict:
        ideas = self._get_book_ideas()
        idea = ideas[datetime.now().day % len(ideas)]
        title = kwargs.get("title", idea.get("title"))
        logline = kwargs.get("logline", idea.get("logline", ""))
        length = kwargs.get("length", idea.get("length", "short"))  # short/medium/full

        # KDP-competitive word targets — minimum 10,000 for a viable ebook
        word_targets = {
            "short":  "12,000-18,000",   # novelette — ~60-80 pages
            "medium": "30,000-45,000",   # novella — ~120-180 pages
            "full":   "55,000-80,000",   # novel — ~220-320 pages
        }
        word_target = word_targets.get(length, "12,000-18,000")

        sys_prompt = self._get_system_prompt()

        # ── Step 1: Build a tight chapter outline ────────────────────────────
        self.logger.info("Pass 1/3 — generating chapter outline for: %s", title)
        outline_prompt = (
            f"You are writing a {self.genre} book.\n"
            f"Title: {title}\nLogline: {logline}\nTarget: {word_target} words\n\n"
            "Generate a CHAPTER-BY-CHAPTER outline. For each chapter provide:\n"
            "- Chapter number and title\n"
            "- POV character\n"
            "- 3-sentence summary of what happens\n"
            "- How this chapter ends (hook/cliffhanger/revelation)\n"
            "- Target word count for this chapter\n\n"
            "Aim for 10-20 chapters. The total should hit the word target.\n"
            "Format each chapter as:\n"
            "CHAPTER N: [Title] | [word count]\n"
            "POV: [character]\n"
            "Summary: [3 sentences]\n"
            "Ends on: [hook]\n"
        )
        outline_raw = self.claude(outline_prompt, system=sys_prompt, max_tokens=4000)

        # ── Step 2: Write each chapter based on outline ──────────────────────
        self.logger.info("Pass 2/3 — writing full manuscript chapter by chapter")
        chapters = []

        # Parse chapter titles from outline
        import re
        chapter_lines = re.findall(r"CHAPTER\s+(\d+):\s*([^\n|]+)", outline_raw, re.IGNORECASE)
        if not chapter_lines:
            chapter_lines = [(str(i), f"Chapter {i}") for i in range(1, 13)]

        # Front matter
        author_name = "J.K. Blaze"  # pen name
        front_matter = (
            f"# {title}\n\n"
            f"*By {author_name}*\n\n"
            f"---\n\n"
            f"*Copyright © {datetime.now().year} WheellsVerse Publishing. All rights reserved.*\n\n"
            f"---\n\n"
        )
        chapters.append(front_matter)

        # Write each chapter (batch in groups to avoid rate limits)
        story_so_far = logline
        for i, (ch_num, ch_title) in enumerate(chapter_lines):
            ch_title = ch_title.strip()
            is_first = i == 0
            is_last  = i == len(chapter_lines) - 1

            instructions = ""
            if is_first:
                instructions = "OPENING CHAPTER: Start in the middle of action or emotion — NO scene-setting paragraphs. Hook the reader within the first sentence."
            elif is_last:
                instructions = "FINAL CHAPTER: Resolve all major threads. End with emotional resonance and a brief tease of Book 2 of the series."

            ch_prompt = (
                f"You are writing Chapter {ch_num} of '{title}' ({self.genre}).\n\n"
                f"Chapter title: {ch_title}\n"
                f"Story so far: {story_so_far[:600]}\n"
                f"{instructions}\n\n"
                "Rules:\n"
                "- Minimum 1,200 words. Write a FULL, complete chapter.\n"
                "- Show don't tell. Strong verbs. Natural dialogue.\n"
                "- End on a hook, tension, or revelation that pulls reader to next chapter.\n"
                "- Include at least one moment of genuine emotion or conflict.\n\n"
                "Format:\n"
                f"## Chapter {ch_num}: {ch_title}\n\n"
                "[full chapter content]\n\n"
                "---\n"
            )
            chapter_text = self.claude(ch_prompt, system=sys_prompt, max_tokens=4000)
            chapters.append(chapter_text)
            # Update rolling summary for next chapter's context
            story_so_far = story_so_far + f" Ch{ch_num}: " + chapter_text[:200]

        # ── Step 3: Assemble + back matter ───────────────────────────────────
        self.logger.info("Pass 3/3 — assembling final manuscript")
        back_matter = (
            "\n\n---\n\n"
            "**THE END**\n\n"
            f"*{title} is Book 1 of an exciting new series. The adventure continues — "
            "stay tuned for Book 2!*\n\n"
            "---\n\n"
            f"### About the Author\n\n"
            f"J.K. Blaze is a prolific author of {self.genre} fiction published by WheellsVerse. "
            "To discover more books, visit wheellsverse.blog.\n"
        )
        result = "\n\n".join(chapters) + back_matter

        safe_title = title.lower().replace(" ", "_").replace("'", "")[:40]
        fpath = self.output_dir / f"{safe_title}_{ts}.md"
        fpath.write_text(result, encoding="utf-8")
        path = self.save_output(result, f"book_{safe_title}_{ts}.md", ext="md")

        word_count = len(result.split())
        self.logger.info("Book written: %s (%d words)", title, word_count)

        # ── Step 4: Generate cover image via DALL-E ──────────────────────────
        cover_path = None
        canva_url  = None
        try:
            cover_path = self._generate_cover_image(title, ts)
            self.logger.info("Cover generated: %s", cover_path)
        except Exception as e:
            self.logger.warning("Cover generation failed: %s", e)

        # ── Step 5: Package as KDP-ready HTML ───────────────────────────────
        html_path = None
        try:
            html_path = self._package_for_kdp(title, result, cover_path, ts)
            self.logger.info("KDP HTML package: %s", html_path)
        except Exception as e:
            self.logger.warning("HTML packaging failed: %s", e)

        # ── Step 6: Create Canva cover design ────────────────────────────────
        try:
            canva_url = self._create_canva_cover(title)
        except Exception as e:
            self.logger.warning("Canva cover creation failed: %s", e)

        try:
            from core.telegram import notify
            cover_note = f"\n🎨 Cover: {'generated' if cover_path else 'pending'}"
            notify(f"📖 Book Written!\nGenre: {self.genre.title()}\nTitle: {title}\n"
                   f"📊 {word_count:,} words{cover_note}\n📁 {fpath.name}")
        except Exception:
            pass

        return {
            "file":       str(path),
            "manuscript": str(fpath),
            "html":       str(html_path) if html_path else None,
            "cover":      str(cover_path) if cover_path else None,
            "canva_url":  canva_url,
            "word_count": word_count,
            "action":     "write",
            "title":      title,
            "genre":      self.genre,
        }

    # ── Cover + packaging helpers ─────────────────────────────────────────────

    def _generate_cover_image(self, title: str, ts: str) -> Path:
        """Generate book cover via DALL-E 3 using the existing kdp_uploader helper."""
        try:
            from core.kdp_uploader import generate_cover
            return generate_cover(title, self.genre)
        except ImportError:
            pass
        # Fallback: generate directly if kdp_uploader not available
        import openai
        import urllib.request
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        prompt = (
            f"Professional book cover for a {self.genre} book titled '{title}'. "
            "Stunning, commercially publishable design. High contrast. "
            "Title text integrated naturally. Evocative, genre-appropriate artwork. "
            "No watermarks, no borders, clean professional design."
        )
        resp = client.images.generate(
            model="dall-e-3", prompt=prompt,
            size="1024x1792",   # portrait — closest to KDP 6×9 ratio
            quality="hd", n=1,
        )
        img_url = resp.data[0].url
        covers_dir = Path(__file__).resolve().parents[2] / "outputs" / "books" / "covers" / "generated"
        covers_dir.mkdir(parents=True, exist_ok=True)
        safe = title.lower().replace(" ", "_")[:30]
        out  = covers_dir / f"cover_{self.genre}_{safe}_{ts}.png"
        urllib.request.urlretrieve(img_url, str(out))
        return out

    def _package_for_kdp(self, title: str, manuscript: str, cover_path, ts: str) -> Path:
        """Convert markdown manuscript to a clean KDP-ready HTML file with cover page."""
        safe = title.lower().replace(" ", "_").replace("'", "")[:40]
        out_dir = Path(__file__).resolve().parents[2] / "outputs" / "books" / "packaged"
        out_dir.mkdir(parents=True, exist_ok=True)
        html_path = out_dir / f"{safe}_{ts}.html"

        # Simple markdown → HTML conversion (no extra deps)
        import re as _re
        lines   = manuscript.split("\n")
        body    = []
        for line in lines:
            if line.startswith("# "):
                body.append(f'<h1 class="title">{line[2:]}</h1>')
            elif line.startswith("## "):
                body.append(f'<h2 class="chapter">{line[3:]}</h2>')
            elif line.startswith("### "):
                body.append(f'<h3>{line[4:]}</h3>')
            elif line.startswith("**") and line.endswith("**"):
                body.append(f'<p class="center"><strong>{line[2:-2]}</strong></p>')
            elif line.startswith("*") and line.endswith("*") and not line.startswith("**"):
                body.append(f'<p class="center"><em>{line[1:-1]}</em></p>')
            elif line.strip() == "---":
                body.append('<hr>')
            elif line.strip() == "":
                body.append('<p>&nbsp;</p>')
            else:
                # Bold and italic inline
                line = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
                line = _re.sub(r'\*(.+?)\*',     r'<em>\1</em>', line)
                body.append(f'<p>{line}</p>')

        cover_html = ""
        if cover_path and Path(str(cover_path)).exists():
            import base64
            with open(cover_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = Path(str(cover_path)).suffix.lstrip(".").lower() or "jpeg"
            cover_html = (
                f'<div class="cover-page">'
                f'<img src="data:image/{ext};base64,{b64}" alt="Book Cover">'
                f'</div>'
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: Georgia, 'Times New Roman', serif; max-width: 680px; margin: 0 auto;
          padding: 40px 30px; line-height: 1.8; color: #1a1a1a; font-size: 16px; }}
  h1.title {{ text-align: center; font-size: 2.2em; margin: 60px 0 10px; color: #111; }}
  h2.chapter {{ font-size: 1.4em; margin: 60px 0 20px; border-bottom: 1px solid #ddd;
                padding-bottom: 8px; color: #222; page-break-before: always; }}
  h3 {{ font-size: 1.1em; color: #444; margin: 30px 0 10px; }}
  p {{ margin: 0 0 1em; text-indent: 1.5em; }}
  p.center {{ text-align: center; text-indent: 0; }}
  hr {{ border: none; border-top: 1px solid #ccc; margin: 40px auto; width: 40%; }}
  .cover-page {{ text-align: center; page-break-after: always; margin-bottom: 60px; }}
  .cover-page img {{ max-width: 100%; max-height: 90vh; box-shadow: 0 4px 24px rgba(0,0,0,.2); }}
  @media print {{
    body {{ font-size: 12pt; }}
    h2.chapter {{ page-break-before: always; }}
  }}
</style>
</head>
<body>
{cover_html}
{''.join(body)}
</body>
</html>"""

        html_path.write_text(html, encoding="utf-8")
        return html_path

    def _create_canva_cover(self, title: str) -> str | None:
        """Create a Canva book cover design (poster format) and return the edit URL."""
        try:
            import requests as _rc
            base = os.getenv("RAILWAY_PUBLIC_URL", "http://127.0.0.1:5050").rstrip("/")
            r = _rc.post(
                f"{base}/api/canva/auto-design",
                json={"title": f"{title} — Book Cover", "platform": "poster"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                return data.get("edit_url")
        except Exception:
            pass
        return None

    def _outline(self, ts: str, **kwargs) -> dict:
        ideas = self._get_book_ideas()
        idea = ideas[datetime.now().day % len(ideas)]
        title = kwargs.get("title", idea.get("title"))
        logline = kwargs.get("logline", idea.get("logline", ""))

        prompt = f"""Create a detailed book outline for a {self.genre} book.

Title: {title}
Logline: {logline}

Deliver:
1. BACK COVER BLURB (150 words — the elevator pitch that sells the book)
2. CHARACTERS:
   - Protagonist: name, age, want vs need, fatal flaw
   - Antagonist/conflict: what opposes the protagonist
   - 2-3 supporting characters with specific roles
3. WORLD/SETTING: Time, place, atmosphere, rules
4. THREE-ACT STRUCTURE:
   Act 1 (chapters 1-5): Setup, inciting incident, first plot point
   Act 2A (chapters 6-12): Rising action, complications, midpoint
   Act 2B (chapters 13-18): Dark night, escalation, second plot point
   Act 3 (chapters 19-22): Climax, resolution, denouement
5. CHAPTER-BY-CHAPTER BREAKDOWN:
   For each chapter: title, POV, what happens, ends on:
6. SERIES POTENTIAL: How this book opens into a series

Format: professional author's outline document."""

        result = self.claude(prompt, system=self._get_system_prompt(), max_tokens=3000)
        safe_title = title.lower().replace(" ", "_")[:30]
        (self.output_dir / f"outline_{safe_title}_{ts}.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"outline_{safe_title}_{ts}.md", ext="md")
        return {"file": str(path), "action": "outline", "title": title}

    def _write_chapter(self, ts: str, **kwargs) -> dict:
        title = kwargs.get("title", "Untitled")
        chapter_num = kwargs.get("chapter", 1)
        chapter_title = kwargs.get("chapter_title", f"Chapter {chapter_num}")
        context = kwargs.get("context", "")
        what_happens = kwargs.get("what_happens", "")

        prompt = f"""Write Chapter {chapter_num} of {title}.

Chapter title: {chapter_title}
Story context so far: {context or 'This is the opening chapter.'}
What must happen in this chapter: {what_happens or 'Introduce the protagonist and inciting incident.'}

Rules:
- Open mid-action or mid-emotion — no scene-setting paragraphs
- End the chapter on a hook, revelation, or cliffhanger
- Target: 2,000-3,000 words
- Include at least one moment of genuine tension
- Advance character development alongside plot

Write the full chapter, formatted as:
## {chapter_title}

[chapter content]

---
*[cliffhanger or transitional line to next chapter]*"""

        result = self.claude(prompt, system=self._get_system_prompt(), max_tokens=4000)
        safe_title = title.lower().replace(" ", "_")[:30]
        fpath = self.output_dir / f"chapter_{chapter_num:02d}_{safe_title}_{ts}.md"
        fpath.write_text(result, encoding="utf-8")
        path = self.save_output(result, f"ch{chapter_num:02d}_{safe_title}_{ts}.md", ext="md")
        return {"file": str(path), "action": "chapter", "chapter": chapter_num}

    def _cover_brief(self, ts: str, **kwargs) -> dict:
        ideas = self._get_book_ideas()
        idea = ideas[datetime.now().day % len(ideas)]
        title = kwargs.get("title", idea.get("title"))

        prompt = f"""Create a book cover design brief for: {title} ({self.genre} genre)

Deliverables:
1. COVER CONCEPT (describe the scene/image that should appear)
2. COLOR PALETTE (3-4 hex codes + mood)
3. TYPOGRAPHY: Font style for title + author name
4. DALL-E PROMPT (ready to paste — generate the cover illustration)
5. CANVA BRIEF: Layout instructions for cover text overlay
6. BACK COVER COPY (200 words max — the blurb + author bio)
7. SPINE TEXT: What to print on the spine
8. SERIES BRANDING: How covers 2-5 should match this style

Amazon KDP cover specs: 2560 x 1600px, RGB, minimum 300dpi"""

        result = self.claude(prompt, system=self._get_system_prompt(), max_tokens=1200)
        covers_dir = Path(__file__).resolve().parents[2] / "outputs" / "books" / "covers"
        covers_dir.mkdir(parents=True, exist_ok=True)
        safe_title = title.lower().replace(" ", "_")[:30]
        (covers_dir / f"cover_{self.genre}_{safe_title}_{ts}.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"cover_{safe_title}_{ts}.md", ext="md")
        return {"file": str(path), "action": "cover", "title": title}

    def _kdp_listing(self, ts: str, **kwargs) -> dict:
        ideas = self._get_book_ideas()
        idea = ideas[datetime.now().day % len(ideas)]
        title = kwargs.get("title", idea.get("title"))
        logline = kwargs.get("logline", idea.get("logline", ""))

        prompt = f"""Write a complete Amazon KDP product listing for:
Title: {title}
Genre: {self.genre}
Logline: {logline}
Price: {self.kdp_price} (KDP) / {self.direct_price} (Gumroad direct)

Amazon KDP Listing:
1. BOOK TITLE (max 200 chars including subtitle)
2. SUBTITLE (optional but recommended for SEO)
3. SERIES NAME + book number
4. DESCRIPTION (4,000 chars max — HTML formatted for KDP):
   - Opening hook paragraph (sells the emotion)
   - 3-5 story beats that create FOMO without spoilers
   - "Perfect for fans of [2 comparable authors]"
   - CTA: "Scroll up and grab your copy today"
5. KEYWORDS (7 KDP backend keywords — long-tail, specific)
6. CATEGORIES (2 Amazon categories + 10 BISAC codes)
7. AUTHOR BIO (150 words — for the author page)
8. A+ CONTENT IDEAS (3 module concepts for the enhanced description)
9. PRICING STRATEGY: Why {self.kdp_price} is optimal for this genre
10. LAUNCH CHECKLIST: First 30 days to maximize ranking

Gumroad listing:
- Title + tagline
- Short description (150 chars)
- Full description (500 words)
- Tags (10)
- Preview chapter to offer free"""

        result = self.claude(prompt, system=self._get_system_prompt(), max_tokens=3000)
        pub_dir = Path(__file__).resolve().parents[2] / "outputs" / "books" / "published"
        pub_dir.mkdir(parents=True, exist_ok=True)
        safe_title = title.lower().replace(" ", "_")[:30]
        (pub_dir / f"kdp_{self.genre}_{safe_title}_{ts}.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"kdp_{safe_title}_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"📕 KDP Listing Ready!\n{title}\n💰 {self.kdp_price} KDP | {self.direct_price} Direct\n📁 {Path(str(path)).name}")
        except Exception:
            pass

        return {"file": str(path), "action": "listing", "title": title}

    def _promote(self, ts: str, **kwargs) -> dict:
        ideas = self._get_book_ideas()
        idea = ideas[datetime.now().day % len(ideas)]
        title = kwargs.get("title", idea.get("title"))

        prompt = f"""Create promotional social media content to sell the {self.genre} book: {title}

Price: {self.kdp_price} on Kindle | {self.direct_price} direct
Store: {self.gumroad_url}

Generate:
1. FACEBOOK POST (200 words):
   - Open with the book's most gripping moment/concept
   - Don't reveal — create massive FOMO
   - "Available now for just {self.kdp_price}" + link
   - 3-5 hashtags

2. INSTAGRAM CAPTION (100 words + 20 hashtags):
   - First line = scroll-stopper
   - 5-bullet teaser (no spoilers)
   - "Link in bio to read now"

3. BOOK TRAILER SCRIPT (30-second voiceover):
   - Dramatic narration + story beats
   - "Available on Amazon Kindle and direct from WheellsVerse"

4. EMAIL SUBJECT LINES (5 options for launch day email)"""

        result = self.claude(prompt, system=self._get_system_prompt(), max_tokens=1500)
        path = self.save_output(result, f"book_promo_{ts}.md", ext="md")

        try:
            from core.facebook import get_facebook
            from core.instagram import get_instagram
            lines = result.split("\n")
            fb_lines, ig_lines = [], []
            in_fb, in_ig = False, False
            for line in lines:
                if "FACEBOOK" in line.upper():
                    in_fb, in_ig = True, False
                elif "INSTAGRAM" in line.upper():
                    in_fb, in_ig = False, True
                elif "BOOK TRAILER" in line.upper() or "EMAIL" in line.upper():
                    in_fb = in_ig = False
                elif in_fb:
                    fb_lines.append(line)
                elif in_ig:
                    ig_lines.append(line)
            fb = get_facebook()
            ig = get_instagram()
            if fb.is_configured() and fb_lines:
                fb.post("\n".join(fb_lines).strip())
            if ig.is_configured() and ig_lines:
                ig.post("\n".join(ig_lines).strip())
        except Exception as e:
            self.logger.debug("Book promo publish skipped: %s", e)

        return {"file": str(path), "action": "promote", "title": title}

    def _plan_series(self, ts: str, **kwargs) -> dict:
        ideas = self._get_book_ideas()
        idea = ideas[0]
        title = kwargs.get("title", idea.get("title"))

        prompt = f"""Plan a complete 5-book {self.genre} series starting with: {title}

Series plan:
1. SERIES NAME + tagline
2. SERIES BIBLE:
   - World/universe rules (applies to all books)
   - Recurring characters + their arc across 5 books
   - Overarching plot thread (the "meta-story" that spans all books)
3. BOOK-BY-BOOK BREAKDOWN:
   Book 1: {title} — [synopsis, cliffhanger, hooks reader into book 2]
   Book 2: [title] — [synopsis, advances meta-story]
   Book 3: [title] — [midpoint of series, major revelation]
   Book 4: [title] — [darkest moment, all hope lost]
   Book 5: [title] — [final confrontation, series conclusion]
4. PUBLISHING STRATEGY:
   - Book 1 price: FREE or $0.99 (hook readers)
   - Books 2-5: $2.99-$4.99 each
   - Series bundle: $14.99
5. MARKETING ANGLE:
   - "If you loved [comp author], you'll love this series"
   - Target reader persona
6. REVENUE PROJECTION:
   - At 50 series sales/month: $X/month
   - At 200 series sales/month: $X/month"""

        result = self.claude(prompt, system=self._get_system_prompt(), max_tokens=3000)
        path = self.save_output(result, f"series_plan_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"📚 5-Book Series Planned!\nGenre: {self.genre.title()}\nBook 1: {title}")
        except Exception:
            pass

        return {"file": str(path), "action": "series"}
