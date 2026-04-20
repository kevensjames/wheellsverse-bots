"""KDP royalty projection — compute expected royalties given price, format, trim.

US marketplace rules (simplified):
  eBook 70% tier: price $2.99-$9.99 → 70% - delivery_fee (file_size_MB * $0.15)
  eBook 35% tier: price <$2.99 or >$9.99 → 35%, no delivery fee
  Paperback: royalty = (price * 0.60) - print_cost
    print_cost (B&W, 6x9) = $0.85 fixed + $0.012/page
  Hardcover: royalty = (price * 0.60) - print_cost
    print_cost = $6.80 + $0.012/page (color cover)
"""
from __future__ import annotations

from typing import Any


def _print_cost_paperback(pages: int) -> float:
    return 0.85 + 0.012 * pages


def _print_cost_hardcover(pages: int) -> float:
    return 6.80 + 0.012 * pages


def project_royalties(
    price: float,
    format: str = "ebook",
    pages: int = 200,
    file_size_mb: float = 2.0,
    monthly_units: int = 10,
) -> dict[str, Any]:
    """Return per-unit royalty + monthly/annual projection."""
    fmt = format.lower()

    if fmt == "ebook":
        if 2.99 <= price <= 9.99:
            royalty_rate = 0.70
            delivery_fee = file_size_mb * 0.15
            per_unit = round(price * royalty_rate - delivery_fee, 2)
            tier = "70%"
        else:
            royalty_rate = 0.35
            per_unit = round(price * royalty_rate, 2)
            delivery_fee = 0.0
            tier = "35%"
        print_cost = 0.0
    elif fmt == "paperback":
        royalty_rate = 0.60
        print_cost = _print_cost_paperback(pages)
        per_unit = round(price * royalty_rate - print_cost, 2)
        delivery_fee = 0.0
        tier = "paperback"
    elif fmt == "hardcover":
        royalty_rate = 0.60
        print_cost = _print_cost_hardcover(pages)
        per_unit = round(price * royalty_rate - print_cost, 2)
        delivery_fee = 0.0
        tier = "hardcover"
    else:
        raise ValueError(f"Unknown format '{format}'. Use ebook|paperback|hardcover")

    per_unit = max(0.0, per_unit)
    monthly = round(per_unit * monthly_units, 2)
    annual = round(monthly * 12, 2)

    return {
        "price": price,
        "format": fmt,
        "tier": tier,
        "royalty_rate": royalty_rate,
        "delivery_fee": round(delivery_fee, 2),
        "print_cost": round(print_cost, 2),
        "per_unit_royalty": per_unit,
        "monthly_units": monthly_units,
        "monthly_projection": monthly,
        "annual_projection": annual,
    }
