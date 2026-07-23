#!/usr/bin/env python3
"""Bot #B03 — Adventure. Sells at $2.99 KDP / $5 direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bots.books.base_book_bot import BaseBookBot, run_book_cli  # noqa: E402

SYSTEM = """You are a master adventure storyteller in the tradition of Jack London,
Wilbur Smith, and Matthew Reilly. Your adventures are breathless — every chapter
a new danger, every page a new discovery. You excel at: exotic locations described
with cinematic precision, heroes who are competent but human (they bleed, they doubt,
they get things wrong), action sequences that are choreographed like a film,
stakes that feel genuinely life-or-death, and a sense of wonder at the world's
hidden places. Your stories move fast. No wasted scenes. Every setback reveals
something crucial. The hero earns their victory through intelligence and sacrifice,
not luck. Readers should feel like they've traveled the world when they finish."""

IDEAS = [
    {"title": "The Last Cartographer", "logline": "A disgraced map-maker discovers a 400-year-old map that proves a lost civilization still exists — and a ruthless collector will kill to keep it secret.", "length": "medium"},
    {"title": "Bone Compass", "logline": "Two rival treasure hunters discover the bones of an ancient warrior contain magnetic properties that point to the greatest treasure in history.", "length": "medium"},
    {"title": "The Frozen Expedition", "logline": "A rescue team sent to find a lost Arctic expedition discovers the original team didn't disappear — they found something and chose not to come back.", "length": "medium"},
    {"title": "Under the Forgotten City", "logline": "A tunnel engineer drilling beneath Rome breaks into a vast underground city that has been deliberately hidden from history.", "length": "medium"},
    {"title": "The Devil's Trade Wind", "logline": "A solo sailor following an ancient route across the Atlantic realizes someone has been sailing a ghost ship the same route, one day behind her, for 200 years.", "length": "medium"},
    {"title": "Storm Season", "logline": "A storm chaser tracking the most powerful hurricane on record discovers it's being steered — and someone doesn't want him to find out who's steering it.", "length": "medium"},
]


class AdventureBot(BaseBookBot):
    GENRE = "adventure"
    GENRE_SYSTEM = SYSTEM

    def __init__(self):
        super().__init__("03_adventure", "adventure")

    def _get_book_ideas(self): return IDEAS
    def _get_system_prompt(self): return SYSTEM


if __name__ == "__main__":
    run_book_cli(AdventureBot, "Adventure")
