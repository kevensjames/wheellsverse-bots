"""Deterministic priority engine for the morning briefing.

Ranks REAL, source-backed signals into today's priorities — it NEVER invents work.
Every priority cites its source (a live probe, an injected monitor snapshot, or an exact
registry field). No LLM, no guessing: priorities are a pure function of current state, so the
briefing is reproducible and auditable. Empty list when there is genuinely nothing to surface.

Severity order (most urgent first):
  CRITICAL  live health failure · injected monitor active-alert · registry incident
  HIGH      registry risk
  MEDIUM    entity needs re-verification (confidence UNKNOWN/UNVERIFIED)
  LOW       operator data still awaiting confirmation (registry.needs_confirmation)
"""
from __future__ import annotations
from typing import Optional
from app.services.holding import registry as reg

CRITICAL, HIGH, MEDIUM, LOW = 0, 1, 2, 3
_SEV = {CRITICAL: "CRITICAL", HIGH: "HIGH", MEDIUM: "MEDIUM", LOW: "LOW"}
_SEVRANK = {"CRITICAL": CRITICAL, "HIGH": HIGH, "MEDIUM": MEDIUM, "LOW": LOW}


def derive_priorities(*, health: Optional[dict] = None, monitor: Optional[dict] = None,
                      signals: Optional[list] = None) -> list[dict]:
    """Return today's ranked priorities, each with a cited source. Deterministic + source-backed."""
    items: list[tuple[int, dict]] = []

    def add(sev, title, source, entity=None, detail=None):
        body = {"severity": _SEV[sev], "title": title, "source": source}
        if entity: body["entity"] = entity
        if detail: body["detail"] = detail
        items.append((sev, body))

    # 1a. live self-observed signals (each at its OWN severity) — source: live public probe.
    #     When signals are supplied they SUBSUME the simple health-arg check (no double-count).
    if signals:
        for s in signals:
            if not s.get("ok", True):
                add(_SEVRANK.get(s.get("severity", "HIGH"), HIGH),
                    f"live signal {s.get('name')}: {s.get('detail', '')}".rstrip(),
                    f"live-signal:{s.get('name')}")
    # 1b. fallback: the simple 2-probe health arg (only when richer signals weren't collected)
    elif health:
        for name, h in health.items():
            code = h.get("http") if isinstance(h, dict) else None
            if code != 200:
                add(CRITICAL, f"{name} health probe not OK (HTTP {code})", "live health probe",
                    entity="kai" if name.startswith("app") else name)

    # 2. injected monitor active alerts (CRITICAL) — only if a real snapshot was supplied
    if isinstance(monitor, dict):
        alerts = monitor.get("active_alerts") or monitor.get("alerts") or []
        if alerts:
            add(CRITICAL, f"prod observability monitor: {len(alerts)} active alert(s)",
                "observability monitor snapshot", detail=alerts[:8])

    # 3. registry incidents (CRITICAL) + risks (HIGH) — logged, source-backed per entity
    for e in reg.all_entities():
        for inc in (getattr(e, "incidents", None) or []):
            add(CRITICAL, f"{e.brand_name}: incident — {inc}", f"registry:{e.entity_id}.incidents", entity=e.entity_id)
        for rk in (getattr(e, "risks", None) or []):
            add(HIGH, f"{e.brand_name}: risk — {rk}", f"registry:{e.entity_id}.risks", entity=e.entity_id)

    # 4. entities needing re-verification (MEDIUM) — confidence UNKNOWN/UNVERIFIED
    for e in reg.all_entities():
        if e.confidence.value in ("UNKNOWN", "UNVERIFIED"):
            add(MEDIUM, f"Re-verify {e.brand_name} (confidence {e.confidence.value})",
                f"registry:{e.entity_id}.confidence", entity=e.entity_id)

    # 5. operator data still awaiting confirmation (LOW) — one grouped item, never fabricated
    nc = reg.needs_confirmation()
    if nc:
        add(LOW, f"Confirm {len(nc)} operator data field(s) across the portfolio",
            "registry.needs_confirmation()", detail=nc[:12])

    items.sort(key=lambda t: t[0])                      # stable: preserves insertion order within a severity
    return [dict(rank=i + 1, **body) for i, (_sev, body) in enumerate(items)]


def demo() -> None:
    """Self-check: priorities are ranked, cited, and derived only from real state."""
    # health failure ranks CRITICAL and cites the probe
    ps = derive_priorities(health={"app_a": {"http": 0}}, monitor={"alerts": ["disk 92%"]})
    assert ps[0]["severity"] == "CRITICAL" and ps[0]["rank"] == 1, ps[:1]
    assert all("source" in p for p in ps), "every priority must cite a source"
    sevs = [p["severity"] for p in ps]
    assert sevs == sorted(sevs, key=["CRITICAL", "HIGH", "MEDIUM", "LOW"].index), sevs  # sorted by urgency
    # a clean state (no health arg, no monitor) still surfaces only registry-grounded items
    base = derive_priorities()
    assert all(p["source"].startswith(("registry:", "registry.")) for p in base), base
    assert isinstance(base, list)
    # live signals rank at their own severity and cite the probe (a failing CRITICAL signal leads)
    sp = derive_priorities(signals=[{"name": "appB_health", "ok": False, "severity": "CRITICAL", "detail": "HTTP 0"},
                                    {"name": "appA_cpu", "ok": True, "severity": "OK", "detail": "54%"}])
    assert sp[0]["source"] == "live-signal:appB_health" and sp[0]["severity"] == "CRITICAL", sp[:1]
    print(f"priorities.demo OK — {len(ps)} ranked w/ health+monitor, {len(base)} registry-only, "
          f"{len(sp)} w/ a failing live signal leading")


if __name__ == "__main__":
    demo()
