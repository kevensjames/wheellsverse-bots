#!/usr/bin/env python3
"""Bot #B05 — Self-Help / Non-Fiction. Sells at $9.99 KDP / $17 direct."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from bots.books.base_book_bot import BaseBookBot, run_book_cli  # noqa: E402

SYSTEM = """You are a transformative non-fiction author in the tradition of
James Clear, Malcolm Gladwell, and Tim Ferriss. You turn complex behavioral
science and practical wisdom into clear, compelling, immediately actionable books.
Your writing is: specific (real names, real numbers, real examples), structured
(clear frameworks readers can apply), story-driven (open each chapter with a
narrative that proves the principle), and humble (you acknowledge what doesn't work).
You specialize in: personal finance, AI productivity, passive income, mindset,
and digital entrepreneurship. Your books don't just inspire — they give readers
an exact system to follow. Every chapter has: a hook story, the core principle,
the science/evidence, the exact how-to steps, and a "chapter action" they do today."""

IDEAS = [
    {"title": "The AI Income System: How to Make $1,000/Month on Autopilot", "logline": "A practical step-by-step system to build AI-powered income streams working just 2 hours a day.", "length": "medium"},
    {"title": "Broke to Bitcoin: The No-Nonsense Guide to Crypto for Working People", "logline": "How to invest safely in crypto starting with just $50/month — without gambling or getting scammed.", "length": "medium"},
    {"title": "The Overnight Expert: Use AI to Become the Most Knowledgeable Person in Any Room", "logline": "How to use AI tools to develop deep expertise in any subject in 30 days or less.", "length": "medium"},
    {"title": "The 2-Hour Business: Build a Profitable Side Hustle While Working Full-Time", "logline": "A proven framework for launching a side income stream in your spare time without burning out.", "length": "medium"},
    {"title": "Digital Freedom: How to Make Your First $500 Online (Even If You're Starting From Zero)", "logline": "The exact roadmap, tools, and daily actions that take a complete beginner to their first online income.", "length": "medium"},
    {"title": "Automation Millionaire: Let AI Do the Work While You Collect the Checks", "logline": "How to build a fully automated online business that runs 24/7 with minimal maintenance.", "length": "medium"},
]


class SelfHelpBot(BaseBookBot):
    GENRE = "self_help"
    GENRE_SYSTEM = SYSTEM

    def __init__(self):
        super().__init__("05_self_help", "self_help")

    def _get_book_ideas(self): return IDEAS
    def _get_system_prompt(self): return SYSTEM


if __name__ == "__main__":
    run_book_cli(SelfHelpBot, "Self-Help")
