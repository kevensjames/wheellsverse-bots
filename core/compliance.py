#!/usr/bin/env python3
"""
core/compliance.py
─────────────────────────────────────────────────────────────────────────────
Honest health state for all WheellsVerse bots.

Replaces the lying "ALL SYSTEMS OK — 13/13 enabled" report that claimed
health while 4 agents were burning consecutive failures on exhausted
API credits. The old check asked "does the bot file exist?"; this one
asks "did the bot's last run actually work?"

Every BaseBot.execute() call writes to this store:
    - success: clears error streak + stamps last_success_ts
    - failure: increments consecutive_failures + saves error text

The compliance agent reads this and tells the truth.

Backend: Redis with filesystem fallback (same pattern as core/dedup.py).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

# ─── Redis init (graceful) ───────────────────────────────────────────────────
_redis_client = None
try:
    import redis  # type: ignore

    _REDIS_URL = os.getenv("REDIS_URL")
    if _REDIS_URL:
        _redis_client = redis.from_url(
            _REDIS_URL,
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
        try:
            _redis_client.ping()
        except Exception:
            _redis_client = None
except Exception:
    _redis_client = None

_FALLBACK_DIR = Path(os.getenv("HEALTH_CACHE_DIR", "/tmp/wv_health"))
_FALLBACK_DIR.mkdir(parents=True, exist_ok=True)

# State persists for 7 days — long enough to detect agents that never recover,
# short enough not to keep old ghosts around forever.
_STATE_TTL_SECONDS = 86400 * 7


# ─── Types ────────────────────────────────────────────────────────────────────
class AgentStatus(str, Enum):
    OK = "ok"                          # last run succeeded within threshold
    STALE = "stale"                    # no run within threshold window
    FAILING = "failing"                # 1-2 consecutive failures
    DEAD = "dead"                      # 3+ consecutive failures
    CREDIT_EXHAUSTED = "credit_exhausted"  # API credit depleted
    UNKNOWN = "unknown"                # agent has never reported


@dataclass
class AgentHealth:
    agent: str
    status: AgentStatus
    last_success_ts: Optional[float]
    last_error: Optional[str]
    consecutive_failures: int
    seconds_since_success: Optional[float]

    def is_healthy(self) -> bool:
        return self.status == AgentStatus.OK


# ─── Storage ─────────────────────────────────────────────────────────────────
def _key(agent: str) -> str:
    return f"wv:health:{agent}"


def _save(agent: str, data: dict) -> None:
    payload = json.dumps(data, default=str)
    if _redis_client:
        try:
            _redis_client.set(_key(agent), payload, ex=_STATE_TTL_SECONDS)
            return
        except Exception:
            pass
    (_FALLBACK_DIR / f"{agent}.json").write_text(payload)


def _load(agent: str) -> Optional[dict]:
    if _redis_client:
        try:
            raw = _redis_client.get(_key(agent))
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    path = _FALLBACK_DIR / f"{agent}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return None
    return None


def _list_known_agents() -> List[str]:
    """Return every agent that has reported state. Used when a caller wants
    to check 'everything we've ever seen' instead of passing a static list."""
    agents: List[str] = []
    if _redis_client:
        try:
            for k in _redis_client.scan_iter(match="wv:health:*"):
                agents.append(k.split("wv:health:", 1)[1])
            return sorted(set(agents))
        except Exception:
            pass
    for p in _FALLBACK_DIR.glob("*.json"):
        agents.append(p.stem)
    return sorted(set(agents))


# ─── Recording API (called by BaseBot.execute) ───────────────────────────────
def record_success(agent: str) -> None:
    """Agent call this after a successful run. Resets the failure streak."""
    _save(agent, {
        "last_success_ts": time.time(),
        "consecutive_failures": 0,
        "last_error": None,
    })


def record_failure(agent: str, error: str) -> None:
    """Agent calls this after a failed run. Increments the streak + saves
    the error text so the compliance reader can classify it (e.g. detect
    'credit balance too low' → CREDIT_EXHAUSTED)."""
    current = _load(agent) or {}
    _save(agent, {
        "last_success_ts": current.get("last_success_ts"),
        "consecutive_failures": int(current.get("consecutive_failures", 0)) + 1,
        "last_error": (error or "")[:500],
        "last_failure_ts": time.time(),
    })


