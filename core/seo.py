"""
core/seo.py — SEO Autopilot

Keyword research, on-page SEO scoring, content optimization,
and Google Search Console integration. NarAI uses this to ensure
every blog post is discoverable and ranking.
"""

from __future__ import annotations
import json
import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

DATA_FILE = Path("data/seo_tracker.json")

BRAND_NICHE = os.getenv("BRAND_NICHE", "AI tools for making money, stock insights, and crypto trends")
CTA_URL = os.getenv("CTA_URL", "https://grateful-flexibility-production.up.railway.app/landing")

# ─── Seed keywords by niche ──────────────────────────────────────────────────

SEED_KEYWORDS: Dict[str, List[str]] = {
    "crypto": [
        "crypto passive income", "bitcoin investing beginner", "how to earn crypto",
        "best crypto for 2025", "crypto affiliate marketing", "defi passive income",
        "coinbase review", "crypto side hustle",
    ],
    "investing": [
        "stock market for beginners", "passive income investing", "dividend stocks 2025",
        "robinhood review", "how to invest $100", "index fund vs etf",
        "best stocks to buy now", "dollar cost averaging explained",
    ],
    "ai_tools": [
        "best AI tools to make money", "ChatGPT side hustle", "AI content creation",
        "make money with AI 2025", "AI affiliate marketing", "jasper ai review",
        "AI for passive income", "automate business with AI",
    ],
    "passive_income": [
        "passive income ideas 2025", "make money online autopilot",
        "digital products passive income", "affiliate marketing for beginners",
        "best passive income streams", "how to earn while you sleep",
        "online income streams", "side hustle passive income",
    ],
    "general": [
        "make money online", "side hustle ideas", "financial freedom 2025",
        "online business ideas", "earn money from home", "digital marketing tips",
    ],
}


# ─── GPT helpers ──────────────────────────────────────────────────────────────

def _gpt(prompt: str, system: str = "", max_tokens: int = 600) -> str:
    from core.llm_client import safe_openai_call
    model = os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini")
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    r = safe_openai_call(messages=msgs, model=model, max_tokens=max_tokens,
                         temperature=0.5, bot_name="seo._gpt")
    return r.choices[0].message.content.strip()


def _gpt_json(prompt: str, system: str = "", max_tokens: int = 800) -> any:
    raw = _gpt(prompt, system, max_tokens)
    try:
        m = re.search(r"```json\s*([\s\S]+?)\s*```", raw)
        return json.loads(m.group(1) if m else raw)
    except Exception:
        return {}


# ─── On-page SEO Scorer ───────────────────────────────────────────────────────

def score_content(content: str, target_keyword: str = "") -> Dict:
    """
    Score a piece of content for on-page SEO quality.
    Returns a 0-100 score with detailed breakdown.
    """
    score = 0
    issues: List[str] = []
    wins: List[str] = []
    kw = target_keyword.lower()

    # Word count
    words = len(content.split())
    if words >= 1200:
        score += 20
        wins.append(f"Word count: {words} words (excellent)")
    elif words >= 700:
        score += 12
        wins.append(f"Word count: {words} words (good)")
    elif words >= 400:
        score += 6
        issues.append(f"Word count: {words} — aim for 800+")
    else:
        issues.append(f"Word count: {words} — too short, aim for 800+")

    # Headings structure
    h1 = len(re.findall(r"^# .+", content, re.MULTILINE))
    h2 = len(re.findall(r"^## .+", content, re.MULTILINE))
    h3 = len(re.findall(r"^### .+", content, re.MULTILINE))
    if h1 == 1:
        score += 10
        wins.append("Has exactly 1 H1")
    elif h1 == 0:
        issues.append("Missing H1 heading")
    else:
        issues.append(f"Multiple H1s ({h1}) — use only one")
    if h2 >= 2:
        score += 10
        wins.append(f"Has {h2} H2 subheadings")
    else:
        issues.append("Add at least 2 H2 subheadings")
    if h3 >= 1:
        score += 5
        wins.append(f"Has {h3} H3 subsections")

    # Keyword presence
    if kw:
        content_lower = content.lower()
        kw_count = content_lower.count(kw)
        kw_density = round(kw_count / max(words, 1) * 100, 2)

        if kw_count >= 1 and re.search(r"^# .+", content, re.MULTILINE):
            h1_text = re.search(r"^# (.+)", content, re.MULTILINE)
            if h1_text and kw in h1_text.group(1).lower():
                score += 15
                wins.append("Keyword in H1")
            else:
                issues.append("Add keyword to H1")

        if 0.5 <= kw_density <= 2.5:
            score += 15
            wins.append(f"Keyword density: {kw_density}% (ideal 0.5-2.5%)")
        elif kw_density > 2.5:
            score += 5
            issues.append(f"Keyword stuffing ({kw_density}%) — reduce usage")
        elif kw_count > 0:
            score += 5
            issues.append(f"Keyword only appears {kw_count}x — add more naturally")
        else:
            issues.append(f"Keyword '{target_keyword}' not found in content")

        # Keyword in first paragraph
        first_para = content[:300].lower()
        if kw in first_para:
            score += 10
            wins.append("Keyword in first paragraph")
        else:
            issues.append("Add keyword to first paragraph")
    else:
        score += 20  # no keyword check — give benefit of doubt

    # Internal/external links
    links = re.findall(r"\[.+?\]\(https?://.+?\)", content)
    if len(links) >= 2:
        score += 10
        wins.append(f"{len(links)} outbound links found")
    elif len(links) == 1:
        score += 5
        issues.append("Add 1-2 more outbound links")
    else:
        issues.append("No links found — add 2-3 relevant links")

    # CTA presence
    if CTA_URL in content or "sign up" in content.lower() or "free" in content.lower():
        score += 5
        wins.append("CTA present")
    else:
        issues.append("Add a CTA or link to lead magnet")

    score = min(score, 100)
    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D"

    return {
        "score": score,
        "grade": grade,
        "word_count": words,
        "keyword": target_keyword,
        "keyword_density_pct": round(words and content.lower().count(kw) / words * 100, 2) if kw else 0,
        "headings": {"h1": h1, "h2": h2, "h3": h3},
        "link_count": len(links),
        "wins": wins,
        "issues": issues,
    }


