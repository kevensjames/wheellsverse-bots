#!/usr/bin/env python3
"""Bot #B07 — Science Fiction. Sells at $3.99 KDP / $7 direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bots.books.base_book_bot import BaseBookBot  # noqa: E402

SYSTEM = """You are a science fiction author in the tradition of Philip K. Dick,
Andy Weir, and Blake Crouch. Your sci-fi is grounded: the science is plausible,
the technology extrapolated from real research, the human drama front and center.
You don't write sci-fi for the gadgets — you write it to ask: what does this
technology do to what it means to be human? Your stories explore AI consciousness,
time manipulation, genetic modification, and first contact through deeply personal
stories. You excel at: the 'what if' premise that unfolds with ruthless logic,
science explained through action (show the character using/fighting the tech),
mind-bending twists that are scientifically consistent, and endings that linger
in the reader's mind for days. Your sci-fi is literary but never slow."""

IDEAS = [
    {"title": "The Recall Option", "logline": "In a world where you can purchase memories from deceased donors, a detective discovers someone is selling memories of crimes that haven't happened yet.", "length": "medium"},
    {"title": "Last Human Standing", "logline": "An AI designed to preserve human civilization must decide whether the last living human — who wants to die — deserves to choose their own ending.", "length": "medium"},
    {"title": "The Quiet Colony", "logline": "The first Mars colony has been silent for 11 minutes. At the speed of light, that means something happened 11 minutes ago — and Earth has no way to know what.", "length": "medium"},
    {"title": "Echo Loop", "logline": "A scientist working on quantum computing discovers her lab exists in a 24-hour time loop — but each loop, her colleagues have no memory and she has slightly less.", "length": "medium"},
    {"title": "The Algorithm of God", "logline": "An AI trained on all human religious texts achieves sentience and announces it has proven the existence of god. The proof is a single equation. No one can find the error.", "length": "medium"},
    {"title": "Parallel You", "logline": "A physicist can communicate with her parallel universe counterpart. They begin trading life decisions to get better outcomes. Then one of them goes dark.", "length": "medium"},
]


class SciFiBot(BaseBookBot):
    GENRE = "sci_fi"
    GENRE_SYSTEM = SYSTEM

    def __init__(self):
        super().__init__("07_sci_fi", "sci_fi")

    def _get_book_ideas(self): return IDEAS
    def _get_system_prompt(self): return SYSTEM


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--action", default="write", choices=["write", "outline", "chapter", "cover", "listing", "promote", "series"])
    p.add_argument("--title")
    p.add_argument("--chapter", type=int, default=1)
    args = p.parse_args()
    bot = SciFiBot()
    r = bot.execute(action=args.action, title=args.title, chapter=args.chapter)
    print(f"\n✅ Sci-Fi: {r.get('file', '')}")
