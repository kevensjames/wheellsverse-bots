"""Fixer: clear stale-error noise from /tmp/wv_health/<bot>.json sidecar files.

Background:
    The `bot_error_spike` scanner watches per-bot logs for ERROR/CRITICAL
    spikes. Two failure modes regularly produce findings that don't need
    code work:

      1. The OLLAMA_MODEL_MAP / LLM-routing bug surfaced as a flood of
         `model 'claude-haiku-4-5-...' not found` errors. Once the .env
         is updated + the wrapper re-reads it, NEW calls succeed — but
         the old ERROR lines stay in the log file forever and the
         per-bot health sidecar in /tmp/wv_health/<bot>.json still
         reports failures from before the fix. Subsequent scanner runs
         see the same old lines + a touched mtime (INFO writes from the
         now-working bot) and re-fire.

      2. Cloud-provider credit exhaustion / rate-limits resolve when
         the operator tops up. The old log lines remain.

    For both of these, the correct auto-action is NOT a code change.
    It's "reset the health sidecar so the panel reflects current
    reality." If the underlying cause IS still active, the next scan
    cycle will re-flag the bot with fresh evidence; we lose nothing by
    clearing.

Strategy:
    For each spiking log file in finding.fix_payload["log_path"]:
      a) Tail the log, extract the most-recent ERROR/CRITICAL line.
      b) Classify by regex against the catalog
         (MODEL_NOT_FOUND, RATE_LIMIT, CREDIT_EXHAUSTED,
          CONNECTION_REFUSED, GENERIC).
      c) Look at the most-recent error's timestamp:
           - >24h old → assume cause is resolved; reset sidecar.
           - <2h old   → DO NOT clear; surface for triage.
           - 2-24h     → reset (gives provider/network time to settle).
      d) "Reset" = remove /tmp/wv_health/<bot>.json so the dashboard
         starts from a clean slate. Bot will re-create on next call.

Safety:
    - No executable code is touched (`requires_smoke_test=False`).
    - Sidecar files are operator-facing health summaries; bot processes
      regenerate them on demand. Deleting one cannot break a bot.
    - For FRESH errors we explicitly refuse to act and return
      `success=False` with a triage pointer in `risk_notes`.
    - Idempotent — re-running on an already-cleared bot is a no-op
      (returns `success=True` with empty `changed_files`).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── Constants ────────────────────────────────────────────────────────────
HEALTH_DIR = Path("/tmp/wv_health")
TAIL_BYTES = 256 * 1024
ERROR_PAT = re.compile(r"\b(ERROR|CRITICAL|FATAL|Traceback)\b")
TS_PATTERNS = [
    re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"),
]
FRESH_WINDOW = timedelta(hours=2)
STALE_WINDOW = timedelta(hours=24)

CATEGORY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("MODEL_NOT_FOUND",   re.compile(r"model '.*' not found|not_found_error|Error code: 404")),
    ("RATE_LIMIT",        re.compile(r"Error code: 429|rate.?limit|RateLimitError")),
    ("CREDIT_EXHAUSTED",  re.compile(r"insufficient_quota|credit balance is too low|credit_balance")),
    ("CONNECTION_REFUSED", re.compile(r"Connection (error|refused)|APIConnectionError|APITimeoutError|Request timed out")),
    ("AUTH_INVALID",      re.compile(r"invalid_api_key|Error code: 401")),
]


# ── FixResult bridge ─────────────────────────────────────────────────────
def _make_result(success: bool, changed_files: list[str], message: str,
                 risk_notes: str = "") -> object:
    try:
        from suprema.autorepair.engine import FixResult
    except ImportError:
        from autorepair.engine import FixResult
    return FixResult(
        success=success,
        changed_files=changed_files,
        message=message,
        risk_notes=risk_notes,
        requires_smoke_test=False,
    )


# ── Helpers ──────────────────────────────────────────────────────────────
def _tail(path: Path, n_bytes: int = TAIL_BYTES) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > n_bytes:
                f.seek(-n_bytes, 2)
                f.readline()
            return f.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _parse_ts(line: str) -> datetime | None:
    for pat in TS_PATTERNS:
        m = pat.match(line)
        if m:
            s = m.group(1).replace("T", " ")
            try:
                return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            except Exception:
                continue
    return None


def _most_recent_error(content: str) -> tuple[str, datetime | None]:
    """Walk the tail backwards, return (line, ts_or_None) of the most
    recent ERROR/CRITICAL line."""
    for line in reversed(content.splitlines()):
        if ERROR_PAT.search(line):
            return line, _parse_ts(line)
    return "", None


def _classify(line: str) -> str:
    for label, pat in CATEGORY_PATTERNS:
        if pat.search(line):
            return label
    return "GENERIC"


def _bot_name_from_log(log_path: Path) -> str:
    """logs/02_mini_course.log → '02_mini_course'."""
    return log_path.stem


def _sidecar_for(bot_name: str) -> Path:
    return HEALTH_DIR / f"{bot_name}.json"


# ── Entry point ──────────────────────────────────────────────────────────
def apply(project: Path, finding: Any) -> object:
    """Clear stale per-bot health sidecar files when the log spike is
    historic (>2h since the last error). For fresh spikes, return
    success=False and surface for operator triage.

    `finding` may be a `Finding` dataclass OR a plain dict (the engine
    passes the dataclass; tests / dry runs sometimes pass dicts).
    """
    # Extract fix_payload regardless of input shape
    if hasattr(finding, "fix_payload"):
        payload = finding.fix_payload or {}
    elif isinstance(finding, dict):
        payload = finding.get("fix_payload") or {}
    else:
        payload = {}

    log_path_str = payload.get("log_path") or ""
    if not log_path_str:
        return _make_result(
            success=False,
            changed_files=[],
            message="no log_path in fix_payload — nothing to act on",
            risk_notes="scanner did not provide log_path; check bot_error_spike output",
        )

    log_path = Path(log_path_str)
    if not log_path.exists():
        # Log was rotated out from under us — treat as resolved.
        bot_name = _bot_name_from_log(log_path)
        return _clear_sidecar(bot_name, "log file no longer exists — assumed resolved")

    content = _tail(log_path)
    if not content:
        # Empty tail — bot is fine.
        bot_name = _bot_name_from_log(log_path)
        return _clear_sidecar(bot_name, "log tail empty — assumed resolved")

    last_line, last_ts = _most_recent_error(content)
    category = _classify(last_line) if last_line else "GENERIC"
    bot_name = _bot_name_from_log(log_path)

    now = datetime.now(timezone.utc)

    # If we cannot parse a timestamp on the most-recent error, fall back to
    # the file's mtime as a proxy for "how stale is the error stream."
    if last_ts is None:
        try:
            last_ts = datetime.fromtimestamp(
                log_path.stat().st_mtime, tz=timezone.utc,
            )
        except Exception:
            last_ts = now  # be conservative — treat as fresh, skip clearing

    age = now - last_ts

    if age < FRESH_WINDOW:
        # FRESH spike — do NOT clear. Operator (or a future code-aware
        # fixer) needs to handle this. Categorise so the triage panel
        # gets useful detail.
        return _make_result(
            success=False,
            changed_files=[],
            message=f"FRESH error spike ({category}); last error {int(age.total_seconds()/60)}m ago — refusing to clear",
            risk_notes=(
                f"bot={bot_name} category={category} — investigate before clearing. "
                f"Last error: {last_line.strip()[:160]}"
            ),
        )

    # STALE (>=2h, often >24h) — the cause is almost certainly resolved
    # (env reload, top-up, deploy). Clear the sidecar so the dashboard
    # reflects reality. If we're wrong, the next scan will re-fire with
    # fresh evidence.
    age_label = "stale" if age >= STALE_WINDOW else "settling"
    msg = (
        f"{age_label} {category} spike on {bot_name} "
        f"(last error {int(age.total_seconds()/3600)}h ago) — cleared sidecar"
    )
    return _clear_sidecar(bot_name, msg)


def _clear_sidecar(bot_name: str, message: str) -> object:
    """Idempotent sidecar reset. Returns FixResult."""
    sidecar = _sidecar_for(bot_name)
    touched: list[str] = []
    try:
        if sidecar.exists():
            sidecar.unlink()
            touched.append(str(sidecar))
        # success even if nothing existed to delete (idempotent)
        return _make_result(
            success=True,
            changed_files=touched,
            message=message + (" (no-op: sidecar already absent)" if not touched else ""),
            risk_notes="health sidecar is regenerated by the bot on its next run",
        )
    except Exception as e:
        return _make_result(
            success=False,
            changed_files=[],
            message=f"failed to clear sidecar for {bot_name}: {e}",
            risk_notes=f"sidecar path: {sidecar}",
        )
