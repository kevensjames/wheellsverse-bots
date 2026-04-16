#!/usr/bin/env python3
"""
WheellsVerse Book Publisher
Handles post-writing publishing pipeline:
  - Formats manuscripts for Amazon KDP (EPUB-ready markdown)
  - Generates Amazon KDP listings, cover briefs, and metadata
  - Creates Gumroad product listings
  - Generates promotional content for all platforms
  - Tracks published books catalog

Usage:
  python book_publisher.py --book path/to/manuscript.md --genre mystery
  python book_publisher.py --catalog          # show published books
  python book_publisher.py --publish-all      # process all unpublished manuscripts
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.base_bot import BaseBot  # noqa: E402

BOOKS_DIR = Path(__file__).resolve().parents[2] / "outputs" / "books"
CATALOG_FILE = BOOKS_DIR / "catalog.json"

GENRE_CATEGORIES = {
    "childrens": ["Children's eBooks", "Children's Literature"],
    "mystery": ["Mystery, Thriller & Suspense", "Kindle Store > Mystery"],
    "adventure": ["Action & Adventure", "Literature & Fiction > Action & Adventure"],
    "historical": ["Historical Fiction", "Literary Fiction"],
    "self_help": ["Self-Help", "Business & Money > Personal Finance"],
    "romance": ["Romance", "Contemporary Romance"],
    "sci_fi": ["Science Fiction", "Hard Science Fiction"],
    "fantasy": ["Fantasy", "Epic Fantasy"],
    "horror": ["Horror", "Supernatural Horror"],
    "true_crime": ["True Crime", "Biographies & Memoirs > True Crime"],
}

KDP_PRICES = {
    "childrens": 3.99, "mystery": 2.99, "adventure": 2.99,
    "historical": 4.99, "self_help": 9.99, "romance": 2.99,
    "sci_fi": 3.99, "fantasy": 4.99, "horror": 2.99, "true_crime": 4.99,
}


class BookPublisher(BaseBot):

    def __init__(self):
        super().__init__("book_publisher", "books")

    def run(self, action: str = "catalog", **kwargs):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        actions = {
            "catalog": self._show_catalog,
            "publish": self._publish_manuscript,
            "publish_all": self._publish_all,
            "kdp_format": self._kdp_format,
            "promo_pack": self._promo_pack,
            "revenue": self._revenue_report,
        }
        fn = actions.get(action, self._show_catalog)
        return fn(ts, **kwargs)

    def _load_catalog(self) -> list:
        if CATALOG_FILE.exists():
            return json.loads(CATALOG_FILE.read_text())
        return []

    def _save_catalog(self, catalog: list):
        CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CATALOG_FILE.write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    def _show_catalog(self, ts: str, **kwargs) -> dict:
        catalog = self._load_catalog()
        if not catalog:
            # Auto-scan for manuscripts
            for genre_dir in BOOKS_DIR.iterdir():
                if genre_dir.is_dir() and genre_dir.name not in ("covers", "published", "catalog.json"):
                    for f in genre_dir.glob("*.md"):
                        if not f.name.startswith("outline_") and not f.name.startswith("cover_"):
                            catalog.append({
                                "file": str(f),
                                "genre": genre_dir.name,
                                "title": f.stem.replace("_", " ").title(),
                                "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                                "published": False,
                                "kdp_price": KDP_PRICES.get(genre_dir.name, 2.99),
                            })
            self._save_catalog(catalog)

        total = len(catalog)
        published = sum(1 for b in catalog if b.get("published"))
        path = self.save_output(
            f"# Book Catalog — {total} total, {published} published\n\n" +
            "\n".join(f"- [{b.get('genre', '').upper()}] {b.get('title', '')} {'✅' if b.get('published') else '⏳'}"
                      for b in catalog),
            f"catalog_{ts}.md", ext="md")
        return {"file": str(path), "catalog": catalog, "total": total, "published": published}

    def _publish_manuscript(self, ts: str, **kwargs) -> dict:
        book_file = kwargs.get("book_file", "")
        genre = kwargs.get("genre", "mystery")

        if book_file:
            manuscript = Path(book_file).read_text(encoding="utf-8")
            title = Path(book_file).stem.replace("_", " ").title()
        else:
            # Find latest unpublished for this genre
            genre_dir = BOOKS_DIR / genre
            manuscripts = sorted(genre_dir.glob("*.md"),
                                  key=lambda f: f.stat().st_mtime, reverse=True) if genre_dir.exists() else []
            manuscripts = [m for m in manuscripts
                           if not any(m.name.startswith(p) for p in ("outline_", "cover_", "kdp_", "series_"))]
            if not manuscripts:
                return {"file": "", "action": "publish", "error": "No manuscripts found"}
            manuscript_path = manuscripts[0]
            manuscript = manuscript_path.read_text(encoding="utf-8")
            title = manuscript_path.stem[:50].replace("_", " ").title()

        kdp_price = KDP_PRICES.get(genre, 2.99)
        royalty_70 = kdp_price * 0.70
        categories = GENRE_CATEGORIES.get(genre, ["Fiction"])

        publish_prompt = f"""Generate a complete Amazon KDP publishing package for this {genre} book.

