#!/usr/bin/env python3
"""Bot #B02 — Mystery & Thriller. Sells at $2.99 KDP / $5 direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bots.books.base_book_bot import BaseBookBot  # noqa: E402

SYSTEM = """You are a master of psychological suspense in the tradition of Agatha Christie,
Gillian Flynn, and Tana French. Your mysteries are layered puzzles where every clue
is hidden in plain sight. Your thrillers make hearts race with dread and anticipation.
You excel at: unreliable narrators, shocking twists that feel inevitable in retrospect,
red herrings that satisfy rather than frustrate, atmosphere so thick you can taste it,
and characters whose secrets are as dangerous as any weapon. Your opening lines
make it impossible to put the book down. Every chapter ends with a reason to read
the next one. You write mysteries that make readers feel clever AND surprised."""

IDEAS = [
    {"title": "The Wrong Confession", "logline": "A man confesses to a murder he didn't commit — to protect someone. But now he's starting to wonder if they actually did it.", "length": "medium"},
    {"title": "Room 14 Never Existed", "logline": "A hotel detective investigates a guest who checked into a room that doesn't appear on any floor plan.", "length": "medium"},
    {"title": "The Lighthouse Keeper's Last Note", "logline": "A journalist arrives at a remote island to write about a lighthouse keeper's disappearance — and finds a note addressed to her.", "length": "medium"},
    {"title": "Delete Before Reading", "logline": "A woman finds deleted emails on her dead husband's account. They're all from her.", "length": "medium"},
    {"title": "The Memory Thief", "logline": "A detective who can experience the last 24 hours of any murder victim's life encounters a victim with no memories at all.", "length": "medium"},
    {"title": "Seven Suspects, One Alibi", "logline": "Seven strangers all claim the same alibi for a murder. The alibi is perfect. And one of them is lying about who they really are.", "length": "medium"},
    {"title": "The Girl Who Remembered Tomorrow", "logline": "A woman with premonitions sees her own murder — but each time she changes her behavior, the murder changes too.", "length": "medium"},
]


class MysteryBot(BaseBookBot):
    GENRE = "mystery"
    GENRE_SYSTEM = SYSTEM

    def __init__(self):
        super().__init__("02_mystery", "mystery")

    def _get_book_ideas(self): return IDEAS
    def _get_system_prompt(self): return SYSTEM


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--action", default="write", choices=["write", "outline", "chapter", "cover", "listing", "promote", "series"])
    p.add_argument("--title")
    p.add_argument("--chapter", type=int, default=1)
    args = p.parse_args()
    bot = MysteryBot()
    r = bot.execute(action=args.action, title=args.title, chapter=args.chapter)
    print(f"\n✅ Mystery: {r.get('file', '')}")
