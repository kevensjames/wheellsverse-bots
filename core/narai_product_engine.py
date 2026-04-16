#!/usr/bin/env python3
"""
core/narai_product_engine.py
─────────────────────────────────────────────────────────────────────────────
NarAI Digital Product Creation Engine

Produces COMPLETE, ready-to-sell product packages for:
  • Gumroad    — viral-modeled, high-converting digital products (11-step)
  • Etsy       — printables, planners, digital art, template packs
  • Payhip     — PDFs, courses, memberships, bundles
  • Amazon KDP — ebooks, low-content books, journals

GUMROAD ENGINE (11-step viral modeling pipeline):
  Step 0  — Viral Product Modeling (analyze & replicate top Gumroad patterns)
  Step 1  — Niche + Viral Product Concept (proven formats only)
  Step 2  — Core Product + Value Stack
  Step 3  — Sales Page (Gumroad-optimized, high-conversion)
  Step 4  — PDF Content (clean modules, table of contents)
  Step 5  — Notion Structure (page layout, databases, templates)
  Step 6  — Cover Design Prompt (DALL·E / Midjourney / Leonardo)
  Step 7  — Cover Auto-Generation (DALL·E → Leonardo fallback)
  Step 8  — Gumroad Upload Data (title, description, price_cents, tags)
  Step 9  — Pricing Strategy (entry / premium / bundle)
  Step 10 — Legal Disclaimer (niche-appropriate)
  Step 11 — Marketing Pack (description, 3 X posts, 2 TikToks, 1 email)

OTHER PLATFORMS (9-step general pipeline):
  1. Strategy  2. Sales Page  3. Content  4. Bonuses  5. Cover
  6. Delivery  7. Pricing     8. Disclaimer  9. Marketing
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("narai_product_engine")

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

PRODUCTS_DIR = DATA_DIR / "narai_products"
PRODUCTS_DIR.mkdir(exist_ok=True)

THINK_PAUSE = 2   # seconds between heavy Claude calls


# ══════════════════════════════════════════════════════════════════════════════
# NICHES — NarAI picks from these based on market intelligence
# ══════════════════════════════════════════════════════════════════════════════

PRODUCT_NICHES = [
    "Trading / Finance",
    "AI tools / automation",
    "Online income / side hustles",
    "Productivity / self-improvement",
    "Tech / data / programming",
]

PLATFORM_PRODUCT_TYPES = {
    "gumroad": ["template_system", "mini_course", "playbook_toolkit", "creator_bundle", "prompt_pack"],
    "etsy": ["printable", "planner", "journal_template", "worksheet", "digital_art_pack", "tracker"],
    "payhip": ["ebook", "course_pdf", "membership_kit", "bundle", "toolkit", "resource_pack"],
    "amazon_kdp": ["ebook", "low_content_book", "journal", "workbook", "planner_book"],
}

# ── Gumroad-specific constants ─────────────────────────────────────────────────

GUMROAD_NICHES = [
    "Trading / Finance",
    "AI / Automation",
    "Online income / business systems",
    "Content creation systems",
    "Tech / programming tools",
    "Design / assets",
]

# Proven Gumroad product formats — NarAI picks exactly one
GUMROAD_FORMATS = {
    "template_system": {
        "label": "Template System",
        "description": "Notion, Excel, Canva, or automation tool templates",
        "delivery": ["Notion template", "PDF guide", "Canva files", "Excel/Sheets"],
        "why_it_sells": "Instant usability — buyers get results in minutes",
    },
    "mini_course": {
        "label": "Mini Course / Workshop",
        "description": "Short, actionable, outcome-focused course (PDF + video links)",
        "delivery": ["PDF workbook", "Video resource list", "Checklist", "Frameworks"],
        "why_it_sells": "Clear skill gain, low time commitment, high perceived value",
    },
    "playbook_toolkit": {
        "label": "Playbook / Guide + Toolkit",
        "description": "Deep PDF guide paired with templates and frameworks",
        "delivery": ["PDF playbook", "Template pack", "Framework sheets", "Examples"],
        "why_it_sells": "Complete system — not just info, but tools to execute",
    },
    "live_training": {
        "label": "Live Training / Membership Model",
        "description": "Trading education, coaching, or community access",
        "delivery": ["PDF curriculum", "Weekly session notes", "Resource vault", "Community link"],
        "why_it_sells": "Ongoing value, recurring revenue, community accountability",
    },
    "creator_bundle": {
        "label": "Creator Toolkit / Bundle",
        "description": "Content packs, scripts, presets, or digital assets",
        "delivery": ["Asset files", "Script pack", "Preset collection", "Usage guide"],
        "why_it_sells": "Saves massive time — everything pre-built and ready to use",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE HELPER (imported from autopilot if available, else standalone)
# ══════════════════════════════════════════════════════════════════════════════

def _claude(prompt: str, system: str = "", max_tokens: int = 4000) -> str:
    import anthropic
    model = os.getenv("NARAI_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    r = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system or _product_system(),
        messages=[{"role": "user", "content": prompt}],
    )
    return r.content[0].text.strip()


def _claude_json(prompt: str, system: str = "", max_tokens: int = 3000) -> Any:
    raw = _claude(prompt, system, max_tokens)
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw.strip())
    except Exception:
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return {}


def _product_system() -> str:
    return (
        "You are NarAI — a world-class digital product strategist and copywriter. "
        "You create premium digital products that sell because they solve real problems "
        "better than anything else on the market. "
        "You write high-conversion sales copy, deep product content, and polished marketing assets. "
        "You think in terms of buyer psychology, transformation, and perceived value. "
        "Every output must feel like a real, premium product ready to sell immediately. "
        "No fluff. No generic content. Authority tone with absolute clarity. "
        "Focus on VALUE, specificity, and real-world usability."
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — PRODUCT STRATEGY
# ══════════════════════════════════════════════════════════════════════════════

def build_product_strategy(
    platform: str,
    market_intel: dict,
    niche_hint: str = "",
) -> dict:
    """
    Generate a high-demand digital product strategy for the given platform.
    Returns a strategy dict with title, audience, problem, transformation, type, price.
    """
    platform_types = PLATFORM_PRODUCT_TYPES.get(platform, ["ebook", "guide"])
    niche_list = "\n".join(f"- {n}" for n in PRODUCT_NICHES)

    strategy = _claude_json(
        f"Platform: {platform.upper()}\n"
        f"Available product types for this platform: {', '.join(platform_types)}\n"
        f"Market intelligence:\n{json.dumps(market_intel, indent=2)[:3000]}\n\n"
        f"{'Niche preference: ' + niche_hint if niche_hint else 'Preferred niches:'}\n"
        f"{niche_list if not niche_hint else ''}\n\n"
        "Research what is SELLING RIGHT NOW on this platform. "
        "Choose the single best product opportunity.\n\n"
        "Return JSON:\n"
        "{\n"
        '  "title": "Premium product title (clear, high-value, no fluff)",\n'
        '  "subtitle": "Supporting subtitle that adds specificity",\n'
        '  "niche": "exact niche from the list",\n'
        '  "product_type": "type from platform list",\n'
        '  "target_audience": "very specific buyer persona",\n'
        '  "problem": "the exact painful problem this solves",\n'
        '  "transformation": {"before": "...", "after": "..."},\n'
        '  "price": 19.99,\n'
        '  "format": "PDF|Notion|Spreadsheet|Video+PDF|Printable",\n'
        '  "unique_angle": "what makes this 10x better than competitors",\n'
        '  "keywords": ["search term 1", "search term 2"],\n'
        '  "competitor_gap": "what existing products miss that this fills"\n'
        "}\n"
        "Pure JSON. No markdown.",
        max_tokens=1200,
    )

    if not isinstance(strategy, dict) or not strategy.get("title"):
        strategy = {
            "title": f"The Ultimate {platform.title()} Playbook",
            "subtitle": "Step-by-Step System to Results Fast",
            "niche": "Online income / side hustles",
            "product_type": platform_types[0],
            "target_audience": "Digital entrepreneurs wanting passive income",
            "problem": "Don't know how to create and sell digital products profitably",
            "transformation": {
                "before": "Struggling to make money online, no proven system",
                "after": "Generating consistent digital product income with a repeatable system",
            },
            "price": 19.99,
            "format": "PDF",
            "unique_angle": "Battle-tested frameworks, not theory",
            "keywords": ["digital products", "passive income", "make money online"],
            "competitor_gap": "Most guides are vague — this gives exact scripts and templates",
        }

    log.info(f"[ProductEngine] Strategy: '{strategy.get('title')}' for {platform}")
    return strategy


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — SALES PAGE
# ══════════════════════════════════════════════════════════════════════════════

def build_sales_page(strategy: dict, platform: str) -> str:
    """
    Generate a full high-conversion sales page for the product.
    Structured: Hook → Problem → Solution → Breakdown → Benefits →
                Social Proof → Price Justification → CTA
    """
    title = strategy.get("title", "")
    audience = strategy.get("target_audience", "")
    problem = strategy.get("problem", "")
    before = strategy.get("transformation", {}).get("before", "")
    after = strategy.get("transformation", {}).get("after", "")
    price = strategy.get("price", 19.99)
    unique = strategy.get("unique_angle", "")
    product_type = strategy.get("product_type", "ebook")

    sales_page = _claude(
        f"Write a COMPLETE, high-conversion sales page for this digital product:\n\n"
        f"Product: {title}\n"
        f"Platform: {platform.upper()}\n"
        f"Type: {product_type}\n"
        f"Target buyer: {audience}\n"
        f"Pain point: {problem}\n"
        f"Before state: {before}\n"
        f"After state (transformation): {after}\n"
        f"Price: ${price}\n"
        f"Unique angle: {unique}\n\n"
        "Write the full sales page with these EXACT sections:\n\n"
        "---\n"
        "## 🪝 HOOK\n"
        "(Powerful opening line — 1-2 sentences that stop the scroll)\n\n"
        "## 😣 THE PROBLEM\n"
        "(Pain agitation — 3-4 paragraphs, get inside their head)\n\n"
        "## 💡 THE SOLUTION\n"
        "(Introduce the product — position it as the missing piece)\n\n"
        "## 📦 WHAT'S INSIDE\n"
        "(Detailed product breakdown — every module/section/template)\n\n"
        "## ✅ YOUR RESULTS\n"
        "(5-7 specific, measurable benefits — outcomes not features)\n\n"
        "## ⭐ WHAT OTHERS ARE SAYING\n"
        "(3 realistic testimonials — specific results, realistic voices, no hype)\n\n"
        "## 💰 INVESTMENT\n"
        f"(Price justification — why ${price} is a steal — compare to alternatives)\n\n"
        "## 🚀 GET INSTANT ACCESS\n"
        "(Strong CTA — urgency + guarantee + what happens after purchase)\n"
        "---\n\n"
        "Style rules:\n"
        "- Clean, persuasive, not hype-heavy\n"
        "- Short paragraphs (2-3 sentences max)\n"
        "- Use bold for key phrases\n"
        "- Sound like a premium course, not a cheap PDF\n"
        "- Every section must transition naturally to the next\n"
        f"- Platform-optimized for {platform} (Gumroad=longer, Etsy=punchy, Payhip=medium, KDP=formal)\n\n"
        "Make this the best sales page ever written for this type of product.",
        max_tokens=4000,
    )

    time.sleep(THINK_PAUSE)
    return sales_page


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — PRODUCT CONTENT
# ══════════════════════════════════════════════════════════════════════════════

def build_product_content(strategy: dict, platform: str) -> str:
    """
    Generate the ACTUAL product content based on product type.
    Handles: ebook, course_pdf, template_pack, prompt_pack, printable, guide, etc.
    """
    title = strategy.get("title", "")
    subtitle = strategy.get("subtitle", "")
    product_type = strategy.get("product_type", "ebook")
    audience = strategy.get("target_audience", "")
    problem = strategy.get("problem", "")
    after = strategy.get("transformation", {}).get("after", "")
    niche = strategy.get("niche", "")

    if product_type in ("ebook", "guide", "course_pdf"):
        content = _build_ebook_content(title, subtitle, audience, problem, after, niche)

    elif product_type in ("template_pack", "swipe_file", "resource_pack", "toolkit"):
        content = _build_template_pack(title, audience, problem, niche)

    elif product_type in ("prompt_pack",):
        content = _build_prompt_pack(title, audience, niche)

    elif product_type in ("printable", "planner", "journal_template",
                          "worksheet", "tracker", "low_content_book",
                          "journal", "workbook", "planner_book"):
        content = _build_printable_content(title, subtitle, audience, product_type, niche)

    elif product_type in ("membership_kit", "bundle"):
        content = _build_bundle_content(title, audience, problem, after, niche)

    else:
        # Generic high-value guide as fallback
        content = _build_ebook_content(title, subtitle, audience, problem, after, niche)

    return content


def _build_ebook_content(
    title: str, subtitle: str, audience: str, problem: str, after: str, niche: str
) -> str:
    """Write a complete ebook with full chapters."""
    # Generate outline first
    outline = _claude_json(
        f"Create a detailed ebook outline for:\n"
        f"Title: {title}\n"
        f"Subtitle: {subtitle}\n"
        f"Audience: {audience}\n"
        f"Problem solved: {problem}\n"
        f"Transformation: {after}\n"
        f"Niche: {niche}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "intro_hook": "compelling intro angle",\n'
        '  "chapters": [\n'
        '    {"num": 1, "title": "...", "summary": "...", '
        '"key_points": ["...", "..."], "action_step": "..."}\n'
        "  ],\n"
        '  "conclusion_angle": "...",\n'
        '  "key_framework": "name of the core framework/system taught"\n'
        "}\n"
        "Include 6-8 chapters. Pure JSON.",
        max_tokens=2000,
    )

    if not isinstance(outline, dict):
        outline = {
            "intro_hook": "The hidden system that changes everything",
            "chapters": [
                {"num": i + 1, "title": f"Chapter {i + 1}", "summary": "",
                 "key_points": ["Key insight", "Actionable step"],
                 "action_step": "Apply the lesson today"}
                for i in range(6)
            ],
            "conclusion_angle": "Your next 30 days",
            "key_framework": "The 5-Step System",
        }

    framework = outline.get("key_framework", "The Core System")
    parts = []
    parts.append(f"# {title}\n")
    if subtitle:
        parts.append(f"## {subtitle}\n\n")
    parts.append(f"*{framework}*\n\n")
    parts.append("---\n\n")

    # Introduction
    intro_hook = outline.get("intro_hook", "")
    intro = _claude(
        f"Write the introduction for the ebook '{title}'.\n"
        f"Hook angle: {intro_hook}\n"
        f"Reader: {audience} struggling with: {problem}\n"
        f"Promise: By the end they will: {after}\n\n"
        "Write 500-700 words. Make it so compelling they MUST keep reading.\n"
        "Include: a story or bold statement, empathy for the reader's pain, "
        "a credibility bridge, and a clear promise of what's inside.",
        max_tokens=1200,
    )
    parts.append(f"## Introduction\n\n{intro}\n\n")

    # Chapters
    for ch in (outline.get("chapters") or [])[:8]:
        ch_num = ch.get("num", 1)
        ch_title = ch.get("title", f"Chapter {ch_num}")
        summary = ch.get("summary", "")
        points = ch.get("key_points", [])
        action = ch.get("action_step", "")

        log.info(f"[ProductEngine] Writing chapter {ch_num}: {ch_title}")
        chapter = _claude(
            f"Write Chapter {ch_num} of '{title}'.\n\n"
            f"Chapter title: {ch_title}\n"
            f"What this chapter covers: {summary}\n"
            f"Key points to teach: {', '.join(points)}\n"
            f"Chapter action step: {action}\n\n"
            "Write 1000-1400 words. Structure:\n"
            "- Opening hook or mini-story (make it real)\n"
            "- Core concept explained simply\n"
            "- 2-3 actionable frameworks or steps\n"
            "- Real examples (specific, not generic)\n"
            "- Chapter Summary (5 bullet points)\n"
            f"- Action Step: {action}\n\n"
            "Write like a bestselling author. Conversational but authoritative.",
            max_tokens=2200,
        )
        parts.append(f"## Chapter {ch_num}: {ch_title}\n\n{chapter}\n\n")
        time.sleep(1)

    # Conclusion
    conc_angle = outline.get("conclusion_angle", "Your next steps")
    conclusion = _claude(
        f"Write the conclusion of '{title}'.\n"
        f"Angle: {conc_angle}\n"
        f"Reader transformation: from '{problem}' → '{after}'\n\n"
        "Write 350-500 words. Give them a 30-day action plan, "
        "an inspiring close, and a strong final CTA.",
        max_tokens=800,
    )
    parts.append(f"## Conclusion: {conc_angle}\n\n{conclusion}\n\n")

    return "".join(parts)


def _build_template_pack(
    title: str, audience: str, problem: str, niche: str
) -> str:
    """Build a complete template pack with multiple ready-to-use templates."""
    pack = _claude(
        f"Create a complete TEMPLATE PACK: '{title}'\n"
        f"Audience: {audience}\n"
        f"Problem solved: {problem}\n"
        f"Niche: {niche}\n\n"
        "Include the following:\n\n"
        "## PACK OVERVIEW\n"
        "(What's included, how to use each template, time saved)\n\n"
        "## TEMPLATE 1: [Name]\n"
        "(Full template with placeholder fields, instructions, example filled-in version)\n\n"
        "## TEMPLATE 2: [Name]\n"
        "(Same format)\n\n"
        "## TEMPLATE 3: [Name]\n\n"
        "## TEMPLATE 4: [Name]\n\n"
        "## TEMPLATE 5: [Name]\n\n"
        "## HOW TO CUSTOMIZE EACH TEMPLATE\n"
        "(Step-by-step personalization guide)\n\n"
        "## PRO TIPS\n"
        "(5 power-user tips for getting maximum value)\n\n"
        "Make each template immediately usable. Include real content, not just labels.",
        max_tokens=4000,
    )
    return pack


def _build_prompt_pack(title: str, audience: str, niche: str) -> str:
    """Build a premium AI prompt pack."""
    pack = _claude(
        f"Create a premium AI PROMPT PACK: '{title}'\n"
        f"Audience: {audience}\n"
        f"Niche: {niche}\n\n"
        "Structure:\n\n"
        "## WELCOME + HOW TO USE THIS PACK\n"
        "(How to get 10x better results from AI using these prompts)\n\n"
        "## CATEGORY 1: [Relevant Category]\n"
        "(8-10 expert-level prompts with:\n"
        "  - The prompt itself (copy-paste ready)\n"
        "  - What it does\n"
        "  - Example output snippet\n"
        "  - How to customize it)\n\n"
        "## CATEGORY 2: [Category]\n"
        "(Same format, 8-10 prompts)\n\n"
        "## CATEGORY 3: [Category]\n"
        "(Same format, 8-10 prompts)\n\n"
        "## CATEGORY 4: [Category]\n"
        "(5-8 advanced prompts)\n\n"
        "## MEGA-PROMPT FRAMEWORK\n"
        "(1 power prompt that combines everything)\n\n"
        "## CHAINING PROMPTS TUTORIAL\n"
        "(How to chain these prompts for complex tasks)\n\n"
        "Make these prompts genuinely powerful, not obvious. Real expert-level craft.",
        max_tokens=4000,
    )
    return pack


def _build_printable_content(
    title: str, subtitle: str, audience: str, product_type: str, niche: str
) -> str:
    """Build printable/planner/journal content structure."""
    content = _claude(
        f"Create a complete {product_type.replace('_', ' ').title()}: '{title}'\n"
        f"Subtitle: {subtitle}\n"
        f"Audience: {audience}\n"
        f"Niche: {niche}\n\n"
        "Provide the COMPLETE content layout including:\n\n"
        "## PRODUCT OVERVIEW\n"
        "(Purpose, how to use, what makes this special)\n\n"
        "## PAGE-BY-PAGE LAYOUT\n"
        "(Describe exactly what goes on each page/section:\n"
        " - Page title\n"
        " - Fields/prompts/sections\n"
        " - Instructions for the user\n"
        " - Design notes for Canva)\n\n"
        "## FULL CONTENT FOR EACH PAGE\n"
        "(Write the actual text, prompts, headers for every page)\n\n"
        "## DESIGN SPECIFICATIONS\n"
        "(Canva dimensions, color palette, fonts, layout guidelines)\n\n"
        "## USAGE GUIDE\n"
        "(How to get the most out of this product — included as a page)\n\n"
        "Make it genuinely beautiful and deeply functional.",
        max_tokens=4000,
    )
    return content


def _build_bundle_content(
    title: str, audience: str, problem: str, after: str, niche: str
) -> str:
    """Build a membership/bundle kit with multiple components."""
    content = _claude(
        f"Create a complete DIGITAL BUNDLE/KIT: '{title}'\n"
        f"Audience: {audience}\n"
        f"Problem: {problem}\n"
        f"Transformation: {after}\n"
        f"Niche: {niche}\n\n"
        "Structure this as a premium bundle with:\n\n"
        "## BUNDLE OVERVIEW\n"
        "(Everything included, total value breakdown, how to use)\n\n"
        "## COMPONENT 1: Main Guide (mini-ebook — 3-4 chapters)\n"
        "(Write the full guide — practical, step-by-step)\n\n"
        "## COMPONENT 2: Template Collection\n"
        "(3-4 ready-to-use templates with full content)\n\n"
        "## COMPONENT 3: Checklists & Frameworks\n"
        "(3 actionable checklists)\n\n"
        "## COMPONENT 4: Resource Rolodex\n"
        "(Top 20 tools, links, and resources with descriptions)\n\n"
        "## COMPONENT 5: Quick Reference Card\n"
        "(1-page cheat sheet of the entire system)\n\n"
        "## WEEKLY/MONTHLY STRUCTURE (if membership)\n"
        "(How content is structured and delivered)\n\n"
        "Every component must deliver standalone value.",
        max_tokens=4000,
    )
    return content


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — BONUS MATERIALS
# ══════════════════════════════════════════════════════════════════════════════

def build_bonus_materials(strategy: dict) -> dict:
    """Generate bonus materials: checklist, quick-start guide, templates."""
    title = strategy.get("title", "")
    audience = strategy.get("target_audience", "")
    after = strategy.get("transformation", {}).get("after", "")
    niche = strategy.get("niche", "")

    bonuses_raw = _claude(
        f"Create BONUS MATERIALS for the product: '{title}'\n"
        f"Buyer: {audience}\n"
        f"Goal: {after}\n"
        f"Niche: {niche}\n\n"
        "Create all three bonuses in full:\n\n"
        "---\n"
        "## BONUS 1: QUICK-START CHECKLIST\n"
        "(20-point checklist — actionable, numbered, no fluff)\n\n"
        "## BONUS 2: QUICK-START GUIDE (3-5 pages)\n"
        "(The fastest path to first results — written as if reader has 30 minutes)\n\n"
        "## BONUS 3: TEMPLATE / SCRIPT / TRACKER\n"
        "(One high-value template directly related to the product — fully filled in)\n"
        "---\n\n"
        "Each bonus must feel like it's worth more than the product itself.",
        max_tokens=3000,
    )

    # Parse into sections
    checklist = _extract_section(bonuses_raw, "QUICK-START CHECKLIST", "QUICK-START GUIDE")
    quickstart = _extract_section(bonuses_raw, "QUICK-START GUIDE", "TEMPLATE")
    template = _extract_section(bonuses_raw, "BONUS 3:", None)

    return {
        "checklist": checklist or bonuses_raw[:1000],
        "quick_start": quickstart or "",
        "template": template or "",
        "raw": bonuses_raw,
    }


def _extract_section(text: str, start_marker: str, end_marker: Optional[str]) -> str:
    """Extract a section of text between two markers."""
    try:
        start_idx = text.find(start_marker)
        if start_idx == -1:
            return ""
        start_idx += len(start_marker)
        if end_marker:
            end_idx = text.find(end_marker, start_idx)
            return text[start_idx:end_idx].strip() if end_idx != -1 else text[start_idx:].strip()
        return text[start_idx:].strip()
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — COVER DESIGN PROMPT
# ══════════════════════════════════════════════════════════════════════════════

def build_cover_design_prompt(strategy: dict, platform: str) -> dict:
    """
    Generate an AI image generation prompt for product cover.
    Returns prompts for Midjourney, DALL·E, and Leonardo AI.
    """
    title = strategy.get("title", "")
    niche = strategy.get("niche", "")
    product_type = strategy.get("product_type", "ebook")
    price = strategy.get("price", 19.99)

    # Determine style based on niche and platform
    style_map = {
        "Trading / Finance": "dark luxury, deep navy and gold, financial charts, premium minimal",
        "AI tools / automation": "futuristic, electric blue and white, circuit patterns, clean tech",
        "Online income / side hustles": "modern bold, gradient orange-to-purple, clean sans-serif",
        "Productivity / self-improvement": "minimalist, soft neutrals, clean lines, premium journaling feel",
        "Tech / data / programming": "dark mode, neon accents, code-inspired, matrix-adjacent but premium",
    }
    niche_style = style_map.get(niche, "modern, clean, premium, bold typography")

    cover_data = _claude_json(
        f"Create detailed AI image generation prompts for a product cover:\n\n"
        f"Product: {title}\n"
        f"Platform: {platform}\n"
        f"Type: {product_type}\n"
        f"Niche: {niche}\n"
        f"Price point: ${price} (must look premium)\n"
        f"Base style: {niche_style}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "midjourney": "full Midjourney prompt with --ar 2:3 --v 6 --style raw parameters",\n'
        '  "dalle": "DALL·E 3 prompt (detailed, descriptive)",\n'
        '  "leonardo": "Leonardo AI prompt with style settings",\n'
        '  "canva_search": "exact Canva template search terms",\n'
        '  "color_palette": ["#hex1", "#hex2", "#hex3"],\n'
        '  "typography": {"title_font": "...", "body_font": "...", "style": "..."},\n'
        '  "visual_elements": ["element1", "element2", "element3"],\n'
        '  "mood": "one word mood/feeling",\n'
        '  "dimensions": "platform-specific (e.g. 1800x2700px for KDP)"\n'
        "}\n"
        "Pure JSON. Make the prompts VERY specific and detailed — not generic.",
        max_tokens=1000,
    )

    if not isinstance(cover_data, dict):
        cover_data = {
            "midjourney": f"Premium digital product cover for '{title}', {niche_style}, "
            "professional mockup, clean white background, high-end design --ar 2:3 --v 6",
            "dalle": f"A premium ebook cover for '{title}'. {niche_style} aesthetic. "
            "Professional typography, high-end design, suitable for digital product marketplace.",
            "leonardo": f"Digital product cover, {niche_style}, premium typography, "
            "professional quality, clean layout",
            "canva_search": "modern ebook cover template premium",
            "color_palette": ["#1a1a2e", "#e94560", "#f5f5f5"],
            "typography": {"title_font": "Montserrat Bold", "body_font": "Inter", "style": "modern sans-serif"},
            "visual_elements": ["gradient background", "bold title", "author name"],
            "mood": "premium",
            "dimensions": "1800x2700px (300 DPI)" if platform == "amazon_kdp" else "1500x1500px",
        }

    return cover_data


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — PRODUCT DELIVERY STRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

def build_delivery_structure(strategy: dict, platform: str) -> dict:
    """
    Define exactly how the product will be delivered:
    files, folder structure, naming conventions.
    """
    title = strategy.get("title", "")
    product_type = strategy.get("product_type", "ebook")
    safe_title = re.sub(r"[^a-zA-Z0-9_]", "_", title[:30])

    structure = _claude_json(
        f"Define the product delivery structure for:\n"
        f"Product: {title}\n"
        f"Type: {product_type}\n"
        f"Platform: {platform}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "main_files": [\n'
        '    {"filename": "exact_filename.pdf", "description": "...", "format": "PDF|DOCX|XLSX|etc"}\n'
        "  ],\n"
        '  "bonus_files": [\n'
        '    {"filename": "bonus_filename.pdf", "description": "..."}\n'
        "  ],\n"
        '  "folder_structure": [\n'
        '    "FolderName/", "FolderName/file.pdf", "Bonuses/bonus1.pdf"\n'
        "  ],\n"
        '  "naming_convention": "brief explanation of naming pattern",\n'
        '  "delivery_notes": "what the buyer receives immediately vs later",\n'
        '  "file_count": 5,\n'
        '  "total_estimated_size": "2-5 MB",\n'
        '  "zip_filename": "exact_zip_name.zip"\n'
        "}\n"
        "Pure JSON. Be extremely specific with filenames.",
        max_tokens=800,
    )

    if not isinstance(structure, dict):
        structure = {
            "main_files": [
                {"filename": f"{safe_title}_Main_Guide.pdf", "description": "Main product content", "format": "PDF"},
            ],
            "bonus_files": [
                {"filename": f"{safe_title}_Checklist.pdf", "description": "Quick-start checklist", "format": "PDF"},
                {"filename": f"{safe_title}_Templates.pdf", "description": "Template pack", "format": "PDF"},
            ],
            "folder_structure": [
                f"{safe_title}/",
                f"{safe_title}/{safe_title}_Main_Guide.pdf",
                f"{safe_title}/Bonuses/",
                f"{safe_title}/Bonuses/{safe_title}_Checklist.pdf",
            ],
            "naming_convention": "ProductName_ComponentName_Version.format",
            "delivery_notes": "Instant download via platform delivery system",
            "file_count": 3,
            "total_estimated_size": "2-5 MB",
            "zip_filename": f"{safe_title}_Complete_Package.zip",
        }

    return structure


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — PRICING STRATEGY
# ══════════════════════════════════════════════════════════════════════════════

def build_pricing_strategy(strategy: dict, platform: str) -> dict:
    """
    Generate tiered pricing with upsells and subscription options.
    """
    title = strategy.get("title", "")
    price = strategy.get("price", 19.99)
    niche = strategy.get("niche", "")
    audience = strategy.get("target_audience", "")

    pricing = _claude_json(
        f"Create a pricing strategy for:\n"
        f"Product: {title}\n"
        f"Platform: {platform}\n"
        f"Niche: {niche}\n"
        f"Buyer: {audience}\n"
        f"Suggested base price: ${price}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "tiers": [\n'
        '    {"name": "Starter", "price": 7.00, "includes": ["...", "..."], "best_for": "..."},\n'
        '    {"name": "Complete", "price": 19.99, "includes": ["...", "..."], "best_for": "..."},\n'
        '    {"name": "Premium", "price": 47.00, "includes": ["...", "..."], "best_for": "..."}\n'
        "  ],\n"
        '  "recommended_tier": "Complete",\n'
        '  "subscription": {"monthly": 9.99, "annual": 79.99, "what_included": "..."},\n'
        '  "launch_price": 9.99,\n'
        '  "launch_duration_days": 7,\n'
        '  "upsells": [\n'
        '    {"name": "...", "price": 27.00, "pitch": "one sentence pitch"}\n'
        "  ],\n"
        '  "bundle_deal": {"name": "...", "original_value": 97.00, "bundle_price": 47.00},\n'
        '  "pricing_psychology": "brief note on why this pricing works for this audience"\n'
        "}\n"
        "Pure JSON. Make pricing realistic and competitive for this platform.",
        max_tokens=1000,
    )

    if not isinstance(pricing, dict):
        pricing = {
            "tiers": [
                {"name": "Starter", "price": 7.00, "includes": ["Main guide PDF"], "best_for": "Budget buyers"},
                {"name": "Complete", "price": price, "includes": ["Main guide", "All bonuses"], "best_for": "Most buyers"},
                {"name": "Premium", "price": price * 3, "includes": ["Everything + 1:1 Q&A"], "best_for": "Serious buyers"},
            ],
            "recommended_tier": "Complete",
            "subscription": {"monthly": 9.99, "annual": 79.99, "what_included": "Monthly new content"},
            "launch_price": round(price * 0.5, 2),
            "launch_duration_days": 7,
            "upsells": [
                {"name": "Done-For-You Templates", "price": 27.00, "pitch": "Skip the setup — use mine directly"},
            ],
            "bundle_deal": {"name": "Complete Bundle", "original_value": price * 5, "bundle_price": price * 2.5},
            "pricing_psychology": "Price anchoring with the Premium tier makes the Complete tier feel like a steal",
        }

    return pricing


# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — LEGAL DISCLAIMER
# ══════════════════════════════════════════════════════════════════════════════

def build_legal_disclaimer(strategy: dict) -> str:
    """
    Generate a niche-appropriate professional legal disclaimer.
    Handles: Trading/Finance, AI/Tech, General digital products.
    """
    niche = strategy.get("niche", "")
    title = strategy.get("title", "")

    niche_lower = niche.lower()
    if "trading" in niche_lower or "finance" in niche_lower:
        disclaimer_type = "financial_trading"
    elif "ai" in niche_lower or "tech" in niche_lower:
        disclaimer_type = "ai_tech"
    else:
        disclaimer_type = "general_income"

    disclaimer = _claude(
        f"Write a professional legal disclaimer for:\n"
        f"Product: {title}\n"
        f"Niche: {niche}\n"
        f"Disclaimer type needed: {disclaimer_type}\n\n"
        "Requirements:\n"
        f"{'- Include CFTC/SEC-style trading disclaimer' if disclaimer_type == 'financial_trading' else ''}\n"
        f"{'- No financial advice, past performance disclaimer' if disclaimer_type == 'financial_trading' else ''}\n"
        f"{'- No guarantees of results from AI tools' if disclaimer_type == 'ai_tech' else ''}\n"
        "- Earnings disclaimer (results not typical)\n"
        "- No guarantee of income or results\n"
        "- Affiliate/FTC disclosure if applicable\n"
        "- Professional advice recommendation\n"
        "- Copyright notice (WheellsVerse)\n\n"
        "Format: Professional block of text, suitable for product footer or dedicated disclaimer page.\n"
        "Length: 200-400 words.\n"
        "Tone: Professional, clear, legally defensive without being intimidating.\n\n"
        "Write the complete disclaimer now.",
        max_tokens=800,
    )

    return disclaimer


# ══════════════════════════════════════════════════════════════════════════════
# STEP 9 — MARKETING ASSETS
# ══════════════════════════════════════════════════════════════════════════════

def build_marketing_assets(strategy: dict, platform: str) -> dict:
    """
    Generate ready-to-use marketing assets:
    - Short product description
    - 3 Twitter/X posts
    - 2 TikTok content ideas
    - 1 email promo
    """
    title = strategy.get("title", "")
    audience = strategy.get("target_audience", "")
    problem = strategy.get("problem", "")
    after = strategy.get("transformation", {}).get("after", "")
    price = strategy.get("price", 19.99)
    niche = strategy.get("niche", "")

    assets_raw = _claude(
        f"Create marketing assets for this digital product:\n\n"
        f"Product: {title}\n"
        f"Platform: {platform}\n"
        f"Audience: {audience}\n"
        f"Problem: {problem}\n"
        f"Transformation: {after}\n"
        f"Price: ${price}\n"
        f"Niche: {niche}\n\n"
        "Write ALL of the following:\n\n"
        "---\n"
        "## SHORT DESCRIPTION (150 words max)\n"
        "(Platform listing short description — hook + what's inside + CTA)\n\n"
        "## TWITTER POST 1\n"
        "(Value-led thread opener about the problem — no direct sell, ends with soft CTA)\n\n"
        "## TWITTER POST 2\n"
        "(Transformation post — before/after format — link to product)\n\n"
        "## TWITTER POST 3\n"
        "(Social proof / results style post — specific numbers, realistic)\n\n"
        "## TIKTOK IDEA 1\n"
        "(Hook: first 3 seconds | Script: 30-60 seconds | CTA | Hashtags)\n\n"
        "## TIKTOK IDEA 2\n"
        "(Different angle — educational, story-based, or trending format)\n\n"
        "## EMAIL PROMO\n"
        "(Subject line | Preview text | Full email body 200-300 words | PS line)\n"
        "---\n\n"
        "Make each asset feel native to its platform. No generic copy.",
        max_tokens=3000,
    )

    return {
        "short_description": _extract_section(assets_raw, "SHORT DESCRIPTION", "TWITTER POST 1"),
        "twitter_posts": [
            _extract_section(assets_raw, "TWITTER POST 1", "TWITTER POST 2"),
            _extract_section(assets_raw, "TWITTER POST 2", "TWITTER POST 3"),
            _extract_section(assets_raw, "TWITTER POST 3", "TIKTOK IDEA"),
        ],
        "tiktok_ideas": [
            _extract_section(assets_raw, "TIKTOK IDEA 1", "TIKTOK IDEA 2"),
            _extract_section(assets_raw, "TIKTOK IDEA 2", "EMAIL PROMO"),
        ],
        "email_promo": _extract_section(assets_raw, "EMAIL PROMO", None),
        "raw": assets_raw,
    }


# ══════════════════════════════════════════════════════════════════════════════
# GUMROAD ENGINE — 11-STEP VIRAL PRODUCT MODELING PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

_GUMROAD_SYSTEM = (
    "You are NarAI — a world-class digital product strategist who has studied "
    "every top-selling product on Gumroad. You understand exactly what makes a "
    "product go viral: specific pain, instant usability, clear ROI, and a value "
    "stack that feels 10x the price. You never create generic products. Every "
    "product you build looks, feels, and converts like a top Gumroad listing. "
    "You write with authority, clarity, and zero fluff. Everything you produce "
    "can be uploaded and sold without editing."
)


def _gumroad_system() -> str:
    return _GUMROAD_SYSTEM


# ── Step 0: Viral Product Modeling ────────────────────────────────────────────

def gumroad_viral_model(market_intel: dict) -> dict:
    """
    Step 0 — CRITICAL: Analyze top Gumroad patterns and select the best
    product format + niche before creating anything.

    Returns the viral model dict that drives all downstream steps.
    """
    niche_list = "\n".join(f"  • {n}" for n in GUMROAD_NICHES)
    format_list = "\n".join(
        f"  • {k}: {v['label']} — {v['why_it_sells']}"
        for k, v in GUMROAD_FORMATS.items()
    )

    model = _claude_json(
        f"You are modeling a TOP-SELLING Gumroad product.\n\n"
        f"Market intelligence available:\n{json.dumps(market_intel, indent=2)[:3000]}\n\n"
        "VALIDATED GUMROAD NICHES (choose one):\n"
        f"{niche_list}\n\n"
        "PROVEN GUMROAD FORMATS (choose one):\n"
        f"{format_list}\n\n"
        "Rules for selection:\n"
        "- Reject weak, oversaturated, or theory-only ideas\n"
        "- Must solve ONE specific problem with a clear, fast result\n"
        "- Must feel practical, not academic\n"
        "- Must have clear ROI: make money, save time, or improve a skill\n"
        "- Must be packageable as a system or bundle, not just content\n\n"
        "Return JSON:\n"
        "{\n"
        '  "selected_niche": "...",\n'
        '  "selected_format": "template_system|mini_course|playbook_toolkit|live_training|creator_bundle",\n'
        '  "format_label": "...",\n'
        '  "market_gap": "what top sellers are missing that this fills",\n'
        '  "buyer_urgency": "why someone buys this TODAY, not tomorrow",\n'
        '  "instant_value": "what the buyer can DO within 10 minutes of buying",\n'
        '  "viral_hook": "one sentence that makes someone say I need this now",\n'
        '  "competitor_weakness": "what existing products do wrong",\n'
        '  "price_ceiling": 49.00,\n'
        '  "modeling_notes": "2-3 sentences on the top Gumroad pattern being replicated"\n'
        "}\n"
        "Pure JSON. No markdown.",
        system=_gumroad_system(),
        max_tokens=1000,
    )

    if not isinstance(model, dict) or not model.get("selected_niche"):
        model = {
            "selected_niche": "AI / Automation",
            "selected_format": "template_system",
            "format_label": "Template System",
            "market_gap": "Most AI tool guides are vague — buyers want copy-paste systems",
            "buyer_urgency": "Everyone is trying to use AI to make money right now",
            "instant_value": "Open the Notion template and run your first AI workflow in 10 minutes",
            "viral_hook": "The exact AI workflow system making creators $5K/month — copy it in one click",
            "competitor_weakness": "Too theoretical, no templates, no real examples",
            "price_ceiling": 37.00,
            "modeling_notes": (
                "Replicating the structure of top Gumroad AI tool bundles: "
                "Notion workspace + PDF guide + prompt pack. High perceived value, "
                "instant usability, proven $10K+ sellers in this format."
            ),
        }

    log.info(f"[GumroadEngine] Viral model: {model.get('selected_format')} in {model.get('selected_niche')}")
    return model


# ── Step 1: Viral Product Concept ─────────────────────────────────────────────

def gumroad_product_concept(viral_model: dict) -> dict:
    """
    Step 1 — Define the specific product concept based on the viral model.
    Must feel like 'I need this NOW'.
    """
    fmt_key = viral_model.get("selected_format", "template_system")
    fmt_info = GUMROAD_FORMATS.get(fmt_key, GUMROAD_FORMATS["template_system"])

    concept = _claude_json(
        f"Create a viral Gumroad product concept.\n\n"
        f"Viral model selected:\n{json.dumps(viral_model, indent=2)}\n\n"
        f"Format: {fmt_info['label']}\n"
        f"Delivery components: {', '.join(fmt_info['delivery'])}\n"
        f"Why this format sells: {fmt_info['why_it_sells']}\n\n"
        "Create a product that makes someone say 'I need this now'.\n\n"
        "Return JSON:\n"
        "{\n"
        '  "product_name": "Premium name — outcome-focused, no fluff",\n'
        '  "tagline": "One sentence. Clear transformation.",\n'
        '  "target_audience": "Very specific. Not \'entrepreneurs\'. E.g. \'Freelance designers billing under $3K/month\'",\n'
        '  "problem": "The exact pain — specific, emotional, real",\n'
        '  "outcome": "The clear after-state they reach by using this",\n'
        '  "delivery_type": "exact format key from the list",\n'
        '  "value_stack": [\n'
        '    {"item": "Main product name", "type": "core", "value": "$X value"},\n'
        '    {"item": "Bonus 1 name", "type": "bonus", "value": "$X value"}\n'
        "  ],\n"
        '  "total_value": "$XXX total value",\n'
        '  "price": 27.00,\n'
        '  "why_buy_now": "urgency reason",\n'
        '  "keywords": ["tag1", "tag2", "tag3", "tag4", "tag5"]\n'
        "}\n"
        "Pure JSON. Product name must sound premium and specific.",
        system=_gumroad_system(),
        max_tokens=1200,
    )

    if not isinstance(concept, dict) or not concept.get("product_name"):
        concept = {
            "product_name": "The AI Income System: Notion Workspace + Automation Playbook",
            "tagline": "The exact system creators use to earn $3K–$10K/month with AI tools — copy it in minutes.",
            "target_audience": "Content creators and freelancers who want to monetize AI but don't know where to start",
            "problem": "You're using AI but still trading time for money — no system, no scale",
            "outcome": "A fully operational AI-powered income system running within 24 hours",
            "delivery_type": "template_system",
            "value_stack": [
                {"item": "AI Income Notion Workspace", "type": "core", "value": "$97 value"},
                {"item": "Automation Playbook PDF", "type": "bonus", "value": "$47 value"},
                {"item": "50 Monetization Prompts", "type": "bonus", "value": "$27 value"},
            ],
            "total_value": "$171 total value",
            "price": 27.00,
            "why_buy_now": "Price increases after 50 sales",
            "keywords": ["AI tools", "automation", "passive income", "Notion template", "make money online"],
        }

    log.info(f"[GumroadEngine] Concept: '{concept.get('product_name')}' @ ${concept.get('price')}")
    return concept


# ── Step 2: Core Product + Value Stack Content ────────────────────────────────

def gumroad_build_product_content(concept: dict, viral_model: dict) -> dict:
    """
    Step 2 — Build the actual product content.
    Returns {pdf_content, notion_structure, value_stack_content}.
    """
    product_name = concept.get("product_name", "")
    audience = concept.get("target_audience", "")
    problem = concept.get("problem", "")
    outcome = concept.get("outcome", "")
    fmt_key = concept.get("delivery_type", "template_system")
    fmt_info = GUMROAD_FORMATS.get(fmt_key, GUMROAD_FORMATS["template_system"])
    value_stack = concept.get("value_stack", [])

    # ── PDF / Core Content ────────────────────────────────────────────────────
    pdf_content = _claude(
        f"Create the CORE PRODUCT CONTENT for: '{product_name}'\n\n"
        f"Format: {fmt_info['label']}\n"
        f"Target: {audience}\n"
        f"Problem: {problem}\n"
        f"Outcome: {outcome}\n"
        f"Value stack: {json.dumps(value_stack, indent=2)}\n\n"
        "Write the COMPLETE PDF content with:\n\n"
        "# TABLE OF CONTENTS\n"
        "(All modules/sections listed)\n\n"
        "# INTRODUCTION\n"
        "(Who this is for, what they'll achieve, how to use this product)\n\n"
        "# MODULE 1: [Name]\n"
        "(Complete content — frameworks, steps, examples, real scenarios)\n\n"
        "# MODULE 2: [Name]\n\n"
        "# MODULE 3: [Name]\n\n"
        "# MODULE 4: [Name]\n\n"
        "# QUICK-WIN ACTION PLAN\n"
        "(What to do in the first 30 minutes to get a result)\n\n"
        "# RESOURCES & TOOLS\n"
        "(Top 10 tools/resources with one-line descriptions)\n\n"
        "Rules:\n"
        "- Every module must be actionable, not theoretical\n"
        "- Include real examples, scripts, or frameworks\n"
        "- Write like you're handing someone a system, not a book\n"
        "- Minimum 1500 words total",
        system=_gumroad_system(),
        max_tokens=4000,
    )
    time.sleep(THINK_PAUSE)

    # ── Notion Structure ──────────────────────────────────────────────────────
    notion_structure = _claude_json(
        f"Design a complete Notion workspace structure for: '{product_name}'\n\n"
        f"The buyer will duplicate this Notion template immediately after purchase.\n"
        f"Format: {fmt_info['label']}\n"
        f"Outcome for buyer: {outcome}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "workspace_name": "...",\n'
        '  "pages": [\n'
        '    {\n'
        '      "title": "Page name",\n'
        '      "icon": "emoji",\n'
        '      "type": "page|database|callout",\n'
        '      "content_description": "What goes here and why",\n'
        '      "sub_pages": ["Sub-page 1", "Sub-page 2"]\n'
        '    }\n'
        "  ],\n"
        '  "databases": [\n'
        '    {\n'
        '      "name": "Database name",\n'
        '      "purpose": "What it tracks",\n'
        '      "properties": ["Property 1 (type)", "Property 2 (type)"]\n'
        '    }\n'
        "  ],\n"
        '  "setup_steps": ["Step 1: ...", "Step 2: ..."],\n'
        '  "first_win": "What the buyer achieves in their first 10 minutes"\n'
        "}\n"
        "Pure JSON. Make this a workspace buyers will actually use every day.",
        system=_gumroad_system(),
        max_tokens=1500,
    )
    time.sleep(THINK_PAUSE)

    # ── Value Stack Bonus Content ─────────────────────────────────────────────
    bonus_items = [v for v in value_stack if v.get("type") == "bonus"]
    bonus_content = _claude(
        f"Create the BONUS CONTENT for '{product_name}'.\n\n"
        f"Bonuses to build:\n{json.dumps(bonus_items, indent=2)}\n\n"
        "For each bonus write:\n"
        "## [BONUS NAME]\n"
        "(Complete, fully usable content — not an outline)\n"
        "- If it's a checklist: write all items\n"
        "- If it's a prompt pack: write all prompts with examples\n"
        "- If it's a framework: write the full framework with instructions\n"
        "- If it's a swipe file: write all copy/scripts\n\n"
        "Each bonus must feel worth MORE than the product price alone.",
        system=_gumroad_system(),
        max_tokens=3000,
    )

    return {
        "pdf_content": pdf_content,
        "notion_structure": notion_structure if isinstance(notion_structure, dict) else {},
        "bonus_content": bonus_content,
    }


# ── Step 3: Gumroad Sales Page ────────────────────────────────────────────────

def gumroad_sales_page(concept: dict, viral_model: dict) -> str:
    """
    Step 3 — Write a Gumroad-optimized high-conversion sales page.
    Tone: Clear, practical, no hype, easy to scan.
    """
    product_name = concept.get("product_name", "")
    tagline = concept.get("tagline", "")
    audience = concept.get("target_audience", "")
    problem = concept.get("problem", "")
    outcome = concept.get("outcome", "")
    value_stack = concept.get("value_stack", [])
    price = concept.get("price", 27.00)
    total_value = concept.get("total_value", "")
    why_buy_now = concept.get("why_buy_now", "")
    viral_hook = viral_model.get("viral_hook", "")
    instant_value = viral_model.get("instant_value", "")

    stack_text = "\n".join(
        f"• {v['item']} ({v.get('value', '')})" for v in value_stack
    )

    page = _claude(
        f"Write a complete Gumroad sales page for:\n\n"
        f"Product: {product_name}\n"
        f"Tagline: {tagline}\n"
        f"Target: {audience}\n"
        f"Problem: {problem}\n"
        f"Outcome: {outcome}\n"
        f"Viral hook: {viral_hook}\n"
        f"What they get instantly: {instant_value}\n"
        f"Price: ${price}\n"
        f"Total value: {total_value}\n"
        f"Value stack:\n{stack_text}\n"
        f"Urgency: {why_buy_now}\n\n"
        "Write exactly these sections in order:\n\n"
        "---\n"
        "**[HOOK]**\n"
        "(1-2 lines. Stops the scroll. No hype — just truth that hits hard.)\n\n"
        "**[PROBLEM]**\n"
        "(2-3 short paragraphs. Get inside their head. Make them feel seen.)\n\n"
        "**[SOLUTION]**\n"
        "(Introduce the product as the exact thing they've been missing.)\n\n"
        "**[WHAT'S INSIDE]**\n"
        "(Bullet-by-bullet breakdown of every item in the value stack.\n"
        " Be specific. 'You'll get X so you can Y' format.)\n\n"
        "**[REAL OUTCOMES]**\n"
        "(5 specific, measurable results — not features, not benefits, OUTCOMES.)\n\n"
        "**[USE-CASE EXAMPLES]**\n"
        "(3 realistic mini-scenarios: 'If you're a [person] who [situation], "
        "here's exactly what you'll do with this...')\n\n"
        "**[PRICING]**\n"
        f"(Why ${price} is obvious. Compare to alternatives. Show the value gap.)\n\n"
        "**[GET IT NOW]**\n"
        "(Strong CTA. What happens immediately after purchase. Risk reversal.)\n"
        "---\n\n"
        "Tone rules:\n"
        "- Conversational but confident\n"
        "- Short paragraphs (2-3 sentences max)\n"
        "- No exclamation marks unless absolutely earned\n"
        "- No hype words: 'amazing', 'incredible', 'game-changer'\n"
        "- Scan-friendly: headers, bullets, white space\n"
        "- Read like a real Gumroad page, not a landing page template",
        system=_gumroad_system(),
        max_tokens=3000,
    )
    return page


# ── Step 4: Cover Design Prompt (Gumroad) ────────────────────────────────────

def gumroad_cover_prompt(concept: dict, viral_model: dict) -> dict:
    """
    Step 4 — Generate AI image prompts optimized for Gumroad covers.
    Gumroad covers: 1280×720px (landscape) or square 1:1.
    """
    product_name = concept.get("product_name", "")
    niche = viral_model.get("selected_niche", "")
    fmt_key = concept.get("delivery_type", "template_system")

    niche_style_map = {
        "Trading / Finance": "dark navy + gold, financial data aesthetic, premium minimal, Bloomberg terminal vibes",
        "AI / Automation": "electric blue + white, circuit/neural network patterns, clean futuristic, tech premium",
        "Online income / business systems": "bold gradient (orange to deep purple), clean sans-serif, wealth creation energy",
        "Content creation systems": "warm neutrals + coral accent, creator aesthetic, modern editorial, Canva-inspired",
        "Tech / programming tools": "dark mode, neon green accent, code elements, VSCode aesthetic, hacker premium",
        "Design / assets": "ultra-clean white, soft shadows, design-tool aesthetic, Figma-inspired premium",
    }
    style = niche_style_map.get(niche, "modern, clean, premium, dark background, bold typography")

    cover = _claude_json(
        f"Generate AI cover image prompts for this Gumroad product:\n\n"
        f"Product: {product_name}\n"
        f"Niche: {niche}\n"
        f"Format: {fmt_key}\n"
        f"Style direction: {style}\n\n"
        "Gumroad cover specs: 1280×720px (16:9) OR 1000×1000px (square)\n"
        "Must convey: premium quality, instant value, credibility\n"
        "Must NOT have: cheap stock photo feel, generic clipart, pixelated text\n\n"
        "Return JSON:\n"
        "{\n"
        '  "dalle": "Full DALL·E 3 prompt — very specific, 100+ words",\n'
        '  "midjourney": "Full Midjourney prompt with --ar 16:9 --v 6 --style raw",\n'
        '  "leonardo": "Leonardo AI prompt with model recommendation",\n'
        '  "canva_search": "exact Canva template search terms",\n'
        '  "color_palette": ["#hex1", "#hex2", "#hex3"],\n'
        '  "typography": {"title_font": "...", "accent_font": "...", "style_note": "..."},\n'
        '  "layout": "describe the cover layout — where text goes, visual hierarchy",\n'
        '  "mood": "premium|minimal|bold|dark|clean",\n'
        '  "dimensions": "1280x720px (16:9) landscape"\n'
        "}\n"
        "Pure JSON. Make the DALL·E prompt extremely detailed and specific.",
        system=_gumroad_system(),
        max_tokens=1000,
    )

    if not isinstance(cover, dict):
        cover = {
            "dalle": (
                f"Premium digital product cover for '{product_name}'. {style} aesthetic. "
                "Clean layout with bold title typography on left, abstract visual on right. "
                "Dark background, professional design, no people, no stock photos. "
                "Looks like a top Gumroad product. High-end, credible, minimal."
            ),
            "midjourney": (
                f"Premium Gumroad product cover, '{product_name}', {style}, "
                "bold typography, dark premium background, digital product mockup "
                "--ar 16:9 --v 6 --style raw"
            ),
            "leonardo": f"Premium digital product cover, {style}, clean minimal design, professional",
            "canva_search": "digital product cover template dark premium",
            "color_palette": ["#0d0d1a", "#f0a500", "#ffffff"],
            "typography": {"title_font": "Inter Bold", "accent_font": "Inter Light", "style_note": "Large title, small tagline below"},
            "layout": "Title left-aligned, large. Accent color bar on left edge. Abstract visual right side.",
            "mood": "premium",
            "dimensions": "1280x720px (16:9) landscape",
        }

    return cover


# ── Step 5: Gumroad Upload Data ───────────────────────────────────────────────

def gumroad_upload_data(concept: dict, sales_page: str, cover_result: dict) -> dict:
    """
    Step 5 — Build the exact data structure for Gumroad API upload.
    price is in CENTS (Gumroad API requirement).
    """
    product_name = concept.get("product_name", "")
    price_usd = float(concept.get("price", 27.00))
    keywords = concept.get("keywords", [])
    tagline = concept.get("tagline", "")
    value_stack = concept.get("value_stack", [])
    why_buy_now = concept.get("why_buy_now", "")

    # Short description (first 500 chars of sales page, clean)
    short_desc = re.sub(r"\*+", "", sales_page[:500]).strip()

    # File list from value stack
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", product_name[:35])
    files = []
    for item in value_stack:
        item_name = re.sub(r"[^a-zA-Z0-9_]", "_", item["item"][:30])
        if "Notion" in item["item"]:
            files.append(f"{safe_name}_Notion_Template_Link.pdf")
        elif "Prompt" in item["item"] or "prompt" in item["item"]:
            files.append(f"{safe_name}_Prompt_Pack.pdf")
        elif "Checklist" in item["item"]:
            files.append(f"{safe_name}_Checklist.pdf")
        else:
            files.append(f"{safe_name}_{item_name}.pdf")
    if not files:
        files = [f"{safe_name}_Main_Guide.pdf", f"{safe_name}_Bonuses.pdf"]

    return {
        "title": product_name,
        "description": sales_page,          # full sales page → Gumroad description
        "short_pitch": short_desc,
        "price": int(price_usd * 100),  # cents — Gumroad API format
        "price_usd": price_usd,
        "published": True,
        "tags": keywords[:10],        # Gumroad supports up to 10 tags
        "tagline": tagline,
        "file_list": files,
        "cover_local": cover_result.get("local_path", ""),
        "cover_url": cover_result.get("url", ""),
        "currency": "usd",
        "custom_summary": why_buy_now,
        "suggested_price": int(price_usd * 1.5 * 100),  # "pay what you want" floor
    }


# ── Step 6: Gumroad Pricing Strategy ─────────────────────────────────────────

def gumroad_pricing(concept: dict) -> dict:
    """
    Step 6 — Gumroad-specific pricing: entry / premium / bundle.
    """
    base_price = float(concept.get("price", 27.00))
    product_name = concept.get("product_name", "")
    total_value = concept.get("total_value", "")

    pricing = _claude_json(
        f"Create a Gumroad pricing strategy for: '{product_name}'\n"
        f"Base price: ${base_price}\n"
        f"Total stated value: {total_value}\n\n"
        "Return JSON:\n"
        "{\n"
        '  "entry": {"price": 7.00, "name": "Starter", "includes": "core product only", "note": "for price-sensitive buyers"},\n'
        '  "main": {"price": 27.00, "name": "Complete", "includes": "everything in the value stack", "note": "recommended"},\n'
        '  "premium": {"price": 67.00, "name": "Premium", "includes": "everything + 1 extra bonus or Q&A access", "note": "for serious buyers"},\n'
        '  "launch_price": 17.00,\n'
        '  "launch_end": "48 hours after publish",\n'
        '  "pay_what_you_want": false,\n'
        '  "pwyw_minimum": null,\n'
        '  "upsell": {"name": "Done-For-You Setup", "price": 97.00, "pitch": "one sentence"},\n'
        '  "bundle": {"name": "Ultimate Bundle", "price": 47.00, "includes": "3 products", "savings": "$XX"},\n'
        '  "why_this_price": "one sentence psychological justification"\n'
        "}\n"
        "Pure JSON. Prices must be Gumroad-realistic (not fake high).",
        system=_gumroad_system(),
        max_tokens=800,
    )

    if not isinstance(pricing, dict):
        pricing = {
            "entry": {"price": 7.00, "name": "Starter", "includes": "Core guide only", "note": "budget buyers"},
            "main": {"price": base_price, "name": "Complete", "includes": "Full value stack", "note": "recommended"},
            "premium": {"price": base_price * 2.5, "name": "Premium", "includes": "Everything + bonus coaching", "note": "serious buyers"},
            "launch_price": round(base_price * 0.6, 2),
            "launch_end": "48 hours after publish",
            "pay_what_you_want": False,
            "pwyw_minimum": None,
            "upsell": {"name": "1:1 Implementation Call", "price": 97.00, "pitch": "Skip the learning curve — I'll set it up with you live"},
            "bundle": {"name": "Creator Mega Bundle", "price": base_price * 1.8, "includes": "3 products", "savings": f"${base_price * 1.2:.0f}"},
            "why_this_price": f"${base_price} is less than one hour of consulting for a complete system",
        }

    return pricing


# ── Step 7: Gumroad Marketing Pack ───────────────────────────────────────────

def gumroad_marketing(concept: dict, viral_model: dict) -> dict:
    """
    Step 7 — Generate the full marketing pack for the Gumroad launch.
    """
    product_name = concept.get("product_name", "")
    tagline = concept.get("tagline", "")
    audience = concept.get("target_audience", "")
    problem = concept.get("problem", "")
    outcome = concept.get("outcome", "")
    price = concept.get("price", 27.00)
    viral_hook = viral_model.get("viral_hook", "")
    instant_value = viral_model.get("instant_value", "")
    niche = viral_model.get("selected_niche", "")

    assets = _claude(
        f"Create a launch marketing pack for this Gumroad product:\n\n"
        f"Product: {product_name}\n"
        f"Tagline: {tagline}\n"
        f"Niche: {niche}\n"
        f"Audience: {audience}\n"
        f"Problem: {problem}\n"
        f"Outcome: {outcome}\n"
        f"Price: ${price}\n"
        f"Viral hook: {viral_hook}\n"
        f"Instant value: {instant_value}\n\n"
        "Create ALL of the following — no placeholders, fully written:\n\n"
        "---\n"
        "## SHORT DESCRIPTION\n"
        "(150 words max. Hook + what's inside + CTA. Goes in Gumroad's short pitch field.)\n\n"
        "## X POST 1\n"
        "(Value post — teach something, no direct sell. Ends with soft CTA. Under 280 chars.)\n\n"
        "## X POST 2\n"
        "(Before/after transformation post. Specific numbers. Link to Gumroad.)\n\n"
        "## X POST 3\n"
        "(Social proof / results post. Realistic but compelling. Under 280 chars.)\n\n"
        "## TIKTOK IDEA 1\n"
        "Hook (first 3s): ...\n"
        "Script (30-60s): ...\n"
        "CTA: ...\n"
        "Hashtags: ...\n\n"
        "## TIKTOK IDEA 2\n"
        "(Different angle — e.g. screen-record walkthrough, day-in-my-life, problem expose)\n\n"
        "## EMAIL\n"
        "Subject: ...\n"
        "Preview: ...\n"
        "Body: (200-300 words, conversational, story-led)\n"
        "PS: ...\n"
        "---\n\n"
        "Every asset must feel native to its platform. No template-speak.",
        system=_gumroad_system(),
        max_tokens=3000,
    )

    return {
        "short_description": _extract_section(assets, "SHORT DESCRIPTION", "X POST 1"),
        "x_posts": [
            _extract_section(assets, "X POST 1", "X POST 2"),
            _extract_section(assets, "X POST 2", "X POST 3"),
            _extract_section(assets, "X POST 3", "TIKTOK IDEA"),
        ],
        "tiktok_ideas": [
            _extract_section(assets, "TIKTOK IDEA 1", "TIKTOK IDEA 2"),
            _extract_section(assets, "TIKTOK IDEA 2", "EMAIL"),
        ],
        "email": _extract_section(assets, "EMAIL", None),
        "raw": assets,
    }


# ── Master Gumroad Builder ────────────────────────────────────────────────────

def build_gumroad_product_package(
    market_intel: dict,
    log_fn=None,
) -> dict:
    """
    Run the full 11-step Gumroad viral product pipeline.

    Steps:
      0  Viral product modeling (analyze & replicate top Gumroad patterns)
      1  Viral product concept (niche + format + value stack)
      2  Core product content (PDF + Notion + bonuses)
      3  Gumroad sales page (high-conversion, platform-native)
      4  Cover design prompts (DALL·E / Midjourney / Leonardo)
      5  Cover auto-generation (DALL·E → Leonardo fallback)
      6  Gumroad upload data (title, description, price_cents, tags)
      7  Pricing strategy (entry / main / premium / launch)
      8  Legal disclaimer
      9  Marketing pack (description, X posts, TikTok, email)
     10  Full structured JSON output (ready to upload)
     11  Save package to disk

    Returns:
        Complete Gumroad product package dict.
    """
    def _log(msg: str, phase: str = "gumroad"):
        log.info(f"[GumroadEngine] {msg}")
        if log_fn:
            log_fn(msg, phase)

    _log("🏭 Gumroad 11-step viral product pipeline starting…", "gumroad")

    # ── Step 0: Viral Modeling ────────────────────────────────────────────────
    _log("Step 0/11: Viral product modeling — analyzing top Gumroad patterns…", "gumroad")
    viral_model = gumroad_viral_model(market_intel)
    _log(
        f"  → Format: {viral_model.get('format_label')} | "
        f"Niche: {viral_model.get('selected_niche')}",
        "gumroad",
    )
    time.sleep(THINK_PAUSE)

    # ── Step 1: Product Concept ───────────────────────────────────────────────
    _log("Step 1/11: Building viral product concept…", "gumroad")
    concept = gumroad_product_concept(viral_model)
    title = concept.get("product_name", "Untitled")
    _log(f"  → '{title}' @ ${concept.get('price')}", "gumroad")
    time.sleep(THINK_PAUSE)

    # ── Step 2: Product Content ───────────────────────────────────────────────
    _log("Step 2/11: Building core product + value stack content…", "gumroad")
    content = gumroad_build_product_content(concept, viral_model)
    time.sleep(THINK_PAUSE)

    # ── Step 3: Sales Page ────────────────────────────────────────────────────
    _log("Step 3/11: Writing Gumroad sales page…", "gumroad")
    sales_page = gumroad_sales_page(concept, viral_model)
    time.sleep(THINK_PAUSE)

    # ── Step 4: Cover Prompts ─────────────────────────────────────────────────
    _log("Step 4/11: Generating cover design prompts…", "gumroad")
    cover_prompts = gumroad_cover_prompt(concept, viral_model)
    time.sleep(1)

    # ── Step 5: Cover Auto-Generation ────────────────────────────────────────
    _log("Step 5/11: Auto-generating cover image…", "gumroad")
    cover_result = _generate_cover_image(
        cover_prompts=cover_prompts,
        platform="gumroad",
        title=title,
        strategy={"product_type": concept.get("delivery_type", "template_system")},
        log_fn=_log,
    )
    time.sleep(1)

    # ── Step 6: Gumroad Upload Data ───────────────────────────────────────────
    _log("Step 6/11: Preparing Gumroad upload data…", "gumroad")
    upload_data = gumroad_upload_data(concept, sales_page, cover_result)
    time.sleep(1)

    # ── Step 7: Pricing ───────────────────────────────────────────────────────
    _log("Step 7/11: Building pricing strategy…", "gumroad")
    pricing = gumroad_pricing(concept)
    time.sleep(1)

    # ── Step 8: Legal Disclaimer ──────────────────────────────────────────────
    _log("Step 8/11: Generating legal disclaimer…", "gumroad")
    strategy_for_disclaimer = {
        "niche": viral_model.get("selected_niche", ""),
        "title": title,
    }
    disclaimer = build_legal_disclaimer(strategy_for_disclaimer)
    time.sleep(1)

    # ── Step 9: Marketing Pack ────────────────────────────────────────────────
    _log("Step 9/11: Creating marketing pack…", "gumroad")
    marketing = gumroad_marketing(concept, viral_model)
    time.sleep(THINK_PAUSE)

    # ── Step 10: Assemble structured JSON output ──────────────────────────────
    _log("Step 10/11: Assembling full structured output…", "gumroad")
    package = {
        # Identity
        "platform": "gumroad",
        "created_at": _now(),
        "status": "complete",
        "title": title,
        "price": concept.get("price", 27.00),
        "product_type": concept.get("delivery_type", "template_system"),
        "niche": viral_model.get("selected_niche", ""),

        # Raw step outputs
        "viral_model": viral_model,
        "concept": concept,
        "strategy": concept,        # alias for compatibility with other systems
        "product_content": content.get("pdf_content", ""),
        "notion_structure": content.get("notion_structure", {}),
        "bonus_content": content.get("bonus_content", ""),
        "sales_page": sales_page,
        "cover_prompts": cover_prompts,
        "cover_image": cover_result,
        "gumroad_upload_data": upload_data,
        "pricing": pricing,
        "disclaimer": disclaimer,
        "marketing": marketing,

        # Convenience fields used by publish helpers
        "description": upload_data.get("short_pitch", ""),
        "listing_content": sales_page,
        "content": sales_page,

        # Structured JSON output (Step 11 format as requested)
        "structured_output": {
            "product_name": title,
            "niche": viral_model.get("selected_niche", ""),
            "target_audience": concept.get("target_audience", ""),
            "problem": concept.get("problem", ""),
            "solution": concept.get("outcome", ""),
            "product_structure": {
                "format": concept.get("delivery_type", ""),
                "value_stack": concept.get("value_stack", []),
                "total_value": concept.get("total_value", ""),
            },
            "sales_page": sales_page,
            "cover_prompt": cover_prompts.get("dalle", ""),
            "pdf_content": content.get("pdf_content", ""),
            "notion_structure": content.get("notion_structure", {}),
            "gumroad_upload_data": upload_data,
            "pricing": pricing,
            "marketing": {
                "short_description": marketing.get("short_description", ""),
                "x_posts": marketing.get("x_posts", []),
                "tiktok_ideas": marketing.get("tiktok_ideas", []),
                "email": marketing.get("email", ""),
            },
        },
    }

    # ── Step 11: Save to disk ─────────────────────────────────────────────────
    _log("Step 11/11: Saving package to disk…", "gumroad")
    try:
        pkg_path = save_product_package(package)
        package["package_path"] = str(pkg_path)
        _log(f"  💾 Saved: {pkg_path.name}", "gumroad")
    except Exception as e:
        _log(f"  ⚠️  Save error: {e}", "gumroad")

    _log(f"✅ Gumroad product complete: '{title}' @ ${concept.get('price')}", "gumroad")
    return package


# ══════════════════════════════════════════════════════════════════════════════
# COVER IMAGE AUTO-GENERATION (DALL·E 3 → Leonardo AI fallback)
# ══════════════════════════════════════════════════════════════════════════════

def _generate_cover_image(
    cover_prompts: dict,
    platform: str,
    title: str,
    strategy: dict,
    log_fn,
) -> dict:
    """
    Attempt to auto-generate the cover using the cover_engine.
    Falls back gracefully — always returns a result dict with the
    Midjourney prompt for manual use even if no API is available.
    """
    try:
        from core.cover_engine import generate_cover, get_available_engines
        engines = get_available_engines()

        if engines["any"]:
            log_fn(
                f"  🎨 Cover: DALL·E={'✅' if engines['dalle'] else '❌'}  "
                f"Leonardo={'✅' if engines['leonardo'] else '❌'} — generating…",
                platform,
            )
            result = generate_cover(
                cover_prompts=cover_prompts,
                platform=platform,
                title=title,
                product_type=strategy.get("product_type", "ebook"),
            )
            if result.get("success"):
                log_fn(
                    f"  🖼️  Cover generated via {result['source'].upper()}: "
                    f"{Path(result['local_path']).name}",
                    platform,
                )
            else:
                log_fn(
                    f"  ⚠️  Cover generation failed ({result.get('error', '')[:60]}) — "
                    f"Midjourney prompt saved for manual use.",
                    platform,
                )
            return result
        else:
            log_fn(
                "  ℹ️  No image API keys set (OPENAI_API_KEY / LEONARDO_API_KEY). "
                "Midjourney prompt saved in package for manual cover creation.",
                platform,
            )
            return {
                "success": False,
                "source": "manual",
                "local_path": "",
                "url": "",
                "midjourney_prompt": cover_prompts.get("midjourney", ""),
                "canva_search": cover_prompts.get("canva_search", ""),
                "error": "No image API key configured.",
            }

    except Exception as e:
        log_fn(f"  ⚠️  Cover engine error: {e}", platform)
        return {
            "success": False,
            "source": "error",
            "local_path": "",
            "url": "",
            "midjourney_prompt": cover_prompts.get("midjourney", ""),
            "error": str(e),
        }


# ══════════════════════════════════════════════════════════════════════════════
# MASTER BUILDER — assembles all 9 steps into one complete package
# ══════════════════════════════════════════════════════════════════════════════

def build_complete_product_package(
    platform: str,
    market_intel: dict,
    niche_hint: str = "",
    log_fn=None,
) -> dict:
    """
    Run all 9 steps and return a fully packaged digital product.

    Args:
        platform:     'gumroad' | 'etsy' | 'payhip' | 'amazon_kdp'
        market_intel: dict from market intelligence module
        niche_hint:   optional niche override
        log_fn:       optional logging callback (msg, phase)

    Returns:
        Complete product package dict with all 9 components.
    """
    def _log(msg: str, phase: str = "product_engine"):
        log.info(f"[ProductEngine] {msg}")
        if log_fn:
            log_fn(msg, phase)

    # ── Gumroad → dedicated 11-step viral engine ─────────────────────────────
    if platform == "gumroad":
        return build_gumroad_product_package(market_intel=market_intel, log_fn=log_fn)

    _log(f"🏭 Starting full product build for {platform.upper()}", platform)

    # ── Step 1: Strategy ──────────────────────────────────────────────────────
    _log("Step 1/9: Building product strategy…", platform)
    strategy = build_product_strategy(platform, market_intel, niche_hint)
    title = strategy.get("title", "Untitled Product")
    _log(f"  → Product: '{title}' ({strategy.get('product_type')}, ${strategy.get('price')})", platform)
    time.sleep(THINK_PAUSE)

    # ── Step 2: Sales Page ────────────────────────────────────────────────────
    _log("Step 2/9: Writing high-conversion sales page…", platform)
    sales_page = build_sales_page(strategy, platform)
    time.sleep(THINK_PAUSE)

    # ── Step 3: Product Content ───────────────────────────────────────────────
    _log("Step 3/9: Creating actual product content…", platform)
    product_content = build_product_content(strategy, platform)
    time.sleep(THINK_PAUSE)

    # ── Step 4: Bonus Materials ───────────────────────────────────────────────
    _log("Step 4/9: Building bonus materials…", platform)
    bonuses = build_bonus_materials(strategy)
    time.sleep(THINK_PAUSE)

    # ── Step 5: Cover Design Prompt + Auto-Generation ────────────────────────
    _log("Step 5/9: Generating cover design prompts…", platform)
    cover_prompts = build_cover_design_prompt(strategy, platform)

    # Try to auto-generate the actual cover image (DALL·E → Leonardo fallback)
    cover_result = _generate_cover_image(cover_prompts, platform, title, strategy, _log)
    time.sleep(1)

    # ── Step 6: Delivery Structure ────────────────────────────────────────────
    _log("Step 6/9: Defining delivery structure…", platform)
    delivery = build_delivery_structure(strategy, platform)
    time.sleep(1)

    # ── Step 7: Pricing Strategy ──────────────────────────────────────────────
    _log("Step 7/9: Building pricing strategy…", platform)
    pricing = build_pricing_strategy(strategy, platform)
    time.sleep(1)

    # ── Step 8: Legal Disclaimer ──────────────────────────────────────────────
    _log("Step 8/9: Generating legal disclaimer…", platform)
    disclaimer = build_legal_disclaimer(strategy)
    time.sleep(1)

    # ── Step 9: Marketing Assets ──────────────────────────────────────────────
    _log("Step 9/9: Creating marketing assets…", platform)
    marketing = build_marketing_assets(strategy, platform)
    time.sleep(THINK_PAUSE)

    # ── Assemble final package ────────────────────────────────────────────────
    package = {
        "platform": platform,
        "created_at": _now(),
        "status": "complete",

        # Step 1
        "strategy": strategy,
        "title": title,
        "price": strategy.get("price", 19.99),
        "product_type": strategy.get("product_type", "ebook"),
        "niche": strategy.get("niche", ""),

        # Step 2
        "sales_page": sales_page,

        # Step 3
        "product_content": product_content,

        # Step 4
        "bonuses": bonuses,

        # Step 5
        "cover_prompts": cover_prompts,
        "cover_image": cover_result,   # {success, source, local_path, url, midjourney_prompt}

        # Step 6
        "delivery": delivery,

        # Step 7
        "pricing": pricing,

        # Step 8
        "disclaimer": disclaimer,

        # Step 9
        "marketing": marketing,

        # Convenience flattening for publish helpers
        "description": marketing.get("short_description", sales_page[:500]),
        "listing_content": _build_listing_content(strategy, sales_page, pricing, disclaimer, platform),
    }

    _log(f"✅ Complete package built for '{title}' on {platform.upper()}", platform)
    return package


def _build_listing_content(
    strategy: dict,
    sales_page: str,
    pricing: dict,
    disclaimer: str,
    platform: str,
) -> str:
    """Assemble the final listing content to post to the platform."""
    title = strategy.get("title", "")
    subtitle = strategy.get("subtitle", "")
    keywords = strategy.get("keywords", [])

    tiers = pricing.get("tiers", [])
    tier_text = "\n".join(
        f"• {t['name']}: ${t['price']} — {', '.join(t.get('includes', []))}"
        for t in tiers
    )

    return (
        f"# {title}\n"
        f"{subtitle}\n\n"
        f"{sales_page}\n\n"
        f"---\n\n"
        f"## PRICING OPTIONS\n{tier_text}\n\n"
        f"---\n\n"
        f"## LEGAL DISCLAIMER\n{disclaimer}\n\n"
        f"---\n\n"
        f"Tags: {', '.join(keywords)}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SAVE PACKAGE TO DISK
# ══════════════════════════════════════════════════════════════════════════════

def save_product_package(package: dict) -> Path:
    """Save complete product package as JSON + human-readable markdown."""
    platform = package.get("platform", "unknown")
    title = package.get("title", "Untitled")
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", title[:40])
    ts = datetime.now().strftime("%Y%m%d_%H%M")

    platform_dir = PRODUCTS_DIR / platform
    platform_dir.mkdir(parents=True, exist_ok=True)

    # JSON package (full data)
    json_path = platform_dir / f"{safe_name}_{ts}.json"
    json_path.write_text(json.dumps(package, indent=2, default=str), encoding="utf-8")

    # Markdown export (human-readable, ready to edit/upload)
    md_path = platform_dir / f"{safe_name}_{ts}.md"
    md_content = _render_markdown_export(package)
    md_path.write_text(md_content, encoding="utf-8")

    log.info(f"[ProductEngine] Saved package: {json_path}")
    return json_path


def _render_markdown_export(package: dict) -> str:
    """Render a clean markdown export of the complete product package."""
    strategy = package.get("strategy", {})
    pricing = package.get("pricing", {})
    cover = package.get("cover_prompts", {})
    delivery = package.get("delivery", {})
    marketing = package.get("marketing", {})
    bonuses = package.get("bonuses", {})

    tiers = pricing.get("tiers", [])
    tier_md = "\n".join(
        f"| {t['name']} | ${t['price']} | {', '.join(t.get('includes', []))} |"
        for t in tiers
    )

    files_md = "\n".join(
        f"- `{f['filename']}` — {f['description']}"
        for f in delivery.get("main_files", []) + delivery.get("bonus_files", [])
    )

    twitter_posts = marketing.get("twitter_posts", [])
    tiktok_ideas = marketing.get("tiktok_ideas", [])

    return f"""# {package.get('title', 'Product')}
