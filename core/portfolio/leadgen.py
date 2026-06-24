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
    prospects = places_scanner.scan(location=camp["city"], categories=[camp["category"]],
                                    limit=camp["limit"], dry_run=dry_scan)
    leads = []
    for p in prospects:
        d = getattr(p, "__dict__", p)
        leads.append({k: d.get(k) for k in
                      ("name", "category", "address", "phone", "website", "rating", "review_count")})

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
