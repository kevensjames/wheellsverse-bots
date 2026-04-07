#!/usr/bin/env python3
"""
core/publisher.py
─────────────────────────────────────────────────────────────────────────────
Multi-Platform Content Publisher

Supported platforms:
  • WordPress  — REST API (Application Password auth)
  • Medium     — Integration Token API
  • Static     — HTML file export (for GitHub Pages / Netlify / any hosting)
  • Ghost      — Admin API (optional)

Configuration (.env):
  WORDPRESS_URL       — e.g. https://yourdomain.com
  WORDPRESS_USER      — WordPress username
  WORDPRESS_APP_PASS  — WordPress Application Password (no spaces)
  MEDIUM_TOKEN        — Medium Integration Token
  MEDIUM_USER_ID      — Medium user ID (auto-fetched if not set)
  GHOST_URL           — Ghost blog URL
  GHOST_ADMIN_KEY     — Ghost Admin API key (format: id:secret)
  STATIC_OUTPUT_DIR   — override for static HTML output dir
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("publisher")

STATIC_DIR = ROOT / "outputs" / "published"
STATIC_DIR.mkdir(parents=True, exist_ok=True)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# ─── WordPress Publisher ──────────────────────────────────────────────────────

class WordPressPublisher:
    """
    Publishes to WordPress via the REST API.
    Requires: Application Password enabled in WordPress user profile.
    """

    def __init__(self):
        self.base_url = _env("WORDPRESS_URL", "").rstrip("/")
        self.user     = _env("WORDPRESS_USER") or _env("WORDPRESS_USERNAME", "")
        self.app_pass = _env("WORDPRESS_APP_PASS") or _env("WORDPRESS_PASSWORD", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.user and self.app_pass)

    def publish(self, piece: Dict) -> Dict:
        if not self.is_configured:
            return {"status": "skipped", "reason": "WordPress not configured",
                    "platform": "wordpress"}

        blog  = piece.get("blog", {})
        seo   = piece.get("seo", {})
        title = blog.get("title", piece.get("topic", "Untitled"))
        # Use HTML version if available, else convert markdown
        content = blog.get("content", "")
        if not content.strip().startswith("<"):
            content = self._md_to_html(content)

        payload = {
            "title":   title,
            "content": content,
            "status":  "publish",
            "slug":    seo.get("slug", ""),
            "excerpt": seo.get("meta_description", ""),
            "meta": {
                "_yoast_wpseo_title":    seo.get("meta_title", title),
                "_yoast_wpseo_metadesc": seo.get("meta_description", ""),
            },
        }

        try:
            resp = requests.post(
                f"{self.base_url}/wp-json/wp/v2/posts",
                json=payload,
                auth=(self.user, self.app_pass.replace(" ", "")),
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            url  = data.get("link", "")
            logger.info(f"WordPress published: {url}")
            return {
                "status":    "published",
                "platform":  "wordpress",
                "url":       url,
                "post_id":   data.get("id"),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"WordPress publish failed: {e}")
            return {"status": "error", "platform": "wordpress", "reason": str(e)}

    def _md_to_html(self, md: str) -> str:
        """Minimal markdown → WordPress-compatible HTML."""
        import re
        html = md
        html = re.sub(r"^## (.+)$",  r"<!-- wp:heading --><h2>\1</h2><!-- /wp:heading -->", html, flags=re.M)
        html = re.sub(r"^### (.+)$", r"<!-- wp:heading {\"level\":3} --><h3>\1</h3><!-- /wp:heading -->", html, flags=re.M)
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         html)
        paras = []
        for line in html.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("<!--") or line.startswith("<h"):
                paras.append(line)
            elif line.startswith("-"):
                paras.append(f"<li>{line[1:].strip()}</li>")
            else:
                paras.append(f"<!-- wp:paragraph --><p>{line}</p><!-- /wp:paragraph -->")
        return "\n".join(paras)


# ─── Medium Publisher ─────────────────────────────────────────────────────────

class MediumPublisher:
    """
    Publishes to Medium via the Integration Token API.
    Get token: medium.com/me/settings → Integration tokens
    """

    API_BASE = "https://api.medium.com/v1"

    def __init__(self):
        self.token   = _env("MEDIUM_TOKEN")
        self.user_id = _env("MEDIUM_USER_ID")
        self._headers = {
            "Authorization":  f"Bearer {self.token}",
            "Content-Type":   "application/json",
            "Accept":         "application/json",
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def _get_user_id(self) -> Optional[str]:
        if self.user_id:
            return self.user_id
        try:
            resp = requests.get(f"{self.API_BASE}/me", headers=self._headers, timeout=10)
            resp.raise_for_status()
            uid = resp.json().get("data", {}).get("id")
            self.user_id = uid
            return uid
        except Exception as e:
            logger.error(f"Medium: could not get user ID: {e}")
            return None

    def publish(self, piece: Dict, status: str = "public") -> Dict:
        if not self.is_configured:
            return {"status": "skipped", "reason": "MEDIUM_TOKEN not set",
                    "platform": "medium"}

        user_id = self._get_user_id()
        if not user_id:
            return {"status": "error", "platform": "medium",
                    "reason": "Could not retrieve Medium user ID"}

        blog  = piece.get("blog", {})
        seo   = piece.get("seo", {})
        title = blog.get("title", piece.get("topic", "Untitled"))
        content = blog.get("content", "")
        tags  = seo.get("keywords", [piece.get("topic", "")])[:5]

        payload = {
            "title":         title,
            "contentFormat": "markdown",
            "content":       content,
            "tags":          tags,
            "publishStatus": status,  # "public", "draft", "unlisted"
            "canonicalUrl":  "",
        }

        try:
            resp = requests.post(
                f"{self.API_BASE}/users/{user_id}/posts",
                json=payload,
                headers=self._headers,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            url  = data.get("url", "")
            logger.info(f"Medium published: {url}")
            return {
                "status":    "published",
                "platform":  "medium",
                "url":       url,
                "post_id":   data.get("id"),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Medium publish failed: {e}")
            return {"status": "error", "platform": "medium", "reason": str(e)}


# ─── Ghost Publisher ──────────────────────────────────────────────────────────

class GhostPublisher:
    """
    Publishes to Ghost CMS via the Admin API.
    Set GHOST_URL and GHOST_ADMIN_KEY (format: id:secret).
    """

    def __init__(self):
        self.ghost_url = _env("GHOST_URL", "").rstrip("/")
        self.admin_key = _env("GHOST_ADMIN_KEY")

    @property
    def is_configured(self) -> bool:
        return bool(self.ghost_url and self.admin_key and ":" in self.admin_key)

    def _get_jwt(self) -> str:
        import hmac
        import hashlib
        import base64
        key_id, secret = self.admin_key.split(":", 1)
        now = int(time.time())
        header  = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT","kid":"' + key_id.encode() + b'"}').rstrip(b"=")
        payload = base64.urlsafe_b64encode(
            json.dumps({"iat": now, "exp": now + 300, "aud": "/admin/"}).encode()
        ).rstrip(b"=")
        sig_input = header + b"." + payload
        sig = base64.urlsafe_b64encode(
            hmac.new(bytes.fromhex(secret), sig_input, hashlib.sha256).digest()
        ).rstrip(b"=")
        return (sig_input + b"." + sig).decode()

    def publish(self, piece: Dict) -> Dict:
        if not self.is_configured:
            return {"status": "skipped", "reason": "Ghost not configured",
                    "platform": "ghost"}
        blog  = piece.get("blog", {})
        seo   = piece.get("seo", {})
        title = blog.get("title", piece.get("topic", "Untitled"))

        try:
            headers = {
                "Authorization": f"Ghost {self._get_jwt()}",
                "Content-Type":  "application/json",
            }
            payload = {
                "posts": [{
                    "title":             title,
                    "markdown":          blog.get("content", ""),
                    "status":            "published",
                    "slug":              seo.get("slug", ""),
                    "meta_title":        seo.get("meta_title", title),
                    "meta_description":  seo.get("meta_description", ""),
                    "tags": [{"name": kw} for kw in seo.get("keywords", [])[:5]],
                }]
            }
            resp = requests.post(
                f"{self.ghost_url}/ghost/api/admin/posts/",
                json=payload,
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()
            post = resp.json().get("posts", [{}])[0]
            url  = post.get("url", "")
            logger.info(f"Ghost published: {url}")
            return {
                "status":   "published",
                "platform": "ghost",
                "url":      url,
                "post_id":  post.get("id"),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Ghost publish failed: {e}")
            return {"status": "error", "platform": "ghost", "reason": str(e)}


# ─── Static HTML Publisher ─────────────────────────────────────────────────────

class StaticPublisher:
    """
    Exports content as standalone HTML files.
    Suitable for GitHub Pages, Netlify, Vercel, or any static host.
    Also generates an index.html listing all published posts.
    """

    def __init__(self):
        self.output_dir = Path(_env("STATIC_OUTPUT_DIR", str(STATIC_DIR)))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def publish(self, piece: Dict) -> Dict:
        blog  = piece.get("blog", {})
        seo   = piece.get("seo", {})
        title = blog.get("title", piece.get("topic", "Untitled"))
        slug  = seo.get("slug") or self._slugify(title)

        # Find the pre-generated HTML file if exists
        output_dir = piece.get("output_dir")
        html_path  = None
        if output_dir:
            html_file = Path(output_dir) / "blog_post.html"
            if html_file.exists():
                html_path = html_file

        dest = self.output_dir / f"{slug}.html"

        try:
            if html_path and html_path.exists():
                import shutil
                shutil.copy2(html_path, dest)
            else:
                from core.output_automation import FileExporter
                FileExporter().export_html(title, blog.get("content", ""), self.output_dir, f"{slug}.html")

            # Rebuild index
            self._rebuild_index()

            url = f"/published/{slug}.html"
            logger.info(f"Static published: {dest.name}")
            return {
                "status":    "published",
                "platform":  "static",
                "url":       url,
                "file":      str(dest),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Static publish failed: {e}")
            return {"status": "error", "platform": "static", "reason": str(e)}

    def _rebuild_index(self):
        """Generate an index.html listing all published posts."""
        posts = sorted(self.output_dir.glob("*.html"),
                       key=lambda f: f.stat().st_mtime, reverse=True)
        posts = [p for p in posts if p.name != "index.html"]

        items = "\n".join(
            f'<li><a href="{p.name}">{p.stem.replace("-"," ").title()}</a>'
            f' <span class="date">{datetime.fromtimestamp(p.stat().st_mtime).strftime("%b %d, %Y")}</span></li>'
            for p in posts[:50]
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WheellsVerse — Blog</title>
<style>
body{{font-family:'Georgia',serif;max-width:700px;margin:60px auto;padding:0 20px;color:#222}}
h1{{font-size:2rem;border-bottom:3px solid #00d4ff;padding-bottom:.5rem}}
ul{{list-style:none;padding:0}}li{{padding:10px 0;border-bottom:1px solid #eee}}
a{{color:#0077cc;text-decoration:none;font-size:1.05rem}}
.date{{color:#999;font-size:.85rem;margin-left:10px}}
</style>
</head>
<body>
<h1>WheellsVerse Blog</h1>
<ul>{items}</ul>
<footer style="margin-top:2rem;color:#aaa;font-size:.8rem">Auto-generated by WheellsVerse</footer>
</body>
</html>"""
        (self.output_dir / "index.html").write_text(html, encoding="utf-8")

    def _slugify(self, text: str) -> str:
        import re
        s = text.lower().strip()
        s = re.sub(r"[^\w\s-]", "", s)
        s = re.sub(r"[\s_-]+", "-", s)
        return s[:60]