**Platform:** {package.get('platform', '').upper()}
**Type:** {package.get('product_type', '')}
**Price:** ${package.get('price', 0)}
**Created:** {package.get('created_at', '')}

---

## STEP 1: PRODUCT STRATEGY

**Niche:** {strategy.get('niche', '')}
**Target Audience:** {strategy.get('target_audience', '')}
**Problem Solved:** {strategy.get('problem', '')}
**Transformation:**
- Before: {strategy.get('transformation', {}).get('before', '')}
- After: {strategy.get('transformation', {}).get('after', '')}
**Unique Angle:** {strategy.get('unique_angle', '')}

---

## STEP 2: SALES PAGE

{package.get('sales_page', '')}

---

## STEP 3: PRODUCT CONTENT

{package.get('product_content', '')[:8000]}

*(Full content saved in JSON package)*

---

## STEP 4: BONUS MATERIALS

### Quick-Start Checklist
{bonuses.get('checklist', '')}

### Quick-Start Guide
{bonuses.get('quick_start', '')}

### Bonus Template / Script
{bonuses.get('template', '')}

---

## STEP 5: COVER DESIGN PROMPTS

**Midjourney:**
```
{cover.get('midjourney', '')}
```

**DALL·E:**
```
{cover.get('dalle', '')}
```

