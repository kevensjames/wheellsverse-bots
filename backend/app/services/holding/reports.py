"""Holding reports — Executive Overview, Company Portfolio, Morning Briefing.

Pure builders (no network, no send). Source-backed only: any datum still marked
REQUIRES_OPERATOR_CONFIRMATION is reported as needing confirmation, never invented.
Live health/monitor data is INJECTED by the caller (the Celery task) so these stay testable;
absent health data is disclosed as unverified, not guessed.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from app.services.holding import registry as reg
from app.services.holding.priorities import derive_priorities

_REVENUE_DISCLAIMER = "REQUIRES_OPERATOR_CONFIRMATION (no source-backed revenue connected)"


def executive_overview() -> dict:
    ents = reg.all_entities()
    return {
        "entities": [
            {"entity_id": e.entity_id, "brand": e.brand_name, "type": e.entity_type,
             "status": e.operational_status, "stage": e.stage, "confidence": e.confidence.value,
             "repository": e.repository, "deployment": e.deployment}
            for e in ents
        ],
        "counts": {
            "total": len(ents),
            "verified": sum(1 for e in ents if e.confidence.value == "VERIFIED"),
            "needs_confirmation_fields": len(reg.needs_confirmation()),
        },
        # financials are NOT summarized — none are source-backed
        "financials": "REQUIRES_OPERATOR_CONFIRMATION (no source-backed revenue/expense connected)",
        "requires_confirmation": reg.needs_confirmation(),
    }


def company_portfolio(entity_id: str) -> Optional[dict]:
    e = reg.get(entity_id)
    if e is None:
        return None
    d = e.as_dict()
    # replace confirm-markers with an explicit disclaimer object so the UI never shows a fake value
    for fld in ("revenue_metrics", "expense_metrics", "customers", "banking_provider_reference",
                "payment_provider_reference", "compliance_items", "ownership"):
        if d.get(fld) == "REQUIRES_OPERATOR_CONFIRMATION":
            d[fld] = {"value": None, "status": "REQUIRES_OPERATOR_CONFIRMATION"}
    return d


def _movement(cur: dict, prev: Optional[dict]) -> dict:
    """REAL day-over-day deltas from a stored prior snapshot. No history yet → honest baseline note."""
    if not prev:
        return {"status": "baseline captured — deltas available from the next daily briefing (no prior snapshot yet)"}
    flds = ("entities_total", "entities_verified", "open_incidents", "open_risks", "fields_awaiting_confirmation")
    d = {"since": prev.get("as_of", "")}
    for f in flds:
        try:
            d[f] = int(cur.get(f, 0)) - int(prev.get(f, 0))
        except Exception:
            pass
    return d


def _capability_kpi() -> str:
    """Live capability-fabric readiness (X/32 AVAILABLE) from the pure seed registry. Fail-open."""
    try:
        from app.services.capability.seed import seed_registry
        from app.services.capability.manifest import Availability
        reg_ = seed_registry()
        return f"{len(reg_.list(availability=Availability.AVAILABLE))}/{len(reg_)} AVAILABLE"
    except Exception:
        return "UNVERIFIED — capability fabric not readable"


def _recent_actions(limit: int = 5) -> list:
    """A short tail of KAI's governed actions (what KAI did lately), from the governance JSONL log.
    Read-only file read, never raises (returns [] if absent). Fail-open."""
    try:
        from app.services.governance import list_actions
        rows = list_actions(limit=limit) or []
        return [{"action": r.get("action") or r.get("type"), "at": r.get("at") or r.get("ts")} for r in rows][:limit]
    except Exception:
        return []


def build_morning_briefing(*, health: Optional[dict] = None, monitor: Optional[dict] = None,
                           signals: Optional[list] = None, prev_kpis: Optional[dict] = None,
                           entity_status: Optional[dict] = None, now_iso: str = "") -> dict:
    """Report-only. Reports source-backed status + explicitly what needs confirmation.
    Never fabricates KPI movement, revenue, or system health it wasn't given. `signals` are
    live self-observed probes (feed priorities); `prev_kpis` is the last stored snapshot (feed movement)."""
    ents = reg.all_entities()
    sys_health = health if health else {"status": "UNVERIFIED — no live health data supplied to this briefing"}
    monitor_state = monitor if monitor else {"status": "UNVERIFIED — no monitor snapshot supplied"}
    ok_probes = sum(1 for h in (health or {}).values() if isinstance(h, dict) and h.get("http") == 200)
    # Source-backed point-in-time KPI snapshot (real counts from live state — never invented):
    kpis = {
        "as_of": now_iso or "",
        "entities_total": len(ents),
        "entities_verified": sum(1 for e in ents if e.confidence.value == "VERIFIED"),
        "open_incidents": sum(len(getattr(e, "incidents", None) or []) for e in ents),
        "open_risks": sum(len(getattr(e, "risks", None) or []) for e in ents),
        "fields_awaiting_confirmation": len(reg.needs_confirmation()),
        "health": f"{ok_probes}/{len(health)} probes OK" if health else "UNVERIFIED — no live probe this briefing",
        "capabilities": _capability_kpi(),   # live X/32 AVAILABLE from the capability fabric
    }
    # Deterministic, source-cited ranked priorities (empty only if nothing is surfaced):
    priorities = derive_priorities(health=health, monitor=monitor, signals=signals)
    return {
        "generated_at": now_iso or "",
        "timezone": "America/New_York",
        "system_health": sys_health,
        "monitor": monitor_state,
        "portfolio_status": [
            {"brand": e.brand_name, "status": e.operational_status, "confidence": e.confidence.value}
            for e in ents
        ],
        # Live per-entity status overlay (source-backed, fetched this briefing) — self-updating deploy/
        # activity state (e.g. real Nexora subscriber/MRR numbers). Absent → disclosed, never guessed.
        "live_entity_status": entity_status if entity_status else {"note": "not collected this briefing"},
        "recent_actions": _recent_actions(),   # short tail of KAI's governed actions
        "kpis": kpis,
        # REAL movement when a prior snapshot exists; honest baseline note on the first run.
        "kpi_movement": _movement(kpis, prev_kpis),
        "todays_priorities": priorities if priorities else (
            "No priorities surfaced — no failing probes, logged risks/incidents, unverified entities, "
            "or pending confirmations."),
        "requires_confirmation": reg.needs_confirmation(),
        "delivery": "report generated in-app only — sending to any external recipient requires explicit approval",
    }


# ── §83 strategic / weekly review ──────────────────────────────────────────────────────────────────
# Each KPI's better direction — wins/losses are computed ONLY from these real deltas, never invented.
_KPI_GOOD_DIRECTION = {"entities_verified": "up", "open_incidents": "down", "open_risks": "down",
                       "fields_awaiting_confirmation": "down"}
_KPI_LABEL = {"entities_verified": "verified entities", "open_incidents": "open incidents",
              "open_risks": "open risks", "fields_awaiting_confirmation": "fields awaiting confirmation"}


def _parse_iso(t):
    """Full-fidelity ISO parse (tz kept, naive assumed UTC); None on failure. Local copy to avoid an
    import cycle (reports ← briefing ← reports)."""
    try:
        dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _current_kpis(now_iso: str = "") -> dict:
    """The same source-backed KPI fields build_morning_briefing snapshots — real counts, never invented."""
    ents = reg.all_entities()
    return {"as_of": now_iso or "", "entities_total": len(ents),
            "entities_verified": sum(1 for e in ents if e.confidence.value == "VERIFIED"),
            "open_incidents": sum(len(getattr(e, "incidents", None) or []) for e in ents),
            "open_risks": sum(len(getattr(e, "risks", None) or []) for e in ents),
            "fields_awaiting_confirmation": len(reg.needs_confirmation())}


def _weekly_period(prior: Optional[dict], now_iso: str) -> str:
    """BAKED-IN fix: derive the label from the ACTUAL baseline snapshot age — never hardcode 'trailing 7
    days' when history is shorter."""
    if not prior:
        return "baseline — no prior snapshot yet; wins/losses become available from the next weekly review"
    p_asof = prior.get("as_of") or ""
    p_dt, n_dt = _parse_iso(p_asof), _parse_iso(now_iso)
    if p_dt and n_dt:
        days = (n_dt - p_dt).total_seconds() / 86400.0
        return f"since {str(p_asof)[:10]} — {days:.1f} day(s) of actual history (real baseline age)"
    return f"since {str(p_asof)[:10]}" if p_asof else "prior snapshot age unknown"