# ─── Social Media Traffic Layer ───────────────────────────────────────────────

class TrafficEngine:
    """
    Distributes content to social platforms for traffic generation.
    Generates hashtags and posting schedules.
    """

    def distribute(self, piece: Dict, platforms: Optional[List[str]] = None) -> Dict:
        """Post to Twitter/LinkedIn/Slack with the generated social content."""
        results = {}
        platforms = platforms or []

        # Slack distribution
        if "slack" in platforms or not platforms:
            try:
                from core.output_automation import get_automator
                auto = get_automator()
                tw_content = piece.get("twitter", {}).get("tweets", [])
                if tw_content:
                    first_tweet = tw_content[0] if tw_content else ""
                    msg = (
                        f"📝 *New Content Published*\n\n"
                        f"*{piece.get('blog', {}).get('title', piece.get('topic',''))}*\n\n"
                        f"{first_tweet[:500]}"
                    )
                    results["slack"] = auto.slack.send(msg)
            except Exception as e:
                results["slack"] = {"status": "error", "reason": str(e)}

        # Generate posting schedule
        results["schedule"] = self._generate_schedule(piece)
        results["hashtags"] = self._generate_hashtags(piece)

        return results

    def _generate_hashtags(self, piece: Dict) -> List[str]:
        """Extract relevant hashtags from the content."""
        seo     = piece.get("seo", {})
        keywords = seo.get("keywords", [])
        topic   = piece.get("topic", "")
        base_tags = ["#AIAutomation", "#Entrepreneurship", "#WheellsVerse",
                     "#PassiveIncome", "#ContentMarketing", "#AITools"]
        kw_tags = [f"#{kw.replace(' ','')}" for kw in keywords[:3] if kw]
        topic_tags = [f"#{w.capitalize()}" for w in topic.split()[:2] if len(w) > 3]
        return list(dict.fromkeys(base_tags + kw_tags + topic_tags))[:10]

    def _generate_schedule(self, piece: Dict) -> Dict:
        """Generate optimal posting times."""
        from datetime import datetime, timedelta
        now   = datetime.now()
        slots = [
            now.replace(hour=9,  minute=0,  second=0, microsecond=0),
            now.replace(hour=12, minute=30, second=0, microsecond=0),
            now.replace(hour=17, minute=0,  second=0, microsecond=0),
            now.replace(hour=20, minute=0,  second=0, microsecond=0),
        ]
        return {
            "twitter_times":  [s.isoformat() for s in slots[:2]],
            "linkedin_times": [s.isoformat() for s in slots[2:3]],
            "next_post":      slots[0].isoformat(),
        }


