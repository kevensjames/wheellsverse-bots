"""Lead-gen campaign runner — scan -> enrich -> draft -> CRM, per niche/city.

Honors "use only configured and authorized credentials": it runs LIVE only where
the key exists (GOOGLE_PLACES_API_KEY for scan, HUNTER_API_KEY for enrichment),
otherwise DRY-RUN with the result explicitly flagged `dry_run: true` so nobody
mistakes sample data for real leads. Reuses SiteBoost's own engines
(core.places_scanner, core.email_enricher) — same chain-exclusion + enrichment.

Produces, per campaign: a lead list, enrichment, templated outreach drafts, a
CRM import CSV, and a quality/next-actions report. Artifacts under
data/launches/leadgen/<slug>/.
"""
from __future__ import annotations

import csv
import io
import os
import re
import time

from core.portfolio import paths

CAMPAIGNS = [
    {"slug": "dental-boston", "niche": "Dental Clinics", "city": "Boston, Massachusetts",
     "category": "dentist", "limit": 100, "value_prop": "fill more new-patient appointments"},
    {"slug": "pi-lawyers-miami", "niche": "Personal Injury Lawyers", "city": "Miami, Florida",
     "category": "lawyer", "limit": 100, "value_prop": "book more qualified case consultations"},
    {"slug": "hvac-houston", "niche": "HVAC Companies", "city": "Houston, Texas",
     "category": "hvac_contractor", "limit": 100, "value_prop": "capture more service-call leads"},
    {"slug": "roofing-phoenix", "niche": "Roofing Companies", "city": "Phoenix, Arizona",
     "category": "roofing_contractor", "limit": 100, "value_prop": "win more roof-replacement quotes"},
    {"slug": "chiro-dallas", "niche": "Chiropractors", "city": "Dallas, Texas",
     "category": "chiropractor", "limit": 100, "value_prop": "grow your new-patient flow"},
    {"slug": "realestate-atlanta", "niche": "Real Estate Agencies", "city": "Atlanta, Georgia",
     "category": "real_estate_agency", "limit": 100, "value_prop": "convert more buyer/seller leads"},
]
_BY_SLUG = {c["slug"]: c for c in CAMPAIGNS}

# Sub-areas per campaign — Google Places searchText caps ~60 results per query,
# so we sweep the metro by neighborhood/suburb and dedupe to approach the target.
_CITY_AREAS = {
    "dental-boston": ["Boston, MA", "South Boston, MA", "Back Bay, Boston, MA", "Dorchester, MA",
                      "Brighton, MA", "Cambridge, MA", "Brookline, MA", "Somerville, MA"],
    "pi-lawyers-miami": ["Miami, FL", "Miami Beach, FL", "Coral Gables, FL", "Brickell, Miami, FL",
                         "Little Havana, Miami, FL", "Coconut Grove, FL", "Hialeah, FL", "Doral, FL"],
    "hvac-houston": ["Houston, TX", "Sugar Land, TX", "Katy, TX", "The Woodlands, TX",
                     "Pasadena, TX", "Pearland, TX", "Spring, TX", "Cypress, TX"],
    "roofing-phoenix": ["Phoenix, AZ", "Scottsdale, AZ", "Mesa, AZ", "Tempe, AZ",
                        "Chandler, AZ", "Glendale, AZ", "Gilbert, AZ", "Peoria, AZ"],
    "chiro-dallas": ["Dallas, TX", "Plano, TX", "Irving, TX", "Garland, TX",
                     "Richardson, TX", "Arlington, TX", "Frisco, TX", "Carrollton, TX"],
    "realestate-atlanta": ["Atlanta, GA", "Buckhead, Atlanta, GA", "Decatur, GA", "Marietta, GA",
                           "Sandy Springs, GA", "Alpharetta, GA", "Roswell, GA", "Midtown, Atlanta, GA"],
}


def _dedupe_key(lead: dict) -> str:
    return re.sub(r"[^a-z0-9]", "", (lead.get("name") or "").lower()) + re.sub(r"\D", "", lead.get("phone") or "")


def credential_status() -> dict:
    return {
        "google_places": bool(os.getenv("GOOGLE_PLACES_API_KEY", "").strip()),
        "hunter": bool(os.getenv("HUNTER_API_KEY", "").strip()),
        "instantly": bool(os.getenv("INSTANTLY_API_KEY", "").strip()),
        "smtp": bool(os.getenv("SMTP_HOST", "").strip()),
        "outbound_domain": bool(os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "").strip()),
    }


