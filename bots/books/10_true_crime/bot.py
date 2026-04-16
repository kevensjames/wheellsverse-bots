#!/usr/bin/env python3
"""Bot #B10 — True Crime (Narrative Non-Fiction style). Sells at $4.99 KDP / $8 direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bots.books.base_book_bot import BaseBookBot  # noqa: E402

SYSTEM = """You are a narrative non-fiction author specializing in true crime and
investigative journalism, in the tradition of Ann Rule, Erik Larson, and
Michelle McNamara. You write true crime as literature: the facts arranged for
maximum dramatic impact, the psychology of criminals explored with empathy
rather than sensationalism, the human cost of crime never lost amid the
procedural details. IMPORTANT: You write NARRATIVE-STYLE true crime based on
fictionalized accounts inspired by real crime patterns and case types — not
claiming to document specific real cases. Your stories are clearly labeled as
'inspired by real events' or are completely fictionalized crime narratives
that read like true crime. You excel at: building suspense from documented facts,
humanizing victims (not reducing them to their deaths), explaining criminal
psychology clearly and compellingly, and weaving multiple timelines into a
coherent narrative. Your books respect victims and illuminate how systems
fail — not just how killers succeed."""

IDEAS = [
    {"title": "The Vanishing Season (Fictional True Crime)", "logline": "A fictionalized account of how a small resort town's isolation made it the perfect hunting ground — and how one determined local reporter refused to let the story die.", "length": "medium"},
    {"title": "Ghost Money: Inside the Rise of Crypto Fraud", "logline": "A fictionalized narrative tracing how a new generation of financial criminals used crypto, social media, and AI to steal millions from ordinary people.", "length": "medium"},
    {"title": "The Identity Thief's Playbook (Fictionalized)", "logline": "A fictionalized account following an investigator who dismantles an identity theft ring operating across three continents using nothing but disposable phones and social engineering.", "length": "medium"},
    {"title": "Dark Web Diaries: The Takedown of Marketplace X", "logline": "A narrative reconstruction — fictionalized — of how law enforcement tracked and dismantled one of the darknet's most sophisticated criminal marketplaces.", "length": "medium"},
    {"title": "The Long Con (Narrative Fiction)", "logline": "A fictionalized multi-year story of an affinity fraud that destroyed an entire tight-knit community — and how one victim eventually unraveled it.", "length": "medium"},
    {"title": "The Art of Disappearing (Fictionalized)", "logline": "Stories of people who successfully vanished from their own lives — some running from danger, some running from themselves — and whether they were ever found.", "length": "medium"},
]


class TrueCrimeBot(BaseBookBot):
    GENRE = "true_crime"
    GENRE_SYSTEM = SYSTEM

    def __init__(self):
        super().__init__("10_true_crime", "true_crime")

    def _get_book_ideas(self): return IDEAS
    def _get_system_prompt(self): return SYSTEM


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--action", default="write", choices=["write", "outline", "chapter", "cover", "listing", "promote", "series"])
    p.add_argument("--title")
    p.add_argument("--chapter", type=int, default=1)
    args = p.parse_args()
    bot = TrueCrimeBot()
    r = bot.execute(action=args.action, title=args.title, chapter=args.chapter)
    print(f"\n✅ True Crime: {r.get('file', '')}")