# ─── Central Publisher ────────────────────────────────────────────────────────

class Publisher:
    """
    Unified publisher — routes content to all configured platforms.
    """

    def __init__(self):
        self.wordpress = WordPressPublisher()
        self.medium    = MediumPublisher()
        self.ghost     = GhostPublisher()
        self.static    = StaticPublisher()
        self.traffic   = TrafficEngine()

    def publish_content(
        self,
        piece: Dict,
        platforms: Optional[List[str]] = None,
    ) -> Dict:
        """
        Publish a content piece to specified platforms.
        platforms: ["wordpress","medium","ghost","static"] — defaults to ["static"]

        Returns:
          {
            "success_count": N,
            "results": {"platform": result_dict, ...},
            "traffic": {...},
          }
        """
        if platforms is None:
            platforms = ["static"]

        results: Dict[str, Any] = {}
        platform_map = {
            "wordpress": self.wordpress.publish,
            "medium":    self.medium.publish,
            "ghost":     self.ghost.publish,
            "static":    self.static.publish,
        }

        for platform in platforms:
            if platform in platform_map:
                results[platform] = platform_map[platform](piece)
            else:
                results[platform] = {"status": "error", "reason": f"Unknown platform: {platform}"}

        # Traffic distribution
        traffic_result = {}
        try:
            traffic_result = self.traffic.distribute(piece, platforms)
        except Exception as e:
            traffic_result = {"error": str(e)}

        success_count = sum(
            1 for r in results.values()
            if r.get("status") in ("published", "ok")
        )

        logger.info(
            f"Published '{piece.get('topic','')[:40]}' — "
            f"{success_count}/{len(platforms)} platforms"
        )

        return {
            "success_count": success_count,
            "total_platforms": len(platforms),
            "results":   results,
            "traffic":   traffic_result,
            "timestamp": datetime.now().isoformat(),
        }

    def get_configured_platforms(self) -> List[str]:
        configured = ["static"]  # always available
        if self.wordpress.is_configured: configured.append("wordpress")
        if self.medium.is_configured:    configured.append("medium")
        if self.ghost.is_configured:     configured.append("ghost")
        return configured


# ─── Singleton ────────────────────────────────────────────────────────────────

_publisher: Optional[Publisher] = None


def get_publisher() -> Publisher:
    global _publisher
    if _publisher is None:
        _publisher = Publisher()
    return _publisher


# ─── Convenience function ─────────────────────────────────────────────────────

def publish_content(piece: Dict, platforms: Optional[List[str]] = None) -> Dict:
    """Module-level convenience wrapper."""
    return get_publisher().publish_content(piece, platforms)
