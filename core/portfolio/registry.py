"""The ten W-MOS businesses, as data. The single source of truth for the portfolio."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Business:
    slug: str
    name: str
    thesis: str
    oss_repo: str
    phase: str = "planning"


BUSINESSES: list[Business] = [
    Business("n8n", "n8n Automation Agency",
             "Sell automation builds + recurring retainers on self-hosted n8n.",
             "https://github.com/n8n-io/n8n"),
    Business("coolify", "Coolify Hosting",
             "Managed deployments on self-hosted Coolify; replace devs' Vercel/Heroku bill.",
             "https://github.com/coollabsio/coolify"),
    Business("listmonk", "Listmonk Email",
             "Newsletter / mailing-list-as-a-service resold to agencies at markup.",
             "https://github.com/knadh/listmonk"),
    Business("ghost", "Ghost Publishing",
             "Run paid publications/newsletters on self-hosted Ghost.",
             "https://github.com/TryGhost/Ghost"),
    Business("calcom", "Cal.com Scheduling",
             "White-labeled scheduling SaaS for dentists, lawyers, consultants.",
             "https://github.com/calcom/cal.com"),
    Business("plausible", "Plausible Analytics",
             "Privacy-first analytics resold per-client to agencies.",
             "https://github.com/plausible/analytics"),
    Business("supabase", "Supabase SaaS Factory",
             "Ship micro-SaaS products fast on Supabase; subscription revenue.",
             "https://github.com/supabase/supabase"),
    Business("medusa", "Medusa Commerce",
             "Commerce platform taking a fee per sale on self-hosted Medusa.",
             "https://github.com/medusajs/medusa"),
    Business("appflowy", "AppFlowy Enterprise",
             "Self-hosted Notion alternative sold to privacy-sensitive enterprises.",
             "https://github.com/AppFlowy-IO/AppFlowy"),
    Business("penpot", "Penpot Design",
             "Self-hosted Figma alternative sold to agencies refusing cloud uploads.",
             "https://github.com/penpot/penpot"),
]


def list_businesses() -> list[Business]:
    return list(BUSINESSES)


def get_business(slug: str) -> Business | None:
    for b in BUSINESSES:
        if b.slug == slug:
            return b
    return None