def _wins_losses(cur: dict, prior: Optional[dict]) -> tuple[list, list]:
    """Wins/losses computed ONLY from real KPI deltas vs a stored prior snapshot. No prior → both empty
    with an honest baseline note handled by the caller. Every item cites the two snapshots."""
    wins, losses = [], []
    if not prior:
        return wins, losses
    src = f"kpi snapshots: {str(prior.get('as_of', ''))[:19]} → {str(cur.get('as_of', ''))[:19]}"
    for metric, good in _KPI_GOOD_DIRECTION.items():
        try:
            pv, cv = int(prior.get(metric, 0)), int(cur.get(metric, 0))
        except Exception:
            continue
        delta = cv - pv
        if delta == 0:
            continue
        improved = (good == "up" and delta > 0) or (good == "down" and delta < 0)
        row = {"metric": metric, "label": _KPI_LABEL.get(metric, metric), "from": pv, "to": cv,
               "delta": delta, "source": src}
        (wins if improved else losses).append(row)
    return wins, losses


def build_weekly_review(*, current_kpis: Optional[dict] = None, prior_kpis: Optional[dict] = None,
                        problems: Optional[list] = None, opportunities: Optional[list] = None,
                        goal_gaps: Optional[list] = None, now_iso: str = "") -> dict:
    """§83 report-only weekly review over kpi_history week-over-week + the existing source-backed builders.

    Sections: period · wins · losses · changes · health · revenue · risks · opportunities · tech_debt ·
    security · next_week. wins/losses come ONLY from REAL KPI deltas (honest baseline note when there is no
    prior week). revenue stays REQUIRES_OPERATOR_CONFIRMATION (never invented). risks/opportunities/tech-debt/
    security are all source-cited reads of existing engines; next_week is deterministic from owner-required
    problems + goal-gap/opportunity next-steps (never generic advice). All sources injectable + fail-open
    (§79 bounded, no LLM, no external send)."""
    cur = current_kpis if current_kpis is not None else _current_kpis(now_iso)
    prior = prior_kpis if prior_kpis is not None else _weekly_baseline()
    wins, losses = _wins_losses(cur, prior)

    probs = problems if problems is not None else _safe_problems()
    opps = opportunities if opportunities is not None else _safe_opportunities()
    gaps = goal_gaps if goal_gaps is not None else _safe_goal_gaps()

    def _cat(p, cats):
        c = p.get("category") if isinstance(p, dict) else getattr(p, "category", "")
        return c in cats

    tech_debt = [_problem_row(p) for p in probs if _cat(p, {"CODE_DEFECT", "DOCUMENTATION", "STALE_PLAN"})]
    security = [_problem_row(p) for p in probs if _cat(p, {"SECURITY"})]

    # risks: registry-cited (source-backed), never invented
    risks = [{"company": e.entity_id, "risk": rk, "source": f"registry:{e.entity_id}.risks"}
             for e in reg.all_entities() for rk in (getattr(e, "risks", None) or [])]

    # next_week: deterministic + cited — owner-required problem actions + open goal-gap/opportunity next steps
    next_week: list = []
    for p in probs:
        if (p.get("owner_required") if isinstance(p, dict) else getattr(p, "owner_required", False)):
            r = _problem_row(p)
            next_week.append({"item": r["observed_facts"], "company": r["company"],
                              "actions": r["recommended_actions"], "source": r["source"]})
    for g in gaps or []:
        d = g if isinstance(g, dict) else dict(g)
        if d.get("verdict") == "GAP":
            for a in (d.get("recommended_actions") or [])[:1]:
                next_week.append({"item": f"Close {d.get('metric')} gap on {d.get('company')}",
                                  "company": d.get("company"), "actions": [a.get("action")],
                                  "source": a.get("source", f"goal:{d.get('goal_id')}")})

    return {
        "generated_at": now_iso or "",
        "period": _weekly_period(prior, now_iso),
        "wins": wins or ("no measured wins this period" if prior else
                         "baseline captured — wins available from the next weekly review (no prior snapshot yet)"),
        "losses": losses or ("no measured regressions this period" if prior else
                             "baseline captured — losses available from the next weekly review (no prior snapshot yet)"),
        "changes": _movement(cur, prior),
        "health": {"open_incidents": cur.get("open_incidents"), "open_risks": cur.get("open_risks"),
                   "verified_entities": cur.get("entities_verified"), "total_entities": cur.get("entities_total"),
                   "note": "registry counts; live probes are run in the morning briefing, not this report"},
        "revenue": _REVENUE_DISCLAIMER,
        "risks": risks,
        "opportunities": [_opportunity_row(o) for o in opps],
        "tech_debt": tech_debt,
        "security": security,
        "next_week": next_week or "no source-backed items queued — nothing owner-required or goal-gapped surfaced",
        "delivery": "report generated in-app only — sending to any external recipient requires explicit approval",
    }


