#!/usr/bin/env python3
"""
pipelines/content_pipeline.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Money-Making Content Pipeline

Full flow:
  Trend Fetch → Topic Scoring → Content Generation → SEO Optimization
  → Monetization Injection → Multi-Format Output → Publish → Analytics

Runs standalone or triggered by the Decision Engine / API.
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("content_pipeline")

OUTPUTS_DIR = ROOT / "outputs" / "content"
REPORTS_DIR = ROOT / "outputs" / "reports"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Topic Scorer ─────────────────────────────────────────────────────────────

class TopicScorer:
    """
    Scores candidate topics by frequency, relevance to niche, and recency.
    Returns top-N ranked topics.
    """

    # Niche: AI tools for making money, stock insights, crypto trends
    NICHE_KEYWORDS = [
        # AI + Tools
        "ai", "chatgpt", "openai", "gpt", "llm", "automation", "ai tools",
        "make money with ai", "ai income", "ai side hustle",
        # Finance + Markets
        "crypto", "bitcoin", "ethereum", "blockchain", "defi", "web3",
        "stocks", "investing", "stock market", "passive income", "trading",
        "portfolio", "dividends", "etf", "bull market", "bear market",
        # Business + Income
        "make money", "income", "side hustle", "revenue", "profit",
        "entrepreneurship", "startup", "saas", "affiliate", "online business",
    ]

    def score(self, topic: str, sources: List[str], recency_boost: float = 1.0) -> float:
        """Score a single topic."""
        t = topic.lower()
        relevance = sum(2.0 for kw in self.NICHE_KEYWORDS if kw in t)
        frequency = min(len(sources), 5) * 1.5
        length_penalty = max(0, 1.0 - (len(topic) / 80))
        return (relevance + frequency + length_penalty) * recency_boost

    def rank(self, raw_topics: List[Dict]) -> List[Dict]:
        """
        raw_topics: [{"text": "...", "sources": ["reddit","trends"], "ts": epoch}]
        Returns list sorted by score descending.
        """
        now = time.time()
        scored = []
        seen = set()
        for item in raw_topics:
            text = item.get("text", "").strip()
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            age_hours = (now - item.get("ts", now)) / 3600
            recency = max(0.3, 1.0 - age_hours / 48)  # decay over 48h
            score = self.score(text, item.get("sources", []), recency)
            scored.append({**item, "score": round(score, 3)})
        return sorted(scored, key=lambda x: x["score"], reverse=True)


# ─── Content Generator ────────────────────────────────────────────────────────

class ContentGenerator:
    """
    Generates blog posts, Twitter threads, and LinkedIn posts using GPT.
    Each piece is SEO-optimized and monetization-ready.
    """

    def __init__(self, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model
        self.brand = os.getenv("BRAND_NAME", "WheellsVerse")
        self.author = os.getenv("AUTHOR_NAME", "J.K. Blaze")
        self.niche = os.getenv("BRAND_NICHE", "AI tools for making money, stock insights, and crypto trends")

    def _call(self, system: str, user: str, max_tokens: int = 2000) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.75,
        )
        return resp.choices[0].message.content.strip()

    def generate_blog_post(self, topic: str, keywords: List[str] = None) -> Dict:
        """Generate a 1000-1500 word SEO blog post."""
        kw_str = ", ".join(keywords or [topic])
        system = (
            f"You are {self.author}, a leading expert on {self.niche}. "
            f"You write for {self.brand}. Your style is bold, practical, and actionable. "
            f"You use short paragraphs, real examples, and numbered lists. "
            f"Always write in a way that drives readers to take action."
        )
        user = f"""Write a complete blog post on: "{topic}"

NICHE FOCUS: AI tools for making money, stock insights, and crypto trends.
Every piece must be relevant to people who want to make money using AI or by investing.

