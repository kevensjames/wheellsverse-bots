from __future__ import annotations


def default_generate(prompt: str, *, system: str | None = None, max_tokens: int = 1200) -> str:
    try:
        from core.base_bot import BaseBot
        bot = BaseBot(name="portfolio_llm", category="portfolio")
        text = bot.claude(prompt, system=system or "You are a concise business operator.",
                          max_tokens=max_tokens)
        return (text or "").strip()
    except Exception:
        return ""