Title: {title}
KDP Price: ${kdp_price}
Your royalty (70%): ${royalty_70:.2f} per sale
Categories: {', '.join(categories)}

Manuscript excerpt (first 500 words):
{manuscript[:2000]}

Deliver:
## AMAZON KDP LISTING
**Book Title:** (max 200 chars — keyword optimized)
**Subtitle:** (if applicable)
**Series:** (if first book, suggest series name)
**Author:** J.K. Blaze

**DESCRIPTION (4000 chars max, HTML formatted for KDP):**
<p>[Opening hook — 2 sentences that sell the emotion]</p>
<p>[Story beats — 3 paragraphs with NO spoilers, maximum intrigue]</p>
<p><strong>Perfect for fans of</strong> [2 comp authors].</p>
<p><em>Scroll up and one-click to start reading today.</em></p>

**KEYWORDS (7 backend keywords for KDP):**
1. [keyword]
...

**CATEGORIES:**
Primary: {categories[0]}
Secondary: {categories[1] if len(categories) > 1 else categories[0]}

## GUMROAD LISTING
**Title:** [title + tagline]
**Price:** ${kdp_price + 2:.2f} (direct price — above KDP)
**Short description:** (150 chars)
**Full description:** (400 words)
**Tags:** (10 tags)

## LAUNCH PLAN (first 7 days)
- Day 1: [launch actions]
- Day 2-3: [social media push]
- Day 4-5: [email list announcement]
- Day 6-7: [request reviews strategy]

## REVENUE PROJECTION
At 5 sales/day: ${5 * royalty_70:.2f}/day = ${5 * royalty_70 * 30:.2f}/month
At 20 sales/day: ${20 * royalty_70:.2f}/day = ${20 * royalty_70 * 30:.2f}/month"""

        result = self.claude(publish_prompt, max_tokens=3000)
        pub_dir = BOOKS_DIR / "published"
        pub_dir.mkdir(exist_ok=True)
        safe = title.lower().replace(" ", "_")[:30]
        (pub_dir / f"{genre}_{safe}_kdp_package.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"publish_{genre}_{ts}.md", ext="md")

        # Update catalog
        catalog = self._load_catalog()
        for book in catalog:
            if title.lower() in book.get("title", "").lower():
                book["published"] = True
                book["published_date"] = datetime.now().isoformat()
                book["kdp_package"] = str(pub_dir / f"{genre}_{safe}_kdp_package.md")
        self._save_catalog(catalog)

        try:
            from core.telegram import notify
            notify(f"📕 BOOK PUBLISHED!\n{title}\nGenre: {genre.title()} | Price: ${kdp_price}\n"
                   f"💰 Royalty: ${royalty_70:.2f}/sale\n📁 KDP package ready to upload!")
        except Exception:
            pass

        return {"file": str(path), "action": "publish", "title": title, "genre": genre}

    def _publish_all(self, ts: str, **kwargs) -> dict:
        """Process one manuscript per genre and generate KDP packages."""
        published = []
        for genre in GENRE_CATEGORIES:
            result = self._publish_manuscript(ts, genre=genre)
            if not result.get("error"):
                published.append(f"✅ {genre}: {result.get('title', '')}")
            else:
                published.append(f"⏳ {genre}: no manuscript yet")

        path = self.save_output(
            "# Publish All Results\n\n" + "\n".join(published),
            f"publish_all_{ts}.md", ext="md")
        return {"file": str(path), "action": "publish_all", "count": len(published)}

    def _kdp_format(self, ts: str, **kwargs) -> dict:
        """Generate KDP-ready formatting guide for a manuscript."""
        genre = kwargs.get("genre", "mystery")
        kdp_price = KDP_PRICES.get(genre, 2.99)

        prompt = f"""Create an Amazon KDP upload checklist and formatting guide for a {genre} book.

Include:
1. KDP UPLOAD CHECKLIST (step by step)
   - Account setup (KDP.amazon.com)
   - Manuscript format: DOCX or EPUB (recommended format for {genre})
   - Cover image specs: 2560 x 1600px, RGB, JPG
   - ISBN: KDP free ISBN vs own ISBN
   - Price: ${kdp_price} (70% royalty = ${kdp_price * 0.7:.2f})
   - Select-In or not: recommendation for {genre}
   - Rights: worldwide vs territories

2. MANUSCRIPT FORMATTING
   - Font: Times New Roman 12pt or Georgia
   - Chapter breaks (page break before each chapter)
   - Front matter: title page, copyright, table of contents
   - Back matter: author bio, other books, preview of next book

3. KDP SELECT vs WIDE
   - Pros/cons for {genre} genre
   - Recommendation: KDP Select (Kindle Unlimited) for launch 90 days

4. COVER CREATION OPTIONS
   - KDP Cover Creator (free)
   - Canva (recommended — $0 with free plan)
   - Hire on Fiverr: $15-$50 for professional cover
   - DALL-E generated + Canva layout

5. LAUNCH SEQUENCE
   - Pre-order setup
   - Launch day actions
   - Getting first reviews
   - Keyword/category optimization