REQUIREMENTS:
- Length: 1000-1500 words
- SEO keywords to include naturally: {kw_str}
- Structure:
  1. Compelling H1 title (include main keyword, make it about making money or AI)
  2. ## Hook — 2-3 sentences that shock, challenge, or promise a specific result.
     Example: "Most people are leaving $500/month on the table by not using this one AI tool."
  3. ## The Opportunity — explain the trend and WHY it matters for income right now
  4. 3-4 H2 sections with practical, step-by-step value content
     Include real tools, platforms, or strategies in each section
  5. ## How to Take Action — numbered steps the reader can start TODAY
  6. ## Free Resources — mention 2-3 free tools or resources
  7. ## CTA — "Join our free daily AI + market signals newsletter at [BRAND_LINK]"
     Also include: "Download our free AI Entrepreneur Blueprint"
- Tone: confident, direct, results-focused
- Use numbers, percentages, and specific tool names
- Include internal linking hints as [LINK: related topic]
- End with: "## Frequently Asked Questions" with 3 Q&As

Return the full article in Markdown format."""

        content = self._call(system, user, max_tokens=2200)

        # Extract title from first H1
        title = topic
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break

        return {
            "type": "blog_post",
            "topic": topic,
            "title": title,
            "content": content,
            "word_count": len(content.split()),
            "keywords": keywords or [topic],
        }

    def generate_twitter_thread(self, topic: str, blog_title: str = "") -> Dict:
        """Generate a 7-10 tweet Twitter/X thread."""
        system = (
            f"You are {self.author} on Twitter/X. You write viral threads about {self.niche}. "
            f"Each tweet is punchy, uses numbers or shocking facts, and makes people want to read the next one."
        )
        user = f"""Write a Twitter/X thread about: "{topic}"
Blog title: {blog_title or topic}

REQUIREMENTS:
- 7-10 tweets
- Tweet 1: Hook (shocking stat or bold claim, end with "🧵 Thread:")
- Tweets 2-8: One key insight per tweet, numbered (2/, 3/, etc.)
- Last tweet: CTA to read the full blog post + relevant hashtags
- Each tweet: max 280 characters
- Use emojis strategically (1-2 per tweet max)
- Make each tweet standalone but part of the story

Format as:
TWEET 1:
[tweet text]

TWEET 2:
[tweet text]
...etc"""

        content = self._call(system, user, max_tokens=800)
        tweets = self._parse_tweets(content)

        return {
            "type": "twitter_thread",
            "topic": topic,
            "content": content,
            "tweets": tweets,
            "count": len(tweets),
        }

    def _parse_tweets(self, raw: str) -> List[str]:
        tweets = []
        current = []
        for line in raw.split("\n"):
            if line.strip().startswith("TWEET ") and ":" in line:
                if current:
                    tweets.append(" ".join(current).strip())
                current = []
            elif line.strip():
                current.append(line.strip())
        if current:
            tweets.append(" ".join(current).strip())
        return [t for t in tweets if t]

    def generate_linkedin_post(self, topic: str, blog_title: str = "") -> Dict:
        """Generate a LinkedIn post (700-1000 chars)."""
        system = (
            f"You are {self.author}, a thought leader on {self.niche}. "
            f"Your LinkedIn posts mix personal insight with professional value. "
            f"You write for entrepreneurs, marketers, and ambitious professionals."
        )
        user = f"""Write a LinkedIn post about: "{topic}"

REQUIREMENTS:
- 700-1000 characters
- Start with a bold first line (no fluff intro)
- Use line breaks for readability (not walls of text)
- Share 1 personal insight or contrarian take
- Include 3-5 practical takeaways
- End with an engaging question to drive comments
- Add 5-8 relevant hashtags at the end
- Mention {self.brand} naturally once
- Professional but conversational tone

Write the full post text only."""

        content = self._call(system, user, max_tokens=400)
        return {
            "type": "linkedin_post",
            "topic": topic,
            "content": content,
            "char_count": len(content),
        }

    def generate_seo_meta(self, topic: str, title: str, blog_content: str) -> Dict:
        """Generate SEO metadata for the blog post."""
        system = "You are an SEO expert. Return JSON only."
        user = f"""Generate SEO metadata for this blog post.
