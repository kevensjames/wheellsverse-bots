#!/usr/bin/env python3
"""
scripts/populate_kit_sequences.py
─────────────────────────────────────────────────────────────────────────────
Populate Kit sequences with the Toodle nurture emails via the v4 API.

Why this exists: Kit's v4 API does NOT have a "create a sequence" endpoint
(the sequence container must be created in the UI), but it DOES support
`POST /v4/sequences/{id}/emails` to add individual emails. This script
reads the paste-ready .txt files in out/kit_pastes/ and posts every email
to the matching sequence — converting the human-readable cadence header
("immediate", "+1 day", "+2 days") into Kit's delay_value/delay_unit pair.

Emails are created with published=false so you can review them in Kit's
UI before activating the sequence. Dupes are skipped (matched by subject)
so re-runs are safe.

Usage:
  /Users/jhonwheeler/wheellsverse_venv/bin/python scripts/populate_kit_sequences.py
  (reads KIT_API_KEY + KIT_DRY_RUN from .env)

Exit codes:
  0 = all expected emails created (or already present)
  1 = at least one expected sequence missing in Kit (create empty containers in UI first)
  2 = Kit API unreachable or KIT_API_KEY not set
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import html
import logging
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.kit import get_kit  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("populate_kit_sequences")

# (sequence_name_in_kit, paste_subdir under out/kit_pastes/)
EXPECTED = [
    ("KDP Launch",    "kdp_launch"),
    ("Welcome",       "welcome"),
    ("KDP Long-Tail", "kdp_long_tail"),
]
PASTES_DIR = ROOT / "out" / "kit_pastes"

_URL_RE = re.compile(r"(https?://[^\s<>\"]+)")


def parse_delay(raw: str) -> tuple[int, str]:
    """
    "immediate"   → (0, "hours")
    "+1 day"      → (1, "days")
    "+N days"     → (N, "days")
    "+N hours"    → (N, "hours")
    """
    s = raw.strip().lower()
    if s in {"immediate", "+0", "+0 days", "now"}:
        return 0, "hours"
    m = re.match(r"^\+?\s*(\d+)\s*(day|days|hour|hours)\b", s)
    if not m:
        raise ValueError(f"unrecognised delay: {raw!r}")
    n = int(m.group(1))
    unit = "days" if m.group(2).startswith("day") else "hours"
    return n, unit


def parse_paste(path: Path) -> dict:
    """
    Each .txt is:
      # EMAIL N — label
      # Delay: <delay-spec>
      # Source: ...

      SUBJECT:
      <one line>

      BODY:
      <prose, paragraphs separated by blank lines>
    """
    text = path.read_text(encoding="utf-8")
    # Header
    delay_m = re.search(r"^#\s*Delay:\s*(.+)$", text, re.MULTILINE)
    delay_raw = delay_m.group(1).strip() if delay_m else "immediate"

    # Subject + body
    subj_m = re.search(r"^SUBJECT:\s*\n(.+?)\n", text, re.MULTILINE)
    body_m = re.search(r"^BODY:\s*\n(.*)$", text, re.DOTALL | re.MULTILINE)
    if not subj_m or not body_m:
        raise ValueError(f"{path}: missing SUBJECT or BODY section")
    return {
        "subject": subj_m.group(1).strip(),
        "body_plain": body_m.group(1).strip(),
        "delay_raw": delay_raw,
    }


def plain_to_html(text: str) -> str:
    """Minimal markdown-ish → HTML: paragraphs on blank lines, auto-link URLs."""
    out_parts: list[str] = []
    for para in re.split(r"\n\s*\n", text.strip()):
        escaped = html.escape(para.strip())
        linked = _URL_RE.sub(
            lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', escaped)
        # Single newlines inside a paragraph → <br/>
        linked = linked.replace("\n", "<br/>")
        out_parts.append(f"<p>{linked}</p>")
    return "\n".join(out_parts)


def list_pastes(subdir: str) -> list[Path]:
    d = PASTES_DIR / subdir
    if not d.is_dir():
        return []
    return sorted(d.glob("*.txt"))


def populate() -> int:
    client = get_kit()
    if not client.is_configured():
        log.error("KIT_API_KEY not set — add to .env first.")
        return 2

    account = client.get_account()
    if "error" in account or "account" not in account:
        log.error("cannot reach Kit API: %s", account)
        return 2
    log.info("connected to Kit account '%s' (dry_run=%s)",
             (account.get("account") or {}).get("name"), client.dry_run)

    sequences = client.list_sequences()
    by_name = {(s.get("name") or "").strip().lower(): s for s in sequences}

    total_created = 0
    total_skipped_dupe = 0
    total_skipped_dry = 0
    missing: list[str] = []
    errors: list[tuple[str, str]] = []

    for seq_name, subdir in EXPECTED:
        sequence = by_name.get(seq_name.strip().lower())
        if not sequence:
            log.warning("[%s] sequence does NOT exist in Kit — create empty "
                        "container in UI first, then re-run this script.",
                        seq_name)
            missing.append(seq_name)
            continue

        seq_id = int(sequence["id"])
        existing = client.list_sequence_emails(seq_id)
        existing_subjects = {(e.get("subject") or "").strip().lower() for e in existing}

        pastes = list_pastes(subdir)
        log.info("[%s] sequence_id=%s, %d existing emails, %d paste files",
                 seq_name, seq_id, len(existing), len(pastes))

        for position, path in enumerate(pastes):
            try:
                parsed = parse_paste(path)
            except Exception as e:
                errors.append((path.name, str(e)))
                continue

            subject = parsed["subject"]
            if subject.strip().lower() in existing_subjects:
                log.info("  ↷ skip dupe (already in sequence): %s", subject)
                total_skipped_dupe += 1
                continue

            delay_value, delay_unit = parse_delay(parsed["delay_raw"])
            content_html = plain_to_html(parsed["body_plain"])

            log.info("  → create [pos=%d, %d %s] %s",
                     position, delay_value, delay_unit, subject)

            result = client.create_sequence_email(
                seq_id,
                subject=subject,
                delay_value=delay_value,
                delay_unit=delay_unit,
                content=content_html,
                position=position,
                published=False,    # user reviews + publishes in Kit UI
            )
            if result.get("_dry_run"):
                total_skipped_dry += 1
                continue
            if "error" in result or result.get("status", 0) >= 400:
                errors.append((subject, str(result)[:300]))
                continue
            total_created += 1

    print()
    print("─" * 60)
    print(f" sequences expected : {len(EXPECTED)}")
    print(f" sequences missing  : {len(missing)}  ({', '.join(missing) if missing else '—'})")
    print(f" emails created     : {total_created}")
    print(f" emails skipped dup : {total_skipped_dupe}")
    if client.dry_run:
        print(f" emails dry-run     : {total_skipped_dry}  (no real POST sent)")
    print(f" errors             : {len(errors)}")
    for subj, err in errors:
        print(f"   • {subj}: {err}")
    print("─" * 60)

    if missing:
        print("\nNext step: open https://app.kit.com → New Sequence → name each one EXACTLY:")
        for name in missing:
            print(f"   '{name}'")
        print("Leave them empty — this script fills the emails. Then re-run.")
        return 1

    if total_created == 0 and not client.dry_run and total_skipped_dupe == 0:
        log.warning("no emails created and no dupes — paste files may be empty?")
    return 0


if __name__ == "__main__":
    sys.exit(populate())