def optimize_content(content: str, target_keyword: str, title: str = "") -> Dict:
    """
    Run SEO score + GPT suggestions to improve the content.
    Returns original score, suggestions, and an optimized version.
    """
    result = score_content(content, target_keyword)
    if result["score"] >= 85:
        return {**result, "suggestions": [], "optimized": content,
                "message": "Content is already well-optimized."}

    issues_str = "\n".join(f"- {i}" for i in result["issues"])
    suggestions_raw = _gpt(
        f"This blog post needs SEO improvements. Issues found:\n{issues_str}\n\n"
        f"Target keyword: {target_keyword}\n"
        f"Give 3-5 specific, actionable improvements (not generic advice). "
        f"Return as JSON array of strings.",
        system="You are an expert SEO consultant. Be specific, actionable.",
        max_tokens=300,
    )
    try:
        m = re.search(r"\[[\s\S]+\]", suggestions_raw)
        suggestions = json.loads(m.group(0)) if m else [suggestions_raw]
    except Exception:
        suggestions = [suggestions_raw]

    # GPT-optimized version (only if score < 70)
    optimized = content
    if result["score"] < 70 and len(content) < 3000:
        optimized = _gpt(
            f"Rewrite this blog post to be better SEO-optimized for the keyword: '{target_keyword}'\n\n"
            f"Issues to fix:\n{issues_str}\n\n"
            f"CONTENT:\n{content[:2000]}",
            system=f"You are an SEO expert rewriting content for {BRAND_NICHE}. "
            f"Keep the same information but improve structure, keyword placement, "
            f"and add CTA to {CTA_URL}",
            max_tokens=1200,
        )

    return {**result, "suggestions": suggestions, "optimized": optimized}


# ─── Keyword Research ─────────────────────────────────────────────────────────

