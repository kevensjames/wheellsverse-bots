"""Honest portfolio scoreboard — real numbers from connected surfaces only.

Design principle (anti-theater): a surface that cannot be measured is reported
as `connected: False` with `value: None`, NEVER as a fake `0`. A real `0` (e.g.
Stripe configured but no sales) is distinct from "not measured". This is the
accountability mirror for the Wheellsverse portfolio — it tells the truth even
when the truth is that nothing has shipped.

Metrics: revenue (last 30 days + all time), MRR, users, trials,
places_scanned, leads, emails_sent, conversion, churn, open_bugs,
deployments — each tagged {value, connected, source, note, label}.

  * Revenue comes from the daily numbers board's ledger (core/board/money.py),
    by New York day, net of refunds and disputes: Stripe and manual entries,
    no live Stripe call. It is connected only when the database answers and
    Stripe is measured over the whole window.
  * MRR and users (active subscriptions) are read live from Stripe, the one
    live call here. Trials and churn are not read yet.
  * places_scanned is SiteBoost's outreach counter, kept on the server disk:
    a deploy resets it. `leads` is the same counter and `conversion` is users
    / leads, under the keys the Command Center reads
    (frontend/admin/command-center.html); conversion is connected only when
    both are and the counter is not 0.
  * Surfaces: Stripe, Kit, Instantly and Meta are connected when their
    sources row is enabled with a completed sync and their connector is
    configured here; SiteBoost when its counters can be read.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

BOARD_SOURCES = ("stripe", "kit", "instantly", "meta_ads")


def _metric(value: Any, connected: bool, source: str, note: str = "", label: Optional[str] = None) -> dict:
    return {"value": (value if connected else None), "connected": connected,
            "source": source, "note": note, "label": label}


def _revenue_block() -> dict:
    """The revenue cards from the ledger (core.board.money.revenue_cards)."""
    try:
        from core.board import money
        return money.revenue_cards()
    except Exception as e:  # pragma: no cover - defensive
        log.warning("scoreboard: revenue not read (%s)", type(e).__name__)
        return {"month": None, "all_time": None, "month_note": "not measured", "all_time_note": "not measured"}


def _stripe_block() -> dict:
    """MRR and active subscriptions, read live from Stripe."""
    try:
        from core.revenue import RevenueEngine
        return RevenueEngine.get().live_mrr()
    except Exception as e:  # pragma: no cover - defensive
        log.warning("scoreboard: Stripe MRR not read (%s)", type(e).__name__)
        return {"configured": False, "mrr": None, "active_subscriptions": None}


def _places_block() -> dict:
    """SiteBoost lead/outreach counters (file-backed, always readable)."""
    try:
        from core.siteboost_state import stats
        s = stats() or {}
        return {"connected": True,
                "places_scanned": int(s.get("places_scanned", 0)),
                "emails_sent": int(s.get("emails_sent", 0))}
    except Exception as e:  # pragma: no cover - defensive
        return {"connected": False, "error": type(e).__name__}


def _board_surfaces() -> dict:
    """{source: connected} for the board's sources: enabled, a completed sync
    (measured_from), and the connector configured on this server."""
    try:
        from core.board import day as board_day
        from core.board import ledger
        rows = {r.get("id"): r for r in ledger.sources_rows()}
    except Exception as e:  # noqa: BLE001 — the database not connected: nothing is connected
        log.warning("scoreboard: sources not read (%s)", type(e).__name__)
        return dict.fromkeys(BOARD_SOURCES, False)
    return {sid: bool(rows.get(sid) and rows[sid].get("enabled") and rows[sid].get("measured_from")
                      and board_day.read_problem(sid) is None)
            for sid in BOARD_SOURCES}


def _money(value: Optional[float]) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _conversion(users, leads, both_connected: bool):
    """users / leads, rounded to 4 places: (value, connected). Not measured
    (None, False) unless both are measured and leads is not 0."""
    if not both_connected or users is None or not leads:
        return None, False
    return round(users / leads, 4), True


def snapshot() -> dict:
    """One honest read of every metric across connected surfaces."""
    rev = _revenue_block()
    live = _stripe_block()
    places = _places_block()
    pc = bool(places.get("connected"))
    mrr_ok = bool(live.get("configured")) and live.get("mrr") is not None
    users_ok = bool(live.get("configured")) and live.get("active_subscriptions") is not None
    live_note = "" if live.get("configured") else live.get("note") or "Stripe key not set"
    if live.get("error"):
        live_note = f"Stripe not read: {live['error']}"
    conv_val, conv_conn = _conversion(live.get("active_subscriptions"), places.get("places_scanned"),
                                      users_ok and pc)

    metrics = {
        "revenue_month": _metric(rev.get("month"), rev.get("month") is not None, "ledger: stripe + manual",
                                 rev.get("month_note", ""), "revenue, last 30 days"),
        "revenue_all_time": _metric(rev.get("all_time"), rev.get("all_time") is not None, "ledger: stripe + manual",
                                    rev.get("all_time_note", ""), "revenue, all time"),
        "mrr": _metric(live.get("mrr"), mrr_ok, "stripe (live)", "" if mrr_ok else live_note, "MRR"),
        "users": _metric(live.get("active_subscriptions"), users_ok, "stripe (active subscriptions)",
                         "" if users_ok else live_note, "users"),
        "trials": _metric(None, False, "stripe (trialing subscriptions)", "not read yet", "trials"),
        "places_scanned": _metric(places.get("places_scanned"), pc, "siteboost",
                                  "counted on the server disk; a deploy resets it", "places scanned (outreach)"),
        # the Command Center's keys (frontend/admin/command-center.html): leads is the places-scanned counter
        "leads": _metric(places.get("places_scanned"), pc, "siteboost",
                         "the places-scanned counter; a deploy resets it", "leads"),
        "emails_sent": _metric(places.get("emails_sent"), pc, "siteboost", "", "emails sent"),
        "conversion": _metric(conv_val, conv_conn, "derived: users / leads", "", "conversion"),
        "churn": _metric(None, False, "stripe (canceled 30d)", "not read yet", "churn"),
        "open_bugs": _metric(None, False, "manual / gh issues (not wired)", "", "open bugs"),
        # honest: no deploy-count source is wired, so report unmeasured (not a fake 0).
        # Matches this module's stated principle and open_bugs above.
        "deployments": _metric(None, False, "no deploy-count source wired",
                               note="deploy count is not wired to a real source", label="deployments"),
    }

    # Surface connectivity — what we can and cannot see, named plainly.
    surfaces = {
        **_board_surfaces(),
        "siteboost": pc,
        "ds24": False,          # no client code in repo
        "stan": False,          # web-login only, no sales API
        "bigcommerce": False,   # config template only, no client
    }

    # Headline truth — the one line a founder reads first.
    headline = (
        f"MRR {_money(metrics['mrr']['value'])} · "
        f"users {metrics['users']['value'] if users_ok else '—'} · "
        f"places scanned {metrics['places_scanned']['value'] if pc else '—'} · "
        f"{metrics['deployments']['value'] if metrics['deployments']['connected'] else '—'} prod deployments"
    )

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "headline": headline,
        "metrics": metrics,
        "surfaces": surfaces,
        "connected_count": sum(1 for v in surfaces.values() if v),
        "total_surfaces": len(surfaces),
    }
