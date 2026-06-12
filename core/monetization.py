#!/usr/bin/env python3
"""
core/monetization.py
─────────────────────────────────────────────────────────────────────────────
Monetization Layer — injects revenue mechanisms into every content piece.

Features:
  • Affiliate link injection (Amazon, generic, custom)
  • Context-aware CTA generation
  • Lead magnet HTML (email capture forms)
  • PDF ebook/outline generator
  • Revenue tracking per content piece

Configuration (.env):
  AMAZON_AFFILIATE_TAG  — e.g. yourstore-20
  AFFILIATE_BASE_URL    — custom affiliate network base URL
  CTA_URL               — your primary CTA destination URL
  LEAD_MAGNET_TITLE     — title for lead magnet offer
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("monetization")

OUTPUTS_DIR = ROOT / "outputs" / "reports"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _build_affiliate_rules() -> List[Tuple[List[str], str, str, str]]:
    """
    Build affiliate rules from environment variables.
    Each program reads its referral/affiliate link from .env so you can
    swap in your own links without touching code.

    Set these in .env:
      AFFILIATE_AMAZON_TAG      — your Amazon Associates tag (e.g. yoursite-20)
      AFFILIATE_COINBASE_URL    — your Coinbase referral link
      AFFILIATE_BINANCE_URL     — your Binance referral link
      AFFILIATE_WEBULL_URL   — your Robinhood referral link
      AFFILIATE_CONVERTKIT_URL  — your ConvertKit affiliate link
      AFFILIATE_JASPER_URL      — your Jasper AI affiliate link
      AFFILIATE_BLUEHOST_URL    — your Bluehost affiliate link
      AFFILIATE_FIVERR_URL      — your Fiverr affiliate link
      AFFILIATE_CLICKBANK_URL   — your ClickBank hop link
      AFFILIATE_APPSUMO_URL     — your AppSumo affiliate link
    """
    amz_tag = _env("AFFILIATE_AMAZON_TAG", "wheellsverse-20")
    amz_tag_2 = _env("AFFILIATE_AMAZON_TAG_2", "naraiinsights-20")
    amz_video_url = _env("AFFILIATE_AMAZON_VIDEO_URL", f"https://www.amazon.com/gp/video/storefront?tag={amz_tag_2}")
    coinbase_url = _env("AFFILIATE_COINBASE_URL", "https://coinbase.com/join/wheellsverse")
    binance_url = _env("AFFILIATE_BINANCE_URL", "https://www.binance.com/en/activity/referral")
    robinhood_url = _env("AFFILIATE_WEBULL_URL", "https://join.robinhood.com/")
    convertkit_url = _env("AFFILIATE_CONVERTKIT_URL", "https://convertkit.com/?lmref=wheellsverse")
    jasper_url = _env("AFFILIATE_JASPER_URL", "https://www.jasper.ai/")
    bluehost_url = _env("AFFILIATE_BLUEHOST_URL", "https://www.bluehost.com/track/wheellsverse/")
    fiverr_url = _env("AFFILIATE_FIVERR_URL", "https://www.fiverr.com/")
    clickbank_url = _env("AFFILIATE_CLICKBANK_URL", "https://www.clickbank.com/")
    appsumo_url = _env("AFFILIATE_APPSUMO_URL", "https://appsumo.com/")

    amz_ai_url = f"https://www.amazon.com/s?k=ai+tools+entrepreneurs+2025&tag={amz_tag}"
    amz_crypto_url = f"https://www.amazon.com/s?k=crypto+investing+books+2025&tag={amz_tag}"

    return [
        # ── Amazon Prime Video ─────────────────────────────────────────────────
        (
            ["amazon prime", "prime video", "streaming", "amazon video", "watch", "movies", "tv shows", "netflix alternative"],
            "Amazon Prime Video — Stream Movies & Shows + Free 2-Day Shipping",
            amz_video_url,
            "affiliate",
        ),
        # ── AI Tools ──────────────────────────────────────────────────────────
        (
            ["chatgpt", "openai", "gpt-4", "gpt", "ai writing", "ai content"],
            "ChatGPT Plus — The #1 AI Tool for Making Money",
            "https://chat.openai.com",
            "sponsored",
        ),
        (
            ["jasper", "ai copywriting", "ai write", "copy.ai", "ai blog", "content ai"],
            "Jasper AI — Write 10x Faster (Free Trial)",
            jasper_url,
            "affiliate",
        ),
        (
            ["midjourney", "dall-e", "ai image", "ai art", "ai design", "stable diffusion"],
            "Midjourney — Turn AI Art Into Income",
            "https://www.midjourney.com",
            "sponsored",
        ),
        (
            ["automation", "zapier", "make.com", "workflow", "automate", "no-code"],
            "Make.com — Automate Everything (Free Plan)",
            "https://www.make.com",
            "sponsored",
        ),
        (
            ["ai tools", "llm", "machine learning", "ai software", "artificial intelligence"],
            "Top AI Tools for Entrepreneurs 2025",
            amz_ai_url,
            "affiliate",
        ),
        # ── Crypto + Investing ────────────────────────────────────────────────
        (
            ["bitcoin", "btc", "crypto buy", "buy bitcoin", "coinbase"],
            "Coinbase — Buy Bitcoin & Crypto (Get $10 Free)",
            coinbase_url,
            "affiliate",
        ),
        (
            ["crypto trading", "binance", "altcoin", "defi", "web3", "ethereum trading"],
            "Binance — World's Largest Crypto Exchange",
            binance_url,
            "affiliate",
        ),
        (
            ["stocks", "stock market", "investing", "etf", "portfolio", "webull"],
            "Robinhood — Invest in Stocks & Crypto, Commission-Free",
            robinhood_url,
            "affiliate",
        ),
        (
            ["options", "day trading", "stock analysis", "trading platform", "tasty"],
            "TastyTrade — Advanced Trading Platform (Free)",
            "https://tastytrade.com",
            "sponsored",
        ),
        (
            ["crypto book", "investing book", "finance book", "learn crypto", "learn stocks"],
            "Best Crypto & Investing Books on Amazon",
            amz_crypto_url,
            "affiliate",
        ),
        # ── Make Money Online ─────────────────────────────────────────────────
        (
            ["side hustle", "passive income", "make money online", "freelance", "income stream"],
            "Fiverr — Sell Your Skills, Earn $500-$5000/mo",
            fiverr_url,
            "affiliate",
        ),
        (
            ["affiliate marketing", "affiliate program", "commission", "clickbank"],
            "ClickBank — Top Affiliate Programs (Free to Join)",
            clickbank_url,
            "affiliate",
        ),
        (
            ["email list", "newsletter", "subscribers", "email marketing", "convertkit"],
            "ConvertKit — Build Your Email List Free (Up to 1,000 subs)",
            convertkit_url,
            "affiliate",
        ),
        (
            ["seo", "google traffic", "keyword research", "backlinks", "rank on google"],
            "Ahrefs — The SEO Tool That Pays for Itself",
            "https://ahrefs.com",
            "sponsored",
        ),
        (
            ["hosting", "wordpress", "website", "domain", "blog start"],
            "Bluehost — Start a Blog for $2.95/mo",
            bluehost_url,
            "affiliate",
        ),
        (
            ["software deal", "saas", "lifetime deal", "appsumo", "tool deal"],
            "AppSumo — Lifetime Software Deals (Save 90%)",
            appsumo_url,
            "affiliate",
        ),
    ]


# Build rules at import time (reads .env)
AFFILIATE_RULES = _build_affiliate_rules()


# ─── CTA Templates ────────────────────────────────────────────────────────────

CTA_TEMPLATES = {
    "general": """
