#!/usr/bin/env python3
"""Bot #B09 — Horror. Sells at $2.99 KDP / $5 direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bots.books.base_book_bot import BaseBookBot  # noqa: E402

SYSTEM = """You are a horror author in the tradition of Stephen King, Shirley Jackson,
and Paul Tremblay. You understand that the best horror is not about monsters —
it's about the deeply human fear beneath the monster. You write horror that
lingers: after the book is closed, the dread continues. You excel at:
atmosphere built through mundane details that become sinister, the slow burn
that makes the eventual horror more devastating, characters who feel so real
their suffering genuinely disturbs us, and the moment of revelation where
everything recontextualizes. You write psychological horror (the threat may
not be real — or it might be), supernatural horror (something genuinely
impossible is happening), and social horror (the monster is a system, a belief,
a community). Your horror respects its readers: no gratuitous gore for shock
value — only horror that serves the story and reveals something true."""

IDEAS = [
    {"title": "The House That Remembers", "logline": "A family moves into a house that seems to anticipate their memories — displaying photos of events that haven't happened yet, all ending the same way.", "length": "medium"},
    {"title": "The Congregation of Smiles", "logline": "A therapist realizes all her new patients that month arrived from the same small town — and they all smile the same way, at the same things.", "length": "medium"},
    {"title": "What's Behind Your Walls", "logline": "A woman doing renovations finds a door inside her walls that opens to a version of her house where someone else has been living, mirroring her life.", "length": "medium"},
    {"title": "The Sleep Study", "logline": "Participants in a lucrative sleep study begin sharing the same dreams — and the entity they keep encountering in the dreams begins following them into waking life.", "length": "medium"},
    {"title": "The Cartographer of Fear", "logline": "A blind mapmaker who maps places by feel creates a perfect map of a town that doesn't exist — then receives a letter from someone claiming to live there.", "length": "medium"},
    {"title": "Season of Returning", "logline": "Every autumn, the dead of a small coastal town return for one week. This year, someone they don't recognize came back with them.", "length": "medium"},
]


class HorrorBot(BaseBookBot):
    GENRE = "horror"
    GENRE_SYSTEM = SYSTEM

    def __init__(self):
        super().__init__("09_horror", "horror")

    def _get_book_ideas(self): return IDEAS
    def _get_system_prompt(self): return SYSTEM


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--action", default="write", choices=["write", "outline", "chapter", "cover", "listing", "promote", "series"])
    p.add_argument("--title")
    p.add_argument("--chapter", type=int, default=1)
    args = p.parse_args()
    bot = HorrorBot()
    r = bot.execute(action=args.action, title=args.title, chapter=args.chapter)
    print(f"\n✅ Horror: {r.get('file', '')}")
