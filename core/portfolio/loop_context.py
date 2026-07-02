"""Per-business context for the W-MOS loop adapters.

The loop's adapters were n8n-hardcoded. This gives every adapter the real business
definition (registry) + the generated GTM kit (core/portfolio/gtm_kits/<slug>.md),
so each of the 10 businesses produces its own artifacts instead of stubs. Adapters
look up context by `action.business` (the slug); dispatch/tick stay unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.portfolio.registry import get_business

_KIT_DIR = Path(__file__).resolve().parent / "gtm_kits"


def kit_path(slug: str) -> Path:
    return _KIT_DIR / f"{slug}.md"


def kit_text(slug: str) -> str:
    p = kit_path(slug)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def kit_section(slug: str, keyword: str) -> str:
    """Return the GTM-kit markdown section whose heading contains `keyword`
    (case-insensitive), from that heading up to the next same-or-higher-level
    heading. Sub-headings are kept. Returns '' if not found."""
    text = kit_text(slug)
    if not text:
        return ""
    out: list[str] = []
    level: int | None = None
    for ln in text.splitlines():
        h = re.match(r"^(#{1,6})\s+(.*)", ln)
        if h:
            hl = len(h.group(1))
            if level is None:
                if keyword.lower() in h.group(2).lower():
                    level = hl
                    out.append(ln)
                continue
            # Sections are all level-2 (## 1..5). Stop only at the next SAME-level
            # heading; a higher-level heading (e.g. a `# H1` inside Landing Copy) is
            # content, not a boundary.
            if hl == level:
                break
            out.append(ln)
            continue
        if level is not None:
            out.append(ln)
    return "\n".join(out).strip()


def business_ctx(slug: str) -> dict:
    """Flat dict of the business's GTM definition + kit availability."""
    b = get_business(slug)
    if b is None:
        return {"slug": slug, "known": False, "has_kit": kit_path(slug).exists()}
    return {
        "slug": b.slug, "name": b.name, "known": True,
        "offer": b.offer, "price": b.price, "icp": b.icp,
        "lead_niche": b.lead_niche, "lead_geo": b.lead_geo,
        "landing_headline": b.landing_headline, "outreach_hook": b.outreach_hook,
        "build_step": b.build_step, "has_kit": kit_path(slug).exists(),
    }
