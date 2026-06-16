"""Notifier — Telegram first, file-log fallback.

Reuses the same TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars the rest
of the workspace uses (wvkey-backed, normally loaded from wheellsverse-bots
.env). If not configured, falls back to the autorepair logs directory."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"


def _load_env_from_wbots() -> None:
    """Best-effort load of TELEGRAM_* env vars from wheellsverse-bots/.env
    if they aren't already in the environment. Skips silently if no .env."""
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        return
    env_file = Path("/Volumes/Wheellsverse/wheellsverse-bots/.env")
    if not env_file.is_file():
        return
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            k = k.strip()
            if k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") and not os.getenv(k):
                os.environ[k] = v.strip().strip('"').strip("'")
    except Exception:
        pass


def _send_telegram(text: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": chat,
        "text": text[:4000],
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=body, timeout=8) as r:
            return r.getcode() == 200
    except Exception:
        return False


def _file_log(text: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    f = LOG_DIR / f"notify-{datetime.utcnow().strftime('%Y%m%d')}.log"
    with f.open("a") as fp:
        fp.write(f"[{datetime.utcnow().isoformat()}Z]\n{text}\n\n")


def format_summary(summary: dict) -> str:
    n = summary.get("findings_count", 0)
    fixed = summary.get("fixes_succeeded", 0)
    attempted = summary.get("fixes_attempted", 0)
    elapsed = summary.get("elapsed_s", 0)

    lines = [
        "*SUPREMA autorepair* — cycle complete",
        f"⏱ {elapsed}s · 📋 {n} findings · 🛠 {fixed}/{attempted} auto-fixed",
    ]

    # By-project tally
    by_proj: dict[str, int] = {}
    for f in summary.get("findings", []):
        by_proj[f["project"]] = by_proj.get(f["project"], 0) + 1
    if by_proj:
        lines.append("")
        lines.append("*Findings by project:*")
        for proj, count in sorted(by_proj.items(), key=lambda x: -x[1]):
            lines.append(f"  • `{proj}`: {count}")

    # Top findings (high severity first)
    high = [f for f in summary.get("findings", []) if f.get("severity") == "high"]
    if high:
        lines.append("")
        lines.append("*High-severity findings* (need attention):")
        for f in high[:5]:
            lines.append(f"  • `{f['project']}`: {f['pattern']} — {f['evidence'][:80]}")

    # Successful fixes
    successes = [(o["finding"], o["result"]) for o in summary.get("fix_outcomes", [])
                 if o["result"].get("success") and o["result"].get("changed_files")]
    if successes:
        lines.append("")
        lines.append("*Auto-fixes applied:*")
        for fnd, res in successes[:10]:
            files = ", ".join(res.get("changed_files", []))[:80]
            lines.append(f"  ✓ `{fnd['project']}`: {fnd['pattern']} → {files}")

    return "\n".join(lines)


def emit(summary: dict) -> None:
    _load_env_from_wbots()
    text = format_summary(summary)
    sent = _send_telegram(text)
    # Always also file-log for forensic trail
    _file_log(("[telegram OK] " if sent else "[telegram NOT sent] ") + text)
