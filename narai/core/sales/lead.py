"""Lead scoring — rule-based with optional LLM enrichment.

Score = weighted sum of signals, clamped [0, 100]. Tier by score:
  80+: hot, 60-79: warm, 40-59: cool, <40: cold.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Optional


# Signals and weights — tune based on historical conversion data
_SCORING_RULES = {
    # Company size
    "company_size": {
        "1-10": 5, "11-50": 15, "51-200": 25, "201-1000": 20, "1000+": 10,
    },
    # Role seniority
    "role": {
        "founder": 30, "ceo": 30, "cto": 28, "vp": 22, "director": 18,
        "manager": 12, "senior": 10, "engineer": 8, "junior": 3, "intern": 0,
    },
    # Industry fit (customize per ICP)
    "industry": {
        "saas": 20, "ecommerce": 18, "agency": 15, "fintech": 18,
        "crypto": 15, "consulting": 12, "media": 10, "other": 5,
    },
    # Engagement signals
    "visited_pricing": 15,
    "opened_last_email": 8,
    "clicked_last_email": 12,
    "replied_cold": 20,
    "book_demo_clicked": 30,
    # Negative signals
    "unsubscribed": -50,
    "bounced_email": -25,
}


@dataclass
class Lead:
    email: str
    name: str = ""
    company: str = ""
    role: str = ""                     # normalize to lowercase keyword
    industry: str = ""                 # normalize
    company_size: str = ""             # bucket
    signals: dict[str, bool] = field(default_factory=dict)  # engagement flags

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_lead(lead: Lead) -> dict[str, Any]:
    """Return {score, tier, breakdown}."""
    breakdown: dict[str, int] = {}
    total = 0

    # Company size bucket
    size_pts = _SCORING_RULES["company_size"].get(lead.company_size, 0)
    if size_pts:
        breakdown["company_size"] = size_pts
        total += size_pts

    # Role
    role_lower = (lead.role or "").lower()
    for key, pts in _SCORING_RULES["role"].items():
        if key in role_lower:
            breakdown[f"role:{key}"] = pts
            total += pts
            break

    # Industry
    industry_lower = (lead.industry or "").lower()
    for key, pts in _SCORING_RULES["industry"].items():
        if key in industry_lower:
            breakdown[f"industry:{key}"] = pts
            total += pts
            break
    else:
        breakdown["industry:other"] = _SCORING_RULES["industry"]["other"]
        total += _SCORING_RULES["industry"]["other"]

    # Engagement flags
    for signal, enabled in lead.signals.items():
        if not enabled:
            continue
        pts = _SCORING_RULES.get(signal)
        if pts:
            breakdown[signal] = pts
            total += pts

    score = max(0, min(100, total))
    if score >= 80:
        tier = "hot"
    elif score >= 60:
        tier = "warm"
    elif score >= 40:
        tier = "cool"
    else:
        tier = "cold"

    return {
        "email": lead.email,
        "score": score,
        "tier": tier,
        "breakdown": breakdown,
    }


def rank_leads(leads: list[Lead]) -> list[dict[str, Any]]:
    """Score a batch and return sorted desc by score."""
    results = [score_lead(lead) for lead in leads]
    results.sort(key=lambda x: x["score"], reverse=True)
    return results
