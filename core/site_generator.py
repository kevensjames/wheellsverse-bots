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
    """Category-deep service cards. 25 categories with specific, plausible copy.

    Even WITHOUT LLM, these defaults produce a far better site than generic copy.
    Each card body is 12-18 words, concrete, references real services or outcomes.
    """
    by_cat = {
        # — Food & beverage —
        "restaurant": [
            {"title": "Seasonal Menu", "body": "Chef-curated dishes from local farms, rotating weekly with the harvest."},
            {"title": "Online Reservations", "body": "Book a table for 2-12 in under 30 seconds, no phone tag."},
            {"title": "Private Events", "body": "Birthdays, anniversaries, business dinners — full venue or semi-private rooms."},
        ],
        "cafe": [
            {"title": "House-Roasted Coffee", "body": "Single-origin and seasonal blends roasted on-site, brewed any way you like."},
            {"title": "Fresh Bakery Case", "body": "Croissants, scones, and pastries made from scratch every morning before open."},
            {"title": "Free WiFi & Workspace", "body": "Quiet booths, fast internet, and outlets at every table for remote work."},
        ],
        "bakery": [
            {"title": "Custom Cakes", "body": "Birthday, wedding, and special-occasion cakes designed to your theme."},
            {"title": "Daily Bread", "body": "Sourdough, baguettes, ciabatta — pulled fresh from the oven every morning."},
            {"title": "Catering & Trays", "body": "Office pastries, brunch spreads, and event dessert tables ready in 24 hrs."},
        ],
        # — Personal care —
        "hair_salon": [
            {"title": "Cut & Color", "body": "Precision cuts plus balayage, highlights, and gloss treatments from senior stylists."},
            {"title": "Smoothing Treatments", "body": "Keratin, Brazilian blowout, and bond-repair systems for damaged or frizzy hair."},
            {"title": "Bridal & Event Styling", "body": "On-location packages for weddings and special occasions, trials included."},
        ],
        "beauty_salon": [
            {"title": "Skincare Facials", "body": "Hydrafacial, chemical peels, and microdermabrasion tailored to your skin type."},
            {"title": "Lash & Brow", "body": "Lash extensions, tinting, brow lamination, microblading — booked in 60-min slots."},
            {"title": "Waxing & Tinting", "body": "Full-body waxing in private rooms, including same-day appointments."},
        ],
        "barber_shop": [
            {"title": "Classic Cuts", "body": "Fades, tapers, scissor cuts — clippered to the exact length you want."},
            {"title": "Beard Service", "body": "Hot-towel shaves, beard line-ups, and beard oil conditioning included."},
            {"title": "Walk-Ins Welcome", "body": "Average 12-minute wait, or skip the line with online check-in."},
        ],
        # — Home services / trades —
        "plumber": [
            {"title": "24/7 Emergency Service", "body": "Burst pipes, no hot water, sewer back-ups — on-site within 90 minutes."},
            {"title": "Installations & Replacement", "body": "Water heaters, faucets, garbage disposals, toilet rebuilds, and full repipes."},
            {"title": "Pre-Purchase Inspections", "body": "Detailed plumbing report before you close on a home, including video scope."},
        ],
        "electrician": [
            {"title": "Panel Upgrades", "body": "200A service upgrades, sub-panels, and full house rewiring on older homes."},
            {"title": "EV Charger Installation", "body": "Level 2 home charger installation with the load calc and permit handled."},
            {"title": "Troubleshooting", "body": "Tripping breakers, flickering lights, dead outlets — diagnosed and fixed same-day."},
        ],
        "roofing_contractor": [
            {"title": "Full Roof Replacement", "body": "Asphalt shingle, metal, or flat — with manufacturer warranty and tear-off included."},
            {"title": "Storm Damage Repair", "body": "Insurance-claim experienced; we handle the adjuster meeting and paperwork."},
            {"title": "Annual Inspections", "body": "Drone-based roof inspection with photos and a 12-page condition report."},
        ],
        "painter": [
            {"title": "Interior Painting", "body": "Two-coat finish with full prep, no-VOC paint, and furniture moved + replaced."},
            {"title": "Exterior Painting", "body": "Power-wash, scrape, prime, paint — with manufacturer 7-year warranty."},
            {"title": "Cabinet Refinishing", "body": "Kitchen cabinet refinishing that lasts longer than full replacement at half the cost."},
        ],
        "moving_company": [
            {"title": "Local Moves", "body": "Hourly rate with 2-4 movers, truck, blankets, and floor protection included."},
            {"title": "Long-Distance Moves", "body": "Flat-rate cross-country moves with binding estimates and on-time delivery guarantee."},
            {"title": "Packing & Unpacking", "body": "Full-service packing including supplies, with custom crating for fragile items."},
        ],
        # — Medical —
        "dentist": [
            {"title": "General Dentistry", "body": "Cleanings, fillings, crowns, and night guards — with same-week appointments available."},
            {"title": "Cosmetic & Whitening", "body": "Whitening, veneers, smile makeovers, and Invisalign for adult straightening."},
            {"title": "Emergency Care", "body": "Same-day appointments for pain, broken teeth, or trauma — call before 4 PM."},
        ],
        "doctor": [
            {"title": "Primary Care", "body": "Annual physicals, sick visits, chronic-condition management, and Medicare wellness."},
            {"title": "Same-Day Sick Visits", "body": "Strep, flu, UTIs, ear infections — see a provider the day you call."},
            {"title": "Telehealth", "body": "Video visits for follow-ups, medication refills, and mental health consultations."},
        ],
        "chiropractor": [
            {"title": "Adjustments", "body": "Spinal manipulation for back pain, neck pain, and headache relief in 20-minute visits."},
            {"title": "Sports Injury", "body": "Active-release technique, dry needling, and rehab plans for runners and athletes."},
            {"title": "Auto Accident Care", "body": "Whiplash and back-injury treatment with attorney coordination if needed."},
        ],
        # — Auto —
        "car_repair": [
            {"title": "Brakes & Suspension", "body": "Brake pads, rotors, struts, alignment — same-day on most makes and models."},
            {"title": "Engine Diagnostics", "body": "Check-engine light diagnosis with shop fee waived if we do the repair."},
            {"title": "Pre-Purchase Inspections", "body": "$99 inspection before you buy a used car — full report you can share."},
        ],
        "car_wash": [
            {"title": "Monthly Unlimited Wash", "body": "$25/month for unlimited washes, no contract, cancel anytime."},
            {"title": "Detailing Packages", "body": "Interior shampoo, leather conditioning, paint clay-bar, and ceramic coatings."},
            {"title": "Express Wash Lane", "body": "Three-minute exterior wash with free vacuums for one hour after."},
        ],
        # — Professional services —
        "lawyer": [
            {"title": "Free Consultation", "body": "30-minute case review with an attorney, no obligation, in person or by phone."},
            {"title": "Estate Planning", "body": "Wills, trusts, healthcare proxies, and power of attorney — fixed-fee packages."},
            {"title": "Personal Injury", "body": "Contingency basis — you pay nothing unless we win your case."},
        ],
        "accounting": [
            {"title": "Tax Preparation", "body": "Personal and business returns, including amendments and IRS audit representation."},
            {"title": "Bookkeeping", "body": "Monthly bookkeeping with QuickBooks setup, reconciliations, and clean financials."},
            {"title": "Business Formation", "body": "LLC, S-Corp setup with EIN filing, operating agreements, and ongoing compliance."},
        ],
        # — Retail —
        "pet_store": [
            {"title": "Premium Pet Food", "body": "Raw, freeze-dried, and grain-free brands not available in big-box stores."},
            {"title": "Self-Wash Stations", "body": "Walk-in dog wash with shampoo, towels, and blow-dryers — $15 per visit."},
            {"title": "Training Classes", "body": "Puppy, basic obedience, and behavior modification with certified trainers."},
        ],
        "florist": [
            {"title": "Same-Day Delivery", "body": "Order by 1 PM for same-day local delivery, freshness guaranteed for 7 days."},
            {"title": "Wedding & Events", "body": "Custom bouquets, ceremony pieces, and reception centerpieces with full setup."},
            {"title": "Subscription Service", "body": "Fresh seasonal arrangement delivered weekly or biweekly to home or office."},
        ],
        "veterinary_care": [
            {"title": "Preventive Care", "body": "Annual wellness exams, vaccines, dental cleanings, and parasite prevention."},
            {"title": "Surgery & Dentistry", "body": "Soft-tissue surgery, orthopedic procedures, and full dental scaling under anesthesia."},
            {"title": "Same-Day Sick Visits", "body": "Walk-ins welcome before 10 AM for vomiting, diarrhea, lameness, or skin issues."},
        ],
        "shoe_store": [
            {"title": "Professional Fitting", "body": "Brannock measurement, gait analysis, and orthotic recommendations from trained staff."},
            {"title": "Repair & Stretching", "body": "Resoling, heel replacement, stretching, and zipper repair while you wait."},
            {"title": "Custom Orthotics", "body": "Computer foot-scan and casted custom orthotics for plantar fasciitis or arch support."},
        ],
        "clothing_store": [
            {"title": "Personal Shopping", "body": "One-on-one styling sessions with curated picks based on your body and budget."},
            {"title": "In-House Tailoring", "body": "Hemming, taper, and full alterations turned around in 5-7 days."},
            {"title": "New Arrivals Weekly", "body": "Hand-picked seasonal pieces from independent brands you won't find at the mall."},
        ],
    }
    return by_cat.get(category, [
        {"title": "Our Services", "body": "Trusted local work backed by years of word-of-mouth referrals from neighbors."},
        {"title": "Why Choose Us", "body": "Family-owned, locally operated, transparent pricing — and we answer the phone."},
        {"title": "Get in Touch", "body": "Call or text for a free estimate, no high-pressure sales calls afterward."},
    ])


