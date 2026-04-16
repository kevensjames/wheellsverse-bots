#!/usr/bin/env python3
"""
core/kdp_validator.py
─────────────────────────────────────────────────────────────────────────────
KDP Pre-Submission Validator

Validates all book metadata, manuscript, and cover before submitting to
Amazon KDP. Catches the most common validation errors before they happen
in the browser, saving time and preventing account flags.

Usage:
    from core.kdp_validator import KDPValidator
    v = KDPValidator()
    result = v.validate(genre="mystery", manuscript_path="...", cover_path="...")
    if not result.is_valid:
        print(result.errors)
    else:
        # safe to upload
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("kdp_validator")

ROOT = Path(__file__).resolve().parent.parent

# ─── KDP constraints (as of 2024) ────────────────────────────────────────────

KDP_TITLE_MAX = 200
KDP_SUBTITLE_MAX = 200
KDP_AUTHOR_MAX = 50
KDP_DESCRIPTION_MIN = 100
KDP_DESCRIPTION_MAX = 4000
KDP_KEYWORD_MAX_LEN = 50
KDP_KEYWORD_COUNT = 7
KDP_MIN_PAGES = 24        # KDP minimum for eBooks
KDP_MIN_WORDS = 2_500     # rough minimum for a publishable eBook
KDP_MAX_FILE_MB = 650       # KDP max manuscript file size in MB
KDP_COVER_MIN_W = 625       # pixels
KDP_COVER_MIN_H = 1000      # pixels
KDP_COVER_MAX_MB = 50
KDP_COVER_RATIO_MIN = 1.33      # height/width ratio (tall cover)
KDP_COVER_RATIO_MAX = 2.00

# Words that trigger KDP content review / rejection
_FLAGGED_CONTENT = [
    "child porn", "child abuse", "incest", "pedophil",
    "terrorism", "bomb making", "drug synthesis",
]

# Genres → valid KDP category names
VALID_CATEGORIES = {
    "childrens": "Children's Books",
    "mystery": "Mystery, Thriller & Suspense",
    "adventure": "Action & Adventure",
    "historical": "Historical Fiction",
    "self_help": "Self-Help",
    "romance": "Romance",
    "sci_fi": "Science Fiction & Fantasy",
    "fantasy": "Science Fiction & Fantasy",
    "horror": "Horror",
    "true_crime": "True Crime",
}

VALID_PRICES = {
    "childrens": (0.99, 9.99),
    "mystery": (0.99, 9.99),
    "default": (0.99, 9.99),
}


@dataclass
class ValidationResult:
    is_valid: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: Dict = field(default_factory=dict)

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.is_valid = False
        logger.warning("KDP validation ERROR: %s", msg)

    def add_warning(self, msg: str):
        self.warnings.append(msg)
        logger.info("KDP validation WARNING: %s", msg)

    def summary(self) -> str:
        parts = [f"Valid: {self.is_valid}"]
        if self.errors:
            parts.append("Errors:\n" + "\n".join(f"  ❌ {e}" for e in self.errors))
        if self.warnings:
            parts.append("Warnings:\n" + "\n".join(f"  ⚠️  {w}" for w in self.warnings))
        return "\n".join(parts)


class KDPValidator:
    """Validates a book package before KDP submission."""

    def validate(
        self,
        genre: str,
        manuscript_path: Optional[str] = None,
        cover_path: Optional[str] = None,
        title: str = "",
        subtitle: str = "",
        author: str = "",
        description: str = "",
        keywords: Optional[List[str]] = None,
        price: float = 2.99,
        series: str = "",
        language: str = "en",
    ) -> ValidationResult:
        """
        Run all validation checks. Returns a ValidationResult.
        Any error means do NOT submit — fix it first.
        """
        result = ValidationResult()

        self._validate_genre(result, genre)
        self._validate_title(result, title)
        self._validate_subtitle(result, subtitle)
        self._validate_author(result, author)
        self._validate_description(result, description)
        self._validate_keywords(result, keywords or [])
        self._validate_price(result, price, genre)
        self._validate_language(result, language)

        if manuscript_path:
            self._validate_manuscript(result, manuscript_path)

        if cover_path:
            self._validate_cover(result, cover_path)

        result.info = {
            "genre": genre,
            "title": title[:60],
            "author": author,
            "price": price,
            "has_cover": bool(cover_path),
            "has_manuscript": bool(manuscript_path),
        }

        if result.is_valid:
            logger.info("KDP validation PASSED for '%s'", title or genre)
        else:
            logger.warning("KDP validation FAILED for '%s' — %d errors", title or genre, len(result.errors))

        return result

    # ── Individual validators ─────────────────────────────────────────────────

    def _validate_genre(self, result: ValidationResult, genre: str):
        if not genre:
            result.add_error("Genre is required.")
        elif genre not in VALID_CATEGORIES:
            result.add_warning(f"Unknown genre '{genre}' — no mapped KDP category. May need manual category selection.")

    def _validate_title(self, result: ValidationResult, title: str):
        if not title or not title.strip():
            result.add_error("Book title is required. KDP will reject submissions without a title.")
            return
        title = title.strip()
        if len(title) > KDP_TITLE_MAX:
            result.add_error(f"Title too long ({len(title)} chars). KDP max is {KDP_TITLE_MAX}.")
        if title.lower().startswith(("test", "sample", "draft", "untitled")):
            result.add_warning("Title starts with 'test/sample/draft/untitled' — KDP may flag this for review.")
        if re.search(r'[<>"/\\]', title):
            result.add_error("Title contains illegal characters (<>\"/\\). Remove them.")
        if not re.search(r'[a-zA-Z]', title):
            result.add_error("Title must contain at least one letter.")
        # Check for ALL CAPS (KDP may reject)
        words = title.split()
        if len(words) > 2 and all(w.isupper() for w in words if len(w) > 2):
            result.add_warning("Title is ALL CAPS — KDP may reject this. Use title case instead.")

    def _validate_subtitle(self, result: ValidationResult, subtitle: str):
        if subtitle and len(subtitle) > KDP_SUBTITLE_MAX:
            result.add_error(f"Subtitle too long ({len(subtitle)}). KDP max is {KDP_SUBTITLE_MAX}.")

    def _validate_author(self, result: ValidationResult, author: str):
        if not author or not author.strip():
            result.add_error("Author name is required. KDP rejects submissions without an author.")
            return
        author = author.strip()
        if len(author) > KDP_AUTHOR_MAX:
            result.add_error(f"Author name too long ({len(author)} chars). Max is {KDP_AUTHOR_MAX}.")
        if not re.search(r'[a-zA-Z]', author):
            result.add_error("Author name must contain letters.")
        # KDP requires first + last name for primary author
        parts = author.split()
        if len(parts) < 2:
            result.add_warning(f"Author '{author}' has only one name part. KDP requires first + last name.")

    def _validate_description(self, result: ValidationResult, description: str):
        if not description or not description.strip():
            result.add_error("Book description is required. KDP will not accept blank descriptions.")
            return
        # Strip HTML for length check
        plain = re.sub(r'<[^>]+>', ' ', description).strip()
        plain = re.sub(r'\s+', ' ', plain)
        if len(plain) < KDP_DESCRIPTION_MIN:
            result.add_error(
                f"Description too short ({len(plain)} chars). KDP minimum is {KDP_DESCRIPTION_MIN}. "
                "Add more detail about the book's plot, characters, or value."
            )
        if len(description) > KDP_DESCRIPTION_MAX:
            result.add_error(f"Description too long ({len(description)} chars). KDP max is {KDP_DESCRIPTION_MAX}.")
        # Check for flagged content
        desc_lower = plain.lower()
        for flag in _FLAGGED_CONTENT:
            if flag in desc_lower:
                result.add_error(f"Description contains flagged content ('{flag}'). KDP will reject this.")
        # Check for spammy repetition
        words = plain.lower().split()
        if len(words) > 10:
            from collections import Counter
            freq = Counter(words)
            top_word, top_count = freq.most_common(1)[0]
            if top_count / len(words) > 0.15 and len(top_word) > 3:
                result.add_warning(
                    f"Description may be spammy — '{top_word}' appears {top_count} times. "
                    "KDP's quality filter may flag this."
                )

    def _validate_keywords(self, result: ValidationResult, keywords: List[str]):
        if not keywords:
            result.add_warning("No keywords provided. KDP strongly recommends 7 keywords for discoverability.")
            return
        if len(keywords) > KDP_KEYWORD_COUNT:
            result.add_error(f"Too many keywords ({len(keywords)}). KDP allows maximum {KDP_KEYWORD_COUNT}.")
        for i, kw in enumerate(keywords):
            kw = kw.strip()
            if not kw:
                result.add_warning(f"Keyword {i + 1} is empty — skip or replace it.")
                continue
            if len(kw) > KDP_KEYWORD_MAX_LEN:
                result.add_error(
                    f"Keyword {i + 1} too long ({len(kw)} chars): '{kw[:30]}...'. Max is {KDP_KEYWORD_MAX_LEN}."
                )
            if '"' in kw or "'" in kw:
                result.add_warning(f"Keyword {i + 1} contains quotes — KDP may strip them.")
        # Check for duplicate keywords
        lower_kws = [k.lower().strip() for k in keywords if k.strip()]
        if len(lower_kws) != len(set(lower_kws)):
            result.add_warning("Duplicate keywords detected. Each keyword should be unique.")

    def _validate_price(self, result: ValidationResult, price: float, genre: str):
        price_range = VALID_PRICES.get(genre, VALID_PRICES["default"])
        lo, hi = price_range
        if not (lo <= price <= hi):
            result.add_error(
                f"Price ${price:.2f} is outside KDP's allowed range (${lo:.2f}–${hi:.2f}) for genre '{genre}'. "
                "Note: 70% royalty only applies to $2.99–$9.99."
            )
        if price < 2.99:
            result.add_warning(
                f"Price ${price:.2f} is below $2.99 — you'll only earn 35% royalty instead of 70%. "
                "Consider pricing at $2.99+ for maximum earnings."
            )
        if price > 9.99:
            result.add_warning(
                f"Price ${price:.2f} is above $9.99 — KDP drops royalty to 35%. "
                "Keep below $9.99 for 70% royalty."
            )

    def _validate_language(self, result: ValidationResult, language: str):
        valid_langs = {"en", "es", "fr", "de", "it", "pt", "nl", "ja", "zh", "ar"}
        if language not in valid_langs:
            result.add_warning(f"Language code '{language}' may not be recognized by KDP. Use ISO 639-1 codes (en, es, fr...).")

    def _validate_manuscript(self, result: ValidationResult, manuscript_path: str):
        path = Path(manuscript_path)
        if not path.exists():
            result.add_error(f"Manuscript file not found: {manuscript_path}")
            return

        # File size check
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > KDP_MAX_FILE_MB:
            result.add_error(
                f"Manuscript file too large ({size_mb:.1f} MB). KDP max is {KDP_MAX_FILE_MB} MB. "
                "Compress images in the manuscript or split it."
            )

        # Check file extension
        ext = path.suffix.lower()
        if ext not in {".docx", ".doc", ".txt", ".html", ".htm", ".epub", ".pdf", ".rtf", ".odt"}:
            result.add_error(
                f"Unsupported manuscript format: '{ext}'. "
                "KDP accepts: .docx, .epub, .html, .txt, .rtf, .pdf"
            )

        # Word count and minimum length (for .txt and .md)
        if ext in {".txt", ".md"}:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                word_count = len(text.split())
                if word_count < KDP_MIN_WORDS:
                    result.add_error(
                        f"Manuscript too short ({word_count:,} words). "
                        f"KDP minimum is ~{KDP_MIN_WORDS:,} words for a publishable eBook. "
                        "KDP may reject very short books or categorize them as pamphlets."
                    )
                elif word_count < 5_000:
                    result.add_warning(
                        f"Manuscript is short ({word_count:,} words). "
                        "Books under 5,000 words may get low reviews. Consider expanding."
                    )
                result.info["word_count"] = word_count
                # Check for flagged content
                text_lower = text.lower()
                for flag in _FLAGGED_CONTENT:
                    if flag in text_lower:
                        result.add_error(
                            f"Manuscript contains flagged content ('{flag}'). "
                            "KDP will reject and may flag your account."
                        )
            except Exception as e:
                result.add_warning(f"Could not read manuscript text for validation: {e}")

    def _validate_cover(self, result: ValidationResult, cover_path: str):
        path = Path(cover_path)
        if not path.exists():
            result.add_error(f"Cover image not found: {cover_path}")
            return

        ext = path.suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".tiff", ".tif"}:
            result.add_error(
                f"Unsupported cover format: '{ext}'. "
                "KDP accepts JPEG, PNG, TIFF."
            )

        # File size
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > KDP_COVER_MAX_MB:
            result.add_error(
                f"Cover image too large ({size_mb:.1f} MB). KDP max is {KDP_COVER_MAX_MB} MB. "
                "Compress the image (JPEG quality 85–90 is fine)."
            )
        if size_mb < 0.05:
            result.add_warning("Cover image seems very small (<50 KB). Check image quality.")

        # Dimensions (requires Pillow)
        try:
            from PIL import Image
            with Image.open(str(path)) as img:
                w, h = img.size
                result.info["cover_size"] = f"{w}x{h}"
                if w < KDP_COVER_MIN_W or h < KDP_COVER_MIN_H:
                    result.add_error(
                        f"Cover too small ({w}x{h}px). "
                        f"KDP minimum is {KDP_COVER_MIN_W}x{KDP_COVER_MIN_H}px. "
                        "Recommended: 2560x1600px or 1600x2560px."
                    )
                ratio = h / w if w > 0 else 0
                if not (KDP_COVER_RATIO_MIN <= ratio <= KDP_COVER_RATIO_MAX):
                    result.add_warning(
                        f"Cover ratio {ratio:.2f} (h/w) is unusual. "
                        f"KDP expects {KDP_COVER_RATIO_MIN}–{KDP_COVER_RATIO_MAX} (tall portrait). "
                        "Ideal: 1.6 ratio (1600x2560px)."
                    )
                if img.mode not in ("RGB", "RGBA"):
                    result.add_warning(f"Cover color mode is '{img.mode}'. Convert to RGB for best compatibility.")
        except ImportError:
            result.add_warning("Pillow not installed — skipping cover dimension check. Run: pip install Pillow")
        except Exception as e:
            result.add_warning(f"Could not validate cover dimensions: {e}")


# ─── Quick validation helper ─────────────────────────────────────────────────

def validate_book(
    genre: str,
    manuscript_path: str = None,
    cover_path: str = None,
    title: str = "",
    author: str = "J.K. Blaze",
    description: str = "",
    keywords: List[str] = None,
    price: float = 2.99,
) -> ValidationResult:
    """Quick validate helper — import and call directly."""
    return KDPValidator().validate(
        genre=genre,
        manuscript_path=manuscript_path,
        cover_path=cover_path,
        title=title,
        author=author,
        description=description,
        keywords=keywords or [],
        price=price,
    )