---

## 🚀 Get Free Daily AI + Market Signals

**{brand}** sends daily signals on stocks, crypto, and AI tools that help you make money.

[→ Join Free — Get Daily Signals]({cta_url}){disclosure}

*Join 10,000+ entrepreneurs who make smarter money decisions with AI.*

---
""",

    "content": """
---

## 📬 Get This Delivered Daily (Free)

Subscribe to **{brand}** — every morning you'll get:
- Top AI tools for making money
- Crypto + stock signals
- Trending income opportunities

[→ Subscribe Free — No Spam]({cta_url}){disclosure}

---
""",

    "tool": """
---

## ⚡ Want AI to Do This for You?

**{brand}'s 70-bot AI system** scans markets, finds opportunities, generates content,
and sends you the best signals every morning — fully automated.

[→ Get Free Daily Signals]({cta_url}){disclosure}

---
""",

    "lead_magnet": """
---

## 📥 Free Download: {lead_magnet_title}

Get the exact AI + Finance framework we use to generate automated income.
Includes tool list, strategies, and a 30-day action plan.

**[Download Free — Instant Access]({cta_url}){disclosure}**

---
""",

    "crypto": """
---

## 📊 Get Daily Crypto Signals (Free)

**{brand}** generates daily crypto trend analysis using AI.
Know what's moving before the crowd does.

