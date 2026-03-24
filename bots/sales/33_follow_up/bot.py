#!/usr/bin/env python3
"""FollowUpBot — sales follow-up sequences"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.base_bot import BaseBot

class FollowUpBot(BaseBot):
    def __init__(self):
        super().__init__("33_follow_up", "sales")

    def run(self, topic: str = None, **kwargs):
        topic = topic or self.config.get("topic", "Follow up on proposal sent 3 days ago")
        self.logger.info(f"Running 33_follow_up: {topic}")

        system = "You are an expert AI assistant specialized in sales follow-up sequences."
        prompt = f"""Complete this professional task:

TOPIC/REQUEST: {topic}

Context: This is for WheellsVerse, an AI automation company owned by Jhon Kevens D Wheeler.
Business niche: AI, automation, entrepreneurship.

Provide a comprehensive, professional, and actionable result.
Include specific examples, metrics, and step-by-step guidance where relevant.
Format with clear headers and sections."""

        result = self.ai(prompt, system=system, max_tokens=2000)
        from datetime import datetime
        out = f"# FollowUpBot Output\n**Topic:** {topic}\n**Date:** {datetime.now():%Y-%m-%d %H:%M}\n\n---\n\n{result}\n\n---\n*WheellsVerse 33_follow_up Bot*"
        path = self.save_output(out, f"33_follow_up_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md", ext="md")
        return {"file": str(path), "topic": topic}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="sales follow-up sequences")
    p.add_argument("--topic", default=None)
    a = p.parse_args()
    bot = FollowUpBot()
    print(bot.execute(topic=a.topic))
