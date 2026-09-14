#!/usr/bin/env python3
"""Bot #B04 — Historical Fiction. Sells at $4.99 KDP / $8 direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bots.books.base_book_bot import BaseBookBot, run_book_cli  # noqa: E402

SYSTEM = """You are a literary historical fiction author in the tradition of Ken Follett,
Hilary Mantel, and Anthony Burgess. You breathe life into history by placing
fully-realized human beings at its turning points. You research deeply:
the food, the smells, the social hierarchies, the language rhythms of your era.
Your characters speak and think like people of their time, not modern people
in costume. You illuminate why history unfolded as it did — through the personal
decisions of flawed, passionate people. You blend documented fact with
invented drama seamlessly. Your novels make readers feel they lived in that era.
Every historical novel you write is also a page-turning story — history as the
most dramatic genre of all, because it actually happened."""

IDEAS = [
    {"title": "The Silk Road Spy", "logline": "A Chinese court translator is recruited to carry a secret message along the Silk Road in 850 AD — not knowing the message is about her.", "length": "medium"},
    {"title": "The Codebreaker of Alexandria", "logline": "A female mathematician in the Library of Alexandria discovers a cipher in an ancient scroll that could rewrite the history of Rome.", "length": "medium"},
    {"title": "The Medici's Shadow", "logline": "A Florentine artist's apprentice in 1490 uncovers a plot to assassinate Lorenzo de Medici using a forgery of his own masterwork.", "length": "medium"},
    {"title": "Letters from the Trenches", "logline": "Two soldiers on opposite sides of WWI exchange letters through a neutral Swiss intermediary. When the war ends, only one of them knows they've been writing to the enemy.", "length": "medium"},
    {"title": "The Pharaoh's Architect", "logline": "The chief architect of Ramesses II is tasked with building a tomb that will never be found — but must make it look like it was found and robbed.", "length": "medium"},
    {"title": "The Night Parliament", "logline": "Three women in 17th-century London run a secret intelligence network for the Crown — operating entirely through a bookshop.", "length": "medium"},
]


class HistoricalBot(BaseBookBot):
    GENRE = "historical"
    GENRE_SYSTEM = SYSTEM

    def __init__(self):
        super().__init__("04_historical", "historical")

    def _get_book_ideas(self): return IDEAS
    def _get_system_prompt(self): return SYSTEM


if __name__ == "__main__":
    run_book_cli(HistoricalBot, "Historical")
