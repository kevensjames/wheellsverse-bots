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
     scheduler-computed cap differs from what's currently set, AND the
     recorded cap was applied to the CURRENT active campaign id (so swapping
     campaigns invalidates the cache and forces a re-apply).

Persistence is a single JSON file on the /var/data volume:

    {
      "start_date":               "YYYY-MM-DD",   # Day 1 of the ramp
      "domain":                   "<sending domain>",
      "ramp":                     [{...}],         # snapshot at start (for audit)
      "last_applied_cap":         <int|null>,     # last cap we PATCHed Instantly to
      "last_applied_at":          "<iso>",        # when
      "last_applied_campaign_id": "<uuid>"        # to which Instantly campaign
    }

`last_applied_campaign_id` is the source-of-truth binding — if the active
campaign changes (operator hits /instantly/auto-create-campaign which mints
a new UUID with `daily_limit: 5`), the cache is forced stale and the next
advance re-PATCHes the new campaign up to the ramp tier.

Concurrency: both `start_warmup()` and `advance_if_needed()` acquire a
module-level lock so the read → blocking Instantly PATCH → write sequence
in advance can't race with an operator-triggered start_warmup. Atomic
tmp+rename file writes only protect READERS — they don't serialize writers.

Day-N is computed in UTC. Instantly campaigns created by
`create_siteboost_campaign` run in `Etc/GMT+12` (UTC-12). The scheduler's
system tick at SITEBOOST_DAILY_HOUR (default 14 UTC = 02:00 in Etc/GMT+12)
runs safely past local-midnight, so a tier-boundary cap bump always lands
after Instantly's own day has rolled. That dodges the 12h-skew failure
mode without dragging tzdata into this module.