def _draft(niche: str, value_prop: str, name: str, domain: str) -> list[dict]:
    n = name or "there"
    return [
        {"day": 0, "subject": f"Quick idea to {value_prop} at {n}",
         "body": (f"Hi {n} team — I help {niche.lower()} {value_prop} without adding front-desk work. "
                  f"Worth a 10-minute look?\n\nUnsubscribe: https://{domain}/u")},
        {"day": 3, "subject": f"Re: {value_prop}",
         "body": (f"Following up — happy to show 2-3 things working for similar {niche.lower()} nearby.\n\n"
                  f"Unsubscribe: https://{domain}/u")},
        {"day": 7, "subject": "Last note",
         "body": (f"No worries if now isn't the time — I can send a quick free tip either way.\n\n"
                  f"Unsubscribe: https://{domain}/u")},
    ]


def _parse_place(p: dict) -> dict:
    return {
        "name": (p.get("displayName") or {}).get("text") or "",
        "address": p.get("formattedAddress") or "",
        "phone": p.get("nationalPhoneNumber") or "",
        "website": p.get("websiteUri") or "",
        "rating": p.get("rating") or 0,
        "review_count": p.get("userRatingCount") or 0,
        "category": (p.get("types") or [""])[0],
    }


def _places_text_search(query: str, key: str, want: int) -> list[dict]:
    """Google Places (New) searchText with pagination — returns ALL matching
    businesses (chains filtered by the caller), not just bad-website ones."""
    import requests
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": key,
               "X-Goog-FieldMask": ("places.displayName,places.formattedAddress,"
                                    "places.nationalPhoneNumber,places.websiteUri,places.rating,"
                                    "places.userRatingCount,places.types,nextPageToken")}
    out: list[dict] = []
    token = None
    for _ in range(5):
        body = {"textQuery": query}
        if token:
            body["pageToken"] = token
        r = requests.post(url, headers=headers, json=body, timeout=20)
        if r.status_code != 200:
            break
        d = r.json()
        out.extend(d.get("places", []))
        token = d.get("nextPageToken")
        if not token or len(out) >= want:
            break
        time.sleep(2)  # next_page token needs a moment to activate
    return out[:want]


def run_campaign(slug: str) -> dict:
    camp = _BY_SLUG.get(slug)
    if camp is None:
        return {"status": "unknown_campaign", "slug": slug}
    creds = credential_status()
    domain = os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "hello.wheellsverse.com").strip()

    # SCAN (live only with the Google key; dry-run flagged otherwise). Chains are
    # excluded by places_scanner's own blocklist + is_targetable filter.
    from core import places_scanner
    dry_scan = not creds["google_places"]
    if dry_scan:
        prospects = places_scanner.scan(location=camp["city"], categories=[camp["category"]],
                                        limit=camp["limit"], dry_run=True)
        leads = [{k: getattr(p, "__dict__", p).get(k) for k in
                  ("name", "category", "address", "phone", "website", "rating", "review_count")}
                 for p in prospects]
    else:
        # REAL: sweep the metro by sub-area (Places searchText caps ~60/query),
        # chains excluded, NO website-quality filter, deduped, stop at target.
        key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
        areas = _CITY_AREAS.get(camp["slug"]) or [camp["city"]]
        seen: set[str] = set()
        leads = []
        for area in areas:
            if len(leads) >= camp["limit"]:
                break
            for p in _places_text_search(f"{camp['niche']} in {area}", key, 60):
                L = _parse_place(p)
                if not L.get("name") or places_scanner._is_chain(L["name"]):
                    continue
                k = _dedupe_key(L)
                if k in seen:
                    continue
                seen.add(k)
                leads.append(L)
                if len(leads) >= camp["limit"]:
                    break

    # ENRICH (live only with Hunter; dry-run flagged otherwise).
    from core import email_enricher
    dry_enrich = not creds["hunter"]
    hkey = os.getenv("HUNTER_API_KEY", "").strip()
    for L in leads:
        if L.get("email") or not L.get("name"):
            continue
        hit = (email_enricher._dry_run_enrich(L) if dry_enrich
               else email_enricher._hunter_domain_lookup(L.get("website") or "", hkey))
        if hit and hit.get("email"):
            L["email"] = hit["email"]
            L["contact_name"] = hit.get("first_name", "")

    # DRAFT (templated — no LLM dependency).
    for L in leads:
        L["outreach"] = _draft(camp["niche"], camp["value_prop"], L.get("name"), domain)

    # CRM IMPORT CSV.
    buf = io.StringIO()
    cols = ["name", "email", "contact_name", "phone", "website", "address", "rating",
            "review_count", "niche", "city", "touch1_subject", "touch1_body"]
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for L in leads:
        t1 = (L.get("outreach") or [{}])[0]
        w.writerow({**L, "niche": camp["niche"], "city": camp["city"],
                    "touch1_subject": t1.get("subject", ""), "touch1_body": t1.get("body", "")})
    crm_csv = buf.getvalue()

    # Persist artifacts.
    base = paths.data_root() / "leadgen" / slug          # under the WMOS data root
    paths.save_json_atomic(base / "leads.json", leads)
    (base / "crm_import.csv").parent.mkdir(parents=True, exist_ok=True)
    (base / "crm_import.csv").write_text(crm_csv, encoding="utf-8")

    # REPORT.
    with_email = sum(1 for L in leads if L.get("email"))
    with_phone = sum(1 for L in leads if L.get("phone"))
    with_site = sum(1 for L in leads if L.get("website"))
    n = len(leads)
    report = {
        "campaign": camp["niche"] + " — " + camp["city"],
        "slug": slug,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "is_real": (not dry_scan and not dry_enrich),
        "dry_run_scan": dry_scan,
        "dry_run_enrich": dry_enrich,
        "total_leads_found": n,
        "target": camp["limit"],
        "data_quality": {
            "with_email": with_email, "with_email_pct": (round(with_email / n * 100) if n else 0),
            "with_phone": with_phone, "with_website": with_site,
        },
        "missing_information": {
            "no_email": n - with_email, "no_website": n - with_site,
        },
        "next_actions": _next_actions(creds, dry_scan, dry_enrich, n, camp["limit"]),
        "artifacts": {"leads": str(base / "leads.json"), "crm_csv": str(base / "crm_import.csv")},
        "credential_status": creds,
    }
    paths.save_json_atomic(base / "report.json", report)
    return report