Topic: {topic}
Title: {title}
Content excerpt: {blog_content[:500]}

Return ONLY valid JSON:
{{
  "meta_title": "60 chars max, include main keyword",
  "meta_description": "155 chars max, compelling, include keyword",
  "keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"],
  "slug": "url-friendly-slug",
  "h1": "Primary heading",
  "h2_suggestions": ["Heading 2", "Heading 3"],
  "schema_type": "Article",
  "estimated_reading_time": "X min read",
  "target_audience": "brief description"
}}"""
        try:
            raw = self._call(system, user, max_tokens=400)
            raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"SEO meta generation failed: {e}")
            slug = topic.lower().replace(" ", "-")[:50]
            return {
                "meta_title": title[:60],
                "meta_description": f"Learn about {topic}. Practical guide by {self.author}.",
                "keywords": [topic],
                "slug": slug,
                "h1": title,
                "h2_suggestions": [],
                "schema_type": "Article",
                "estimated_reading_time": "5 min read",
                "target_audience": "entrepreneurs and marketers",
            }


# ─── Content Pipeline ──────────────────────────────────────────────────────────

class ContentPipeline:
    """
    Full money-making content pipeline.

    Steps:
      1. fetch_trends()       — Google Trends + Reddit + News
      2. score_topics()       — rank by frequency, relevance, recency
      3. generate_content()   — blog + Twitter thread + LinkedIn post
      4. optimize_seo()       — meta tags, keywords, slug
      5. inject_monetization() — affiliate links, CTAs, lead magnets
      6. save_outputs()       — /outputs/content/
      7. track_analytics()    — /outputs/reports/
    """

    def __init__(self, memory=None, intelligence=None):
        self.generator = ContentGenerator()
        self.scorer = TopicScorer()
        self.memory = memory
        self.intelligence = intelligence
        self._run_history: List[Dict] = []

    # ── Step 1: Fetch Trends ──────────────────────────────────────────────────

    def fetch_trends(self) -> List[Dict]:
        """Aggregate trending topics from all available sources."""
        raw_topics: List[Dict] = []
        now = time.time()

        # Google Trends
        try:
            from core.integrations import get_integrations
            hub = get_integrations()
            data = hub.get_google_trends()
            for t in data.get("trending_now", [])[:20]:
                raw_topics.append({"text": t, "sources": ["google_trends"], "ts": now})
        except Exception as e:
            logger.warning(f"Google Trends fetch failed: {e}")

        # Reddit
        try:
            from core.integrations import get_integrations
            hub = get_integrations()
            feed = hub.get_entrepreneurship_feed()
            for post in feed.get("posts", [])[:15]:
                raw_topics.append({
                    "text": post.get("title", "")[:80],
                    "sources": ["reddit"],
                    "ts": now,
                    "score_raw": post.get("score", 0),
                })
        except Exception as e:
            logger.warning(f"Reddit fetch failed: {e}")

        # News headlines
        try:
            from core.integrations import get_integrations
            hub = get_integrations()
            news = hub.get_business_news()
            for a in news.get("articles", [])[:10]:
                raw_topics.append({
                    "text": a.get("title", "")[:80],
                    "sources": ["news"],
                    "ts": now,
                })
        except Exception as e:
            logger.warning(f"News fetch failed: {e}")

        logger.info(f"Fetched {len(raw_topics)} raw topics from all sources")
        return raw_topics

    # ── Step 2: Score Topics ──────────────────────────────────────────────────

    def score_topics(self, raw_topics: List[Dict], top_n: int = 3) -> List[Dict]:
        """Rank topics, optionally boosting those with high past performance."""
        ranked = self.scorer.rank(raw_topics)

        # Boost topics that performed well historically
        if self.intelligence:
            try:
                perf = self.intelligence.get_topic_scores()
                for item in ranked:
                    key = item["text"].lower()[:30]
                    if key in perf:
                        item["score"] *= (1 + perf[key] / 100)
                ranked.sort(key=lambda x: x["score"], reverse=True)
            except Exception:
                pass

        selected = ranked[:top_n]
        logger.info(f"Selected top {len(selected)} topics: {[t['text'][:40] for t in selected]}")
        return selected

    # ── Step 3 + 4: Generate + SEO ────────────────────────────────────────────

    def generate_content_piece(self, topic: str) -> Dict:
        """
        Generate all content formats for one topic.
        Returns structured piece with blog, social, and SEO data.
        """
        logger.info(f"Generating content for: {topic[:60]}")
        piece: Dict[str, Any] = {
            "topic": topic,
            "generated_at": datetime.now().isoformat(),
        }

        # Blog post (most important — drives SEO + monetization)
        blog = self.generator.generate_blog_post(topic)
        piece["blog"] = blog

        # SEO metadata
        seo = self.generator.generate_seo_meta(topic, blog["title"], blog["content"])
        piece["seo"] = seo

        # Social content
        piece["twitter"] = self.generator.generate_twitter_thread(topic, blog["title"])
        piece["linkedin"] = self.generator.generate_linkedin_post(topic, blog["title"])

        return piece

    # ── Step 5: Monetization ─────────────────────────────────────────────────

    def inject_monetization(self, piece: Dict) -> Dict:
        """Inject affiliate links, CTAs, and lead magnets into content."""
        try:
            from core.monetization import get_monetization_engine
            engine = get_monetization_engine()

            # Inject into blog post
            if "blog" in piece:
                piece["blog"]["content"] = engine.inject_affiliate_links(
                    piece["blog"]["content"], piece["topic"]
                )
                piece["blog"]["content"] += "\n\n" + engine.generate_cta(piece["topic"])

            # Add lead magnet HTML
            piece["lead_magnet_html"] = engine.generate_email_capture(
                piece["blog"]["title"],
                piece["topic"],
            )

            # Generate affiliate summary
            piece["monetization"] = {
                "cta_injected": True,
                "affiliate_links": True,
                "lead_magnet_created": True,
            }
        except Exception as e:
            logger.warning(f"Monetization injection failed (non-fatal): {e}")
            piece["monetization"] = {"error": str(e)}

        return piece

    # ── Step 6: Save Outputs ─────────────────────────────────────────────────

    def save_outputs(self, piece: Dict) -> Dict[str, Path]:
        """Save all content formats to /outputs/content/."""
        slug = piece.get("seo", {}).get("slug") or _slugify(piece["topic"])
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = OUTPUTS_DIR / f"{ts_str}_{slug[:40]}"
        base_dir.mkdir(parents=True, exist_ok=True)
        saved: Dict[str, Path] = {}

        # Blog post markdown
        if "blog" in piece:
            blog = piece["blog"]
            seo = piece.get("seo", {})
            md_content = (
                f"---\n"
                f"title: \"{blog['title']}\"\n"
                f"slug: {seo.get('slug', slug)}\n"
                f"meta_title: {seo.get('meta_title', blog['title'])}\n"
                f"meta_description: {seo.get('meta_description', '')}\n"
                f"keywords: {', '.join(seo.get('keywords', []))}\n"
                f"reading_time: {seo.get('estimated_reading_time', '5 min')}\n"
                f"generated_at: {piece['generated_at']}\n"
                f"author: {self.generator.author}\n"
                f"---\n\n"
                f"{blog['content']}"
            )
            path = base_dir / "blog_post.md"
            path.write_text(md_content, encoding="utf-8")
            saved["blog_md"] = path

            # Blog HTML (styled)
            html = _blog_to_html(blog["title"], blog["content"],
                                 seo, self.generator.author, self.generator.brand)
            path_html = base_dir / "blog_post.html"
            path_html.write_text(html, encoding="utf-8")
            saved["blog_html"] = path_html

        # Twitter thread
        if "twitter" in piece:
            path = base_dir / "twitter_thread.txt"
            path.write_text(piece["twitter"]["content"], encoding="utf-8")
            saved["twitter"] = path

        # LinkedIn post
        if "linkedin" in piece:
            path = base_dir / "linkedin_post.txt"
            path.write_text(piece["linkedin"]["content"], encoding="utf-8")
            saved["linkedin"] = path

        # Lead magnet HTML
        if "lead_magnet_html" in piece:
            path = base_dir / "lead_magnet.html"
            path.write_text(piece["lead_magnet_html"], encoding="utf-8")
            saved["lead_magnet"] = path

        # Full piece JSON
        safe_piece = {k: v for k, v in piece.items() if k != "lead_magnet_html"}
        path = base_dir / "content_data.json"
        path.write_text(json.dumps(safe_piece, indent=2, ensure_ascii=False), encoding="utf-8")
        saved["json"] = path

        piece["output_dir"] = str(base_dir)
        piece["saved_files"] = {k: str(v) for k, v in saved.items()}
        logger.info(f"Saved {len(saved)} files → {base_dir.name}")
        return saved

    # ── Step 7: Analytics ─────────────────────────────────────────────────────

    def track_analytics(self, run_result: Dict) -> Path:
        """Append run metrics to the analytics report."""
        report_path = REPORTS_DIR / "content_analytics.json"
        records: List[Dict] = []
        if report_path.exists():
            try:
                records = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        entry = {
            "run_at": datetime.now().isoformat(),
            "topics_fetched": run_result.get("topics_fetched", 0),
            "pieces_created": run_result.get("pieces_created", 0),
            "pieces_published": run_result.get("pieces_published", 0),
            "topics": [p.get("topic", "")[:60] for p in run_result.get("pieces", [])],
            "word_counts": [p.get("blog", {}).get("word_count", 0) for p in run_result.get("pieces", [])],
            "estimated_reach": run_result.get("estimated_reach", 0),
            "errors": run_result.get("errors", []),
        }
        records.insert(0, entry)
        records = records[:500]  # keep last 500 runs
        report_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

        # Also save to memory if available
        if self.memory:
            try:
                self.memory.save(
                    key=f"content_run_{datetime.now().strftime('%Y%m%d_%H%M')}",
                    content=json.dumps(entry),
                    source="content_pipeline",
                    tags=["analytics", "content"],
                )
            except Exception:
                pass

        return report_path

    # ── Master Run ─────────────────────────────────────────────────────────────

    def run(
        self,
        topics: Optional[List[str]] = None,
        top_n: int = 3,
        publish: bool = False,
        publish_platforms: Optional[List[str]] = None,
    ) -> Dict:
        """
        Execute the full content pipeline.

        Args:
            topics:            Override trend fetching with explicit topics.
            top_n:             Number of top topics to generate content for.
            publish:           Auto-publish after generation.
            publish_platforms: ["wordpress","medium","static"] subsets.

        Returns structured result dict with all pieces and stats.
        """
        start = time.time()
        result: Dict[str, Any] = {
            "run_at": datetime.now().isoformat(),
            "pieces": [],
            "errors": [],
            "published": [],
            "topics_fetched": 0,
            "pieces_created": 0,
            "pieces_published": 0,
            "estimated_reach": 0,
        }

        # ── 1. Topics
        if topics:
            raw_topics = [{"text": t, "sources": ["manual"], "ts": time.time()} for t in topics]
        else:
            raw_topics = self.fetch_trends()
        result["topics_fetched"] = len(raw_topics)

        if not raw_topics:
            result["errors"].append("No topics found from any source")
            return result

        # ── 2. Score
        selected_topics = self.score_topics(raw_topics, top_n=top_n)
        if not selected_topics:
            result["errors"].append("Topic scoring returned no results")
            return result

        # ── 3–5. Generate, SEO, Monetize
        for topic_item in selected_topics:
            topic = topic_item["text"]
            try:
                piece = self.generate_content_piece(topic)
                piece = self.inject_monetization(piece)
                self.save_outputs(piece)
                result["pieces"].append(piece)
                result["pieces_created"] += 1

                # Save to memory
                if self.memory:
                    try:
                        self.memory.save(
                            key=f"content_{_slugify(topic)[:40]}_{datetime.now().strftime('%Y%m%d')}",
                            content=piece.get("blog", {}).get("title", topic),
                            source="content_pipeline",
                            tags=["content", "blog", topic_item.get("sources", [""])[0]],
                            metadata={"topic": topic, "word_count": piece.get("blog", {}).get("word_count", 0)},
                        )
                    except Exception:
                        pass

                # Report to intelligence
                if self.intelligence:
                    try:
                        self.intelligence.record_content_created(topic, piece)
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"Content generation failed for '{topic}': {e}")
                result["errors"].append(f"{topic[:40]}: {e}")

        # ── 5b. Auto-post to social (browser automation)
        self._auto_post_social(result["pieces"])

        # ── 6. Publish (optional)
        if publish and result["pieces"]:
            try:
                from core.publisher import get_publisher
                pub = get_publisher()
                for piece in result["pieces"]:
                    platforms = publish_platforms or ["static"]
                    pub_result = pub.publish_content(piece, platforms=platforms)
                    result["published"].append(pub_result)
                    result["pieces_published"] += pub_result.get("success_count", 0)
            except Exception as e:
                logger.error(f"Publishing failed: {e}")
                result["errors"].append(f"publish: {e}")

        # ── 7. Analytics
        result["duration_s"] = round(time.time() - start, 2)
        result["estimated_reach"] = result["pieces_created"] * 1500  # rough estimate
        self.track_analytics(result)

        # Notify via Slack
        self._send_completion_notify(result)

        # Store run history (last 50)
        self._run_history.insert(0, {
            "run_at": result["run_at"],
            "pieces": result["pieces_created"],
            "published": result["pieces_published"],
            "errors": len(result["errors"]),
            "duration_s": result["duration_s"],
            "topics": [t["text"][:50] for t in selected_topics],
        })
        self._run_history = self._run_history[:50]

        logger.info(
            f"Content pipeline complete — "
            f"{result['pieces_created']} pieces | "
            f"{result['pieces_published']} published | "
            f"{len(result['errors'])} errors | "
            f"{result['duration_s']}s"
        )
        return result

    def _auto_post_social(self, pieces: List[Dict]):
        """
        Auto-post generated content to Twitter/X and LinkedIn if:
          - AUTO_POST_TWITTER=true (or AUTO_POST_LINKEDIN=true) in .env
          - Matching credentials are set
          - Playwright browsers are available
        """
        auto_tw = os.getenv("AUTO_POST_TWITTER", "false").lower() == "true"
        auto_li = os.getenv("AUTO_POST_LINKEDIN", "false").lower() == "true"
        if not auto_tw and not auto_li:
            return

        try:
            from core.browser import is_available, post_twitter_thread, post_linkedin
            if not is_available():
                logger.warning("Auto-post skipped — Playwright not available")
                return
        except ImportError:
            logger.warning("Auto-post skipped — core.browser not found")
            return

        for piece in pieces:
            topic = piece.get("topic", "")[:60]

            if auto_tw and os.getenv("TWITTER_EMAIL") and os.getenv("TWITTER_PASSWORD"):
                tweets = piece.get("twitter", {}).get("tweets", [])
                if tweets:
                    try:
                        post_twitter_thread(tweets)
                        logger.info(f"Auto-posted Twitter thread: {topic}")
                    except Exception as e:
                        logger.error(f"Twitter auto-post failed for '{topic}': {e}")

            if auto_li and os.getenv("LINKEDIN_EMAIL") and os.getenv("LINKEDIN_PASSWORD"):
                li_content = piece.get("linkedin", {}).get("content", "")
                if li_content:
                    try:
                        post_linkedin(li_content)
                        logger.info(f"Auto-posted LinkedIn: {topic}")
                    except Exception as e:
                        logger.error(f"LinkedIn auto-post failed for '{topic}': {e}")

    def _send_completion_notify(self, result: Dict):
        try:
            from core.output_automation import get_automator
            auto = get_automator()
            topics_str = ", ".join(
                p.get("topic", "")[:40] for p in result["pieces"][:3]
            )
            msg = (
                f"✍️ *Content Pipeline Complete*\n"
                f"• Pieces created: {result['pieces_created']}\n"
                f"• Published: {result['pieces_published']}\n"
                f"• Topics: {topics_str}\n"
                f"• Duration: {result['duration_s']}s"
            )
            auto.slack.send(msg)
        except Exception:
            pass

    def get_history(self, limit: int = 20) -> List[Dict]:
        return self._run_history[:limit]

    def get_analytics(self) -> List[Dict]:
        report_path = REPORTS_DIR / "content_analytics.json"
        if report_path.exists():
            try:
                return json.loads(report_path.read_text(encoding="utf-8"))[:50]
            except Exception:
                pass
        return []


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    import re
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:60]


def _blog_to_html(title: str, content: str, seo: Dict, author: str, brand: str) -> str:
    """Convert markdown blog post to styled standalone HTML."""
    import re
    # Basic markdown → HTML
    html_body = content
    html_body = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html_body, flags=re.M)
    html_body = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html_body, flags=re.M)
    html_body = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html_body, flags=re.M)
    html_body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_body)
    html_body = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html_body)
    html_body = re.sub(r"^- (.+)$", r"<li>\1</li>", html_body, flags=re.M)
    html_body = re.sub(r"(<li>.*</li>)", r"<ul>\1</ul>", html_body, flags=re.S)
    html_body = "\n".join(
        f"<p>{line}</p>" if line and not line.startswith("<") else line
        for line in html_body.split("\n")
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{seo.get('meta_title', title)}</title>
<meta name="description" content="{seo.get('meta_description', '')}">
<meta name="keywords" content="{', '.join(seo.get('keywords', []))}">
<meta property="og:title" content="{seo.get('meta_title', title)}">
<meta property="og:description" content="{seo.get('meta_description', '')}">
<style>
  body{{font-family:'Georgia',serif;max-width:780px;margin:60px auto;padding:0 20px;
        color:#222;line-height:1.8;background:#fff}}
  h1{{font-size:2rem;color:#111;margin-bottom:.4rem;line-height:1.2}}
  h2{{font-size:1.4rem;color:#333;margin-top:2rem;border-left:4px solid #00d4ff;padding-left:12px}}
  h3{{font-size:1.15rem;color:#444;margin-top:1.5rem}}
  p{{margin:.9rem 0}}
  ul{{padding-left:1.5rem}}
  li{{margin:.4rem 0}}
  a{{color:#0077cc;text-decoration:none}}a:hover{{text-decoration:underline}}
  .meta{{color:#777;font-size:.85rem;margin-bottom:2rem;border-bottom:1px solid #eee;padding-bottom:1rem}}
  .cta-box{{background:#f0f9ff;border:2px solid #00d4ff;border-radius:8px;padding:20px;margin:2rem 0;text-align:center}}
  .cta-btn{{background:#00d4ff;color:#000;padding:10px 24px;border-radius:6px;font-weight:700;display:inline-block;margin-top:10px}}
  footer{{margin-top:3rem;padding-top:1rem;border-top:1px solid #eee;color:#999;font-size:.8rem}}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">By {author} · {brand} · {datetime.now().strftime('%B %d, %Y')} · {seo.get('estimated_reading_time', '5 min read')}</div>
{html_body}
<footer>{brand} · Generated with AI · {datetime.now().strftime('%Y')}</footer>
</body>
</html>"""


# ─── Singleton ────────────────────────────────────────────────────────────────

_pipeline: Optional[ContentPipeline] = None


def get_content_pipeline(memory=None, intelligence=None) -> ContentPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ContentPipeline(memory=memory, intelligence=intelligence)
    return _pipeline
