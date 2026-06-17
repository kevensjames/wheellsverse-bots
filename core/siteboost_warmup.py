"""SiteBoost outbound-domain warmup ramp.

Cold-email best practice: a brand-new sending domain (hello.wheellsverse.com)
should NOT immediately blast at full volume. Mailbox providers (Gmail, Outlook,
Yahoo) score sender reputation by send volume + engagement curve; an unknown
domain that suddenly sends 50/day gets sandboxed or spam-filed regardless of
how good the content is.

The cure is a gradual ramp over ~14 days while engagement accumulates. This
module owns:
  1. The ramp schedule (a list of (start_day, daily_cap) tiers)
  2. The start-date file (when warmup began for the active domain)
  3. `current_cap()` — given today, what should daily_limit be?
  4. `advance_if_needed()` — idempotent; PATCHes Instantly only when the
     scheduler-computed cap differs from what's currently set

This is intentionally a file-backed state machine (no DB), same as the rest
of SiteBoost's persistence layer — survives container restarts because
WARMUP_PATH lives on the /var/data volume.

Operator tunes the ramp by editing WARMUP_RAMP below. Keys are start_day
(1-indexed: Day 1 is the day warmup begins). Daily cap stays at that value
until the next tier's start_day kicks in. Last tier = steady state.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger("siteboost_warmup")

ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_WARMUP = ROOT / "data" / "launches" / "siteboost" / "warmup_start.json"
WARMUP_PATH = Path(os.getenv("SITEBOOST_WARMUP_PATH", str(_DEFAULT_WARMUP)))

# Standard ISP-friendly ramp: 5/day for first 3 days, doubling roughly every
# 3-4 days, plateauing at 50/day. 50/day per mailbox is conservative — single
# mailbox can usually do 100-200 once warmed, but 50 keeps deliverability
# headroom for cold sends (lower reply/engagement than warm). Operator can
# raise the steady-state by editing the last tier.
#
# Format: list of (start_day, daily_cap). Tiers must be sorted by start_day.
WARMUP_RAMP: list[tuple[int, int]] = [
    (1,   5),    # Days 1-3:  5 sends/day (matches campaign create-default)
    (4,  10),   # Days 4-7:  10/day
    (8,  25),   # Days 8-11: 25/day
    (12, 40),   # Days 12-14: 40/day
    (15, 50),   # Day 15+:   50/day steady state
]

STEADY_STATE_DAY = WARMUP_RAMP[-1][0]


def _today() -> date:
    return datetime.utcnow().date()


def _save_start(start_iso: str, domain: str) -> None:
    WARMUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "start_date": start_iso,
        "domain": domain,
        "ramp": [{"start_day": d, "daily_cap": cap} for d, cap in WARMUP_RAMP],
    }
    tmp = WARMUP_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(WARMUP_PATH)


def start_warmup(domain: str = "", start_date: str = "") -> dict:
    """Mark today (or start_date if given) as Day 1 of warmup for `domain`.

    Safe to re-call: overwrites the start file. Use when switching to a new
    outbound domain, or to restart the ramp after a deliverability incident.
    """
    iso = start_date or _today().isoformat()
    dom = domain or os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "").strip()
    _save_start(iso, dom)
    logger.info(f"[warmup] started: domain={dom!r} date={iso}")
    return {"status": "ok", "start_date": iso, "domain": dom}


def get_status() -> dict:
    """Return current warmup state: start date, days elapsed, current cap,
    next tier preview, and whether we're at steady state."""
    if not WARMUP_PATH.exists():
        return {"status": "not_started",
                "hint": "POST /admin/siteboost/warmup/start to begin"}
    try:
        data = json.loads(WARMUP_PATH.read_text())
    except Exception as e:
        return {"status": "error", "error": f"corrupt warmup file: {e!s}"}

    start_iso = data.get("start_date", "")
    try:
        start = date.fromisoformat(start_iso)
    except Exception:
        return {"status": "error", "error": f"bad start_date: {start_iso!r}"}

    today = _today()
    day_n = (today - start).days + 1  # Day 1 = same day as start
    cap, tier_idx = _cap_for_day(day_n)
    next_tier = WARMUP_RAMP[tier_idx + 1] if tier_idx + 1 < len(WARMUP_RAMP) else None

    return {
        "status": "warming" if day_n < STEADY_STATE_DAY else "steady",
        "start_date": start_iso,
        "today": today.isoformat(),
        "day_n": day_n,
        "current_cap": cap,
        "next_tier": (
            {"day": next_tier[0], "cap": next_tier[1],
             "days_until": next_tier[0] - day_n}
            if next_tier else None
        ),
        "domain": data.get("domain", ""),
        "ramp": data.get("ramp", []),
    }


def _cap_for_day(day_n: int) -> tuple[int, int]:
    """Pick the tier whose start_day is ≤ day_n. Returns (cap, tier_index).

    For day_n < 1 (i.e. start_date is in the future — operator typo'd a date),
    returns the Day-1 cap to avoid sending nothing. For day_n past steady state,
    returns the last tier (the steady-state cap)."""
    safe_day = max(day_n, 1)
    chosen_idx = 0
    for idx, (start_day, _cap) in enumerate(WARMUP_RAMP):
        if start_day <= safe_day:
            chosen_idx = idx
        else:
            break
    return WARMUP_RAMP[chosen_idx][1], chosen_idx


def advance_if_needed() -> dict:
    """Idempotent: compute today's cap, PATCH Instantly only if different.

    Scheduler calls this once/day. No-op when warmup not started, when cap
    matches Instantly's current daily_limit (we cache the last-applied cap
    in the warmup file), or when Instantly API key is missing.
    """
    if not WARMUP_PATH.exists():
        return {"status": "noop", "reason": "warmup not started"}
    try:
        data = json.loads(WARMUP_PATH.read_text())
    except Exception as e:
        return {"status": "error", "error": f"corrupt warmup file: {e!s}"}

    status = get_status()
    if status.get("status") in ("error", "not_started"):
        return {"status": "noop", "reason": status.get("status")}
    target_cap = status["current_cap"]
    last_applied = data.get("last_applied_cap")
    if last_applied == target_cap:
        return {"status": "noop", "reason": "cap unchanged",
                "current_cap": target_cap, "day_n": status["day_n"]}

    from core.siteboost_instantly import set_campaign_daily_limit
    patch_result = set_campaign_daily_limit(target_cap)
    if patch_result.get("status") != "ok":
        return {"status": "failed", "reason": "Instantly patch failed",
                "patch_result": patch_result}

    data["last_applied_cap"] = target_cap
    data["last_applied_at"] = datetime.utcnow().isoformat() + "Z"
    tmp = WARMUP_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(WARMUP_PATH)

    logger.info(f"[warmup] advanced: day={status['day_n']} cap={target_cap}")
    return {"status": "ok", "applied_cap": target_cap, "day_n": status["day_n"],
            "instantly": patch_result}
