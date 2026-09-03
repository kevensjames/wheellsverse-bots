"""Deterministic priority engine — and THE single §22 prioritization ladder for the holding OS.

Ranks REAL, source-backed signals into today's priorities — it NEVER invents work.
Every priority cites its source (a live probe, an injected monitor snapshot, or an exact
registry field). No LLM, no guessing: priorities are a pure function of current state, so the
briefing is reproducible and auditable. Empty list when there is genuinely nothing to surface.

§22 SINGLE RANKER — the ordered ladder below is the ONE ranking authority. `rank_key` is the one
sort key; `briefing._oa_key`/`today_for_you` and `proposals.build_daily_plan` sort through it
instead of keeping their own severity→ordinal maps. Each priority is placed on a ladder rung
(from its source) and, within a rung, refined by severity — so every stream orders consistently.
"""
from __future__ import annotations
from typing import Optional
from app.services.holding import registry as reg

# §22 ladder, most-urgent → least (rung index = ladder position). THE single ordered ranking.
LADDER = (
    "safety_security",          # 1  safety / security
    "broken_prod",              # 2  broken production
    "customer_impact",          # 3  customer impact
    "incomplete_safe_deploy",   # 4  incomplete but safe deploy
    "financial_loss",           # 5  financial loss
    "operator_blocker",         # 6  operator blocker
    "high_confidence_revenue",  # 7  high-confidence revenue
    "roadmap",                  # 8  roadmap
    "reliability",              # 9  reliability
    "self_improvement",         # 10 bounded self-improvement
    "speculative",              # 11 speculative
)
_RUNG = {name: i for i, name in enumerate(LADDER)}

CRITICAL, HIGH, MEDIUM, LOW = 0, 1, 2, 3
_SEV = {CRITICAL: "CRITICAL", HIGH: "HIGH", MEDIUM: "MEDIUM", LOW: "LOW"}
_SEVRANK = {"CRITICAL": CRITICAL, "HIGH": HIGH, "MEDIUM": MEDIUM, "LOW": LOW, "INFO": LOW, "OK": LOW}
# Fallback for items carrying only a severity (owner actions, proposals) and no explicit ladder rung —
# each severity band maps to the ladder rung it belongs to, so the ONE rank_key orders every stream.
_SEVERITY_RUNG = {"CRITICAL": "broken_prod", "HIGH": "reliability", "MEDIUM": "reliability",
                  "LOW": "speculative", "INFO": "speculative", "OK": "speculative"}


def rank_key(item: dict) -> tuple:
    """THE §22 sort key (lower = more urgent): (ladder rung, severity, explicit priority int).
    An item may name its ladder rung via ``rung`` (a LADDER name); otherwise the rung is derived
    from its ``severity``. Deterministic — the one ranker priorities/briefing/proposals all use."""
    # A genuinely severity-less item is lowest-urgency (sorts LAST), not mid — matches the old
    # proposals/briefing maps that put ''-severity at the bottom (§22 consolidation regression fix).
    sev = item.get("severity") or item.get("priority_name") or "LOW"
    rung = item.get("rung")
    if rung not in _RUNG:
        rung = _SEVERITY_RUNG.get(sev, "reliability")
    pr = item.get("priority")
    return (_RUNG[rung], _SEVRANK.get(sev, MEDIUM), pr if isinstance(pr, int) else 2)