# ─── Reading API (called by compliance agent) ────────────────────────────────
def check(agent: str, stale_threshold_sec: int = 3600) -> AgentHealth:
    """Classify a single agent. Stale threshold defaults to 1 hour — tune
    per-agent via stale_threshold_sec if you have bots that legitimately
    run less often."""
    data = _load(agent)
    if not data:
        return AgentHealth(agent, AgentStatus.UNKNOWN, None, None, 0, None)

    now = time.time()
    last_success = data.get("last_success_ts")
    failures = int(data.get("consecutive_failures", 0))
    last_error = (data.get("last_error") or "").lower()
    seconds_since = (now - last_success) if last_success else None

    # Order matters: credit-exhausted trumps dead/failing because the fix
    # is different (top up money vs. debug code).
    if any(phrase in last_error for phrase in (
        "credit balance is too low",
        "credit balance too low",
        "insufficient_quota",
    )):
        status = AgentStatus.CREDIT_EXHAUSTED
    elif failures >= 3:
        status = AgentStatus.DEAD
    elif failures > 0:
        status = AgentStatus.FAILING
    elif seconds_since is not None and seconds_since > stale_threshold_sec:
        status = AgentStatus.STALE
    elif last_success is None:
        status = AgentStatus.UNKNOWN
    else:
        status = AgentStatus.OK

    return AgentHealth(
        agent=agent,
        status=status,
        last_success_ts=last_success,
        last_error=data.get("last_error"),
        consecutive_failures=failures,
        seconds_since_success=seconds_since,
    )


_SCHEDULE_FALLBACK_SEC = 3600  # used when a bot has no schedule field at all
_SCHEDULE_MIN_THRESHOLD_SEC = 1800  # 30min floor, even for @hourly bots