def _next_actions(creds, dry_scan, dry_enrich, n, target) -> list[str]:
    acts = []
    if dry_scan:
        acts.append("Set GOOGLE_PLACES_API_KEY in Railway → re-run for REAL businesses (these are dry-run samples).")
    if dry_enrich:
        acts.append("Set HUNTER_API_KEY in Railway → real contact emails (these are dry-run guesses).")
    if not creds["instantly"] and not creds["smtp"]:
        acts.append("Set INSTANTLY_API_KEY (+ campaign) or SMTP creds → enable sending.")
    if not creds["outbound_domain"]:
        acts.append("Set SITEBOOST_OUTBOUND_DOMAIN to a sending subdomain (not the apex).")
    if not dry_scan and n < target:
        acts.append(f"Only {n}/{target} found — widen radius/categories or add nearby cities.")
    acts.append("Review the outreach drafts + value prop before any send (operator approval).")
    return acts


def list_campaigns() -> list[dict]:
    return [{k: c[k] for k in ("slug", "niche", "city", "limit")} for c in CAMPAIGNS]


def reenrich(slug: str) -> dict:
    """Re-run Hunter enrichment on ALREADY-scanned leads (no re-scan, no Places cost).
    For when Hunter quota refreshes/upgrades. Fills only leads still missing an email."""
    camp = _BY_SLUG.get(slug)
    if camp is None:
        return {"status": "unknown_campaign", "slug": slug}
    if not os.getenv("HUNTER_API_KEY", "").strip():
        return {"status": "blocked", "reason": "HUNTER_API_KEY not set", "slug": slug}
    import json as _json
    base = paths.data_root() / "leadgen" / slug
    lp = base / "leads.json"
    if not lp.exists():
        return {"status": "no_scan", "reason": "run the campaign first", "slug": slug}

    from core import email_enricher
    hkey = os.getenv("HUNTER_API_KEY", "").strip()
    leads = _json.loads(lp.read_text(encoding="utf-8"))
    before = sum(1 for L in leads if L.get("email"))
    for L in leads:
        if L.get("email") or not L.get("website"):
            continue
        hit = email_enricher._hunter_domain_lookup(L.get("website") or "", hkey)
        if hit and hit.get("email"):
            L["email"] = hit["email"]
            L["contact_name"] = hit.get("first_name", "")
    after = sum(1 for L in leads if L.get("email"))
    paths.save_json_atomic(lp, leads)
    return {"status": "reenriched", "slug": slug, "emails_before": before,
            "emails_after": after, "new_emails": after - before, "total": len(leads)}