def derive_priorities(*, health: Optional[dict] = None, monitor: Optional[dict] = None,
                      signals: Optional[list] = None) -> list[dict]:
    """Return today's ranked priorities, each with a cited source + §22 ladder rung. Deterministic."""
    items: list[dict] = []

    def add(rung, sev, title, source, entity=None, detail=None):
        body = {"severity": _SEV[sev], "rung": rung, "title": title, "source": source}
        if entity: body["entity"] = entity
        if detail: body["detail"] = detail
        items.append(body)

    # 1a. live self-observed signals (each at its OWN severity) — source: live public probe.
    #     When signals are supplied they SUBSUME the simple health-arg check (no double-count).
    if signals:
        for s in signals:
            if not s.get("ok", True):
                add("broken_prod", _SEVRANK.get(s.get("severity", "HIGH"), HIGH),
                    f"live signal {s.get('name')}: {s.get('detail', '')}".rstrip(),
                    f"live-signal:{s.get('name')}")
    # 1b. fallback: the simple 2-probe health arg (only when richer signals weren't collected)
    elif health:
        for name, h in health.items():
            code = h.get("http") if isinstance(h, dict) else None
            if code != 200:
                add("broken_prod", CRITICAL, f"{name} health probe not OK (HTTP {code})", "live health probe",
                    entity="kai" if name.startswith("app") else name)

    # 2. injected monitor active alerts (CRITICAL) — only if a real snapshot was supplied
    if isinstance(monitor, dict):
        alerts = monitor.get("active_alerts") or monitor.get("alerts") or []
        if alerts:
            add("broken_prod", CRITICAL, f"prod observability monitor: {len(alerts)} active alert(s)",
                "observability monitor snapshot", detail=alerts[:8])

    # 3. registry incidents (CRITICAL, broken-prod) + risks (HIGH, reliability) — source-backed per entity
    for e in reg.all_entities():
        for inc in (getattr(e, "incidents", None) or []):
            add("broken_prod", CRITICAL, f"{e.brand_name}: incident — {inc}", f"registry:{e.entity_id}.incidents", entity=e.entity_id)
        for rk in (getattr(e, "risks", None) or []):
            add("reliability", HIGH, f"{e.brand_name}: risk — {rk}", f"registry:{e.entity_id}.risks", entity=e.entity_id)

    # 4. entities needing re-verification (MEDIUM, reliability) — confidence UNKNOWN/UNVERIFIED
    for e in reg.all_entities():
        if e.confidence.value in ("UNKNOWN", "UNVERIFIED"):
            add("reliability", MEDIUM, f"Re-verify {e.brand_name} (confidence {e.confidence.value})",
                f"registry:{e.entity_id}.confidence", entity=e.entity_id)

    # 5. operator data still awaiting confirmation (LOW, speculative) — one grouped item, never fabricated
    nc = reg.needs_confirmation()
    if nc:
        add("speculative", LOW, f"Confirm {len(nc)} operator data field(s) across the portfolio",
            "registry.needs_confirmation()", detail=nc[:12])

    items.sort(key=rank_key)                            # THE §22 ladder; stable within a rung (insertion order)
    return [dict(rank=i + 1, **body) for i, body in enumerate(items)]


def demo() -> None:
    """Self-check: priorities are ranked by the ONE §22 ladder, cited, and derived only from real state."""
    # health failure ranks CRITICAL (broken-prod) and cites the probe
    ps = derive_priorities(health={"app_a": {"http": 0}}, monitor={"alerts": ["disk 92%"]})
    assert ps[0]["severity"] == "CRITICAL" and ps[0]["rank"] == 1, ps[:1]
    assert all("source" in p and "rung" in p for p in ps), "every priority cites a source + names a ladder rung"
    # output is ordered by the §22 ladder (broken-prod → reliability → speculative here)
    rungs = [p["rung"] for p in ps]
    assert rungs == sorted(rungs, key=LADDER.index), rungs
    assert [rank_key(p) for p in ps] == sorted(rank_key(p) for p in ps), "sorted by the single rank_key"
    sevs = [p["severity"] for p in ps]
    assert sevs == sorted(sevs, key=["CRITICAL", "HIGH", "MEDIUM", "LOW"].index), sevs  # ladder ⇒ severity-monotonic here
    # rank_key is the shared authority: an owner action (severity-only, no rung) orders by the same key
    assert rank_key({"severity": "CRITICAL"}) < rank_key({"severity": "HIGH"}) < rank_key({"severity": "LOW"})
    # a clean state (no health arg, no monitor) still surfaces only registry-grounded items
    base = derive_priorities()
    assert all(p["source"].startswith(("registry:", "registry.")) for p in base), base
    assert isinstance(base, list)
    # live signals rank at their own severity and cite the probe (a failing CRITICAL signal leads)
    sp = derive_priorities(signals=[{"name": "appB_health", "ok": False, "severity": "CRITICAL", "detail": "HTTP 0"},
                                    {"name": "appA_cpu", "ok": True, "severity": "OK", "detail": "54%"}])
    assert sp[0]["source"] == "live-signal:appB_health" and sp[0]["severity"] == "CRITICAL", sp[:1]
    print(f"priorities.demo OK — {len(ps)} ranked by the §22 ladder w/ health+monitor, {len(base)} registry-only, "
          f"{len(sp)} w/ a failing live signal leading")


if __name__ == "__main__":
    demo()