def _build_llm_prompt(prospect: dict) -> str:
    """Build a rich, business-specific prompt for the LLM copywriter."""
    city = prospect.get("address", "").split(",")[-3:] if "," in prospect.get("address", "") else ["the area"]
    city_part = city[-2].strip() if len(city) >= 2 else "the area"
    rating_blurb = ""
    if prospect.get("rating") and prospect.get("review_count"):
        rating_blurb = (f"They have {prospect['rating']}/5 stars from "
                        f"{prospect['review_count']} Google reviews — use this as social proof. ")
    return f"""You are an expert landing-page copywriter for local small businesses. Your job is to write copy that makes the specific business below feel REAL, LOCAL, and TRUSTED — not generic.

BUSINESS DETAILS
  Name:     {prospect['name']}
  Category: {prospect.get('category', 'local business')}
  Address:  {prospect.get('address', 'unknown')}
  Phone:    {prospect.get('phone', '')}
  Rating:   {prospect.get('rating', 'unknown')}/5 from {prospect.get('review_count', 0)} reviews

CONTEXT
{rating_blurb}This is a real business in {city_part}. The copy will live on a sample
website preview I'm sending the owner. They will see it and judge whether you understand
their business. Generic copy = no reply. Specific, locally-flavored, plausible copy = reply.

TONE
- Trusted neighbor, not used-car salesperson
- NO emojis, NO "transform your life", NO "elevate your experience", NO hype
- Reference the actual category-specific services (e.g. "Brake rotor resurfacing" not "Quality service")
- Reference the actual local area when possible ({city_part})

OUTPUT — strict JSON, exactly these keys:
{{
  "hero_headline":  "4-8 words, business-specific, evocative",
  "hero_sub":       "12-22 words, specific concrete benefit",
  "about_paragraph": "3 sentences, references local context + specific services",
  "cta_text":       "3-6 words, action verb + outcome",
  "service_cards": [
    {{"title": "Specific service name (3-4 words)", "body": "Concrete description (12-18 words)"}},
    {{"title": "...", "body": "..."}},
    {{"title": "...", "body": "..."}}
  ]
}}

Return ONLY the JSON object. No markdown fences, no explanation."""


