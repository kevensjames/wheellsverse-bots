#!/usr/bin/env python3
"""
core/reddit.py
─────────────────────────────────────────────────────────────────────────────
Reddit automation — post valuable content to targeted subreddits.

Strategy:
  - Post genuine, helpful content (no spam — Reddit bans spam instantly)
  - Subtle blog link in body (only when allowed by subreddit rules)
  - Self-post format: personal story + key insights + question at end
  - Target high-traffic finance/passive income subreddits

Target subreddits by niche:
  Passive income:  r/passiveincome, r/passive_income_ideas
  Crypto:          r/CryptoCurrency, r/Bitcoin, r/CryptoMarkets
  Side hustles:    r/sidehustle, r/WorkOnline
  Personal finance: r/personalfinance, r/financialindependence
  AI/Tech:         r/artificial, r/ChatGPT, r/AItools

Credentials needed in .env:
  REDDIT_CLIENT_ID      — from reddit.com/prefs/apps → "script" app
  REDDIT_CLIENT_SECRET  — same page
  REDDIT_USERNAME       — your Reddit username
  REDDIT_PASSWORD       — your Reddit password
  REDDIT_USER_AGENT     — e.g. "WheellsVerse/1.0 by u/yourusername"
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("reddit")

# ── Subreddit map by content niche ────────────────────────────────────────────

SUBREDDIT_MAP = {
    "passive_income": [
        "passiveincome",
        "passive_income_ideas",
        "financialindependence",
    ],
    "crypto": [
        "CryptoCurrency",
        "Bitcoin",
        "CryptoMarkets",
    ],
    "side_hustle": [
        "sidehustle",
        "WorkOnline",
        "beermoney",
    ],
    "personal_finance": [
        "personalfinance",
        "financialindependence",
        "Frugal",
    ],
    "ai_tools": [
        "artificial",
        "ChatGPT",
        "singularity",
    ],
    "investing": [
        "investing",
        "stocks",
        "ValueInvesting",
    ],
}

# Keywords → niche mapping for auto-routing
NICHE_KEYWORDS = {
    "passive_income": ["passive", "income stream", "residual", "dividend", "royalt"],
    "crypto": ["bitcoin", "crypto", "blockchain", "ethereum", "btc", "eth", "defi", "nft"],
    "side_hustle": ["side hustle", "freelance", "gig", "fiverr", "upwork", "extra income"],
    "personal_finance": ["budget", "debt", "savings", "emergency fund", "net worth", "frugal"],
    "ai_tools": ["ai tool", "chatgpt", "openai", "automation", "prompt", "llm"],
    "investing": ["invest", "stock", "portfolio", "etf", "robinhood", "brokerage"],
}


class RedditClient:

    def __init__(self):
        self.client_id = os.getenv("REDDIT_CLIENT_ID", "")
        self.client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        self.username = os.getenv("REDDIT_USERNAME", "")
        self.password = os.getenv("REDDIT_PASSWORD", "")
        self.user_agent = os.getenv(
            "REDDIT_USER_AGENT",
            f"WheellsVerse/1.0 by u/{os.getenv('REDDIT_USERNAME', 'wheellsverse')}"
        )
        self._reddit = None

    def _get_reddit(self):
        if self._reddit is None:
            try:
                import praw
            except ImportError:
                raise RuntimeError(
                    "praw not installed. Run: pip install praw"
                )
            if not all([self.client_id, self.client_secret,
                        self.username, self.password]):
                raise RuntimeError(
                    "Reddit credentials missing. Add to .env:\n"
                    "  REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,\n"
                    "  REDDIT_USERNAME, REDDIT_PASSWORD"
                )
            self._reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                username=self.username,
                password=self.password,
                user_agent=self.user_agent,
            )
        return self._reddit

    # ── Niche detection ───────────────────────────────────────────────────────

    def detect_niche(self, text: str) -> str:
        """Auto-detect the best niche/subreddit group for a piece of content."""
        text_lower = text.lower()
        scores = {niche: 0 for niche in NICHE_KEYWORDS}
        for niche, keywords in NICHE_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    scores[niche] += 1
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "passive_income"

    def get_target_subreddits(self, niche: str, limit: int = 2) -> List[str]:
        """Return the top subreddits for a niche."""
        return SUBREDDIT_MAP.get(niche, SUBREDDIT_MAP["passive_income"])[:limit]

    # ── Posting ───────────────────────────────────────────────────────────────

    def post_self(self, subreddit: str, title: str, body: str) -> Dict:
        """
        Submit a self (text) post to a subreddit.
        Returns {id, url, subreddit, title}.
        """
        r = self._get_reddit()
        sub = r.subreddit(subreddit)
        submission = sub.submit(title=title[:300], selftext=body)
        url = f"https://reddit.com{submission.permalink}"
        logger.info(f"Reddit post submitted: r/{subreddit} — {url}")
        return {
            "id": submission.id,
            "url": url,
            "subreddit": subreddit,
            "title": title[:80],
        }

    def post_to_niche(
        self,
        title: str,
        body: str,
        niche: Optional[str] = None,
        subreddits: Optional[List[str]] = None,
        delay_seconds: int = 30,
    ) -> List[Dict]:
        """
        Post content to 1-2 subreddits relevant to the niche.
        delay_seconds: pause between posts to avoid spam detection.
        Returns list of post results.
        """
        if subreddits:
            targets = subreddits[:2]
        else:
            detected_niche = niche or self.detect_niche(body + " " + title)
            targets = self.get_target_subreddits(detected_niche)

        results = []
        for i, sub in enumerate(targets):
            if i > 0 and delay_seconds:
                time.sleep(delay_seconds)
            try:
                result = self.post_self(sub, title, body)
                results.append({**result, "status": "posted"})
                logger.info(f"Posted to r/{sub}: {result['url']}")
            except Exception as e:
                logger.error(f"Reddit post failed (r/{sub}): {e}")
                results.append({"subreddit": sub, "status": "error", "error": str(e)})

        return results

    def post_from_repurposed(self, repurposed_output: Dict) -> List[Dict]:
        """
        Post to Reddit using content from core/repurpose.py output.
        Expects repurposed_output["formats"]["reddit_post"] to exist.
        """
        reddit_content = repurposed_output.get("formats", {}).get("reddit_post", "")
        title = repurposed_output.get("title", "")

        if not reddit_content:
            return [{"status": "skipped", "reason": "No reddit_post in repurposed output"}]

        # Parse "TITLE: ...\n\n{body}" format from repurpose.py
        lines = reddit_content.splitlines()
        post_title = title
        body = reddit_content

        if lines and lines[0].startswith("TITLE:"):
            post_title = lines[0].replace("TITLE:", "").strip() or title
            body = "\n".join(lines[2:]).strip()

        niche = self.detect_niche(body + " " + post_title)
        return self.post_to_niche(title=post_title, body=body, niche=niche)

    # ── Status ────────────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        return bool(self.client_id and self.client_secret
                    and self.username and self.password)

    def get_status(self) -> Dict:
        if not self.is_connected():
            return {
                "connected": False,
                "reason": "Add REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, "
                          "REDDIT_USERNAME, REDDIT_PASSWORD to .env",
            }
        try:
            r = self._get_reddit()
            user = r.user.me()
            return {
                "connected": True,
                "username": str(user.name),
                "karma": user.link_karma + user.comment_karma,
                "account_age": str(user.created_utc),
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}


# ── Singleton ─────────────────────────────────────────────────────────────────

_client: Optional[RedditClient] = None


def get_reddit() -> RedditClient:
    global _client
    if _client is None:
        _client = RedditClient()
    return _client