def _parse_schedule_seconds(schedule: str) -> Optional[int]:
    """Translate a bot's `schedule` config string to an interval in seconds.

    Supported shapes (observed across the fleet):
      "@daily"             → 24h
      "@daily 14:30"       → 24h  (the HH:MM is the trigger time, not the period)
      "@hourly"            → 1h
      "@every_2hours"      → 2h
      "@every_3hours"      → 3h
      "@weekly"            → 7d
      "@monthly"           → 30d
      "300" / "3600"       → that many seconds (raw int as string)

    Returns None when the format is unrecognised — the caller falls back
    to the flat default."""
    if not schedule or not isinstance(schedule, str):
        return None
    s = schedule.strip().lower()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    # Prefix-style: "@daily 07:00", "@weekly mon 09:00", "@hourly *", etc.
    # The period word fixes the cadence; the trailing token is the trigger
    # time within that period (mostly ignored by the watchdog).
    if s.startswith("@daily"):
        return 86400
    if s.startswith("@hourly"):
        return 3600
    if s.startswith("@weekly"):
        return 7 * 86400
    if s.startswith("@monthly"):
        return 30 * 86400
    # @every_N<unit>. Accept both long ("hours", "minutes", "days") and
    # short ("h", "m", "d") unit suffixes.
    import re
    m = re.match(r"^@every_(\d+)([a-z]+)$", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit in ("m", "min", "minute", "minutes"):
            return n * 60
        if unit in ("h", "hr", "hour", "hours"):
            return n * 3600
        if unit in ("d", "day", "days"):
            return n * 86400
        if unit in ("w", "week", "weeks"):
            return n * 7 * 86400
    return None


def _threshold_for_agent(agent: str, default_sec: int = _SCHEDULE_FALLBACK_SEC) -> int:
    """Derive a stale-threshold for `agent` from its bots/.../config.json
    `schedule` field. The threshold is 2× the schedule interval — gives one
    full cycle of slack before alerting — clamped to a 30min floor.

    Falls back to `default_sec` when the config or schedule can't be parsed."""
    import json
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent
    # Bots live under one of: bots/agent_workforce/, bots/marketing/,
    # bots/social_media/, bots/specialized/, bots/core/<dir>/. Try them all.
    for sub in ("agent_workforce", "marketing", "social_media", "specialized", "core"):
        candidate = repo_root / "bots" / sub / agent / "config.json"
        if candidate.is_file():
            try:
                cfg = json.loads(candidate.read_text())
            except Exception:
                return default_sec
            interval = _parse_schedule_seconds(cfg.get("schedule", ""))
            if interval is None:
                return default_sec
            return max(2 * interval, _SCHEDULE_MIN_THRESHOLD_SEC)
    return default_sec


def check_all(agent_list: Optional[List[str]] = None,
              stale_threshold_sec: Optional[int] = 3600) -> List[AgentHealth]:
    """Classify many agents. Pass an explicit list to also flag
    'UNKNOWN — never reported' for agents that should have run. If you
    pass None, returns only agents that have *ever* reported.

    `stale_threshold_sec` semantics:
      - int     → use this for ALL agents (legacy behaviour)
      - None    → derive per-agent from each bot's config.json schedule
                  via _threshold_for_agent(). `@daily` bots get a 48h
                  threshold; `@every_2hours` bots get 4h; etc. Falls back
                  to 3600 when the schedule isn't parseable.
    """
    if agent_list is None:
        agent_list = _list_known_agents()
    if stale_threshold_sec is None:
        return [check(a, _threshold_for_agent(a)) for a in agent_list]
    return [check(a, stale_threshold_sec) for a in agent_list]


def reset(agent: str) -> None:
    """Clear recorded state for an agent. Useful after you've hand-fixed
    a bot and want the streak to restart clean."""
    if _redis_client:
        try:
            _redis_client.delete(_key(agent))
        except Exception:
            pass
    path = _FALLBACK_DIR / f"{agent}.json"
    if path.exists():
        path.unlink()


# ─── Telegram formatter ──────────────────────────────────────────────────────
def format_telegram_report(results: List[AgentHealth]) -> str:
    """Build a Telegram message that tells the truth.

    NOTE: plain text. If your Telegram sender uses MarkdownV2, escape the
    returned string before sending (or switch that sender to parse_mode=None
    — easier than escaping every '.', '-', '!' the emoji bar contains).
    """
    total = len(results)
    healthy = sum(1 for r in results if r.is_healthy())

    credit_dead = [r for r in results if r.status == AgentStatus.CREDIT_EXHAUSTED]
    dead = [r for r in results if r.status == AgentStatus.DEAD]
    failing = [r for r in results if r.status == AgentStatus.FAILING]
    stale = [r for r in results if r.status == AgentStatus.STALE]
    unknown = [r for r in results if r.status == AgentStatus.UNKNOWN]

    if healthy == total and total > 0:
        header = "🤖 Compliance Agent — Health Check\n✅ ALL SYSTEMS OK"
    elif total == 0:
        header = "🤖 Compliance Agent — Health Check\n❓ No agents have reported yet"
    else:
        header = (
            f"🤖 Compliance Agent — Health Check\n"
            f"⚠️ {healthy}/{total} agents healthy"
        )
    lines = [header]

    if credit_dead:
        lines.append(f"\n💸 CREDIT EXHAUSTED ({len(credit_dead)}):")
        for r in credit_dead:
            lines.append(f"  • {r.agent}")
        lines.append("  → Top up Anthropic/OpenAI credits.")

    if dead:
        lines.append(f"\n🔴 DEAD ({len(dead)}):")
        for r in dead:
            err = (r.last_error or "").split("\n")[0][:80]
            lines.append(f"  • {r.agent} — {r.consecutive_failures} failures | {err}")

    if failing:
        lines.append(f"\n🟡 FAILING ({len(failing)}):")
        for r in failing:
            lines.append(f"  • {r.agent} — {r.consecutive_failures}x")

    if stale:
        lines.append(f"\n⏰ STALE ({len(stale)}):")
        for r in stale:
            mins = int(r.seconds_since_success / 60) if r.seconds_since_success else "?"
            lines.append(f"  • {r.agent} — no output for {mins}m")

    if unknown:
        lines.append(f"\n❓ NEVER REPORTED ({len(unknown)}):")
        for r in unknown:
            lines.append(f"  • {r.agent}")

    return "\n".join(lines)


def to_json(results: List[AgentHealth]) -> str:
    """Serialize for dashboards or other consumers."""
    return json.dumps([asdict(r) for r in results], default=str, indent=2)


def backend() -> str:
    """Report which backend is active — useful for self-diagnosis."""
    return "redis" if _redis_client else "filesystem"
