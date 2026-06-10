"""Site preview generator — produces a custom HTML site for each prospect.

Stage 3 of the SiteBoost pipeline. Three sub-templates by category:
    - restaurant  (menu, hours, photos, reservation CTA)
    - service     (services list, before/after, get-quote CTA)
    - retail      (product grid, hours, directions CTA)

Personalization layer uses LLM (Claude or GPT) to write:
    - hero headline + sub
    - "about" paragraph
    - 3 service/menu/product cards (no real data needed — plausible defaults)

Output:
    data/launches/siteboost/runs/<date>-<location>/03-previews/<slug>.html

For "live" hosting: deploy these HTML files to Cloudflare Pages at
preview.wheellsverse.com/<slug>. Done by `wrangler pages publish` — see README.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "local_prospect" / "templates"
logger = logging.getLogger("site_generator")

# Category → template mapping. Anything not listed falls back to "service".
CATEGORY_TEMPLATE_MAP = {
    "restaurant": "site_restaurant.html", "cafe": "site_restaurant.html",
    "bakery": "site_restaurant.html",
    "hair_salon": "site_service.html", "beauty_salon": "site_service.html",
    "barber_shop": "site_service.html",
    "plumber": "site_service.html", "electrician": "site_service.html",
    "roofing_contractor": "site_service.html",
    "general_contractor": "site_service.html",
    "dentist": "site_service.html", "doctor": "site_service.html",
    "chiropractor": "site_service.html",
    "auto_repair": "site_service.html", "car_repair": "site_service.html",
    "car_wash": "site_service.html",
    "lawyer": "site_service.html", "accounting": "site_service.html",
    "veterinary_care": "site_service.html",
    "pet_store": "site_retail.html", "florist": "site_retail.html",
    "shoe_store": "site_retail.html", "clothing_store": "site_retail.html",
}


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9-]", "-", text.lower())
    return re.sub(r"-+", "-", s).strip("-")[:60]


def _template_for(category: str) -> Path:
    name = CATEGORY_TEMPLATE_MAP.get(category, "site_service.html")
    return TEMPLATES_DIR / name


def _personalize_copy(prospect: dict, dry_run: bool = True) -> dict:
    """Generate personalized copy fields. In dry-run, uses deterministic defaults."""
    name = prospect["name"]
    cat = prospect.get("category", "service")

    if dry_run:
        # Deterministic, plausible copy — no API call needed
        return {
            "hero_headline": f"Welcome to {name}",
            "hero_sub": f"Trusted by {prospect.get('review_count', 12)} happy customers in your neighborhood.",
            "about_paragraph": (
                f"{name} has been serving the community with care for years. "
                f"Quality work, fair prices, and the kind of personal service "
                f"that built our reputation one customer at a time."
            ),
            "cta_text": _default_cta(cat),
            "service_cards": _default_cards(cat),
        }
    # Live mode: call LLM. Implementation calls Anthropic Messages API.
    return _llm_personalize(prospect)


def _default_cta(category: str) -> str:
    if "restaurant" in category or category in {"cafe", "bakery"}:
        return "View Menu & Reserve a Table"
    if category in {"pet_store", "florist", "shoe_store", "clothing_store"}:
        return "Visit the Store"
    return "Get a Free Quote"


def _default_cards(category: str) -> list[dict]:
    by_cat = {
        "restaurant": [
            {"title": "Today's Specials", "body": "Chef's seasonal picks, updated daily."},
            {"title": "Reservations", "body": "Book a table for 2-12 guests."},
            {"title": "Private Events", "body": "Host birthdays, anniversaries, business dinners."},
        ],
        "hair_salon": [
            {"title": "Cut & Color", "body": "Precision cuts and on-trend color from $45."},
            {"title": "Treatments", "body": "Keratin smoothing, deep conditioning, scalp care."},
            {"title": "Bridal Styling", "body": "On-location packages available."},
        ],
        "plumber": [
            {"title": "24/7 Emergency", "body": "Burst pipes, no hot water, sewer back-ups."},
            {"title": "Installations", "body": "Water heaters, faucets, garbage disposals."},
            {"title": "Inspections", "body": "Pre-purchase home plumbing inspections."},
        ],
        "dentist": [
            {"title": "General Dentistry", "body": "Cleanings, fillings, crowns."},
            {"title": "Cosmetic", "body": "Whitening, veneers, smile makeovers."},
            {"title": "Emergency", "body": "Same-day appointments for pain or trauma."},
        ],
    }
    return by_cat.get(category, [
        {"title": "Our Services", "body": "Trusted work, fair pricing, friendly team."},
        {"title": "About Us", "body": "Locally owned and operated for years."},
        {"title": "Contact", "body": "Call us today for a free estimate."},
    ])


def _llm_personalize(prospect: dict) -> dict:
    """Hit Anthropic Messages API for personalized copy. Falls back to defaults on error."""
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic SDK not installed; using defaults. pip install anthropic")
        return _personalize_copy(prospect, dry_run=True)
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return _personalize_copy(prospect, dry_run=True)
    client = anthropic.Anthropic(api_key=key)
    prompt = (
        f"You're writing landing-page copy for a small local business that doesn't have a website yet.\n"
        f"Business name: {prospect['name']}\n"
        f"Category: {prospect.get('category', 'small business')}\n"
        f"Location: {prospect.get('address', 'their neighborhood')}\n"
        f"Phone: {prospect.get('phone', '')}\n"
        f"\nWrite a JSON object with these fields, all in a warm, trustworthy small-business tone "
        f"(NO hype, NO emojis, NO 'transform your life' language):\n"
        f'  - hero_headline (max 60 chars)\n'
        f'  - hero_sub (max 100 chars)\n'
        f'  - about_paragraph (2-3 sentences)\n'
        f'  - cta_text (max 30 chars)\n'
        f'  - service_cards (array of exactly 3 objects with title + body, body 12 words max)\n'
        f"\nReturn ONLY the JSON, no markdown."
    )
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        return json.loads(text)
    except Exception as e:
        logger.warning(f"LLM personalize failed for {prospect['name']!r}: {e}; using defaults.")
        return _personalize_copy(prospect, dry_run=True)


def _render(template_path: Path, prospect: dict, copy: dict) -> str:
    """Lightweight string substitution. Keeps templates simple — no Jinja dependency."""
    tmpl = template_path.read_text(encoding="utf-8")
    cards_html = "\n".join(
        f'<div class="card"><h3>{html.escape(c["title"])}</h3>'
        f'<p>{html.escape(c["body"])}</p></div>'
        for c in copy["service_cards"]
    )
    fields = {
        "BUSINESS_NAME": html.escape(prospect["name"]),
        "HERO_HEADLINE": html.escape(copy["hero_headline"]),
        "HERO_SUB": html.escape(copy["hero_sub"]),
        "ABOUT_PARAGRAPH": html.escape(copy["about_paragraph"]),
        "CTA_TEXT": html.escape(copy["cta_text"]),
        "PHONE": html.escape(prospect.get("phone", "")),
        "ADDRESS": html.escape(prospect.get("address", "")),
        "CARDS_HTML": cards_html,  # Already escaped above
        "YEAR": str(time.gmtime().tm_year),
    }
    for k, v in fields.items():
        tmpl = tmpl.replace(f"{{{{ {k} }}}}", v)
    return tmpl


def generate_previews(enriched_path: Path, dry_run: bool = True) -> Path:
    """Read enriched JSON, generate HTML previews, write to runs/<date>/03-previews/."""
    enriched = json.loads(enriched_path.read_text())
    stamp = time.strftime("%Y-%m-%d")
    slug_loc = enriched["_meta"]["location"].lower().replace(",", "").replace(" ", "-")[:40]
    out_dir = ROOT / "data" / "launches" / "siteboost" / "runs" / f"{stamp}-{slug_loc}" / "03-previews"
    out_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    for p in enriched["enriched"]:
        copy = _personalize_copy(p, dry_run=dry_run)
        tmpl_path = _template_for(p.get("category", ""))
        if not tmpl_path.exists():
            logger.warning(f"Template missing: {tmpl_path}; skipping {p['name']}")
            continue
        html_out = _render(tmpl_path, p, copy)
        slug = _slugify(p["name"])
        (out_dir / f"{slug}.html").write_text(html_out, encoding="utf-8")
        generated.append({
            "name": p["name"], "slug": slug,
            "preview_url": f"https://preview.wheellsverse.com/{slug}",
            "category": p.get("category", ""),
            "template": tmpl_path.name,
        })

    manifest = out_dir.parent / "03-previews-manifest.json"
    manifest.write_text(json.dumps({
        "_meta": {"generated_at": stamp, "n_previews": len(generated), "dry_run": dry_run},
        "previews": generated,
    }, indent=2))
    logger.info(f"[generate] {len(generated)} previews → {out_dir}")
    return manifest


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--enriched", required=True)
    p.add_argument("--live", action="store_true")
    args = p.parse_args()
    out = generate_previews(Path(args.enriched), dry_run=not args.live)
    print(f"OK · preview manifest: {out}")
