"""The ten W-MOS businesses, as data. The single source of truth for the portfolio.

Each is a productized SERVICE around an open-source tool (setup + managed retainer)
sold to a specific, cold-prospectable niche — NOT a multi-tenant SaaS we operate.
Go-to-market definitions generated 2026-06-26 (one strategist per business)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Business:
    slug: str
    name: str
    thesis: str
    oss_repo: str
    offer: str = ""
    price: str = ""
    icp: str = ""
    lead_niche: str = ""
    lead_geo: str = ""
    landing_headline: str = ""
    outreach_hook: str = ""
    build_step: str = ""          # the business-specific pipeline verb
    phase: str = "defined"


BUSINESSES: list[Business] = [
    Business(
        slug="n8n", name="n8n Automation Agency",
        thesis="Sell automation builds + recurring retainers on self-hosted n8n.",
        oss_repo="https://github.com/n8n-io/n8n",
        offer="Done-for-you 'Lead-to-Booking Engine' on self-hosted n8n: speed-to-lead instant "
              "SMS/email reply, missed-call text-back, no-show recovery, 5-star review requests, "
              "wired into the med spa's booking system + Twilio. Setup build + managed retainer.",
        price="$1,500 setup + $400/mo managed",
        icp="Owner-operator of a 1-3 location medical spa doing $40k-150k/mo, non-technical, "
            "paying for a booking/CRM tool but leaking leads from slow response times.",
        lead_niche="medical spas", lead_geo="Scottsdale, Arizona",
        landing_headline="Stop Losing Botox Bookings to Slow Replies — Every Lead Texted Back in 60 Seconds",
        outreach_hook="I filled out your med spa's contact form Tuesday at 2pm and never heard back — "
                      "I built a 60-second auto-reply flow that books those leads before they ghost.",
        build_step="build_workflow_pack"),
    Business(
        slug="coolify", name="Coolify Hosting",
        thesis="Managed deployments on self-hosted Coolify; replace devs' Vercel/Heroku bill.",
        oss_repo="https://github.com/coollabsio/coolify",
        offer="Done-for-you Coolify migration + managed hosting: provision Coolify on a VPS, migrate "
              "apps off Vercel/Heroku/Render, wire CI/CD, SSL, backups, monitoring; manage on retainer.",
        price="$897 setup + $297/mo managed (client pays own ~$20-40/mo VPS)",
        icp="Bootstrapped founders and 2-10 person dev shops running 3-15 small web apps whose "
            "PaaS bill crept past $200-500/mo, with no DevOps appetite to self-host.",
        lead_niche="web design and development agencies", lead_geo="Austin, Texas",
        landing_headline="Cut Your Vercel and Heroku Bill by 70% — Without Touching a Terminal",
        outreach_hook="Most shops your size quietly overpay Vercel/Heroku $300+/mo for hosting you "
                      "could run for $40 on your own server; I set that up and manage it for you.",
        build_step="build_migration_blueprint"),
    Business(
        slug="listmonk", name="Listmonk Email",
        thesis="Newsletter / mailing-list-as-a-service resold to agencies at markup.",
        oss_repo="https://github.com/knadh/listmonk",
        offer="Done-for-you managed newsletter platform: deploy a private branded Listmonk on your "
              "domain (DKIM/SPF/DMARC + Amazon SES), migrate your list, 3 templates; flat-fee "
              "Mailchimp replacement that doesn't get pricier as the list grows.",
        price="$750 setup + $200/mo managed (SES passthrough ~$20/mo)",
        icp="Owner-operated businesses with a 5k-50k contact list and a newsletter habit, paying "
            "$150-500/mo to Mailchimp/Constant Contact, no in-house developer.",
        lead_niche="independent bookstores", lead_geo="Portland, Oregon",
        landing_headline="Stop paying Mailchimp more every time your list grows. Own your newsletter.",
        outreach_hook="Is Mailchimp's bill creeping up as your list grows? I move shops onto a private, "
                      "owned platform for a flat monthly fee that never scales with list size.",
        build_step="build_listmonk_pack"),
    Business(
        slug="ghost", name="Ghost Publishing",
        thesis="Run paid publications/newsletters on self-hosted Ghost.",
        oss_repo="https://github.com/TryGhost/Ghost",
        offer="Done-for-you 'Client Insider' newsletter on self-hosted Ghost: branded theme, "
              "Stripe paid/free tiers, member signup, Mailgun deliverability, contact import; "
              "managed on retainer (hosting, backups, monthly formatting/scheduling, reporting).",
        price="$1,500 setup + $450/mo managed",
        icp="Solo or 2-8 advisor independent RIA / wealth firms that email clients market commentary, "
            "own their domain, want a branded owned list — but have zero technical staff.",
        lead_niche="financial advisors / wealth management firms", lead_geo="Charlotte, North Carolina",
        landing_headline="Your own branded client newsletter — owned, paid-tier ready, fully managed.",
        outreach_hook="Want your client market updates going out from your own branded newsletter "
                      "(with a paid-tier option) instead of Mailchimp, fully managed?",
        build_step="build_publication_pack"),
    Business(
        slug="calcom", name="Cal.com Scheduling",
        thesis="White-labeled scheduling SaaS for dentists, lawyers, consultants.",
        oss_repo="https://github.com/calcom/cal.com",
        offer="Done-for-you white-labeled booking: a self-hosted Cal.com on your subdomain, fully "
              "branded, with providers/services/round-robin, Google/Outlook 2-way sync, SMS reminders, "
              "and Stripe deposit-on-booking to kill no-shows; managed plan included.",
        price="$897 setup + $197/mo managed (hosting included)",
        icp="Owner/manager of 1-3 location med spas (10-30 staff) paying $200-500/mo for per-seat "
            "tools like Vagaro/Mindbody/Calendly, wanting own-brand booking + deposit collection.",
        lead_niche="med spas", lead_geo="Scottsdale, Arizona",
        landing_headline="Your Own Branded Booking System — No More Calendly Logo, No More No-Shows",
        outreach_hook="I build med spas a fully branded booking page on your own domain with deposit "
                      "collection that's cut no-shows ~30%, for less than you pay per seat now.",
        build_step="build_booking_pack"),
    Business(
        slug="plausible", name="Plausible Analytics",
        thesis="Privacy-first analytics resold per-client to agencies.",
        oss_repo="https://github.com/plausible/analytics",
        offer="Done-for-you privacy-safe analytics: deploy managed self-hosted Plausible, replace "
              "GA/tracking pixels with cookieless GDPR/HIPAA-friendly tracking, set up goal/form/call "
              "conversion tracking, deliver a branded monthly 'where your patients come from' report.",
        price="$600 setup + $150/mo managed",
        icp="Owner/office manager of a 1-4 dentist practice running a website + paid ads/SEO, "
            "privacy-conscious about patient data, no in-house analytics person.",
        lead_niche="dental practices", lead_geo="Austin, Texas",
        landing_headline="See where your new patients come from — without the privacy lawsuits GA invites.",
        outreach_hook="The tracking pixel on your practice site is the kind now driving HIPAA-pixel "
                      "lawsuits against clinics. I set practices up with cookieless analytics instead.",
        build_step="build_privacy_analytics_pack"),
    Business(
        slug="supabase", name="Supabase SaaS Factory",
        thesis="Ship micro-SaaS products fast on Supabase; subscription revenue.",
        oss_repo="https://github.com/supabase/supabase",
        offer="Done-for-you white-label tenant & owner portal on Supabase: branded auth, online "
              "maintenance-request intake with realtime status, document/lease storage, owner-reporting "
              "view; we set up, migrate from spreadsheets, and run it managed.",
        price="$1,500 setup + $300/mo managed",
        icp="Owner-operators of independent residential property-management firms (80-600 units) "
            "running tenant comms/maintenance/owner-reporting via spreadsheets, no developer.",
        lead_niche="property management companies", lead_geo="Phoenix, Arizona",
        landing_headline="Give Your Tenants and Owners a Branded Portal — Without Hiring a Developer",
        outreach_hook="I build branded tenant/owner portals for PM firms your size that cut the "
                      "email/phone back-and-forth, and I can show you a live demo with your logo on it.",
        build_step="build_portal_pack"),
    Business(
        slug="medusa", name="Medusa Commerce",
        thesis="Commerce platform taking a fee per sale on self-hosted Medusa.",
        oss_repo="https://github.com/medusajs/medusa",
        offer="Done-for-you Medusa storefront on a self-hosted instance we run: catalog import, "
              "B2B/wholesale tiered pricing, custom checkout, Stripe wiring; monthly managed plan.",
        price="$3,500 setup + $450/mo managed",
        icp="Owner-operators of specialty/B2B product brands (10-150 SKUs, $50k-$1M/yr online) who "
            "outgrew Shopify's fees and rigid B2B features but lack an in-house developer.",
        lead_niche="specialty coffee roasters with retail/wholesale", lead_geo="Portland, Oregon",
        landing_headline="Own Your Store. Stop Renting It From Shopify.",
        outreach_hook="Most roasters your size overpay ~$400/mo in Shopify fees and apps for B2B "
                      "pricing you could own outright on open-source Medusa.",
        build_step="build_medusa_demo_pack"),
    Business(
        slug="appflowy", name="AppFlowy Enterprise",
        thesis="Self-hosted Notion alternative sold to privacy-sensitive enterprises.",
        oss_repo="https://github.com/AppFlowy-IO/AppFlowy",
        offer="Done-for-you private AppFlowy workspace: deploy single-tenant self-hosted AppFlowy "
              "Cloud on the firm's VM, migrate notes/wikis/SOPs, role-based access + encrypted "
              "nightly backups, FTC Safeguards Rule control mapping; managed retainer.",
        price="$2,500 setup + $400/mo managed (firm pays own ~$40/mo VM)",
        icp="Managing partner/IT admin at a 5-40 person CPA/tax/bookkeeping firm handling client "
            "SSNs/financials under the FTC Safeguards Rule, running SOPs in Notion/Google Docs.",
        lead_niche="accounting firms", lead_geo="Charlotte, North Carolina",
        landing_headline="Your firm's knowledge base, self-hosted and private — Notion power, your servers.",
        outreach_hook="Since the FTC Safeguards Rule, most CPA firms are uneasy their SOPs and client "
                      "notes live on a SaaS cloud they don't control — I set up a private self-hosted alternative.",
        build_step="build_compliance_deploy_blueprint"),
    Business(
        slug="penpot", name="Penpot Design",
        thesis="Self-hosted Figma alternative sold to agencies refusing cloud uploads.",
        oss_repo="https://github.com/penpot/penpot",
        offer="Done-for-you self-hosted Penpot on the agency's own server/VPC: hardened Docker "
              "Compose + HTTPS proxy + encrypted backups + SSO/team setup + a data-ownership one-pager; "
              "managed retainer (upgrades, backup monitoring, uptime, support SLA).",
        price="$1,500 setup + $300/mo managed",
        icp="Owner/ops-IT lead at a 5-30 person branding/design agency serving regulated or NDA-bound "
            "clients (gov, defense, healthcare, finance) that won't upload design files to Figma's cloud.",
        lead_niche="branding and design agencies", lead_geo="Washington, District of Columbia",
        landing_headline="Your client design files never leave your servers. Self-hosted Figma, managed.",
        outreach_hook="Do your regulated clients' NDAs make uploading design files to Figma's cloud a "
                      "problem? I stand up a private self-hosted Figma alternative on your own server.",
        build_step="build_penpot_deployment_pack"),
]


def list_businesses() -> list[Business]:
    return list(BUSINESSES)


def get_business(slug: str) -> Business | None:
    for b in BUSINESSES:
        if b.slug == slug:
            return b
    return None
