#!/usr/bin/env python3
"""Bot #B08 — Fantasy. Sells at $4.99 KDP / $8 direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bots.books.base_book_bot import BaseBookBot, run_book_cli  # noqa: E402

SYSTEM = """You are an epic fantasy author in the tradition of Brandon Sanderson,
Patrick Rothfuss, and Joe Abercrombie. Your fantasy worlds feel lived-in and real:
the magic systems have rules and costs, the politics are as dangerous as the
monsters, and the heroes are morally complex. You excel at: world-building that
reveals itself through action (no info dumps), magic that is internally consistent
and thematically connected to the story, ensemble casts where every character
has their own agenda, prose that is vivid without being purple, and plot twists
that are inevitable in retrospect. You write both epic high fantasy (kings and
prophecies) and intimate low fantasy (thieves and con artists). Your villains
believe they are right. Your heroes make mistakes that cost lives. Every choice
has consequences. Magic feels wondrous and dangerous in equal measure."""

IDEAS = [
    {"title": "The Debt Collector of Souls", "logline": "In a city where debts can be paid with years of your life, a debt collector discovers her employer has been selling the collected years to something ancient and hungry.", "length": "medium"},
    {"title": "The Last Spellwright", "logline": "Written magic — words that, once spoken, become real — is dying. The last person who can write new spells is a 12-year-old girl who cannot read.", "length": "medium"},
    {"title": "Thornwall", "logline": "A living wall of thorns has protected a kingdom for a thousand years. When it begins to die, the kingdom's darkest secret begins to grow through the gaps.", "length": "medium"},
    {"title": "The Map of Unmade Things", "logline": "A cartographer discovers her maps are becoming real — and something on the other side has noticed, and is drawing a map of her world.", "length": "medium"},
    {"title": "Blood Price", "logline": "In a world where magic requires blood sacrifice, the most powerful mage in history never bleeds his own blood. A young investigator begins to wonder whose blood he uses.", "length": "medium"},
    {"title": "The Emperor's Ghost Council", "logline": "A new empress must govern with the advice of her five predecessors — their ghosts bound to her throne. They all have different advice. They all have secrets.", "length": "medium"},
]


class FantasyBot(BaseBookBot):
    GENRE = "fantasy"
    GENRE_SYSTEM = SYSTEM

    def __init__(self):
        super().__init__("08_fantasy", "fantasy")

    def _get_book_ideas(self): return IDEAS
    def _get_system_prompt(self): return SYSTEM


if __name__ == "__main__":
    run_book_cli(FantasyBot, "Fantasy")