# ── §85 company deep dive (EXTENDS company_portfolio; never replaces it) ─────────────────────────────
def company_deep_dive(entity_id: str, *, signals: Optional[dict] = None, problems: Optional[list] = None,
                      opportunities: Optional[list] = None, proposals: Optional[list] = None,
                      goal_gaps: Optional[list] = None, now_iso: str = "") -> Optional[dict]:
    """§85 richer per-company view: the source-backed portfolio dict (money/customers still disclaimed by
    company_portfolio) FOLDED with live signals, health, deploy-truth, this company's problems, opportunities,
    open proposals, §82 goal-gap, and a real timeline. All sources injectable + fail-open. Unknown entity →
    None (fail-closed, same as company_portfolio). No fabrication — an absent source is disclosed, not guessed."""
    base = company_portfolio(entity_id)          # None if unknown; money/customers already disclaimed
    if base is None:
        return None

    sig = signals if signals is not None else _entity_signal(entity_id)
    detail = (sig.get("detail") if isinstance(sig, dict) else {}) or {}

    probs = problems if problems is not None else _safe_problems()
    my_probs = [_problem_row(p) for p in probs if _company_of(p) == entity_id]

    opps = opportunities if opportunities is not None else _safe_opportunities()
    my_opps = [_opportunity_row(o) for o in opps if _company_of(o) == entity_id]

    props = proposals if proposals is not None else _safe_proposals()
    my_props = [p for p in props if (p.get("entity") if isinstance(p, dict) else None) == entity_id]

    gaps = goal_gaps if goal_gaps is not None else _safe_goal_gaps(company=entity_id)
    my_gaps = [g for g in (gaps or []) if (g.get("company") if isinstance(g, dict) else None) == entity_id] \
        if goal_gaps is not None else (gaps or [])

    # real, timestamped timeline from this company's proposals (created/decided) — cited, newest-first
    timeline: list = []
    for p in my_props:
        if p.get("created_at"):
            timeline.append({"at": p["created_at"], "event": f"proposal created: {p.get('title')}",
                             "status": p.get("status"), "source": f"proposal:{p.get('id')}"})
        if p.get("decided_at"):
            timeline.append({"at": p["decided_at"], "event": f"proposal {p.get('status')}: {p.get('title')}",
                             "source": f"proposal:{p.get('id')}"})
    timeline.sort(key=lambda r: str(r["at"]), reverse=True)

    base.update({
        "generated_at": now_iso or "",
        "live_signals": sig,
        "health": {"reachable": (sig.get("ok") if isinstance(sig, dict) else None),
                   "http": (sig.get("http") if isinstance(sig, dict) else None),
                   "source": (sig.get("source") if isinstance(sig, dict) else None)},
        "deploy_truth": {"repository": base.get("repository"), "deployment": base.get("deployment"),
                         "live_git_sha": detail.get("git_sha"), "deploy_id": detail.get("deploy_id"),
                         "reachable": (sig.get("ok") if isinstance(sig, dict) else None),
                         "source": (sig.get("source") if isinstance(sig, dict) else "registry")},
        "problems": my_probs,
        "opportunities": my_opps,
        "proposals": my_props,
        "goal_gap": my_gaps,
        "timeline": timeline,
    })
    return base


