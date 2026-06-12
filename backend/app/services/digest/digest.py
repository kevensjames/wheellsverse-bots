"""Operator Digest — proactive, cross-subsystem 'what needs attention today'.

Distinct from the business Daily Brief (services/briefing — users/subs/supreme/
LLM-failures). This one synthesizes KAI's OWN subsystems (audit health + blocked
plans + negative feedback + active lessons + twin) via the LLM into a short
operator-facing digest, and PUSHES it to Telegram (reusing the supreme
telegram_send path that the .env Telegram fix unblocked).

Snapshot gathering is defensive (one failing subsystem won't sink the digest)
and LLM synthesis is fail-soft. Operator-triggered in v1 (a daily scheduler is
a clean follow-up).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
DIGEST_LOG_PATH = Path(
    os.environ.get("KAI_DIGEST_LOG_PATH", str(_REPO_ROOT / "data" / "digest" / "digests.jsonl"))
)
DIGEST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_MAX_TOKENS = 700

_SYNTH_SYSTEM = (
    "You are KAI writing a short daily Operator Digest for your principal. "
    "Given the system snapshot, write a concise brief (<180 words):\n"
    "  1. One line on overall health.\n"
    "  2. What needs attention (blocked plans, negative feedback, audit issues, "
    "failures) — bullet points, most important first.\n"
    "  3. Up to 3 recommended next actions.\n"
    "Be direct and specific. No filler, no preamble, no sign-off."
)


def gather_snapshot() -> dict[str, Any]:
    """Compact cross-subsystem state. Each block is defensive — a failing
    subsystem degrades to a note rather than sinking the digest."""
    snap: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat()}

    try:
        from app.services.audit import run_audit
        a = run_audit()
        snap["audit"] = {
            "scoped_enabled": a["summary"]["scoped_enabled"],
            "scoped_total": a["summary"]["scoped_total"],
            "total_records": a["summary"]["total_records"],
            "issues": a["issues"],
        }
    except Exception as e:
        snap["audit"] = {"error": str(e)}

    try:
        from app.services import planning
        st = planning.stats()
        blocked = planning.list_plans(status="blocked", limit=10)
        snap["planning"] = {
            "active": st.get("active", 0), "blocked": st.get("blocked", 0),
            "done": st.get("done", 0),
            "blocked_titles": [p.title for p in blocked],
        }
    except Exception as e:
        snap["planning"] = {"error": str(e)}

    try:
        from app.services import learning
        lst = learning.stats()
        down = learning.list_feedback(rating="down", limit=5)
        snap["learning"] = {
            "active_lessons": lst.get("active_lessons", 0),
            "feedback_total": lst.get("feedback_total", 0),
            "recent_down": [f.note for f in down if f.note],
        }
    except Exception as e:
        snap["learning"] = {"error": str(e)}

    try:
        from app.services import twin
        tw = twin.stats()
        snap["twin"] = {"active_entries": tw.get("active_entries", 0),
                        "drafts": tw.get("drafts", 0)}
    except Exception as e:
        snap["twin"] = {"error": str(e)}

    return snap


def build_digest(*, router, user_id, prefer_local: bool = False,
                 max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
    """Snapshot → LLM-synthesized digest text. Fail-soft: on router error,
    falls back to a plain rendering of the snapshot."""
    snap = gather_snapshot()
    user_msg = "SYSTEM SNAPSHOT:\n" + json.dumps(snap, indent=2, default=str) + \
        "\n\nWrite the Operator Digest."
    try:
        result = router.complete(
            user_id=user_id, messages=[{"role": "user", "content": user_msg}],
            system=_SYNTH_SYSTEM, max_tokens=max_tokens, temperature=0.4,
            prefer_local=prefer_local,
        )
        text = (getattr(result, "content", "") or "").strip()
        cost = _result_cost(result)
    except Exception as e:
        logger.warning("digest: router.complete failed: %s", e)
        text, cost = _fallback_text(snap), 0.0
    if not text:
        text = _fallback_text(snap)
    return {"digest": text, "snapshot": snap, "cost_usd": cost}


def send_digest(*, router, user_id, deliver: bool = True,
                prefer_local: bool = False) -> dict[str, Any]:
    """Build the digest, optionally push to Telegram, and log it.
    Returns {digest, sent, cost_usd, snapshot}."""
    built = build_digest(router=router, user_id=user_id, prefer_local=prefer_local)
    sent = False
    if deliver:
        try:
            from app.services.supreme.scanner import telegram_send
            sent = bool(telegram_send("🔔 KAI Operator Digest\n\n" + built["digest"]))
        except Exception as e:
            logger.warning("digest: telegram send failed: %s", e)
            sent = False
    _log(built["digest"], sent, built["cost_usd"])
    return {"digest": built["digest"], "sent": sent,
            "cost_usd": built["cost_usd"], "snapshot": built["snapshot"]}


def list_digests(limit: int = 20) -> list[dict[str, Any]]:
    if not DIGEST_LOG_PATH.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in reversed(DIGEST_LOG_PATH.read_text().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(out) >= max(1, min(int(limit), 200)):
                break
    except Exception:
        return out
    return out


# ─── internals ──────────────────────────────────────────────────────


def _log(digest: str, sent: bool, cost: float) -> None:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "sent": sent,
           "cost_usd": cost, "digest": digest}
    try:
        with DIGEST_LOG_PATH.open("a") as fp:
            fp.write(json.dumps(rec, default=str) + "\n")
    except Exception as e:  # pragma: no cover
        logger.warning("digest: log write failed: %s", e)


def _fallback_text(snap: dict[str, Any]) -> str:
    a = snap.get("audit", {})
    p = snap.get("planning", {})
    lr = snap.get("learning", {})
    lines = ["Operator Digest (LLM unavailable — raw snapshot):"]
    if isinstance(a, dict):
        lines.append(f"- system: {a.get('scoped_enabled','?')}/{a.get('scoped_total','?')} "
                     f"features on, {len(a.get('issues',[]))} issue(s)")
    if isinstance(p, dict):
        lines.append(f"- plans: {p.get('active',0)} active, {p.get('blocked',0)} blocked")
        if p.get("blocked_titles"):
            lines.append(f"  blocked: {', '.join(p['blocked_titles'][:5])}")
    if isinstance(lr, dict):
        lines.append(f"- learning: {lr.get('active_lessons',0)} active lessons, "
                     f"{lr.get('feedback_total',0)} feedback")
    return "\n".join(lines)


def _result_cost(result) -> float:
    for attr in ("total_cost_usd", "cost_usd", "cost"):
        v = getattr(result, attr, None)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0
