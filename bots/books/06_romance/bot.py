#!/usr/bin/env python3
"""Bot #B06 — Romance. Sells at $2.99 KDP / $5 direct. Highest volume genre on Amazon."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bots.books.base_book_bot import BaseBookBot, run_book_cli  # noqa: E402

SYSTEM = """You are a romance author with a gift for emotional tension and swoon-worthy
moments. You write in multiple subgenres: contemporary, historical, paranormal,
and romantic suspense. Your romances have: genuine chemistry built through
meaningful conflict (not misunderstandings), protagonists with real lives and
ambitions beyond the love interest, tension that builds until the reader is
begging for the payoff, and an emotionally satisfying HEA (Happily Ever After)
that feels earned. Your writing is warm, witty, and often funny. You understand
the fantasy: romance readers want to feel the butterflies vicariously.
You write kissing scenes that make hearts race and dialogue that crackles.
Romance is the #1 selling genre on Amazon — you write books that hit tropes
readers love while feeling fresh and specific."""

IDEAS = [
    {"title": "The Wrong Wedding Date", "logline": "When two rival event planners are accidentally booked for the same wedding, they have to work together — or call the whole thing off. The problem: they have history.", "length": "medium"},
    {"title": "Midnight at the Bookshop", "logline": "A woman inherits a mysterious bookshop in Paris and discovers the previous owner left notes in every book — apparently written to her, somehow, decades before she was born.", "length": "medium"},
    {"title": "The Fake Boyfriend Protocol", "logline": "A data scientist creates an algorithm to find her perfect match. The algorithm keeps returning the same result: her infuriating co-founder.", "length": "medium"},
    {"title": "One More Sunrise", "logline": "Two strangers meet at a dawn beach and agree to watch one sunrise together. They don't exchange names. They keep accidentally meeting.", "length": "medium"},
    {"title": "The Chef and the Critic", "logline": "A renowned food critic who destroyed a chef's restaurant five years ago shows up needing his catering for her sister's wedding. He agrees — for a price.", "length": "medium"},
    {"title": "Storm Watch", "logline": "A wildlife photographer and a gruff lighthouse keeper are stranded together for a week by a storm. She thinks he's hiding something. He is.", "length": "medium"},
]


class RomanceBot(BaseBookBot):
    GENRE = "romance"
    GENRE_SYSTEM = SYSTEM

    def __init__(self):
        super().__init__("06_romance", "romance")

    def _get_book_ideas(self): return IDEAS
    def _get_system_prompt(self): return SYSTEM


if __name__ == "__main__":
    run_book_cli(RomanceBot, "Romance")
