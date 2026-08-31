"""Continuous holding watch loop (Wave 1) — proactive change + anomaly detection.

Senses the current observable holding state (read-only), diffs it against the last-seen state, and
raises alerts ONLY on material CHANGE — which is inherently spam-free (an ongoing issue produces one
alert when it starts and one when it recovers, never a repeat every tick). Alerts go only to the
operator's own channel and only when delivery is opted in (delivery.send_alert is gated). Flag-gated
by KAI_HOLDING_WATCH_ENABLED; report-only; never mutates anything but its own state row.
"""
from __future__ import annotations

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}


def collect_state() -> dict:
    """A flat dict of comparable facts (stable keys) from the read-only collectors. Best-effort."""
    facts: dict = {}
    try:
        from app.services.holding.signals import collect_live_signals
        for s in collect_live_signals():
            facts[f"signal:{s.get('name')}"] = bool(s.get("ok"))
    except Exception:
        pass
    try:
        from app.services.holding.entity_status import collect_live_entity_status
        for eid, v in collect_live_entity_status().items():
            facts[f"entity:{eid}:live"] = bool(v.get("ok"))
            d = v.get("detail") or {}
            if eid == "nexora":
                for k in ("subscribers", "mrr", "stripe_set"):
                    if k in d:
                        facts[f"entity:nexora:{k}"] = d[k]
            if eid == "suprema" and d.get("scheduler_running") is not None:
                facts["entity:suprema:scheduler_running"] = bool(d["scheduler_running"])
    except Exception:
        pass
    try:
        from app.services.holding import registry as reg
        ents = reg.all_entities()
        facts["kpi:open_risks"] = sum(len(getattr(e, "risks", None) or []) for e in ents)
        facts["kpi:open_incidents"] = sum(len(getattr(e, "incidents", None) or []) for e in ents)
        facts["kpi:entities_verified"] = sum(1 for e in ents if e.confidence.value == "VERIFIED")
    except Exception:
        pass
    return facts


def diff(prev: dict, cur: dict) -> list:
    """Change events between prev and cur facts. Empty on first run (no prev). Pure + deterministic."""
    if not prev:
        return []
    ev: list = []
    def add(key, severity, message): ev.append({"key": key, "severity": severity, "message": message})
    for key, now in cur.items():
        if key not in prev or prev[key] == now:
            continue                                    # unchanged (or a newly-seen fact) → no alert
        was = prev[key]
        if isinstance(now, bool) and isinstance(was, bool):
            if key.endswith(":live"):
                eid = key.split(":")[1]
                add(key, "CRITICAL" if not now else "INFO", f"{eid} {'is DOWN' if not now else 'is back UP'}")
            elif key.startswith("signal:"):
                add(key, "CRITICAL" if not now else "INFO",
                    f"signal {key.split(':', 1)[1]} {'FAILING' if not now else 'recovered'}")
            elif key.endswith("scheduler_running"):
                add(key, "HIGH" if not now else "INFO", f"Suprema scanner {'STOPPED' if not now else 'restarted'}")
            elif key.endswith("stripe_set"):
                add(key, "INFO", f"Nexora Stripe {'now configured' if now else 'unset'}")
        elif isinstance(now, (int, float)) and isinstance(was, (int, float)):
            if key == "kpi:open_incidents" and now > was:
                add(key, "CRITICAL", f"new incident(s): {was} → {now}")
            elif key == "kpi:open_risks" and now > was:
                add(key, "HIGH", f"new risk(s) logged: {was} → {now}")
            elif key == "kpi:entities_verified" and now < was:
                add(key, "MEDIUM", f"an entity lost VERIFIED status: {was} → {now}")
            elif key == "entity:nexora:subscribers" and now < was:
                add(key, "HIGH", f"Nexora subscribers dropped: {was} → {now}")
            elif key == "entity:nexora:mrr" and now != was:
                add(key, "HIGH" if now < was else "INFO", f"Nexora MRR changed: {was} → {now}")
    ev.sort(key=lambda e: _SEV_ORDER.get(e["severity"], 9))
    return ev


def format_alert(events: list) -> str:
    return "⚠️ KAI holding watch — change detected:\n" + "\n".join(
        f"[{e['severity']}] {e['message']}" for e in events[:10])


def run_watch(*, deliver: bool = True) -> dict:
    """Sense → diff vs last → alert on change → persist. Flag-gated + report-only. Never raises fatally."""
    try:
        from app.config import settings
        if not getattr(settings, "KAI_HOLDING_WATCH_ENABLED", False):
            return {"ran": False, "reason": "KAI_HOLDING_WATCH_ENABLED off"}
        from app.services.holding import watch_store
        cur = collect_state()
        prev = watch_store.load().get("state", {})
        events = diff(prev, cur)
        delivered = {"delivered": False, "reason": "no change" if prev else "baseline (first run)"}
        if deliver and events:
            from app.services.holding.delivery import send_alert
            delivered = send_alert(format_alert(events))
        watch_store.save(cur, {})
        return {"ran": True, "baseline": not prev, "events": events, "delivered": delivered}
    except Exception as e:
        return {"ran": False, "reason": f"watch error: {str(e)[:100]}"}


def demo() -> None:
    """Pure self-check of the change detector (no network/DB)."""
    base = {"entity:kai:live": True, "signal:appA_cpu": True, "kpi:open_risks": 1,
            "entity:nexora:subscribers": 5, "entity:suprema:scheduler_running": True}
    assert diff({}, base) == [], "first run must be a silent baseline"
    assert diff(base, base) == [], "no change → no alert (spam-free)"
    changed = {**base, "entity:kai:live": False, "kpi:open_risks": 3,
               "entity:nexora:subscribers": 2, "entity:suprema:scheduler_running": False}
    ev = diff(base, changed)
    keys = {e["key"]: e["severity"] for e in ev}
    assert keys.get("entity:kai:live") == "CRITICAL", ev
    assert keys.get("kpi:open_risks") == "HIGH" and keys.get("entity:nexora:subscribers") == "HIGH", ev
    assert keys.get("entity:suprema:scheduler_running") == "HIGH", ev
    assert ev[0]["severity"] == "CRITICAL", "most severe first"
    # recovery is detected on the reverse transition
    rec = diff(changed, base)
    assert any(e["key"] == "entity:kai:live" and "back UP" in e["message"] for e in rec), rec
    print(f"watch.demo OK — baseline silent, {len(ev)} change alerts ranked, recovery detected")


if __name__ == "__main__":
    demo()