Operator tunes the ramp by editing WARMUP_RAMP below. Tiers are sorted at
import-time and an assertion enforces strictly increasing start_days, so a
misordered edit fails LOUDLY rather than silently mis-capping.
"""
from __future__ import annotations

import json
import logging
import os
import threading
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
# Format: list of (start_day, daily_cap). Tiers must be sorted by start_day
# and strictly increasing — enforced at module load.
WARMUP_RAMP: list[tuple[int, int]] = sorted([
    (1,   5),    # Days 1-3:  5 sends/day (matches campaign create-default)
    (4,  10),   # Days 4-7:  10/day
    (8,  25),   # Days 8-11: 25/day
    (12, 40),   # Days 12-14: 40/day
    (15, 50),   # Day 15+:   50/day steady state
], key=lambda t: t[0])

# Loud-fail if a future edit duplicates a start_day or sets a non-positive cap.
assert all(WARMUP_RAMP[i][0] < WARMUP_RAMP[i + 1][0]
           for i in range(len(WARMUP_RAMP) - 1)), \
    "WARMUP_RAMP start_days must be strictly increasing"
assert all(cap > 0 for _, cap in WARMUP_RAMP), \
    "WARMUP_RAMP daily_caps must all be positive"

STEADY_STATE_DAY = WARMUP_RAMP[-1][0]

# Serializes any read-modify-write sequence against the warmup state file.
# Both /warmup/start and /warmup/advance handlers run in FastAPI's threadpool
# (def routes, not async def), and the scheduler's system tick runs from
# another thread. All three paths land in this module's functions, so an
# in-process Lock is sufficient — there's no cross-process writer.
_WARMUP_LOCK = threading.Lock()


def _today() -> date:
    return datetime.utcnow().date()


def _ramp_snapshot() -> list[dict]:
    """Always derive the persisted ramp shape from the LIVE module constant."""
    return [{"start_day": d, "daily_cap": cap} for d, cap in WARMUP_RAMP]


def _load_state() -> dict:
    """Read the persisted warmup state, or return an empty dict if absent.

    Returns the raw on-disk payload — callers decide what to do with missing
    keys. Never raises (corrupt JSON returns {} + logs)."""
    if not WARMUP_PATH.exists():
        return {}
    try:
        return json.loads(WARMUP_PATH.read_text())
    except Exception as e:
        logger.warning(f"[warmup] corrupt state file at {WARMUP_PATH}: {e}")
        return {}


def _atomic_write(payload: dict) -> None:
    WARMUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WARMUP_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(WARMUP_PATH)


def _save_start_inner(start_iso: str, domain: str) -> dict:
    """Write the start payload. Preserves last_applied_* fields when the
    operator re-calls with the SAME start_date + domain (so an idempotent
    restart doesn't accidentally trigger a redundant PATCH on the next tick).

    Caller MUST hold _WARMUP_LOCK. Returns the new payload."""
    existing = _load_state()
    same_inputs = (
        existing.get("start_date") == start_iso
        and existing.get("domain") == domain
    )
    payload = {
        "start_date": start_iso,
        "domain": domain,
        "ramp": _ramp_snapshot(),
    }
    if same_inputs:
        # Preserve the cap binding so the next tick sees the cache as warm.
        for k in ("last_applied_cap", "last_applied_at", "last_applied_campaign_id"):
            if k in existing:
                payload[k] = existing[k]
    _atomic_write(payload)
    return payload


def start_warmup(domain: str = "", start_date: str = "") -> dict:
    """Mark today (or `start_date` if given) as Day 1 of the warmup ramp.

    Safe to re-call. Behavior:
      - Same start_date + domain → preserves last_applied_* cache (idempotent
        no-op for the next scheduler tick).
      - Different start_date OR different domain → resets the cap binding
        (a deliberate restart on a new domain SHOULD re-PATCH from scratch).
    """
    iso = start_date or _today().isoformat()
    dom = domain or os.getenv("SITEBOOST_OUTBOUND_DOMAIN", "").strip()
    with _WARMUP_LOCK:
        payload = _save_start_inner(iso, dom)
    logger.info(f"[warmup] started: domain={dom!r} date={iso} "
                f"(carried_cache={('last_applied_cap' in payload)})")
    return {"status": "ok", "start_date": iso, "domain": dom,
            "carried_cache": "last_applied_cap" in payload}


def get_status() -> dict:
    """Current warmup state: start date, days elapsed, current cap, next
    tier preview, ramp (LIVE, not the persisted snapshot), and the bound
    campaign id (so the dashboard can spot a mismatch with the active one)."""
    data = _load_state()
    if not data:
        return {"status": "not_started",
                "hint": "POST /admin/siteboost/warmup/start to begin"}

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
        "ramp": _ramp_snapshot(),          # live, derived from WARMUP_RAMP
        "ramp_at_start": data.get("ramp", []),
        "last_applied_cap": data.get("last_applied_cap"),
        "last_applied_at": data.get("last_applied_at"),
        "last_applied_campaign_id": data.get("last_applied_campaign_id", ""),
    }


def _cap_for_day(day_n: int) -> tuple[int, int]:
    """Pick the tier whose start_day is ≤ day_n. Returns (cap, tier_index).

    Robust to a misordered WARMUP_RAMP (no early break) — though the
    module-load assertion above should make that unreachable in practice.
    For day_n < 1 returns the Day-1 cap. Beyond steady state, returns the
    last tier's cap."""
    safe_day = max(day_n, 1)
    chosen_idx = 0
    chosen_start = WARMUP_RAMP[0][0]
    for idx, (start_day, _cap) in enumerate(WARMUP_RAMP):
        if start_day <= safe_day and start_day >= chosen_start:
            chosen_idx = idx
            chosen_start = start_day
    return WARMUP_RAMP[chosen_idx][1], chosen_idx


def advance_if_needed() -> dict:
    """Idempotent: compute today's cap, PATCH Instantly only when needed.

    Triggers a PATCH when EITHER:
      (a) the cached last_applied_cap differs from today's target, OR
      (b) the active campaign id has changed since we last applied
          (so a freshly-auto-created campaign — which Instantly minted with
          daily_limit=5 — gets pulled back onto the ramp immediately).

    Concurrency-safe: holds _WARMUP_LOCK across the whole read → PATCH →
    re-read → write sequence so a concurrent start_warmup can't be
    overwritten by a stale snapshot.
    """
    with _WARMUP_LOCK:
        data = _load_state()
        if not data:
            return {"status": "noop", "reason": "warmup not started"}

        status = get_status()
        if status.get("status") in ("error", "not_started"):
            return {"status": "noop", "reason": status.get("status")}

        target_cap = status["current_cap"]
        last_cap = data.get("last_applied_cap")
        last_cid = data.get("last_applied_campaign_id", "")

        # Active campaign id is the source-of-truth binding. If it differs
        # from what we last applied to, treat the cap cache as stale.
        from core.siteboost_instantly import get_active_campaign_id, set_campaign_daily_limit
        current_cid = get_active_campaign_id()
        if not current_cid:
            return {"status": "noop",
                    "reason": "no active Instantly campaign — auto-create first"}

        cache_valid = (last_cap == target_cap and last_cid == current_cid)
        if cache_valid:
            return {"status": "noop", "reason": "cap unchanged",
                    "current_cap": target_cap, "day_n": status["day_n"]}

        patch_result = set_campaign_daily_limit(target_cap)
        if patch_result.get("status") != "ok":
            return {"status": "failed", "reason": "Instantly patch failed",
                    "patch_result": patch_result}

        # RE-READ before writing back: a concurrent start_warmup() may have
        # mutated the file while we were blocked on the network call. We
        # only own the last_applied_* fields — preserve everything else.
        fresh = _load_state()
        if not fresh:
            # Bizarre: file was deleted under us. Fall back to writing what we
            # know, accepting we may overwrite a deletion. Logged for forensics.
            logger.warning("[warmup] state file disappeared during advance")
            fresh = data
        fresh["last_applied_cap"] = target_cap
        fresh["last_applied_at"] = datetime.utcnow().isoformat() + "Z"
        fresh["last_applied_campaign_id"] = current_cid
        _atomic_write(fresh)

    logger.info(f"[warmup] advanced: day={status['day_n']} cap={target_cap} "
                f"campaign={current_cid[:8]}...")
    return {"status": "ok", "applied_cap": target_cap, "day_n": status["day_n"],
            "campaign_id": current_cid, "instantly": patch_result}
