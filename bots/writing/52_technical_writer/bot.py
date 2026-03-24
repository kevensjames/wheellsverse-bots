#!/usr/bin/env python3
"""TechnicalWriterBot — technical documentation and guides"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from core.base_bot import BaseBot

class TechnicalWriterBot(BaseBot):
    def __init__(self):
        super().__init__("52_technical_writer", "writing")

    def run(self, topic: str = None, **kwargs):
        topic = topic or self.config.get("topic", "Bot ecosystem API documentation")
        self.logger.info(f"Running 52_technical_writer: {topic}")

        system = "You are an expert AI assistant specialized in technical documentation and guides."
        prompt = f"""Complete this professional task:

TOPIC/REQUEST: {topic}

Context: This is for WheellsVerse, an AI automation company owned by Jhon Kevens D Wheeler.
Business niche: AI, automation, entrepreneurship.

Provide a comprehensive, professional, and actionable result.
Include specific examples, metrics, and step-by-step guidance where relevant.
Format with clear headers and sections."""

        result = self.ai(prompt, system=system, max_tokens=2000)
        from datetime import datetime
        out = f"# TechnicalWriterBot Output\n**Topic:** {topic}\n**Date:** {datetime.now():%Y-%m-%d %H:%M}\n\n---\n\n{result}\n\n---\n*WheellsVerse 52_technical_writer Bot*"
        path = self.save_output(out, f"52_technical_writer_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md", ext="md")
        return {"file": str(path), "topic": topic}

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="technical documentation and guides")
    p.add_argument("--topic", default=None)
    a = p.parse_args()
    bot = TechnicalWriterBot()
    print(bot.execute(topic=a.topic))