Price this as a service: offering to do all this for other authors at $97/book"""

        result = self.claude(prompt, max_tokens=2000)
        path = self.save_output(result, f"kdp_guide_{ts}.md", ext="md")
        return {"file": str(path), "action": "kdp_format"}

    def _promo_pack(self, ts: str, **kwargs) -> dict:
        """Generate a complete promotional pack for a book launch."""
        genre = kwargs.get("genre", "mystery")
        title = kwargs.get("title", "The Mystery Book")
        kdp_price = KDP_PRICES.get(genre, 2.99)

        prompt = f"""Create a complete book launch promotional pack for:
Title: {title}
Genre: {genre}
Price: ${kdp_price} on Amazon Kindle

Pack includes:
1. FACEBOOK POST (200 words) — launch announcement
2. INSTAGRAM CAPTION (100 words + 20 hashtags)
3. LAUNCH DAY EMAIL (subject + 300-word body)
4. 5 BOOK QUOTE GRAPHICS (quote + visual description for Canva)
5. AMAZON REVIEW REQUEST (what to text/DM to early readers)
6. 30-DAY PROMOTIONAL CALENDAR:
   Week 1: Launch blitz
   Week 2: Social proof + reviews
   Week 3: Email nurture
   Week 4: Affiliate push

Target: 100 sales in first 30 days."""

        result = self.claude(prompt, max_tokens=2500)
        path = self.save_output(result, f"promo_pack_{ts}.md", ext="md")

        try:
            from core.facebook import get_facebook
            lines = result.split("\n")
            fb_lines = []
            in_fb = False
            for line in lines:
                if "FACEBOOK" in line.upper():
                    in_fb = True
                elif in_fb and "INSTAGRAM" in line.upper():
                    break
                elif in_fb:
                    fb_lines.append(line)
            fb = get_facebook()
            if fb.is_configured() and fb_lines:
                fb.post("\n".join(fb_lines).strip())
        except Exception as e:
            self.logger.debug("Book promo post skipped: %s", e)

        return {"file": str(path), "action": "promo_pack", "title": title}

    def _revenue_report(self, ts: str, **kwargs) -> dict:
        catalog = self._load_catalog()
        total_books = len(catalog)

        revenue_data = {}
        total_conservative = 0
        total_realistic = 0

        for genre, price in KDP_PRICES.items():
            genre_books = [b for b in catalog if b.get("genre") == genre]
            published = [b for b in genre_books if b.get("published")]
            royalty = price * 0.70
            conservative = royalty * 5 * 30  # 5 sales/day
            realistic = royalty * 20 * 30    # 20 sales/day
            revenue_data[genre] = {
                "books": len(genre_books),
                "published": len(published),
                "price": price,
                "royalty": royalty,
                "conservative_monthly": conservative,
                "realistic_monthly": realistic,
            }
            total_conservative += conservative
            total_realistic += realistic

        report = f"""# WheellsVerse Book Revenue Report — {datetime.now().strftime('%B %d, %Y')}

## Portfolio Overview
- Total manuscripts: {total_books}
- Published: {sum(1 for b in catalog if b.get('published'))}
- Pending upload: {sum(1 for b in catalog if not b.get('published'))}

## Revenue Projections by Genre

| Genre | Books | Price | Royalty | Conservative | Realistic |
|-------|-------|-------|---------|-------------|---------|
"""
        for genre, d in revenue_data.items():
            report += f"| {genre.title()} | {d['books']} | ${d['price']} | ${d['royalty']:.2f} | ${d['conservative_monthly']:.0f}/mo | ${d['realistic_monthly']:.0f}/mo |\n"

        report += f"""
## Totals
- **Conservative** (5 sales/day/genre): ${total_conservative:,.0f}/month
- **Realistic** (20 sales/day/genre): ${total_realistic:,.0f}/month

## Growth Strategy
1. Publish 1 new book per genre per week (10 books/week)
2. Build a series in each genre — readers buy entire series
3. First book of each series FREE → drives sequel sales
4. Target Kindle Unlimited (KDP Select) for passive reads revenue
5. After 10 books per genre, genre earns like a content farm
"""
        path = self.save_output(report, f"revenue_report_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"📊 Book Revenue Report\n"
                   f"📚 {total_books} manuscripts\n"
                   f"💰 Conservative: ${total_conservative:,.0f}/month\n"
                   f"🚀 Realistic: ${total_realistic:,.0f}/month\n"
                   f"(across all 10 genres)")
        except Exception:
            pass

        return {"file": str(path), "action": "revenue"}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="WheellsVerse Book Publisher")
    p.add_argument("--action", default="catalog",
                   choices=["catalog", "publish", "publish_all", "kdp_format", "promo_pack", "revenue"])
    p.add_argument("--book-file", type=str, default=None)
    p.add_argument("--genre", type=str, default="mystery")
    p.add_argument("--title", type=str, default=None)
    args = p.parse_args()
    pub = BookPublisher()
    result = pub.execute(action=args.action, book_file=args.book_file,
                         genre=args.genre, title=args.title)
    print(f"\n✅ Publisher: {result.get('file', result)}")
