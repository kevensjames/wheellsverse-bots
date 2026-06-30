"""Factory budget ceilings + spend ledger (monthly). Mirrors core.portfolio.budget
but on the factory data root. Append-only ledger, summed on read. Month is a
'YYYY-MM' string supplied by the caller (deterministic)."""
from __future__ import annotations

from dataclasses import dataclass

from factory import paths


@dataclass
class Ceilings:
    per_project_month: float
    portfolio_month: float


def _portfolio_file():
    return paths.data_root() / "portfolio.json"


def _spend_file():
    return paths.data_root() / "spend.jsonl"


def load_ceilings() -> Ceilings:
    cfg = paths.load_json(_portfolio_file(), {}) or {}
    c = cfg.get("ceilings", {})
    return Ceilings(
        per_project_month=float(c.get("per_project_month", 100.0)),
        portfolio_month=float(c.get("portfolio_month", 500.0)),
    )


def record_spend(slug: str, amount: float, kind: str, month: str) -> None:
    paths.append_jsonl(_spend_file(), {
        "slug": slug, "amount": float(amount), "kind": kind, "month": month,
    })


def spent(month: str, slug: str | None = None) -> float:
    total = 0.0
    for row in paths.read_jsonl(_spend_file()):
        if row.get("month") != month:
            continue
        if slug is not None and row.get("slug") != slug:
            continue
        total += float(row.get("amount", 0.0))
    return total


def would_exceed(slug: str, amount: float, month: str) -> bool:
    c = load_ceilings()
    if spent(month, slug) + amount > c.per_project_month:
        return True
    if spent(month) + amount > c.portfolio_month:
        return True
    return False
