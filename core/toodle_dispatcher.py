"""
core/toodle_dispatcher.py
─────────────────────────────────────────────────────────────────────────────
Path B: SMTP-based per-subscriber email sender for the Toodle nurture flow.

Why this exists: Kit's free tier blocks sequence creation, so the Toodle
Capture Agent writes per-email rows into `toodle_email_queue` at capture
time. This dispatcher walks the queue and sends each due email via the
existing Gmail SMTP credentials (`EMAIL_USER`, `EMAIL_PASSWORD` env vars)
that `core/lead_capture.py` already uses.

Rate-limit: ≤ 60 sends per dispatcher run, ≤ 1 send per second within a
run. Gmail personal accounts cap around 500/day; Workspace around 2,000.
This keeps us well under either ceiling.

Run modes:
  process_due(limit=N, dry_run=False)
    Loads up to N rows where status='pending' and scheduled_for <= now,
    sends each via SMTP, marks 'sent' / 'failed' with details.

Cron entry (every 15 min):
  */15 * * * * cd /Volumes/Wheellsverse/wheellsverse-bots && \\
      /Users/jhonwheeler/wheellsverse_venv/bin/python \\
      scripts/dispatch_toodle_emails.py >> data/toodle_dispatch.log 2>&1
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import os
import re
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger("toodle_dispatcher")

PASTES_DIR = ROOT / "out" / "kit_pastes"

# SMTP config
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "WheellsVerse")
BRAND = os.getenv("BRAND_NAME", "WheellsVerse")

# Self-imposed rate limits
MAX_PER_RUN = int(os.getenv("TOODLE_DISPATCH_MAX_PER_RUN", "60"))
MIN_INTERVAL_SECONDS = float(os.getenv("TOODLE_DISPATCH_MIN_INTERVAL", "1.0"))

_URL_RE = re.compile(r"(https?://[^\s<>\"]+)")


def is_smtp_configured() -> bool:
    return bool(EMAIL_USER and EMAIL_PASSWORD)


# ── Paste-file parsing (reused from populate_kit_sequences.py philosophy) ────

def _paste_file_for(slug: str, position: int) -> Optional[Path]:
    """Locate `out/kit_pastes/<slug>/<NN>_*.txt` where NN = position+1."""
    seq_dir = PASTES_DIR / slug
    if not seq_dir.is_dir():
        return None
    prefix = f"{position + 1:02d}_"
    for f in sorted(seq_dir.glob("*.txt")):
        if f.name.startswith(prefix):
            return f
    return None


def _parse_paste(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    subj_m = re.search(r"^SUBJECT:\s*\n(.+?)\n", text, re.MULTILINE)
    body_m = re.search(r"^BODY:\s*\n(.*)$", text, re.DOTALL | re.MULTILINE)
    if not subj_m or not body_m:
        raise ValueError(f"{path}: missing SUBJECT or BODY section")
    return {
        "subject": subj_m.group(1).strip(),
        "body_plain": body_m.group(1).strip(),
    }


def _personalize(text: str, first_name: str) -> str:
    """{{first_name}} placeholder replacement with a sensible fallback."""
    name = (first_name or "there").strip()
    return text.replace("{{first_name}}", name)


def _plain_to_html(text: str) -> str:
    """Paragraphs on blank lines, auto-linked URLs, html-escaped specials."""
    parts: list[str] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        escaped = html_lib.escape(para.strip())
        linked = _URL_RE.sub(
            lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', escaped)
        linked = linked.replace("\n", "<br/>")
        parts.append(f"<p>{linked}</p>")
    return "\n".join(parts)


# ── SMTP send ────────────────────────────────────────────────────────────────

def _send_smtp(to_email: str, subject: str, body_plain: str, body_html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{EMAIL_FROM_NAME} <{EMAIL_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_plain, "plain"))
    msg.attach(MIMEText(body_html, "html"))
    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=30) as server:
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(msg)


# ── Dispatcher ───────────────────────────────────────────────────────────────

async def process_due(
    session_factory,
    *,
    limit: int = MAX_PER_RUN,
    dry_run: bool = False,
) -> dict:
    """
    Walk the queue, send up to `limit` due rows.
    Returns: {"sent", "failed", "skipped_dry", "remaining_due"}
    """
    # Import here to avoid circular import at module-load time
    from narai.api.routes.toodle import ToodleEmailQueue

    sent = 0
    failed = 0
    skipped_dry = 0
    errors: list[str] = []
    cap = max(1, min(limit, MAX_PER_RUN))

    now = datetime.now(timezone.utc)

    async with session_factory() as session:  # type: AsyncSession
        stmt = (
            select(ToodleEmailQueue)
            .where(ToodleEmailQueue.status == "pending")
            .where(ToodleEmailQueue.scheduled_for <= now)
            .order_by(ToodleEmailQueue.scheduled_for.asc())
            .limit(cap)
        )
        due_rows = (await session.execute(stmt)).scalars().all()
        log.info("[dispatcher] found %d due rows (cap=%d, dry_run=%s)",
                 len(due_rows), cap, dry_run)

        for row in due_rows:
            paste_path = _paste_file_for(row.sequence_slug, row.position)
            if not paste_path:
                row.status = "failed"
                row.error = f"paste file missing for {row.sequence_slug} pos={row.position}"
                row.sent_at = now
                failed += 1
                continue

            try:
                parsed = _parse_paste(paste_path)
            except Exception as e:
                row.status = "failed"
                row.error = f"parse error: {e}"
                row.sent_at = now
                failed += 1
                continue

            subject = _personalize(parsed["subject"], row.first_name)
            body_plain = _personalize(parsed["body_plain"], row.first_name)
            body_html = _plain_to_html(body_plain)

            if dry_run or not is_smtp_configured():
                row.status = "dry_run"
                row.sent_at = now
                row.error = None if is_smtp_configured() else "SMTP not configured (dry_run)"
                skipped_dry += 1
                log.info("[dispatcher DRY] would send to=%s subject=%s",
                         row.email, subject)
                continue

            try:
                # In-process throttle: never faster than MIN_INTERVAL_SECONDS
                if sent > 0:
                    time.sleep(MIN_INTERVAL_SECONDS)
                # SMTP is sync; offload so the event loop isn't blocked
                await asyncio.to_thread(
                    _send_smtp, row.email, subject, body_plain, body_html
                )
                row.status = "sent"
                row.sent_at = datetime.now(timezone.utc)
                row.error = None
                sent += 1
                log.info("[dispatcher OK] to=%s subject=%s", row.email, subject)
            except Exception as e:
                row.status = "failed"
                row.sent_at = datetime.now(timezone.utc)
                row.error = str(e)[:1000]
                failed += 1
                errors.append(f"{row.email}: {e}")
                log.error("[dispatcher ERR] to=%s err=%s", row.email, e)

        await session.commit()

        # Count what's still due for the next run
        remaining_stmt = (
            select(func.count(ToodleEmailQueue.id))
            .where(ToodleEmailQueue.status == "pending")
            .where(ToodleEmailQueue.scheduled_for <= datetime.now(timezone.utc))
        )
        remaining = (await session.execute(remaining_stmt)).scalar_one()

    return {
        "sent": sent,
        "failed": failed,
        "skipped_dry": skipped_dry,
        "remaining_due": int(remaining),
        "errors": errors,
    }