def _parse_llm_json(text: str) -> Optional[dict]:
    """Strip markdown fences and parse JSON. Returns None on any parsing error."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        d = json.loads(text)
        # Validate shape
        if all(k in d for k in ("hero_headline", "hero_sub", "about_paragraph",
                                 "cta_text", "service_cards")):
            return d
    except Exception:
        pass
    return None


def _try_anthropic_personalize(prospect: dict) -> Optional[dict]:
    """Try Anthropic first. Returns None on any failure (caller falls back)."""
    try:
        import anthropic
    except ImportError:
        return None
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": _build_llm_prompt(prospect)}],
        )
        return _parse_llm_json(resp.content[0].text)
    except Exception as e:
        logger.info(f"Anthropic personalize failed ({type(e).__name__}); trying OpenAI fallback")
        return None


def _try_openai_personalize(prospect: dict) -> Optional[dict]:
    """OpenAI fallback (used when Anthropic is unavailable/out of credit)."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    try:
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": _build_llm_prompt(prospect)}],
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        return _parse_llm_json(resp.choices[0].message.content)
    except Exception as e:
        logger.warning(f"OpenAI personalize also failed ({type(e).__name__}: {e}); using defaults")
        return None


def _llm_personalize(prospect: dict) -> dict:
    """Generate personalized copy. Anthropic → OpenAI → defaults.

    Tries Anthropic first (highest quality). If billing/credit fails, transparently
    falls back to OpenAI. If both fail, uses the category-deep defaults — which are
    themselves much better than nothing.
    """
    result = _try_anthropic_personalize(prospect)
    if result:
        logger.info(f"[generate] LLM (anthropic) personalized: {prospect['name']!r}")
        return result
    result = _try_openai_personalize(prospect)
    if result:
        logger.info(f"[generate] LLM (openai) personalized: {prospect['name']!r}")
        return result
    logger.info(f"[generate] LLM unavailable; using deep-defaults for: {prospect['name']!r}")
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
    """Read enriched JSON, generate HTML previews, write to runs/<date>/03-previews/.

    Runs path is configurable via SITEBOOST_RUNS_PATH — defaults to the in-repo
    ephemeral location for local dev, but production sets this to /var/data/...
    on the mounted Railway volume so preview HTML survives container redeploys.
    Without this, every cold email's preview URL breaks on the next deploy —
    a catastrophic UX failure for prospects clicking your links.
    """
    enriched = json.loads(enriched_path.read_text())
    stamp = time.strftime("%Y-%m-%d")
    slug_loc = enriched["_meta"]["location"].lower().replace(",", "").replace(" ", "-")[:40]
    runs_dir = Path(os.getenv("SITEBOOST_RUNS_PATH", str(ROOT / "data" / "launches" / "siteboost" / "runs")))
    out_dir = runs_dir / f"{stamp}-{slug_loc}" / "03-previews"
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
            "preview_url": f"https://app.wheellsverse.com/p/{slug}",
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
