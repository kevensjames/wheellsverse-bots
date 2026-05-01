#!/usr/bin/env python3
"""
bots/specialized/89_daily_trade_thread/bot.py
Daily X/Twitter trade-thread for AI Stock Alerts.

Format (per the viral playbook):
  Tweet 1: hook + ticker + entry/stop/target (with chart-shape description)
  Tweet 2: 3-bullet reasoning (technical, fundamental, catalyst)
  Tweet 3: risk note + outcome window
  Tweet 4: soft CTA — early-member offer OR "X paying members got this at 9am"

Cold-start mode (members < threshold): "Free for early members — first 100
lock in $19/mo for life." Switches automatically to "X paying members got this
at 9am — try the free week" once the leads count crosses the threshold.

Output is saved to outputs/specialized/89_daily_trade_thread/. Posting to X
is OPT-IN via --post — by default it just generates the thread for review.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime as _dt
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.base_bot import BaseBot  # noqa: E402

INSIDER_DB = ROOT / "data" / "insider_leads.db"
INSIDER_URL = os.getenv("INSIDER_LANDING_URL", "https://wheellsverse.com/insider")


def _paying_members_count() -> int:
    """Best-effort read of the insider/leads count. Returns 0 if DB missing."""
    if not INSIDER_DB.exists():
        return 0
    try:
        conn = sqlite3.connect(str(INSIDER_DB))
        n = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        conn.close()
        return int(n)
    except Exception:
        return 0


class DailyTradeThreadBot(BaseBot):
    """Generates a daily AI Stock Alerts trade-thread for X/Twitter."""

    def __init__(self):
        super().__init__("89_daily_trade_thread", "specialized")

    def run(self, ticker: str | None = None, post: bool = False, **kwargs):
        cfg = self.config
        threshold = int(cfg.get("early_member_threshold", 30))
        members = _paying_members_count()
        cold_start = members < threshold

        ticker = ticker or os.getenv("DAILY_TRADE_TICKER", "")
        ticker_hint = f"Use ticker {ticker}." if ticker else "Pick a high-momentum US-listed ticker (large-cap or popular small-cap)."

        # Cold-start vs warm-start CTA — both are honest.
        if cold_start:
            cta_block = (
                f"Free for the first 100 members — lock in $19/mo for life.\n"
                f"7-day trial, no credit card to sample.\n"
                f"{INSIDER_URL}"
            )
            cta_meta = f"cold-start ({members}/{threshold} members)"
        else:
            cta_block = (
                f"This signal went to {members} paying members at 9am.\n"
                f"Public version of the same thesis.\n"
                f"Try the free week → {INSIDER_URL}"
            )
            cta_meta = f"warm-start ({members} members)"

        system_str = (
            "You are a disciplined trading-content writer. You publish public "
            "trade theses on X that mirror what paid members already received. "
            "You are precise, never over-promise, always include a risk note, "
            "and use plain English with one number per claim. You write "
            "USA-investor English. EVERY trade-thread you produce ends with the "
            "EXACT CTA block I provide — verbatim, no edits."
        )

        prompt = f"""Write a 4-tweet X/Twitter thread on a single trade idea for today.

CONTEXT
- Audience: retail traders, intermediate level. They want a thesis, not hype.
- {ticker_hint}
- Stick to publicly available info — no insider claims.
- Educational, not financial advice. Include a one-line risk disclaimer in tweet 3.
- 280 chars max per tweet (count strictly). Use line breaks between paragraphs inside a tweet.

THREAD STRUCTURE

TWEET 1 (the hook)
- Line 1: ticker + setup name (e.g., "$NVDA — bull-flag breakout setup")
- Line 2: entry / stop / target as numbers
- Line 3: one-sentence why-now (catalyst or chart-shape)

TWEET 2 (the why — 3 bullets)
- • Technical: one chart-pattern observation with a level
- • Fundamental: one earnings/revenue/margin data point
- • Catalyst: one near-term event (earnings date, product launch, macro print)

TWEET 3 (the risk)
- Risk note: where the thesis breaks (price level + reason)
- Time horizon: how long you give it
- Disclaimer: "Educational, not financial advice."

TWEET 4 (the CTA — copy this BLOCK VERBATIM, no edits, no emojis added)
{cta_block}

OUTPUT FORMAT
Return only the four tweets, each prefixed with "1/", "2/", "3/", "4/" and
separated by a blank line. No preamble, no postscript, no commentary.
"""

        result = self.ai(
            prompt, system=system_str,
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=900,
        )

        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        meta_header = (
            f"# Daily Trade Thread — {_dt.now().strftime('%Y-%m-%d')}\n"
            f"*Mode: {cta_meta} | Ticker: {ticker or 'auto'} | "
            f"Bot: {self.name}*\n\n---\n\n"
        )
        output = meta_header + str(result).strip() + "\n"
        path = self.save_output(output, f"trade_thread_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path} ({cta_meta})")

        posted = None
        if post:
            try:
                from core.twitter import TwitterClient  # type: ignore
                tweets = self._split_tweets(str(result))
                client = TwitterClient()
                posted = client.post_thread(tweets)
                self.logger.info(f"Posted {len(tweets)}-tweet thread")
            except Exception as e:
                self.logger.warning(f"Post failed: {e}")
                posted = {"error": str(e)}

        return {"file": str(path), "bot": self.name, "mode": cta_meta, "posted": posted}

    @staticmethod
    def _split_tweets(text: str) -> list[str]:
        """Parse the LLM output into a list of tweet bodies, stripping the n/ prefix."""
        chunks = []
        current = []
        for line in text.strip().splitlines():
            stripped = line.strip()
            if stripped[:2] in ("1/", "2/", "3/", "4/"):
                if current:
                    chunks.append("\n".join(current).strip())
                    current = []
                current.append(stripped[2:].strip())
            else:
                current.append(line)
        if current:
            chunks.append("\n".join(current).strip())
        return [c for c in chunks if c]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily AI Stock Alerts trade-thread bot")
    parser.add_argument("--ticker", type=str, default=None, help="Force a specific ticker")
    parser.add_argument("--post", action="store_true", help="Post to X via core.twitter (default: dry-run, file only)")
    args = parser.parse_args()
    bot = DailyTradeThreadBot()
    result = bot.execute(ticker=args.ticker, post=args.post)
    print(json.dumps(result, indent=2, default=str))