# ── shared adapters + fail-open readers (each defaults to a real source; None-arg → live read) ────────
def _company_of(o) -> str:
    return (o.get("company") if isinstance(o, dict) else getattr(o, "company", "")) or ""


def _problem_row(p) -> dict:
    d = p.as_dict() if hasattr(p, "as_dict") else dict(p)
    return {"company": d.get("company"), "system": d.get("system"), "severity": d.get("severity"),
            "category": d.get("category"), "observed_facts": d.get("observed_facts"),
            "recommended_actions": d.get("recommended_actions") or [], "confidence": d.get("confidence"),
            "evidence": d.get("evidence") or [], "source": d.get("root_signature") or d.get("problem_id")}


def _opportunity_row(o) -> dict:
    d = o.as_dict() if hasattr(o, "as_dict") else dict(o)
    return {"title": d.get("title"), "company": d.get("company"), "category": d.get("category"),
            "why_now": d.get("why_now"), "expected_benefit": d.get("expected_benefit"),
            "confidence": d.get("confidence"), "recommended_next_step": d.get("recommended_next_step"),
            "evidence": d.get("evidence") or [], "source": d.get("signature")}


def _weekly_baseline() -> Optional[dict]:
    try:
        from app.services.holding import kpi_history
        return kpi_history.snapshot_before(days=7)
    except Exception:
        return None


def _safe_problems() -> list:
    try:
        from app.services.holding.holding_problems import detect_problems
        return detect_problems()
    except Exception:
        return []


def _safe_opportunities() -> list:
    try:
        from app.services.holding.opportunity_engine import detect_opportunities
        return detect_opportunities()
    except Exception:
        return []


def _safe_goal_gaps(company: Optional[str] = None) -> list:
    try:
        from app.services.holding.goal_registry import analyze_all
        return analyze_all(company=company, status="active")
    except Exception:
        return []


def _safe_proposals() -> list:
    try:
        from app.services.holding.proposals_store import list_proposals
        return list_proposals(limit=200)
    except Exception:
        return []


def _entity_signal(entity_id: str) -> dict:
    try:
        from app.services.holding.entity_status import collect_live_entity_status
        return collect_live_entity_status().get(entity_id, {"ok": None, "note": "no live probe for this entity"})
    except Exception:
        return {"ok": None, "note": "entity status unavailable"}