def research_keywords(topic: str, niche: str = "general", count: int = 10) -> Dict:
    """
    Generate keyword opportunities for a topic using GPT + seed keywords.
    Returns keywords with estimated intent and difficulty.
    """
    seeds = SEED_KEYWORDS.get(niche, SEED_KEYWORDS["general"])
    seeds_str = ", ".join(seeds[:5])

    raw = _gpt_json(
        f"Generate {count} SEO keyword opportunities for the topic: '{topic}'\n"
        f"Niche: {niche} ({BRAND_NICHE})\n"
        f"Seed keywords for context: {seeds_str}\n\n"
        f"Return a JSON array of objects, each with:\n"
        f"  - keyword (string)\n"
        f"  - search_intent (informational/commercial/transactional/navigational)\n"
        f"  - estimated_difficulty (low/medium/high)\n"
        f"  - estimated_monthly_searches (rough range like '1k-5k')\n"
        f"  - content_angle (brief description of content to write for this keyword)",
        system="You are an expert SEO keyword researcher. Focus on long-tail, low-competition opportunities.",
        max_tokens=1000,
    )

    keywords = raw if isinstance(raw, list) else []

    # Save for tracking
    _track_keywords(topic, keywords)

    return {
        "topic": topic,
        "niche": niche,
        "keywords": keywords,
        "count": len(keywords),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_quick_wins(niche: str = "general") -> List[Dict]:
    """Keywords with low difficulty and clear commercial intent — best to target now."""
    all_kw = _load_tracker().get("keywords", {})
    wins = []
    for topic, kws in all_kw.items():
        for kw in kws:
            if (kw.get("estimated_difficulty", "") == "low"
                    and kw.get("search_intent", "") in ("commercial", "transactional")):
                wins.append({**kw, "topic": topic})
    return sorted(wins, key=lambda x: x.get("keyword", ""))


# ─── GSC Integration ──────────────────────────────────────────────────────────

def get_gsc_insights(days: int = 28) -> Dict:
    """Pull real search performance data from Google Search Console."""
    try:
        from core.gsc import get_top_queries, get_low_ctr_opportunities
        queries = get_top_queries(days=days)
        opportunities = get_low_ctr_opportunities(days=days)
        return {
            "configured": True,
            "top_queries": queries[:20] if queries else [],
            "opportunities": opportunities[:10] if opportunities else [],
            "period_days": days,
        }
    except Exception as e:
        log.warning(f"GSC not configured: {e}")
        return {"configured": False, "error": str(e)}


def generate_seo_content(keyword: str, niche: str = "general") -> Dict:
    """
    Generate a fully SEO-optimized blog post for a target keyword.
    Returns scored content ready to publish.
    """
    from core.goal_tracker import increment
    from core.personality import get_identity

    identity = get_identity()
    article = _gpt(
        f"Write a comprehensive, SEO-optimized blog post targeting: '{keyword}'\n\n"
        f"Requirements:\n"
        f"- Title (H1): includes keyword, is compelling (click-worthy)\n"
        f"- Introduction: keyword in first sentence, hook reader immediately\n"
        f"- Body: 3-5 H2 sections with actionable tips and real numbers\n"
        f"- Include at least 2 external links (use placeholder [LINK])\n"
        f"- Conclusion: summary + CTA to get free AI Blueprint at {CTA_URL}\n"
        f"- Length: 800-1000 words\n"
        f"- Niche: {niche} | Brand: {BRAND_NICHE}",
        system=f"{identity}\n\nYou write SEO-optimized content that ranks and converts.",
        max_tokens=1500,
    )

    seo_result = score_content(article, keyword)

    try:
        increment("blog_posts", 1)
    except Exception:
        pass

    return {
        "keyword": keyword,
        "article": article,
        "seo_score": seo_result["score"],
        "seo_grade": seo_result["grade"],
        "word_count": seo_result["word_count"],
        "issues": seo_result["issues"],
        "wins": seo_result["wins"],
    }


# ─── Keyword tracker ──────────────────────────────────────────────────────────

def _load_tracker() -> Dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {"keywords": {}, "rankings": {}, "updated_at": ""}


def _save_tracker(data: Dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2))


def _track_keywords(topic: str, keywords: List):
    data = _load_tracker()
    data["keywords"][topic] = keywords
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_tracker(data)


def update_ranking(keyword: str, position: float, impressions: int = 0, clicks: int = 0):
    """Record a keyword's current search ranking for tracking over time."""
    data = _load_tracker()
    history = data["rankings"].setdefault(keyword, [])
    history.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "position": position,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": round(clicks / max(impressions, 1) * 100, 2),
    })
    if len(history) > 90:
        history[:] = history[-90:]
    _save_tracker(data)


def summary() -> Dict:
    data = _load_tracker()
    rankings = data.get("rankings", {})
    keywords_tracked = sum(len(v) for v in data.get("keywords", {}).values())
    avg_pos = round(
        sum(r[-1]["position"] for r in rankings.values() if r) / max(len(rankings), 1), 1
    ) if rankings else 0

    return {
        "keywords_researched": keywords_tracked,
        "keywords_ranked": len(rankings),
        "avg_position": avg_pos,
        "quick_wins_available": len(get_quick_wins()),
        "gsc_configured": bool(os.getenv("GSC_SERVICE_ACCOUNT_FILE")),
        "updated_at": data.get("updated_at", ""),
    }
