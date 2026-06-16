#!/usr/bin/env python3
"""Export sequences to a Mailmeteor-friendly CSV.

Mailmeteor reads from Google Sheets and merges via Gmail. Free tier = 50/day,
no warmup needed (uses your existing Gmail's reputation). Perfect for the
zero-budget launch path.

Differs from export_sequences_csv.py (Instantly-format):
    - Plain column names (Mailmeteor uses {{Column}} syntax, no `custom_var_` prefix)
    - Each row = 1 prospect + ALL THREE touches as separate columns
    - Manual scheduling — you upload to Google Sheets, run Mailmeteor 3 times
      (Day 0, Day 3, Day 7), each time using a different subject/body column

Usage:
    python3 scripts/export_mailmeteor.py \\
        --sequences data/launches/siteboost/runs/<date>/04-sequences.json \\
        --out mailmeteor_upload.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def export(sequences_path: Path, out_path: Path) -> dict:
    data = json.loads(sequences_path.read_text())
    sequences = data.get("sequences", [])
    if not sequences:
        return {"ok": False, "reason": "no sequences in file"}

    # Mailmeteor column names — use {{ColumnName}} in Gmail template body
    fieldnames = [
        "Email",
        "FirstName",
        "LastName",
        "BusinessName",
        "PreviewURL",
        "Subject1", "Body1",
        "Subject2", "Body2",
        "Subject3", "Body3",
    ]

    rows = []
    for seq in sequences:
        name = (seq.get("to_name") or "").strip()
        parts = name.split(maxsplit=1)
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""

        # Extract preview URL from touch 1 body (first https://preview. line)
        body1 = seq["touches"][0]["body"]
        preview_url = ""
        for line in body1.splitlines():
            line = line.strip()
            if line.startswith("https://preview."):
                preview_url = line
                break

        rows.append({
            "Email":        seq["to_email"],
            "FirstName":    first,
            "LastName":     last,
            "BusinessName": seq.get("business_name", ""),
            "PreviewURL":   preview_url,
            "Subject1":     seq["touches"][0]["subject"],
            "Body1":        seq["touches"][0]["body"],
            "Subject2":     seq["touches"][1]["subject"],
            "Body2":        seq["touches"][1]["body"],
            "Subject3":     seq["touches"][2]["subject"],
            "Body3":        seq["touches"][2]["body"],
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    return {"ok": True, "n_rows": len(rows), "out": str(out_path)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sequences", required=True, help="Path to 04-sequences.json")
    p.add_argument("--out", default="mailmeteor_upload.csv")
    args = p.parse_args()

    seq_path = Path(args.sequences)
    if not seq_path.exists():
        print(f"ERROR: {seq_path} not found", file=sys.stderr)
        return 1

    result = export(seq_path, Path(args.out))
    if not result["ok"]:
        print(f"ERROR: {result['reason']}", file=sys.stderr)
        return 1

    print(f"✓ Wrote {result['n_rows']} rows → {result['out']}")
    print()
    print("  Next steps (Mailmeteor mail merge — $0 path):")
    print()
    print("  1. Open https://docs.google.com/spreadsheets/u/0/")
    print("  2. New blank sheet → File → Import → Upload → select")
    print(f"       {result['out']}")
    print("       Import location: Replace current sheet · Separator: Detect automatically")
    print()
    print("  3. Install Mailmeteor add-on (one-time):")
    print("       Extensions → Add-ons → Get add-ons → search 'Mailmeteor' → Install")
    print()
    print("  4. SEND TOUCH 1 (today):")
    print("       Extensions → Mailmeteor → Create new campaign")
    print("       Template: select 'Compose in Gmail'")
    print("       Subject: {{Subject1}}")
    print("       Body:    {{Body1}}")
    print("       From:    hello@wheellsverse.com  (use Gmail 'Send mail as')")
    print("       Recipient column: Email")
    print("       → Send")
    print()
    print("  5. SEND TOUCH 2 (3 days later):")
    print("       Same sheet, Mailmeteor new campaign")
    print("       Subject: {{Subject2}} · Body: {{Body2}}")
    print("       → Send")
    print()
    print("  6. SEND TOUCH 3 (7 days from touch 1):")
    print("       Subject: {{Subject3}} · Body: {{Body3}}")
    print("       → Send")
    print()
    print("  Free tier: 50 sends/day. Stay under that or upgrade Mailmeteor.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
