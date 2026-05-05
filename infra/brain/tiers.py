"""Response tier classifier.
FAST: short factual queries, greetings, quick lookups — uses cheap/fast model.
DEEP: analysis, trading, research, multi-step reasoning — uses primary model.
Classifier uses keyword heuristics + token count; no extra LLM call needed."""
import re

# tokens above this threshold → deep regardless of content
_DEEP_TOKEN_THRESHOLD = 200

_DEEP_KEYWORDS = frozenset({
    "analyze", "explain", "compare", "predict", "forecast", "strategy",
    "backtest", "trade", "invest", "research", "summarize", "write",
    "draft", "plan", "debug", "code", "implement", "design", "review",
    "why", "how does", "what would", "elaborate", "deep dive",
    "breakdown", "thesis", "hypothesis", "report",
})

_FAST_KEYWORDS = frozenset({
    "hi", "hello", "hey", "thanks", "what is", "define", "who is",
    "when", "quick", "brief", "tldr", "one line", "yes", "no",
    "list", "price of", "current", "now",
})


def classify(prompt: str) -> str:
    """Return 'fast' or 'deep' based on prompt content."""
    lower = prompt.lower()
    word_count = len(prompt.split())

    if word_count > _DEEP_TOKEN_THRESHOLD:
        return "deep"

    for kw in _DEEP_KEYWORDS:
        if kw in lower:
            return "deep"

    for kw in _FAST_KEYWORDS:
        if lower.strip().startswith(kw):
            return "fast"

    # default: fast for short, deep for longer
    return "fast" if word_count < 20 else "deep"


def tier_params(tier: str) -> dict:
    """Return litellm kwargs for the given tier."""
    if tier == "fast":
        return {"temperature": 0.5, "max_tokens": 512}
    return {"temperature": 0.7, "max_tokens": 4096}
