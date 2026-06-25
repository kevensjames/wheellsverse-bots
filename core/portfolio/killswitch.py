"""Kill Switch — ROI triage across the portfolio. RECOMMEND-ONLY.

Computes each business's ROI from REAL data (spend from the budget ledger;
revenue is not yet attributable per-business because no W-MOS business is live —
that is stated honestly, not faked). Flags below-threshold spenders as
pause-candidates. It NEVER auto-pauses — the operator decides — consistent with
the rest of the safety floor.

Honest distinction: a business with spend AND no return is a pause-candidate; a
business with no spend and no revenue is merely DORMANT (nothing to kill), not
failing. This avoids the trap of "flag all ten zeros as failures".
"""
from __future__ import annotations

from core.portfolio import budget, registry


def _classify(spend: float, revenue: float, roi, threshold: float) -> str:
    if spend == 0 and revenue == 0:
        return "dormant"                       # never started; nothing to kill
    if roi is not None and roi < threshold:
        return "pause_candidate"               # burning with sub-threshold return
    return "ok"


def assess(month: str, *, threshold: float = 1.0) -> dict:
    """One ROI read across all businesses for the given 'YYYY-MM'."""
    rows = []
    for b in registry.list_businesses():
        spend = float(budget.spent(month, b.slug))
        revenue = 0.0  # no per-business revenue source wired (no business is live)
        roi = (revenue / spend) if spend > 0 else None
        rows.append({
            "slug": b.slug, "name": b.name,
            "spend": round(spend, 2), "revenue": round(revenue, 2),
            "roi": (round(roi, 3) if roi is not None else None),
            "status": _classify(spend, revenue, roi, threshold),
        })
    pause = [r["slug"] for r in rows if r["status"] == "pause_candidate"]
    dormant = [r["slug"] for r in rows if r["status"] == "dormant"]
    return {
        "month": month,
        "threshold": threshold,
        "businesses": rows,
        "pause_candidates": pause,
        "dormant": dormant,
        "auto_paused": [],   # always empty — recommend-only, operator decides
        "note": ("Recommend-only; nothing is auto-paused. Revenue is not yet "
                 "attributable per-business because no business is live — so this "
                 "currently triages spend, not return."),
    }
