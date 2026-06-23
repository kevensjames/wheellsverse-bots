"""Read-side aggregation for the Portfolio HQ toodle. Pure reads over Plan-1
engine state — composes registry + per-business state + loops + the audit log.
"""
from __future__ import annotations

from core.portfolio import loops, paths, registry, state


def business_summary(slug: str, name: str) -> dict:
    st = state.load_state(slug)
    steps = loops.load_loop(slug)
    nxt = loops.select_next_step(steps, st)
    return {
        "slug": slug,
        "name": name,
        "phase": st.get("phase", "planning"),
        "completed": len(st.get("completed_verbs", [])),
        "pending": len(st.get("pending_verbs", [])),
        "next_step": nxt.verb if nxt is not None else None,
        "total_steps": len(steps),
    }


def portfolio_overview() -> list[dict]:
    return [business_summary(b.slug, b.name) for b in registry.list_businesses()]


def recent_audit(limit: int = 50) -> list[dict]:
    rows = paths.read_jsonl(paths.data_root() / "audit.jsonl")
    return list(reversed(rows))[:limit]
