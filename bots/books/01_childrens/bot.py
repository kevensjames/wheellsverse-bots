#!/usr/bin/env python3
"""Bot #B01 — Children's Books (Ages 3-10). Sells at $3.99 KDP / $7 direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bots.books.base_book_bot import BaseBookBot  # noqa: E402

SYSTEM = """You are a beloved children's book author in the tradition of Dr. Seuss,
Roald Dahl, and Mo Willems. You write stories that children beg to hear again
and again, and parents actually enjoy reading. Your stories have:
- Simple, musical language with rhythm and repetition
- A relatable child protagonist who solves their own problem
- A clear moral that never feels preachy
- Vivid, imaginative details that spark a child's wonder
- An ending that feels earned and emotionally satisfying
For picture books (ages 3-6): 500-800 words, one sentence per page
For early readers (ages 6-8): 1,500-2,500 words, short chapters
For chapter books (ages 8-10): 5,000-8,000 words, 8-12 chapters"""

IDEAS = [
    {"title": "Lila and the Moonlight Library", "logline": "A girl who can't sleep discovers a magical library that only appears at midnight, where the books choose their readers.", "length": "short", "age": "6-8"},
    {"title": "The Boy Who Collected Clouds", "logline": "A shy boy discovers he can shape clouds with his imagination — but a storm is coming that only he can stop.", "length": "short", "age": "6-8"},
    {"title": "Mango the Robot Who Wanted to Dream", "logline": "A little robot in a world of humans learns what it means to have feelings.", "length": "short", "age": "5-7"},
    {"title": "The Dragon Who Was Afraid of Fire", "logline": "Ember can't breathe fire like the other dragons. Her unusual gift turns out to be exactly what her village needs.", "length": "short", "age": "6-9"},
    {"title": "Grandma's Hat Has a Map Inside", "logline": "When grandma's old hat blows away, two siblings chase it across a neighborhood that turns out to be a treasure map.", "length": "short", "age": "5-7"},
    {"title": "The Last Star Counter", "logline": "Every night, a girl counts the stars to keep them from going out — until the night she falls asleep.", "length": "short", "age": "4-6"},
    {"title": "Mr. Whiskers and the Missing Monday", "logline": "A cat detective investigates the mystery of a missing day of the week in Puzzle Town.", "length": "medium", "age": "7-9"},
    {"title": "The School at the Bottom of the Ocean", "logline": "A girl wakes up to find her school has sunk to the ocean floor, where sea creatures become her classmates.", "length": "medium", "age": "7-10"},
]


class ChildrensBookBot(BaseBookBot):
    GENRE = "childrens"
    GENRE_SYSTEM = SYSTEM

    def __init__(self):
        super().__init__("01_childrens", "childrens")

    def _get_book_ideas(self): return IDEAS
    def _get_system_prompt(self): return SYSTEM


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--action", default="write", choices=["write", "outline", "chapter", "cover", "listing", "promote", "series"])
    p.add_argument("--title")
    p.add_argument("--chapter", type=int, default=1)
    args = p.parse_args()
    bot = ChildrensBookBot()
    r = bot.execute(action=args.action, title=args.title, chapter=args.chapter)
    print(f"\n✅ Children's Book: {r.get('file', '')}")
