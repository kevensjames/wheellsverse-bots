#!/usr/bin/env python3
"""
core/publish_pipeline.py
─────────────────────────────────────────────────────────────────────────────
One-command publish pipeline.

Takes any generated content file (markdown) and pushes it to every connected
platform simultaneously:

  ✅ Twitter/X     — auto-thread from article
  ✅ TikTok        — caption + script (posts when video_url provided)
  ✅ ConvertKit    — broadcast email to subscriber list
  ✅ Blog          — saves formatted HTML to outputs/published/blog/
  ✅ Facebook      — posts to Wheellsverse Page
  ✅ Instagram     — generates image with DALL-E + publishes post
  🔜 LinkedIn      — when token connected

Usage:
  from core.publish_pipeline import get_publisher
  pub = get_publisher()
  result = pub.publish(content="...", title="...", platforms=["twitter","tiktok","email","blog"])
─────────────────────────────────────────────────────────────────────────────
"""

import concurrent.futures
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("publish_pipeline")

BLOG_DIR = ROOT / "outputs" / "published" / "blog"


# ── HTML blog template ─────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<meta name="description" content="{description}"/>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      max-width:780px;margin:40px auto;padding:0 20px;line-height:1.7;color:#1a1a2e}}
h1{{color:#0d0f14;font-size:2em;margin-bottom:.4em}}
h2{{color:#16213e;border-bottom:2px solid #00d4ff;padding-bottom:.3em;margin-top:2em}}
a{{color:#0099bb;text-decoration:none}}a:hover{{text-decoration:underline}}
.cta{{background:linear-gradient(135deg,#0d0f14,#16213e);color:#fff;
      padding:28px 32px;border-radius:12px;margin:40px 0;border-left:4px solid #00d4ff}}
.cta h3{{color:#00d4ff;margin:0 0 12px}}
.cta a{{color:#00ff88;font-weight:600}}
.tag{{display:inline-block;background:#e8f4fd;color:#0099bb;padding:3px 10px;
      border-radius:20px;font-size:12px;margin:0 4px 4px 0}}
footer{{margin-top:60px;padding-top:20px;border-top:1px solid #eee;color:#888;font-size:13px}}
img{{max-width:100%;border-radius:8px}}
blockquote{{border-left:4px solid #00d4ff;margin-left:0;padding-left:20px;color:#555}}
</style>
</head>
<body>
<article>
<h1>{title}</h1>
<p style="color:#888;font-size:13px">By <strong>J.K. Blaze</strong> · WheellsVerse · {date}</p>
{body_html}
</article>

<div class="cta">
  <h3>💰 Start Building Passive Income Today</h3>
  <p>
    📈 <a href="{robinhood_url}" target="_blank">Get free stocks on Webull</a> — zero commission investing<br/>
    ₿ <a href="{coinbase_url}" target="_blank">Earn $10 in free Bitcoin on Coinbase</a> — best crypto platform<br/>
    🛒 <a href="https://www.amazon.com/s?k=passive+income+books&tag={amazon_tag}" target="_blank">Best passive income books on Amazon</a><br/>
    🎬 <a href="{amazon_video_url}" target="_blank">Amazon Prime Video — Stream &amp; Save</a>
  </p>
</div>

<div style="background:linear-gradient(135deg,#0a0a0a,#1a1a2e);color:#fff;padding:32px;border-radius:12px;margin:40px 0;text-align:center;border:1px solid #00ff88">
  <h3 style="color:#00ff88;margin:0 0 8px;font-size:1.4em">🤖 Want This Running For Your Business?</h3>
  <p style="color:#ccc;margin:0 0 24px">Get all 83 AI bots that write, publish, and monetize content automatically — 24/7.</p>
  <div style="display:flex;gap:16px;justify-content:center;flex-wrap:wrap">
    <a href="{bot_pack_url}" target="_blank"
       style="background:#00ff88;color:#000;padding:14px 28px;border-radius:8px;font-weight:700;text-decoration:none;font-size:1em">
      🚀 Get the Bot Pack — $97
    </a>
    <a href="{pro_url}" target="_blank"
       style="background:transparent;color:#00d4ff;padding:14px 28px;border-radius:8px;font-weight:700;text-decoration:none;font-size:1em;border:2px solid #00d4ff">
      ⚡ WheellsVerse Pro — $29/mo
    </a>
  </div>
</div>

<div style="background:linear-gradient(135deg,#0d0f14,#1a1a2e);border:1px solid #00d4ff;border-radius:12px;padding:28px 32px;margin:40px 0;text-align:center">
  <h3 style="color:#00d4ff;margin:0 0 8px;font-size:1.3em">📬 Get Free Weekly Money Tips</h3>
  <p style="color:#ccc;margin:0 0 20px;font-size:14px">Join thousands of readers getting passive income strategies every Monday. Free.</p>
  <form id="wv-capture" onsubmit="wvSubscribe(event)" style="display:flex;gap:10px;max-width:420px;margin:0 auto;flex-wrap:wrap;justify-content:center">
    <input type="email" id="wv-email" placeholder="your@email.com" required
           style="flex:1;min-width:200px;padding:12px 16px;border-radius:8px;border:1px solid #00d4ff;background:#0d0f14;color:#fff;font-size:14px;outline:none">
    <button type="submit" id="wv-btn"
            style="background:#00d4ff;color:#000;padding:12px 22px;border-radius:8px;border:none;font-weight:700;cursor:pointer;font-size:14px">
      Subscribe →
    </button>
  </form>
  <p id="wv-msg" style="color:#00ff88;margin:12px 0 0;display:none;font-weight:600">✅ You are in! Check your inbox.</p>
  <p style="color:#666;font-size:11px;margin:10px 0 0">No spam. Unsubscribe any time.</p>
</div>
<script>
async function wvSubscribe(e){{
  e.preventDefault();
  var btn=document.getElementById('wv-btn');
  btn.textContent='...';btn.disabled=true;
  try{{
    await fetch('/api/subscribe',{{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{email:document.getElementById('wv-email').value}})
    }});
    document.getElementById('wv-capture').style.display='none';
    document.getElementById('wv-msg').style.display='block';
  }}catch(err){{
    btn.textContent='Subscribe →';btn.disabled=false;
  }}
}}
</script>

<footer>
  © {year} WheellsVerse by J.K. Blaze · All rights reserved ·
  <a href="https://wheellsverse.com">wheellsverse.com</a>
</footer>
</body>
</html>
"""


def _md_to_html(md: str) -> str:
    """Minimal markdown → HTML converter (no external deps)."""
    html = md
    # Headers
    html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    # Bold/italic
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    # Links
    html = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', html)
    # Code
    html = re.sub(r'`(.+?)`', r'<code>\1</code>', html)
    # Blockquote
    html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
    # Lists
    html = re.sub(r'^[\-\*] (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
    html = re.sub(r'(<li>.*?</li>\n?)+', lambda m: '<ul>' + m.group() + '</ul>', html, flags=re.DOTALL)
    # Paragraphs
    parts = re.split(r'\n\n+', html.strip())
    paras = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if re.match(r'^<(h[1-6]|ul|ol|li|blockquote)', p):
            paras.append(p)
        else:
            paras.append(f'<p>{p.replace(chr(10), " ")}</p>')
    return '\n'.join(paras)


def _compose_social_image_url(title: str, snippet: str, platform: str) -> Optional[str]:
    """Build a sharp DALL-E HD + Pillow text image and return a public HTTPS URL
    Meta can fetch. Returns None on any failure so the caller can decide whether
    to skip or fall back."""
    try:
        from core.social_image import generate_social_image, upload_to_public_url
        local = generate_social_image(headline=title, subtext=snippet, platform=platform)
        if not local:
            return None
        return upload_to_public_url(local)
    except Exception as e:
        logger.warning("Social image composition failed (%s): %s", platform, e)
        return None


class PublishPipeline:
    """Publish content to all connected platforms in parallel."""

    ALL_PLATFORMS = ["twitter", "tiktok", "email", "blog", "facebook", "instagram"]

    def __init__(self):
        self._twitter = None
        self._tiktok = None
        self._convertkit = None

    def _tw(self):
        if self._twitter is None:
            from core.twitter import get_twitter
            self._twitter = get_twitter()
        return self._twitter

    def _tt(self):
        if self._tiktok is None:
            from core.tiktok import get_tiktok
            self._tiktok = get_tiktok()
        return self._tiktok

    def _ck(self):
        if self._convertkit is None:
            from core.convertkit import get_convertkit
            self._convertkit = get_convertkit()
        return self._convertkit

    # ── Facebook & Instagram publishers ───────────────────────────────────────

    def _publish_facebook(self, title: str, content: str,
                          hashtags: List[str], image_url: Optional[str] = None,
                          video_url: Optional[str] = None) -> Dict:
        try:
            from core.facebook import get_facebook
            fb = get_facebook()
            if not fb.is_configured():
                return {"platform": "facebook", "status": "skipped",
                        "reason": "No Facebook credentials. Add FACEBOOK_PAGE_TOKEN+FACEBOOK_PAGE_ID or FACEBOOK_EMAIL+FACEBOOK_PASSWORD to .env"}
            clean = re.sub(r'[#*`>]', '', content).strip()
            snippet = clean[:300].rsplit(' ', 1)[0] + '...' if len(clean) > 300 else clean
            tags = ' '.join(f'#{h}' for h in (hashtags or [])[:5])
            message = f"{title}\n\n{snippet}\n\n{tags}"
            # If no image was supplied AND no video, compose a sharp landscape
            # image so FB doesn't fall back to a plain text post or whatever
            # link-preview thumbnail FB scrapes from the page.
            if not image_url and not video_url:
                image_url = _compose_social_image_url(title, snippet, "facebook_feed")
            result = fb.post(message, image_url=image_url, video_url=video_url)
            return {"platform": "facebook", **result}
        except Exception as e:
            return {"platform": "facebook", "status": "error", "error": str(e)}

    def _publish_instagram(self, title: str, content: str,
                           hashtags: List[str], image_url: Optional[str] = None) -> Dict:
        try:
            from core.instagram import get_instagram
            ig = get_instagram()
            if not ig.is_configured():
                return {"platform": "instagram", "status": "skipped",
                        "reason": "No Instagram credentials. Add INSTAGRAM_PAGE_TOKEN+INSTAGRAM_ACCOUNT_ID or INSTAGRAM_USERNAME+INSTAGRAM_PASSWORD to .env"}
            clean = re.sub(r'[#*`>]', '', content).strip()
            snippet = clean[:200].rsplit(' ', 1)[0] + '...' if len(clean) > 200 else clean
            tags = ' '.join(f'#{h}' for h in (hashtags or [])[:20])
            caption = f"{title}\n\n{snippet}\n\n{tags}"
            # IG requires an image for non-Reel posts. Pre-compose a sharp one
            # here so the Instagram client never has to fall back to its
            # internal DALL-E text-overlay path (which produces blurry text).
            if not image_url:
                image_url = _compose_social_image_url(title, snippet, "instagram_feed")
            result = ig.post(caption, image_url=image_url)
            return {"platform": "instagram", **result}
        except Exception as e:
            return {"platform": "instagram", "status": "error", "error": str(e)}

    # ── Platform publishers ────────────────────────────────────────────────────

    def _publish_twitter(self, title: str, content: str,
                         hashtags: List[str]) -> Dict:
        if not os.getenv("TWITTER_EMAIL"):
            return {"platform": "twitter", "status": "skipped",
                    "reason": "TWITTER_EMAIL not set in .env"}
        try:
            from core.twitter import get_twitter
            from core.browser import post_twitter_thread, is_available
            if not is_available():
                return {"platform": "twitter", "status": "skipped",
                        "reason": "Playwright not installed — run: playwright install chromium"}
            tw = get_twitter()
            tweets = tw.format_thread_from_markdown(content)
            result = post_twitter_thread(tweets)
            if result.get("status") == "posted":
                # Register tweet IDs for performance tracking
                try:
                    from core.performance import register_tweet_ids
                    ids = [t.get("id") for t in result.get("tweet_list", []) if t.get("id")]
                    if ids:
                        register_tweet_ids(ids)
                except Exception:
                    pass
                return {"platform": "twitter", "status": "posted",
                        "tweets": result.get("tweets", 0),
                        "screenshot": result.get("screenshot", "")}
            return {"platform": "twitter", "status": "error",
                    "error": result.get("error") or result.get("reason", "unknown")}
        except Exception as e:
            return {"platform": "twitter", "status": "error", "error": str(e)}

    def _publish_tiktok(self, title: str, content: str,
                        video_url: Optional[str] = None) -> Dict:
        tt = self._tt()
        if not tt.is_connected():
            return {"platform": "tiktok", "status": "skipped",
                    "reason": "Not authorized — click Connect TikTok in dashboard"}

        # Build a punchy caption from the title
        tags = "#passiveincome #money #investing #sidehustle #crypto #makemoney #financialfreedom"
        caption = f"{title[:150]}\n\n{tags}"

        if not video_url:
            return {"platform": "tiktok", "status": "content_saved",
                    "caption": caption,
                    "reason": "No video_url — caption generated, provide video to post"}
        try:
            result = tt.post_video_from_url(video_url=video_url, caption=caption)
            return {"platform": "tiktok", "status": "posted",
                    "publish_id": result.get("publish_id")}
        except Exception as e:
            return {"platform": "tiktok", "status": "error", "error": str(e)}

    def _publish_email(self, title: str, content: str) -> Dict:
        ck = self._ck()
        if not ck.is_connected():
            return {"platform": "email", "status": "skipped",
                    "reason": "No credentials — add CONVERTKIT_API_KEY to .env"}
        try:
            # Build HTML email body
            body_html = _md_to_html(content)
            amazon_tag = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")
            amazon_tag_2 = os.getenv("AFFILIATE_AMAZON_TAG_2", "naraiinsights-20")
            amazon_video_url = os.getenv("AFFILIATE_AMAZON_VIDEO_URL", f"https://www.amazon.com/gp/video/storefront?tag={amazon_tag_2}")
            coinbase_url = os.getenv("AFFILIATE_COINBASE_URL", "")
            robinhood_url = os.getenv("AFFILIATE_WEBULL_URL", "")
            footer_html = (
                f'<hr/><p><strong>💰 Today\'s affiliate picks:</strong><br/>'
                f'📈 <a href="{robinhood_url}">Free stock on Robinhood</a> | '
                f'₿ <a href="{coinbase_url}">$10 Bitcoin on Coinbase</a> | '
                f'🛒 <a href="https://amazon.com/s?k=money&tag={amazon_tag}">Amazon deals</a> | '
                f'🎬 <a href="{amazon_video_url}">Amazon Prime Video</a></p>'
            )
            result = ck.create_broadcast(
                subject=title,
                content=body_html + footer_html,
                description=f"WheellsVerse — {title}",
            )
            broadcast_id = result.get("broadcast", {}).get("id")
            # draft with unconfirmed send address
            if result.get("status") == "draft":
                return {"platform": "email", "status": "draft_created",
                        "note": "Confirm sending address at app.convertkit.com → Settings → Email"}
            if broadcast_id:
                try:
                    ck.send_broadcast(broadcast_id)
                    return {"platform": "email", "status": "sent",
                            "broadcast_id": broadcast_id}
                except Exception:
                    return {"platform": "email", "status": "draft_created",
                            "broadcast_id": broadcast_id,
                            "send_url": f"https://app.convertkit.com/broadcasts/{broadcast_id}"}
            return {"platform": "email", "status": "draft_created",
                    "broadcast_id": broadcast_id}
        except Exception as e:
            return {"platform": "email", "status": "error", "error": str(e)}

    def _publish_blog(self, title: str, content: str,
                      slug: str = "") -> Dict:
        try:
            BLOG_DIR.mkdir(parents=True, exist_ok=True)
            slug = slug or re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
            # Clean slug filename (no timestamp prefix) — the URL the bots
            # announce and the file on disk are now the same thing, so
            # shared links stop 404'ing. Re-publishing an article with the
            # same title intentionally overwrites; 80 chars is a reasonable
            # SEO-friendly cap (old limit was 60 which truncated too many
            # titles and caused accidental slug collisions).
            slug_truncated = slug[:80]
            filename = f"{slug_truncated}.html"
            filepath = BLOG_DIR / filename

            body_html = _md_to_html(content)
            description = re.sub(r'<[^>]+>', '', body_html)[:160]
            amazon_tag = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")

            from core.click_tracker import tracking_url
            site_base = os.getenv("CTA_URL", "https://wheellsverse-bots.pages.dev")
            html = _HTML_TEMPLATE.format(
                title=title,
                description=description,
                date=datetime.now().strftime("%B %d, %Y"),
                year=datetime.now().year,
                body_html=body_html,
                amazon_tag=amazon_tag,
                amazon_video_url=tracking_url("amazon_video", site_base),
                coinbase_url=tracking_url("coinbase", site_base),
                robinhood_url=tracking_url("webull", site_base),
                bot_pack_url=os.getenv("STRIPE_BOT_PACK_URL", "https://buy.stripe.com/dRmdR81zDeSeeuF347a3u03"),
                pro_url=os.getenv("STRIPE_PRO_URL", "https://buy.stripe.com/aFa28q6TX6lI72d9sva3u04"),
            )
            filepath.write_text(html, encoding="utf-8")
            logger.info(f"Blog post saved: {filepath}")

            # Mirror to frontend/blog/ for Cloudflare Pages deployment
            cf_blog_dir = ROOT / "frontend" / "blog"
            cf_blog_dir.mkdir(parents=True, exist_ok=True)
            cf_path = cf_blog_dir / filename
            cf_path.write_text(html, encoding="utf-8")
            logger.info(f"Copied to Cloudflare Pages dir: {cf_path.name}")

            # Auto-commit and push so Cloudflare Pages deploys immediately
            try:
                import subprocess
                subprocess.run(["git", "add", str(cf_path)], cwd=str(ROOT), check=True, capture_output=True)
                subprocess.run(
                    ["git", "commit", "-m", f"Auto-publish: {title[:60]}"],
                    cwd=str(ROOT), check=True, capture_output=True
                )
                subprocess.run(["git", "push", "origin", "main"], cwd=str(ROOT), check=True, capture_output=True)
                logger.info(f"Auto-pushed to git → Cloudflare Pages deploying: {filename}")
            except Exception as git_err:
                logger.warning(f"Git auto-push failed (manual push needed): {git_err}")

            # Best-effort IndexNow ping — tells Bing/Yandex to recrawl this
            # URL within minutes. No-op if INDEXNOW_KEY isn't configured.
            try:
                from core import indexnow
                site_base_for_ping = os.getenv("CTA_URL", "https://wheellsverse.com").rstrip("/")
                indexnow.ping_urls([f"{site_base_for_ping}/blog/{slug_truncated}"])
            except Exception as _e:
                logger.debug("IndexNow ping skipped: %s", _e)

            # Return BOTH slug (backward compat) and basename — the basename
            # is the truncated+cleaned stem that matches the file on disk,
            # and is what callers should use to build share URLs.
            return {"platform": "blog", "status": "saved",
                    "file": str(filepath.relative_to(ROOT)),
                    "slug": slug,
                    "filename": filename,
                    "basename": slug_truncated}
        except Exception as e:
            return {"platform": "blog", "status": "error", "error": str(e)}

    # ── Main publish ───────────────────────────────────────────────────────────

    def publish(
        self,
        content: str,
        title: str = "",
        platforms: Optional[List[str]] = None,
        video_url: Optional[str] = None,
        image_url: Optional[str] = None,
        hashtags: Optional[List[str]] = None,
        slug: str = "",
    ) -> Dict:
        """
        Publish content to all specified platforms simultaneously.

        Args:
            content:   Markdown content string
            title:     Article/post title
            platforms: Subset of ["twitter","tiktok","email","blog"] or None = all
            video_url: Optional video URL for TikTok video posts
            hashtags:  List of hashtags (without #)
            slug:      URL slug for blog post

        Returns:
            {"results": [...per platform...], "published": N, "skipped": N}
        """
        if not title:
            # Extract title from first # heading
            m = re.search(r'^#+ (.+)$', content, re.MULTILINE)
            title = m.group(1) if m else "WheellsVerse Post"

        target_platforms = platforms or self.ALL_PLATFORMS
        hashtags = hashtags or ["passiveincome", "money", "investing", "sidehustle"]

        tasks = {}
        if "twitter" in target_platforms:
            tasks["twitter"] = lambda: self._publish_twitter(title, content, hashtags)
        if "tiktok" in target_platforms:
            tasks["tiktok"] = lambda: self._publish_tiktok(title, content, video_url)
        if "email" in target_platforms:
            tasks["email"] = lambda: self._publish_email(title, content)
        if "blog" in target_platforms:
            tasks["blog"] = lambda: self._publish_blog(title, content, slug)
        if "facebook" in target_platforms:
            tasks["facebook"] = lambda: self._publish_facebook(title, content, hashtags, image_url, video_url)
        if "instagram" in target_platforms:
            tasks["instagram"] = lambda: self._publish_instagram(title, content, hashtags, image_url)

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(fn): name for name, fn in tasks.items()}
            for fut in concurrent.futures.as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as e:
                    name = futures[fut]
                    results.append({"platform": name, "status": "error",
                                    "error": str(e)})

        published = sum(1 for r in results if r.get("status") in
                        ("posted", "saved", "draft_created", "content_saved", "sent"))
        skipped = sum(1 for r in results if r.get("status") == "skipped")

        # Build the live URL for every saved blog post using the real
        # filename on disk (not the raw, un-truncated slug). This is what
        # was broken before — the URL and the filename had drifted apart
        # because the filename was prefixed with a timestamp and truncated
        # to 60 chars while the URL used the full raw slug.
        blog_saved = [r for r in results if r.get("platform") == "blog" and r.get("status") == "saved"]
        site_base = os.getenv("CTA_URL", "https://wheellsverse.com").rstrip("/")
        for r in blog_saved:
            # Prefer basename (new publisher output); fall back to slug for
            # any caller that's somehow producing old-shape results.
            basename = r.get("basename") or r.get("slug", "")
            r["live_url"] = f"{site_base}/blog/{basename}"

        # Best-effort legacy Netlify deploy. The site is now served by the
        # Railway FastAPI app directly from frontend/blog/, so this step is
        # no-op on Railway deploys — left in place for any environment that
        # still uses a separate Netlify frontend.
        if blog_saved:
            try:
                import subprocess
                deploy = subprocess.run(
                    ["netlify", "deploy", "--dir", ".", "--prod"],
                    capture_output=True, text=True, timeout=120,
                    cwd=str(ROOT / "frontend")
                )
                deployed = deploy.returncode == 0
                for r in blog_saved:
                    r["netlify_deployed"] = deployed
                logger.info(f"Netlify deploy: {'✅ ok' if deployed else '✗ ' + deploy.stderr[:200]}")
            except Exception as e:
                logger.warning(f"Netlify deploy skipped: {e}")

        logger.info(f"Publish complete: {published} published, {skipped} skipped")

        # Telegram notification
        try:
            from core.telegram import notify_pipeline_complete
            blog_result = next((r for r in results if r.get("platform") == "blog"), {})
            blog_url = blog_result.get("live_url", "")
            notify_pipeline_complete(
                pipeline_name=title[:60],
                published=published,
                skipped=skipped,
                blog_url=blog_url,
            )
        except Exception:
            pass

        return {
            "title": title,
            "results": results,
            "published": published,
            "skipped": skipped,
        }

    def publish_from_file(self, md_path: str, **kwargs) -> Dict:
        """Publish directly from a markdown file path."""
        content = Path(md_path).read_text(encoding="utf-8")
        return self.publish(content=content, **kwargs)

    def get_status(self) -> Dict:
        """Which platforms are connected."""
        tw = self._tw()
        tt = self._tt()
        ck = self._ck()
        return {
            "twitter": tw.get_status(),
            "tiktok": tt.get_status(),
            "convertkit": ck.get_status(),
            "blog": {"connected": True, "path": str(BLOG_DIR.relative_to(ROOT))},
            "facebook": {"connected": bool(os.getenv("FACEBOOK_PAGE_TOKEN")),
                           "page_id": os.getenv("FACEBOOK_PAGE_ID", "not set")},
            "instagram": {"connected": bool(os.getenv("INSTAGRAM_PAGE_TOKEN")),
                           "account_id": os.getenv("INSTAGRAM_ACCOUNT_ID", "not set")},
        }


_pipeline: Optional[PublishPipeline] = None


def get_publisher() -> PublishPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = PublishPipeline()
    return _pipeline
