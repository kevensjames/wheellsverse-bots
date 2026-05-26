#!/usr/bin/env python3
"""
scripts/build_kit_pastes.py
─────────────────────────────────────────────────────────────────────────────
Convert the three Toodle email sequence playbooks into paste-ready text
blocks for Kit's (formerly ConvertKit) sequence-builder UI.

Input  (3 files, paste-ready already filled with real URLs):
  marketing/kdp_nurture_sequence.md
  marketing/welcome_sequence.md
  marketing/kdp_longtail_sequence.md

Output:
  out/kit_pastes/<sequence>/<NN>_<slug>.txt   ← one file per email
  out/kit_pastes/README.md                    ← paste-order instructions

Each output file is structured as:
  SUBJECT:
  <one line>

  BODY:
  <body text — paste this into the email-body field>

This script is read-only on your repo (only writes to out/) and never hits
the Kit API. It exists purely to make the manual paste step faster.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out" / "kit_pastes"

# (Sequence name as it will appear in Kit, source playbook, expected cadence)
SEQUENCES = [
    ("KDP Launch",    "marketing/kdp_nurture_sequence.md",
     ["immediate", "+1 day", "+2 days", "+2 days", "+2 days"]),
    ("Welcome",       "marketing/welcome_sequence.md",
     ["immediate", "+2 days"]),
    ("KDP Long-Tail", "marketing/kdp_longtail_sequence.md",
     ["immediate", "+7 days", "+9 days"]),
]


def slug(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:40] or "untitled"


def parse_emails(md_text: str) -> list[dict]:
    """
    Return [{"label", "subject", "body"}].

    Recognises both authoring conventions used in the playbooks:
      ## EMAIL N — short description    or    ### EMAIL N — ...
      **SUBJECT** ... **BODY** ... (next email heading OR --- terminates body)
    """
    # Drop YAML frontmatter if present (Welcome playbook doesn't have one).
    if md_text.startswith("---"):
        end = md_text.find("\n---", 3)
        if end != -1:
            md_text = md_text[end + 4:]

    # Strip everything from production-notes onward
    cut = md_text.find("<!--")
    if cut != -1:
        md_text = md_text[:cut]

    email_heading = re.compile(r"^#{2,3}\s+EMAIL\s+(\d+)[\s—\-:]+(.+)$", re.MULTILINE)
    starts = list(email_heading.finditer(md_text))

    emails: list[dict] = []
    for i, m in enumerate(starts):
        head_end = m.end()
        next_start = starts[i + 1].start() if i + 1 < len(starts) else len(md_text)
        block = md_text[head_end:next_start]
        # Stop at the "## After you paste into Kit" boundary
        stop = re.search(r"^##\s+After you paste into Kit", block, re.MULTILINE)
        if stop:
            block = block[: stop.start()]

        subject = _extract_field(block, "SUBJECT")
        body = _extract_field(block, "BODY")
        emails.append({
            "label": f"EMAIL {m.group(1)} — {m.group(2).strip()}",
            "subject": subject,
            "body": body,
        })
    return emails


def _extract_field(block: str, name: str) -> str:
    """
    Grab the prose after **NAME** until the next **NAME**-style marker,
    horizontal rule, or end of block. Trims surrounding blank lines.
    """
    pattern = rf"\*\*{name}\*\*\s*\n+(.*?)(?=\n\*\*[A-Z .]+\*\*\s*\n|\n---\s*\n|\Z)"
    m = re.search(pattern, block, re.DOTALL)
    if not m:
        return ""
    return m.group(1).strip()


def write_paste_file(out_dir: Path, idx: int, email: dict, delay: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = out_dir / f"{idx:02d}_{slug(email['label'])}.txt"
    fn.write_text(
        f"# {email['label']}\n"
        f"# Delay: {delay}\n"
        f"# Source: paste-ready — drop straight into Kit's sequence builder.\n"
        f"\n"
        f"SUBJECT:\n"
        f"{email['subject']}\n"
        f"\n"
        f"BODY:\n"
        f"{email['body']}\n",
        encoding="utf-8",
    )
    return fn


def build_readme(written: list[tuple[str, list[Path], list[str]]]) -> str:
    lines = [
        "# Toodle — Kit Sequence Pastes",
        "",
        "Each subdirectory below corresponds to one Kit sequence. Open each",
        "`.txt` file in order, copy the SUBJECT line into Kit's subject field,",
        "and copy everything under BODY into Kit's body field. Set the delay",
        "shown in the file header.",
        "",
        "Sequences must be created in Kit's UI first (no API for that). The",
        "name in Kit MUST match the env var below — case-insensitive lookup,",
        "but spaces and word boundaries count.",
        "",
        "| Sequence name in Kit | Env var | Files |",
        "| --- | --- | --- |",
    ]
    env_map = {
        "KDP Launch":    "KIT_SEQUENCE_KDP_NAME",
        "Welcome":       "KIT_SEQUENCE_WELCOME_NAME",
        "KDP Long-Tail": "KIT_SEQUENCE_KDP_LONGTAIL_NAME",
    }
    for seq_name, paths, _ in written:
        env = env_map.get(seq_name, "(no env var)")
        files = ", ".join(p.name for p in paths)
        lines.append(f"| {seq_name} | `{env}` | {files} |")

    lines += [
        "",
        "## After pasting",
        "",
        "Run the verifier to confirm Kit resolves all three by name:",
        "",
        "```bash",
        "/Users/jhonwheeler/wheellsverse_venv/bin/python scripts/toodle_kit_check.py",
        "```",
        "",
        "Exit 0 = ready to flip `KIT_DRY_RUN=false`. Exit 1 = one or more",
        "sequences missing (the verifier prints which).",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, list[Path], list[str]]] = []

    for seq_name, src_path, delays in SEQUENCES:
        src = ROOT / src_path
        if not src.exists():
            print(f"✗ source missing: {src_path}", file=sys.stderr)
            return 1

        emails = parse_emails(src.read_text(encoding="utf-8"))
        if not emails:
            print(f"✗ no emails parsed from {src_path}", file=sys.stderr)
            return 1
        if len(emails) != len(delays):
            print(f"⚠ {src_path}: parsed {len(emails)} emails but cadence "
                  f"defines {len(delays)}. Using as many as match.",
                  file=sys.stderr)

        seq_dir = OUT_DIR / slug(seq_name)
        paths = []
        for i, email in enumerate(emails, start=1):
            delay = delays[i - 1] if i - 1 < len(delays) else "(unspecified)"
            if not email["subject"] or not email["body"]:
                print(f"⚠ {src_path} email {i}: subject/body missing — review the source.",
                      file=sys.stderr)
            paths.append(write_paste_file(seq_dir, i, email, delay))

        written.append((seq_name, paths, delays))
        print(f"  {seq_name:18}  {len(paths)} emails → {seq_dir.relative_to(ROOT)}")

    readme = OUT_DIR / "README.md"
    readme.write_text(build_readme(written), encoding="utf-8")
    print(f"  README              → {readme.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