[→ Get Free Crypto Signals]({cta_url}){disclosure}

---
""",

    "stocks": """
---

## 📈 Get Daily Stock Insights (Free)

**{brand}** scans stock markets every morning and sends you AI-generated insights
on what's worth watching today.

[→ Join Free — Daily Stock Signals]({cta_url}){disclosure}

---
""",
}


# ─── Monetization Engine ──────────────────────────────────────────────────────

class MonetizationEngine:

    def __init__(self):
        self.amazon_tag = _env("AMAZON_AFFILIATE_TAG", "wheellsverse-20")
        self.cta_url = _env("CTA_URL", "https://wheellsverse.com")
        self.brand = _env("BRAND_NAME", "WheellsVerse")
        self.lead_title = _env("LEAD_MAGNET_TITLE", "The AI Entrepreneur Blueprint")
        self.affiliate_base = _env("AFFILIATE_BASE_URL", "")
        self._injections: List[Dict] = []  # revenue tracking

    # ── Affiliate Links ───────────────────────────────────────────────────────

    def find_affiliate_matches(self, content: str, topic: str = "") -> List[Dict]:
        """Find which affiliate products match this content/topic."""
        combined = (content + " " + topic).lower()
        matches = []
        for kws, product, url, disclosure in AFFILIATE_RULES:
            if any(kw in combined for kw in kws):
                final_url = url.format(tag=self.amazon_tag) if "{tag}" in url else url
                matches.append({
                    "product": product,
                    "url": final_url,
                    "disclosure": disclosure,
                    "keywords": kws,
                })
        return matches[:3]  # max 3 affiliate mentions per piece

    def inject_affiliate_links(self, content: str, topic: str = "") -> str:
        """
        Inject contextual affiliate links into blog content.
        Inserts a 'Recommended Resources' section before the FAQ.
        """
        matches = self.find_affiliate_matches(content, topic)
        if not matches:
            return content

        resources = "\n\n## 🔗 Recommended Resources\n\n"
        resources += "*Disclosure: Some links below are affiliate links. "
        resources += "We earn a small commission at no extra cost to you.*\n\n"
        for m in matches:
            resources += f"- **[{m['product']}]({m['url']})** — {'Recommended' if m['disclosure'] == 'affiliate' else 'Sponsored'}\n"

        # Insert before FAQ section if it exists, else append
        if "## Frequently Asked Questions" in content:
            content = content.replace(
                "## Frequently Asked Questions",
                resources + "\n## Frequently Asked Questions"
            )
        else:
            content += resources

        self._injections.append({
            "ts": datetime.now().isoformat(),
            "topic": topic[:40],
            "links": len(matches),
            "products": [m["product"] for m in matches],
        })
        return content

    # ── CTA Generator ─────────────────────────────────────────────────────────

    def generate_cta(
        self,
        topic: str = "",
        cta_type: str = "auto",
        cta_url: str = "",
    ) -> str:
        """
        Generate a context-appropriate call-to-action block.
        cta_type: "general" | "content" | "tool" | "lead_magnet" | "auto"
        """
        if cta_type == "auto":
            topic_lower = topic.lower()
            if any(kw in topic_lower for kw in ["crypto", "bitcoin", "ethereum", "defi", "web3", "btc", "eth"]):
                cta_type = "crypto"
            elif any(kw in topic_lower for kw in ["stock", "invest", "dividend", "etf", "market", "trading", "portfolio"]):
                cta_type = "stocks"
            elif any(kw in topic_lower for kw in ["content", "blog", "write", "post", "newsletter"]):
                cta_type = "content"
            elif any(kw in topic_lower for kw in ["tool", "software", "automate", "ai", "chatgpt"]):
                cta_type = "tool"
            elif any(kw in topic_lower for kw in ["free", "guide", "how to", "tips", "blueprint"]):
                cta_type = "lead_magnet"
            else:
                cta_type = "general"

        template = CTA_TEMPLATES.get(cta_type, CTA_TEMPLATES["general"])
        return template.format(
            brand=self.brand,
            cta_url=cta_url or self.cta_url,
            lead_magnet_title=self.lead_title,
            disclosure=" _(affiliate link)_" if self.amazon_tag else "",
        )

    # ── Lead Magnet (Email Capture) ───────────────────────────────────────────

    def generate_email_capture(
        self,
        blog_title: str,
        topic: str,
        offer_title: str = "",
    ) -> str:
        """Generate a standalone email capture HTML page / popup."""
        offer = offer_title or self.lead_title
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{offer} — Free Download</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',Arial,sans-serif;background:linear-gradient(135deg,#0d0f14 0%,#13161d 100%);
     min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.box{{background:#1a1e28;border:1px solid #2a2f3e;border-radius:16px;padding:48px 40px;
      max-width:520px;width:100%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.4)}}
.badge{{display:inline-block;background:rgba(0,212,255,.12);color:#00d4ff;border:1px solid rgba(0,212,255,.3);
        border-radius:20px;padding:4px 14px;font-size:12px;font-weight:700;margin-bottom:16px}}
h1{{color:#e0e6f0;font-size:1.6rem;line-height:1.3;margin-bottom:10px}}
.sub{{color:#8891a8;font-size:14px;line-height:1.6;margin-bottom:28px}}
.benefits{{text-align:left;margin-bottom:28px}}
.benefits li{{color:#a0a8b8;font-size:13px;padding:5px 0;list-style:none}}
.benefits li::before{{content:"✓ ";color:#00ff88;font-weight:700}}
input{{width:100%;padding:13px 16px;border-radius:8px;border:1px solid #2a2f3e;
       background:#0d0f14;color:#e0e6f0;font-size:14px;margin-bottom:12px;outline:none}}
input:focus{{border-color:#00d4ff}}
.btn{{width:100%;padding:14px;background:linear-gradient(135deg,#00d4ff,#0099bb);
      color:#000;border:none;border-radius:8px;font-weight:700;font-size:15px;
      cursor:pointer;transition:opacity .2s}}
.btn:hover{{opacity:.9}}
.fine{{color:#555e77;font-size:11px;margin-top:12px}}
.topic{{color:#555e77;font-size:12px;margin-top:20px}}
</style>
</head>
<body>
<div class="box">
  <div class="badge">FREE DOWNLOAD</div>
  <h1>🚀 {offer}</h1>
  <p class="sub">Get the exact blueprint that powers our AI automation system.<br>
  Based on the insights from: <em>{blog_title[:60]}</em></p>
  <ul class="benefits">
    <li>The 7-step content automation framework</li>
    <li>AI prompt templates that generate income</li>
    <li>The $0 traffic strategy using trending topics</li>
    <li>Our full tool stack (most are free)</li>
  </ul>
  <form onsubmit="handleSubmit(event)">
    <input type="text"  name="name"  placeholder="Your first name" required>
    <input type="email" name="email" placeholder="Your best email" required>
    <button type="submit" class="btn">→ Send Me the Blueprint</button>
  </form>
  <p class="fine">No spam. Unsubscribe anytime. We hate spam too.</p>
  <p class="topic">Related: {topic[:50]}</p>
</div>
<script>
function handleSubmit(e){{
  e.preventDefault();
  const name=e.target.name.value,email=e.target.email.value;
  document.querySelector('.box').innerHTML=
    '<div style="padding:40px;color:#e0e6f0"><h2 style="color:#00ff88;font-size:2rem">🎉 You\'re In!</h2>'
    +'<p style="margin-top:12px;color:#8891a8">Check your email — '+email+'<br>Your blueprint is on the way!</p></div>';
  // TODO: POST to your email service (ConvertKit, Mailchimp, etc.)
  // fetch('/api/leads',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name,email,topic:'{topic[:40]}'}})}} )
}}
</script>
</body>
</html>"""

    # ── Lead Magnet PDF ───────────────────────────────────────────────────────

    def generate_lead_magnet_pdf(
        self,
        topic: str,
        output_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """Generate a simple PDF lead magnet outline using OpenAI + reportlab."""
        output_dir = output_dir or (ROOT / "outputs" / "reports")
        output_dir.mkdir(parents=True, exist_ok=True)

        from core.llm_client import safe_openai_call

        try:
            prompt = f"""Create a lead magnet outline for: "{topic}"
Brand: {self.brand}

Generate a 5-chapter ebook outline with:
- Compelling title
- Subtitle
- Tagline
- 5 chapters, each with: title, 3 key points, 1 actionable exercise

Format as JSON:
{{
  "title": "...",
  "subtitle": "...",
  "tagline": "...",
  "chapters": [
    {{"num": 1, "title": "...", "points": ["...","...","..."], "exercise": "..."}},
    ...
  ]
}}"""
            resp = safe_openai_call(
                messages=[{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=1200, temperature=0.7,
                bot_name="monetization",
            )
            raw = resp.choices[0].message.content.strip()
            raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
            outline = json.loads(raw)
        except Exception as e:
            logger.warning(f"Lead magnet outline generation failed: {e}")
            outline = {
                "title": self.lead_title,
                "subtitle": f"The Complete Guide to {topic}",
                "tagline": "From Beginner to Profitable in 30 Days",
                "chapters": [
                    {"num": i, "title": f"Chapter {i}", "points": ["Key point 1", "Key point 2", "Key point 3"], "exercise": "Complete the worksheet"}
                    for i in range(1, 6)
                ],
            }

        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

            slug = re.sub(r"[^\w-]", "-", topic.lower())[:40]
            fname = f"lead_magnet_{slug}.pdf"
            path = output_dir / fname

            doc = SimpleDocTemplate(str(path), pagesize=letter,
                                       leftMargin=inch, rightMargin=inch,
                                       topMargin=inch, bottomMargin=inch)
            styles = getSampleStyleSheet()
            story = []

            # Cover
            story.append(Paragraph(outline["title"], ParagraphStyle(
                "Cover", parent=styles["Title"],
                fontSize=24, textColor=colors.HexColor("#0d0d0d"),
                spaceAfter=8, alignment=1,
            )))
            story.append(Paragraph(outline["subtitle"], ParagraphStyle(
                "Sub", parent=styles["Normal"],
                fontSize=14, textColor=colors.grey, alignment=1, spaceAfter=4,
            )))
            story.append(Paragraph(outline["tagline"], ParagraphStyle(
                "Tag", parent=styles["Normal"],
                fontSize=11, textColor=colors.HexColor("#0099bb"), alignment=1, spaceAfter=20,
            )))
            story.append(Paragraph(f"By {self.brand}", ParagraphStyle(
                "By", parent=styles["Normal"],
                fontSize=10, textColor=colors.grey, alignment=1,
            )))
            story.append(Spacer(1, 30))
            story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#00d4ff")))
            story.append(Spacer(1, 20))

            # Chapters
            for ch in outline.get("chapters", []):
                story.append(Paragraph(
                    f"Chapter {ch['num']}: {ch['title']}",
                    ParagraphStyle("ChTitle", parent=styles["Heading2"],
                                   fontSize=14, textColor=colors.HexColor("#0d0d0d"), spaceAfter=8)
                ))
                for pt in ch.get("points", []):
                    story.append(Paragraph(f"• {pt}", ParagraphStyle(
                        "Pt", parent=styles["Normal"],
                        fontSize=11, leftIndent=20, spaceAfter=4,
                    )))
                if ch.get("exercise"):
                    story.append(Paragraph(
                        f"📝 Exercise: {ch['exercise']}",
                        ParagraphStyle("Ex", parent=styles["Normal"],
                                       fontSize=10, textColor=colors.HexColor("#0099bb"),
                                       leftIndent=20, spaceAfter=14)
                    ))
                story.append(Spacer(1, 10))

            # CTA page
            story.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
            story.append(Spacer(1, 20))
            story.append(Paragraph(f"Want More? Visit {self.cta_url}", ParagraphStyle(
                "CTA", parent=styles["Normal"],
                fontSize=12, textColor=colors.HexColor("#0099bb"), alignment=1,
            )))

            doc.build(story)
            logger.info(f"Lead magnet PDF created: {path}")
            return path

        except ImportError:
            logger.warning("reportlab not installed — skipping PDF generation")
            return None
        except Exception as e:
            logger.error(f"PDF generation failed: {e}")
            return None

    # ── Revenue Tracking ──────────────────────────────────────────────────────

    def get_injection_stats(self) -> Dict:
        return {
            "total_injections": len(self._injections),
            "total_links": sum(i["links"] for i in self._injections),
            "recent": self._injections[-10:],
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_engine: Optional[MonetizationEngine] = None


def get_monetization_engine() -> MonetizationEngine:
    global _engine
    if _engine is None:
        _engine = MonetizationEngine()
    return _engine