**Leonardo AI:**
```
{cover.get('leonardo', '')}
```

**Canva Search:** `{cover.get('canva_search', '')}`
**Colors:** {', '.join(cover.get('color_palette', []))}
**Typography:** {cover.get('typography', {}).get('title_font', '')} / {cover.get('typography', {}).get('body_font', '')}
**Dimensions:** {cover.get('dimensions', '')}

---

## STEP 6: DELIVERY STRUCTURE

**Files included:**
{files_md}

**Folder Structure:**
```
{chr(10).join(delivery.get('folder_structure', []))}
```

**ZIP filename:** `{delivery.get('zip_filename', '')}`
**Delivery notes:** {delivery.get('delivery_notes', '')}

---

## STEP 7: PRICING STRATEGY

| Tier | Price | Includes |
|------|-------|----------|
{tier_md}

**Recommended tier:** {pricing.get('recommended_tier', '')}
**Launch price:** ${pricing.get('launch_price', '')} (for {pricing.get('launch_duration_days', 7)} days)

**Upsells:**
{chr(10).join(f"- {u['name']}: ${u['price']} — {u['pitch']}" for u in pricing.get('upsells', []))}

**Bundle deal:** {pricing.get('bundle_deal', {}).get('name', '')} — ${pricing.get('bundle_deal', {}).get('bundle_price', '')} (saves ${round(pricing.get('bundle_deal', {}).get('original_value', 0) - pricing.get('bundle_deal', {}).get('bundle_price', 0), 2)})

---

## STEP 8: LEGAL DISCLAIMER

{package.get('disclaimer', '')}

---

## STEP 9: MARKETING ASSETS

### Short Description
{marketing.get('short_description', '')}

### Twitter/X Posts
**Post 1:**
{twitter_posts[0] if len(twitter_posts) > 0 else ''}

**Post 2:**
{twitter_posts[1] if len(twitter_posts) > 1 else ''}

**Post 3:**
{twitter_posts[2] if len(twitter_posts) > 2 else ''}

### TikTok Ideas
**Idea 1:**
{tiktok_ideas[0] if len(tiktok_ideas) > 0 else ''}

**Idea 2:**
{tiktok_ideas[1] if len(tiktok_ideas) > 1 else ''}

### Email Promo
{marketing.get('email_promo', '')}
"""
