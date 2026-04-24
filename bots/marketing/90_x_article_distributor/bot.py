#!/usr/bin/env python3
"""
Bot #90 — X Article Distributor
Category: marketing
Purpose: Distribution-first counterweight to the revenue gate. The gate
         PAUSES new content creation when audience is small; THIS bot
         takes the content you already have and gets it in front of
         humans on X. It should run regardless of audience size — that's
         how the audience grows.

Posts one tweet per run, linking to the canonical blog article that's
been distributed least recently (or never). Rotates through a small bank
of hook templates so consecutive tweets don't look stamped-out.

ACTIONS
  link   (default)  Post one tweet: hook + article URL.
  thread            Post a short thread built from the article.
  status            Print distribution state without posting.
  backfill          Queue every never-distributed article for immediate
                    distribution on subsequent runs. Doesn't post itself.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
BLOG_DIR = ROOT / "frontend" / "blog"
STATE_FILE = ROOT / "data" / "x_distribution_state.json"
DEFAULT_SITE = "https://wheellsverse.com"

# Hook templates — rotated per-run so the feed doesn't look botted. `{title}`
# is the article H1 (cleaned); `{url}` is the canonical URL with UTM.
_HOOK_TEMPLATES = [
    "💡 {title}\n\n{url}",
    "New post ↓\n\n{title}\n\n{url}",
    "If you're still sleeping on this, read it:\n\n{title}\n\n{url}",
    "Most people get this wrong.\n\n{title}\n\n{url}",
    "5-minute read that might actually help:\n\n{title}\n\n{url}",
    "Quick thread-worthy read:\n\n{title}\n\n{url}",
    "Worth 3 minutes of your day:\n\n{title}\n\n{url}",
]

# Slugs to exclude from distribution — index page + meta content.
_SKIP_SLUGS = {"index", "landing-page-copy"}


class XArticleDistributorBot(BaseBot):

    # The whole point of this bot is to run when content creation is
    # gated. Skipping the audience check is intentional.
    revenue_gate_enabled = False

    # Dedup is handled via our own state file (distribution history), and
    # the base dedup would false-fire on `action="link"` being the default
    # every run. Our per-article dedup is stricter.
    dedup_enabled = False

    def __init__(self):
        super().__init__("90_x_article_distributor", "marketing")
        self.site_base = os.getenv("CTA_URL", DEFAULT_SITE).rstrip("/")

    # ─── State persistence ─────────────────────────────────────────────

    def _load_state(self) -> Dict[str, str]:
        """Return {slug: iso_timestamp_last_distributed}. Missing file = empty."""
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text())
            except Exception:
                # Corrupted state — don't crash, start fresh and log it so
                # the operator can investigate.
                self.logger.warning("distribution state unreadable, resetting")
                return {}
        return {}

    def _save_state(self, state: Dict[str, str]) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))

    # ─── Article selection ─────────────────────────────────────────────

    def _list_canonical_slugs(self) -> List[str]:
        if not BLOG_DIR.exists():
            return []
        return sorted(
            p.stem for p in BLOG_DIR.iterdir()
            if p.is_file() and p.suffix == ".html" and p.stem not in _SKIP_SLUGS
            # _archive/ is a subdir so it's already excluded by p.is_file()
            # on iterdir + suffix check
        )

    def _pick_next(self, state: Dict[str, str]) -> Optional[str]:
        """Return the slug that has been distributed least recently, or
        None if there's nothing to distribute."""
        slugs = self._list_canonical_slugs()
        if not slugs:
            return None
        # Never-distributed articles win first (empty string sorts before
        # any timestamp). Among those, alphabetical — deterministic.
        slugs.sort(key=lambda s: (state.get(s, ""), s))
        return slugs[0]

    # ─── HTML → tweet text ─────────────────────────────────────────────

    @staticmethod
    def _extract_title(html: str, fallback_slug: str) -> str:
        # Prefer <h1> over <title> — the <title> tag often includes a
        # "— WheellsVerse" suffix we don't want in the tweet.
        m = re.search(r"<h1[^>]*>(.+?)</h1>", html, re.IGNORECASE | re.DOTALL)
        if m:
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()
        m = re.search(r"<title>([^<]+?)(?:\s+—\s+WheellsVerse)?</title>",
                      html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return fallback_slug.replace("-", " ").title()

    @staticmethod
    def _extract_description(html: str) -> str:
        m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"',
                      html, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _compose_link_tweet(self, slug: str, title: str) -> str:
        """Build a single tweet: rotating template + trimmed title + URL."""
        # UTM so you can separate X-driven traffic from organic in analytics.
        url = f"{self.site_base}/blog/{slug}?utm_source=x&utm_medium=social&utm_campaign=distribution"
        template = random.choice(_HOOK_TEMPLATES)
        # Reserve ~40 chars for the URL so we never blow the 280-cap.
        title_budget = 260 - len(template.replace("{title}", "").replace("{url}", "")) - len(url)
        if title_budget < 20:
            # Pathological case: very long URL. Fall back to minimal template.
            template = "{title}\n\n{url}"
            title_budget = 280 - len(url) - 4
        trimmed = title if len(title) <= title_budget else title[:title_budget - 1].rstrip() + "…"
        return template.format(title=trimmed, url=url)[:280]

    # ─── Actions ───────────────────────────────────────────────────────

    def run(self, action: str = "link", **kwargs):
        action = action or "link"
        dispatch = {
            "link": self._post_link,
            "thread": self._post_thread,
            "status": self._show_status,
            "backfill": self._backfill,
        }
        fn = dispatch.get(action, self._post_link)
        return fn(**kwargs)

    def _post_link(self, **_) -> Dict:
        """Pick one article, post one tweet. The core of this bot."""
        from core.twitter import get_twitter

        state = self._load_state()
        slug = self._pick_next(state)
        if not slug:
            return {"status": "idle", "reason": "no canonical articles on disk"}

        path = BLOG_DIR / f"{slug}.html"
        html = path.read_text(encoding="utf-8")
        title = self._extract_title(html, slug)
        tweet_text = self._compose_link_tweet(slug, title)

        client = get_twitter()
        if not client.is_connected():
            return {"status": "error",
                    "reason": "Twitter client not connected — check .env creds"}

        # This is the only call that can spend API quota or trigger the
        # browser fallback. Everything before is read-only.
        try:
            result = client.post_tweet(tweet_text)
        except Exception as e:
            # Don't mark distributed on failure — we want to retry this
            # article on the next run.
            self.logger.error("X post failed for %s: %s", slug, e)
            raise

        state[slug] = datetime.now(timezone.utc).isoformat()
        self._save_state(state)

        # Mirror to output dir so the dashboard / compliance reader can see it
        out = self.save_json({
            "slug": slug,
            "title": title,
            "tweet_text": tweet_text,
            "tweet": result,
            "distributed_at": state[slug],
        })
        self.logger.info("Distributed %s → %s", slug, result.get("url", "(unknown)"))
        return {"status": "posted", "slug": slug, "tweet": result, "file": str(out)}

    def _post_thread(self, **_) -> Dict:
        """Build a thread from the article and post it.

        Uses the existing TwitterClient.format_thread_from_markdown, but
        feeds it a markdown-ish distillation of the HTML (paragraphs only,
        no styling). Works on most articles; not as good as the original
        source markdown would be (which isn't persisted).
        """
        from core.twitter import get_twitter

        state = self._load_state()
        slug = self._pick_next(state)
        if not slug:
            return {"status": "idle", "reason": "no canonical articles on disk"}

        path = BLOG_DIR / f"{slug}.html"
        html = path.read_text(encoding="utf-8")
        title = self._extract_title(html, slug)

        # Strip everything that's not text. Approximate markdown.
        body = re.sub(r"<aside[^>]*>.*?</aside>", "", html,
                      flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<script[^>]*>.*?</script>", "", body,
                      flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<style[^>]*>.*?</style>", "", body,
                      flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<(?:p|h[23]|li)[^>]*>", "\n", body, flags=re.IGNORECASE)
        body = re.sub(r"<[^>]+>", "", body)
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        md = f"# {title}\n\n{body}"

        tweets = get_twitter().format_thread_from_markdown(md, max_tweets=6)
        # Append a final CTA with the canonical URL so readers can click through.
        url = f"{self.site_base}/blog/{slug}?utm_source=x&utm_medium=social&utm_campaign=thread"
        tweets[-1] = (tweets[-1] + "\n\n→ " + url)[:280]

        client = get_twitter()
        if not client.is_connected():
            return {"status": "error", "reason": "Twitter client not connected"}

        try:
            results = client.post_thread(tweets)
        except Exception as e:
            self.logger.error("X thread failed for %s: %s", slug, e)
            raise

        state[slug] = datetime.now(timezone.utc).isoformat()
        self._save_state(state)
        out = self.save_json({
            "slug": slug, "title": title, "thread": results,
            "distributed_at": state[slug],
        })
        self.logger.info("Threaded %s → %d tweets", slug, len(results))
        return {"status": "posted", "slug": slug, "thread": results, "file": str(out)}

    def _show_status(self, **_) -> Dict:
        state = self._load_state()
        slugs = self._list_canonical_slugs()
        distributed = [s for s in slugs if s in state]
        pending = [s for s in slugs if s not in state]
        return {
            "status": "info",
            "total_articles": len(slugs),
            "distributed": len(distributed),
            "pending": len(pending),
            "next_up": self._pick_next(state),
            "pending_sample": pending[:10],
        }

    def _backfill(self, **_) -> Dict:
        """No-op queue verification. Lists articles that are pending
        distribution. Doesn't post — safe to call often."""
        return self._show_status()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="X Article Distributor")
    parser.add_argument("--action", default="link",
                        choices=["link", "thread", "status", "backfill"])
    args = parser.parse_args()
    bot = XArticleDistributorBot()
    result = bot.execute(action=args.action)
    print(json.dumps(result, indent=2, default=str))
