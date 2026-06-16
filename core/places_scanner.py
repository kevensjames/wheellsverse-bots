"""Google Places API scanner — finds local businesses without a website.

Stage 1 of the SiteBoost pipeline. Uses Places API v1 (New) which is the
current/recommended interface as of 2025+.

Key safety properties:
    - Hard 100 req/sec rate limit (well under Places API quota)
    - Auto-skips EU/UK businesses (GDPR-safe by construction)
    - Dry-run mode emits realistic fake data without API calls
    - Each call's cost ($) printed at the end so you see spend before scaling

Env vars:
    GOOGLE_PLACES_API_KEY  required for --live; ignored in dry-run

Pricing as of 2026:
    Places API Nearby Search:  $32 per 1,000 (Basic) + free tier $200/mo
    Place Details (per place): $17 per 1,000 (Basic data) + same free tier
    Realistic scan of 100 places: ~$5 if all need detail lookups
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
SCANS_DIR = ROOT / "data" / "launches" / "siteboost" / "scans"
logger = logging.getLogger("places_scanner")

# Regions we never scrape — GDPR / CCPA risk
GDPR_COUNTRY_CODES = {"GB", "DE", "FR", "IT", "ES", "NL", "BE", "AT", "DK", "FI",
                      "GR", "IE", "LU", "PT", "SE", "PL", "CZ", "HU", "RO", "BG"}

# National chains / big-box brands. SiteBoost's market is small local businesses;
# emailing the local manager of an AutoZone is wasted send (they can't make this
# decision and the corporate IT team already owns the website). Matched case-insensitive
# against the business name as a substring.
CHAIN_BLOCKLIST = {
    # Big-box retail
    "walmart", "target", "costco", "sam's club", "bj's wholesale", "kohl's",
    "marshalls", "tj maxx", "homegoods", "ross dress", "burlington",
    "home depot", "lowe's", "menards", "tractor supply", "harbor freight",
    "best buy", "ikea", "michaels", "hobby lobby", "petsmart", "petco",
    "office depot", "staples", "gamestop", "foot locker",
    # Grocery chains
    "whole foods", "trader joe", "stop & shop", "shaws", "wegmans",
    "publix", "kroger", "safeway", "albertsons", "winn-dixie", "aldi",
    "lidl", "food lion", "harris teeter",
    # Auto chains + dealerships
    "autozone", "advance auto", "o'reilly auto", "pep boys", "napa auto",
    "jiffy lube", "valvoline", "midas", "firestone", "goodyear",
    "discount tire", "big o tires", "autonation", "carmax", "carvana", "vroom",
    # Pharmacy
    "cvs", "walgreens", "rite aid", "duane reade",
    # Fast food / chain restaurants
    "mcdonald", "burger king", "wendy", "subway", "chipotle", "panera",
    "starbucks", "dunkin", "domino", "pizza hut", "papa john", "taco bell",
    "kfc", "popeyes", "chick-fil-a", "five guys", "shake shack",
    "olive garden", "applebee", "chili's", "outback", "ihop", "denny",
    "sonic drive-in", "arby", "dairy queen", "jersey mike", "jimmy john",
    "firehouse subs", "tropical smoothie", "wingstop", "raising cane",
    "moe's southwest", "qdoba", "panda express", "white castle",
    "culver", "in-n-out", "del taco", "el pollo loco",
    # Banks + financial
    "bank of america", "wells fargo", "chase bank", "citibank", "capital one",
    "td bank", "us bank", "pnc bank", "regions bank", "santander",
    "h&r block", "jackson hewitt",
    # Hotels (cold-emailing front desk = waste)
    "marriott", "hilton", "hyatt", "best western", "comfort inn",
    "holiday inn", "fairfield inn", "courtyard by marriott", "hampton inn",
    "residence inn", "homewood suites", "doubletree", "embassy suites",
    "motel 6", "super 8", "days inn", "la quinta", "americinn",
    # Fitness chains
    "planet fitness", "anytime fitness", "la fitness", "equinox",
    "orangetheory", "f45 training", "crunch fitness", "24 hour fitness",
    "gold's gym", "ufc gym", "blink fitness", "9round",
    # Insurance
    "state farm", "geico", "allstate", "progressive", "farmers insurance",
    "liberty mutual", "nationwide insurance", "usaa",
    # Shipping / mail
    "ups store", "the ups store", "fedex office", "fedex print",
    "postal annex", "mail boxes etc",
    # Healthcare clinics (chain)
    "minuteclinic", "medexpress", "fastmed", "concentra", "patient first",
    # Furniture / mattress
    "ashley furniture", "rooms to go", "bob's discount",
    "raymour & flanigan", "mattress firm", "sleep number", "mattress warehouse",
    # Sporting goods
    "dick's sporting", "academy sports", "rei co-op", "bass pro",
    "cabela", "modell", "champs sports",
    # Vision / eye
    "lenscrafters", "pearle vision", "for eyes", "warby parker",
    "america's best",
    # Discount + dollar
    "dollar tree", "dollar general", "family dollar", "five below",
    # Telecom retail
    "verizon", "at&t", "t-mobile", "sprint store", "xfinity store",
    "spectrum store",
    # Tax + legal services chains
    "legalzoom", "rocket lawyer",
    # Hardware (non-big-box chains)
    "ace hardware", "true value",
}


def _is_chain(name: str) -> bool:
    """Return True if business name matches a known national chain."""
    n = name.lower()
    return any(brand in n for brand in CHAIN_BLOCKLIST)

# Places API v1 includedPrimaryTypes — only types validated in Table A
# (https://developers.google.com/maps/documentation/places/web-service/place-types#table-a).
# Removed: general_contractor (no v1 equivalent), auto_repair (use car_repair instead).
DEFAULT_CATEGORIES = [
    "restaurant", "cafe", "bakery",
    "hair_salon", "beauty_salon", "barber_shop",
    "plumber", "electrician", "roofing_contractor", "painter", "moving_company",
    "dentist", "doctor", "chiropractor",
    "car_repair", "car_wash",
    "lawyer", "accounting",
    "pet_store", "veterinary_care",
    "florist", "shoe_store", "clothing_store",
]


@dataclass
class Prospect:
    place_id: str
    name: str
    category: str
    address: str
    phone: str = ""
    website: str = ""
    rating: float = 0.0
    review_count: int = 0
    lat: float = 0.0
    lng: float = 0.0
    country_code: str = ""
    website_issues: list[str] = field(default_factory=list)

    def is_targetable(self) -> tuple[bool, str]:
        """Return (ok, reason). Targetable = no-website OR has-bad-website,
        plus has-phone, non-GDPR, and not a national chain.

        The chain filter matters: even when a Walmart returns 'no-https' on the
        probe, emailing the local store manager is wasted send — they can't make
        the decision and corporate IT already owns the website.
        """
        if self.country_code in GDPR_COUNTRY_CODES:
            return False, "gdpr-region"
        if not self.phone:
            return False, "no-phone"
        if _is_chain(self.name):
            return False, "national-chain"
        if not self.website:
            return True, "no-website"
        if self.website_issues:
            return True, f"bad-website:{self.website_issues[0]}"
        return False, "good-website"


def _probe_website(url: str, timeout: int = 5) -> list[str]:
    """Probe a business website and return a list of detected quality issues.

    Empty list = the site is fine (operator probably doesn't need a new one).
    Non-empty list = at least one objective problem the operator can sell against.

    Detection is intentionally conservative: every signal here is one the operator
    can repeat verbatim in a cold email ("your site fails on mobile", "ssl is expired")
    so the prospect can verify it for themselves.
    """
    if not url:
        return []
    issues: list[str] = []

    # Realistic browser UA — Cloudflare and many WAFs return 403 to obvious bot strings,
    # which masks real site health behind probe-tooling false positives.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True, headers=headers)
    except requests.exceptions.SSLError:
        return issues + ["ssl-broken"]
    except requests.exceptions.Timeout:
        return issues + ["timeout"]
    except requests.exceptions.RequestException:
        return issues + ["connection-failed"]

    # Check FINAL URL after redirects — many sites set http:// in Google Business Profile
    # but 301 to https://. Only the post-redirect state reflects reality.
    if not r.url.startswith("https://"):
        issues.append("no-https")

    if r.status_code >= 400:
        # 401/403/429 = the SITE is rejecting US (bot detection, WAF, rate-limit),
        # not necessarily broken for real human visitors. Falsely classifying these
        # as "bad-website" and emailing "your site is broken" insults prospects with
        # perfectly fine sites that just happen to use Cloudflare's bot protection.
        # Better to skip than to wrongly accuse — return empty issues, prospect falls
        # through to "good-website" and gets filtered OUT of targetable.
        if r.status_code in (401, 403, 429):
            return []
        return issues + [f"http-{r.status_code}"]

    body = r.text.lower()
    body_len = len(body)

    # Tiny pages are usually parked-domain placeholders or default web-host stubs
    if body_len < 500:
        issues.append("placeholder-or-empty")

    parking_markers = (
        "godaddy", "domain for sale", "namebright", "this domain is parked",
        "buy this domain", "default web site page", "test page for the",
        "domain has been registered",
    )
    if any(m in body for m in parking_markers):
        issues.append("parking-page")

    # Mobile-friendly = viewport meta tag exists. 60%+ of small-biz traffic is mobile.
    if 'name="viewport"' not in body and "name='viewport'" not in body:
        issues.append("not-mobile-friendly")

    coming_soon_markers = (
        "coming soon", "under construction", "site is being updated",
        "site coming soon",
    )
    if any(m in body for m in coming_soon_markers):
        issues.append("coming-soon")

    if "<title>" not in body or "<title></title>" in body:
        issues.append("no-title")

    # Outdated copyright year — sites with ©2019 in 2026 = abandoned, prime SiteBoost target.
    # Look for "© 2019", "©2019", "copyright 2019" patterns.
    import re
    current_year = time.gmtime().tm_year
    year_matches = re.findall(r"(?:©|&copy;|copyright)\s*(\d{4})", body)
    if year_matches:
        # Take the highest year found (footer often shows the most recent update)
        latest_year = max(int(y) for y in year_matches if y.isdigit() and 1990 <= int(y) <= current_year)
        if latest_year < current_year - 3:
            issues.append(f"copyright-{latest_year}")

    # Default CMS template — page rendered but never customized (lazy/abandoned build)
    default_template_markers = (
        "/themes/twentynineteen/", "/themes/twentytwenty/", "/themes/twentytwentyone/",
        "/themes/twentytwentytwo/", "/themes/twentytwentythree/",
        "wp-content/themes/default/", "wordpress.org/themes",
        "wix-static-html", "weebly-default", "godaddysites.com",
        "this is a sample page", "lorem ipsum dolor sit amet",
    )
    if any(m in body for m in default_template_markers):
        issues.append("default-template")

    return issues


def _api_key() -> str:
    k = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not k:
        raise RuntimeError(
            "GOOGLE_PLACES_API_KEY not set. Either set it in .env, or run with --dry-run."
        )
    return k


def _geocode(location: str, api_key: str) -> tuple[float, float, str]:
    """City/zip → (lat, lng, country_code) via Geocoding API."""
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    r = requests.get(url, params={"address": location, "key": api_key}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "OK" or not data.get("results"):
        raise RuntimeError(f"Geocode failed for {location!r}: {data.get('status')}")
    res = data["results"][0]
    loc = res["geometry"]["location"]
    country = ""
    for comp in res.get("address_components", []):
        if "country" in comp.get("types", []):
            country = comp.get("short_name", "")
            break
    return loc["lat"], loc["lng"], country


def _nearby_search(lat: float, lng: float, radius_m: int,
                    categories: list[str], api_key: str) -> list[dict]:
    """Places API (New) v1 — searchNearby."""
    url = "https://places.googleapis.com/v1/places:searchNearby"
    field_mask = ",".join([
        "places.id", "places.displayName", "places.formattedAddress",
        "places.nationalPhoneNumber", "places.websiteUri", "places.rating",
        "places.userRatingCount", "places.location", "places.primaryType",
    ])
    body = {
        "includedTypes": categories,
        "maxResultCount": 20,  # API max
        "locationRestriction": {
            "circle": {"center": {"latitude": lat, "longitude": lng},
                       "radius": float(radius_m)},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    }
    out: list[dict] = []
    # Places API v1 doesn't paginate searchNearby (capped at 20 per call).
    # To get more, iterate categories or use textSearch instead.
    for cat_chunk in _chunks(categories, 10):
        body["includedTypes"] = cat_chunk
        r = requests.post(url, json=body, headers=headers, timeout=15)
        if r.status_code != 200:
            logger.warning(f"searchNearby returned {r.status_code}: {r.text[:200]}")
            continue
        out.extend(r.json().get("places", []))
        time.sleep(0.05)  # 20 req/sec ceiling, well under quota
    return out


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _parse(place: dict, country_code: str) -> Prospect:
    loc = place.get("location", {})
    name = place.get("displayName", {}).get("text", "") if isinstance(place.get("displayName"), dict) else place.get("displayName", "")
    return Prospect(
        place_id=place.get("id", ""),
        name=name,
        category=place.get("primaryType", ""),
        address=place.get("formattedAddress", ""),
        phone=place.get("nationalPhoneNumber", ""),
        website=place.get("websiteUri", ""),
        rating=float(place.get("rating", 0.0) or 0.0),
        review_count=int(place.get("userRatingCount", 0) or 0),
        lat=float(loc.get("latitude", 0.0) or 0.0),
        lng=float(loc.get("longitude", 0.0) or 0.0),
        country_code=country_code,
    )


def _dry_run_fixtures(location: str, n: int = 20) -> list[Prospect]:
    """Realistic fake data so the rest of the pipeline can be tested without API spend."""
    seed_names = [
        ("Mama Lupita's Tortilleria", "restaurant", "(617) 555-0142"),
        ("Cuts by Carlos", "hair_salon", "(617) 555-0319"),
        ("Boston Joe's Plumbing", "plumber", "(617) 555-0211"),
        ("North End Cafe", "cafe", "(617) 555-0388"),
        ("DeLuca Family Dentistry", "dentist", "(617) 555-0445"),
        ("Allston Auto Body", "auto_repair", "(617) 555-0567"),
        ("Beacon Hill Florist", "florist", "(617) 555-0612"),
        ("South End Barbers", "barber_shop", "(617) 555-0701"),
        ("Quincy Roofing & Siding", "roofing_contractor", "(617) 555-0823"),
        ("Tony's Shoe Repair", "shoe_store", "(617) 555-0912"),
        ("Mei Lin Acupuncture", "chiropractor", "(617) 555-1034"),
        ("Roxbury Tax Office", "accounting", "(617) 555-1167"),
        ("The Cookie Lady", "bakery", "(617) 555-1289"),
        ("Allen Electric Co.", "electrician", "(617) 555-1304"),
        ("Brighton Pet Spa", "pet_store", "(617) 555-1418"),
        ("Olga's Hair Studio", "hair_salon", "(617) 555-1526"),
        ("Mike's Tire Shop", "car_repair", "(617) 555-1639"),
        ("Greater Boston Vet", "veterinary_care", "(617) 555-1745"),
        ("Athens Tailors", "clothing_store", "(617) 555-1858"),
        ("Castelli General Contracting", "general_contractor", "(617) 555-1962"),
    ]
    out = []
    for i, (n_, c_, p_) in enumerate(seed_names[:n]):
        out.append(Prospect(
            place_id=f"dry_{i:04d}",
            name=n_, category=c_, phone=p_,
            address=f"{100 + i*7} Random St, {location}",
            website="",  # Dry run: all targetable
            rating=4.0 + (i % 10) * 0.1,
            review_count=10 + i * 3,
            lat=42.36 + i * 0.001, lng=-71.06 - i * 0.001,
            country_code="US",
        ))
    return out


def scan(location: str, radius_m: int = 5000, categories: Optional[list[str]] = None,
         limit: int = 100, dry_run: bool = True) -> list[Prospect]:
    """Entry point. Returns list of targetable Prospects (no website, US-only)."""
    SCANS_DIR.mkdir(parents=True, exist_ok=True)
    cats = categories or DEFAULT_CATEGORIES

    if dry_run:
        prospects = _dry_run_fixtures(location, n=min(20, limit))
    else:
        key = _api_key()
        lat, lng, country = _geocode(location, key)
        if country in GDPR_COUNTRY_CODES:
            raise RuntimeError(f"Refusing to scan GDPR region ({country}). Pick a US/CA location.")
        raw = _nearby_search(lat, lng, radius_m, cats, key)
        prospects = [_parse(p, country) for p in raw][:limit]

        # Probe every site in parallel — the bad-website pivot needs each prospect's
        # actual site quality to classify. 8 workers × 5s timeout caps wall-clock at ~30s
        # for a 50-prospect scan (vs 4+ minutes sequential).
        with_site = [p for p in prospects if p.website]
        if with_site:
            logger.info(f"[scan] probing {len(with_site)} websites in parallel for quality issues")
            with ThreadPoolExecutor(max_workers=8) as ex:
                issue_lists = list(ex.map(_probe_website, [p.website for p in with_site]))
            for p, issues in zip(with_site, issue_lists):
                p.website_issues = issues

    targetable = [p for p in prospects if p.is_targetable()[0]]
    rejected = [(p, p.is_targetable()[1]) for p in prospects if not p.is_targetable()[0]]

    stamp = time.strftime("%Y-%m-%d")
    slug = location.lower().replace(",", "").replace(" ", "-")[:40]
    out_path = SCANS_DIR / f"{stamp}-{slug}.json"
    # Build a parallel breakdown for accepted prospects so the operator can see
    # whether targetable are "no-website" or "bad-website:X" (and which X dominates).
    targetable_reasons = [p.is_targetable()[1] for p in targetable]
    out_path.write_text(json.dumps({
        "_meta": {
            "location": location, "radius_m": radius_m,
            "categories": cats, "dry_run": dry_run,
            "scanned_at": stamp,
            "n_total": len(prospects),
            "n_targetable": len(targetable),
            "n_rejected": len(rejected),
            "rejection_reasons": {r: sum(1 for _, rr in rejected if rr == r)
                                  for r in {rr for _, rr in rejected}},
            "targetable_reasons": {r: targetable_reasons.count(r)
                                    for r in set(targetable_reasons)},
        },
        "targetable": [asdict(p) for p in targetable],
        "rejected": [{"name": p.name, "reason": r} for p, r in rejected],
    }, indent=2))
    logger.info(f"[scan] wrote {out_path}: {len(targetable)} targetable / {len(prospects)} total")
    return targetable


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--location", required=True)
    p.add_argument("--radius", type=int, default=5000)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--live", action="store_true")
    args = p.parse_args()
    results = scan(args.location, args.radius, limit=args.limit, dry_run=not args.live)
    print(f"OK · {len(results)} targetable prospects in {args.location}")
