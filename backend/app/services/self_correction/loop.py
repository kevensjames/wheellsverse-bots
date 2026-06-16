"""Correction loop orchestrator — ties critic + reviser into one call.

Flow:
  1. critique(draft) → verdict
  2. if not verdict.needs_revision: return (draft, verdict, 0 iterations)
  3. revise(draft, verdict) → new draft
  4. (optional) critique again until ok or max_iterations
  5. return (final_text, verdicts, iterations)

Default max_iterations=1: ONE critique + AT MOST ONE revision per chat
turn. That's the cost ceiling — operator opts in to pay it. Higher
values are possible but risk runaway latency on the cheap critic loop.

Persistence: every correction event is appended to data/self_correction/
events.jsonl so the admin panel can show "5 corrections today, average
1.2 iterations, biggest fix was ___".
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.self_correction.critic import Verdict, critique
from app.services.self_correction.reviser import revise

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]
EVENTS_PATH = Path(
    os.environ.get(
        "KAI_SELF_CORRECTION_EVENTS_PATH",
        str(_REPO_ROOT / "data" / "self_correction" / "events.jsonl"),
    )
)
EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULT_MAX_ITERATIONS = 1


@dataclass(slots=True)
class CorrectionResult:
    final_text: str
    iterations: int                  # # of critique passes that ran
    verdicts: list[Verdict] = field(default_factory=list)
    total_cost: float = 0.0          # critic+reviser cost, in USD
    was_revised: bool = False        # did we end up changing the draft?

    def to_event_dict(self, *, user_message: str) -> dict[str, Any]:
        """Audit record. Truncates long strings so the event log stays
        grep-friendly."""
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "user_message": _truncate(user_message, 400),
            "iterations": self.iterations,
            "was_revised": self.was_revised,
            "total_cost_usd": round(self.total_cost, 6),
            "final_severity": (
                self.verdicts[-1].severity if self.verdicts else "none"
            ),
            "verdicts": [
                {
                    "ok": v.ok,
                    "severity": v.severity,
                    "critique": _truncate(v.critique, 300),
                    "suggestions": v.suggestions[:5],
                }
                for v in self.verdicts
            ],
            "final_text_preview": _truncate(self.final_text, 200),
        }


def run_correction_loop(
    *,
    user_message: str,
    initial_draft: str,
    router,
    original_adapter,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    prefer_local: bool = False,
) -> CorrectionResult:
    """Run up to `max_iterations` critique + revise cycles.

    `original_adapter` is the adapter that produced `initial_draft` —
    the reviser uses the SAME quality bar for any rewrite. The CRITIC
    picks its own (cheap) adapter inside critique().
    """
    max_iterations = max(1, min(int(max_iterations), 3))  # hard cap at 3
    result = CorrectionResult(final_text=initial_draft, iterations=0)
    current_text = initial_draft

    for _ in range(max_iterations):
        try:
            verdict, critic_cost = critique(
                user_message=user_message,
                draft_response=current_text,
                router=router,
                prefer_local=prefer_local,
            )
        except Exception as e:
            logger.warning("self_correction: critique crashed: %s", e)
            break

        result.verdicts.append(verdict)
        result.total_cost += critic_cost
        result.iterations += 1

        if not verdict.needs_revision:
            # OK or minor — accept current text. We're done.
            break

        # Revise. If revise fails, current_text stays the same and we'd
        # loop again — but we cap at max_iterations so this doesn't spin.
        try:
            revised, revise_cost = revise(
                user_message=user_message,
                draft_response=current_text,
                verdict=verdict,
                router=router,
                original_adapter=original_adapter,
            )
        except Exception as e:
            logger.warning("self_correction: revise crashed: %s", e)
            break

        result.total_cost += revise_cost
        if revised and revised != current_text:
            current_text = revised
            result.was_revised = True

    result.final_text = current_text
    _append_event(result, user_message=user_message)
    return result


# ─── event log (admin view) ─────────────────────────────────────────


def list_events(*, limit: int = 50) -> list[dict[str, Any]]:
    """Newest-first slice. Same pattern as the failure + governance logs."""
    if not EVENTS_PATH.exists():
        return []
    limit = max(1, min(int(limit), 500))
    out: list[dict[str, Any]] = []
    try:
        with EVENTS_PATH.open() as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning("self_correction: read events failed: %s", e)
        return []
    out.reverse()
    return out[:limit]


def stats_summary() -> dict[str, Any]:
    """Quick aggregate for the admin panel header."""
    rows = list_events(limit=500)
    if not rows:
        return {
            "total_recent": 0,
            "revisions_applied": 0,
            "avg_iterations": 0.0,
            "by_final_severity": {},
            "total_cost_usd": 0.0,
        }
    total = len(rows)
    revisions = sum(1 for r in rows if r.get("was_revised"))
    iters = sum(int(r.get("iterations", 0)) for r in rows)
    by_sev: dict[str, int] = {}
    cost = 0.0
    for r in rows:
        s = r.get("final_severity") or "none"
        by_sev[s] = by_sev.get(s, 0) + 1
        c = r.get("total_cost_usd")
        if isinstance(c, (int, float)):
            cost += c
    return {
        "total_recent": total,
        "revisions_applied": revisions,
        "avg_iterations": round(iters / total, 2),
        "by_final_severity": by_sev,
        "total_cost_usd": round(cost, 4),
    }


# ─── helpers ────────────────────────────────────────────────────────


def _append_event(result: CorrectionResult, *, user_message: str) -> None:
    try:
        with EVENTS_PATH.open("a") as fp:
            fp.write(
                json.dumps(result.to_event_dict(user_message=user_message), default=str)
                + "\n"
            )
    except Exception as e:
        logger.warning("self_correction: event append failed: %s", e)


def _truncate(s: str, n: int) -> str:
    s = s or ""
    if len(s) > n:
        return s[:n] + f"… ({len(s)} chars)"
    return s
