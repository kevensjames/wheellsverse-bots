#!/usr/bin/env python3
"""Export composed sequences to a CSV that Instantly/Smartlead/Lemlist can import.

Use this if you don't want to set up the INSTANTLY_API_KEY integration —
just upload the CSV manually in the Instantly UI.

CSV columns match Instantly's lead-import format exactly:
    email, first_name, last_name, company_name, custom_var_1, ...

Each prospect produces ONE row with multiple custom_var columns:
    custom_var_preview_url   — the live preview URL
    custom_var_touch_1_subject / custom_var_touch_1_body
    custom_var_touch_2_subject / custom_var_touch_2_body
    custom_var_touch_3_subject / custom_var_touch_3_body

In Instantly: create a 3-step campaign, paste each subject + body into the
corresponding step, set step gaps to 3 days each, upload this CSV as leads.

Usage:
    python3 scripts/export_sequences_csv.py \\
        --sequences data/launches/siteboost/runs/<date>/04-sequences.json \\
        --out instantly_upload.csv
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

    fieldnames = [
        "email", "first_name", "last_name", "company_name",
        "custom_var_preview_url",
        "custom_var_touch_1_subject", "custom_var_touch_1_body",
        "custom_var_touch_2_subject", "custom_var_touch_2_body",
        "custom_var_touch_3_subject", "custom_var_touch_3_body",
    ]

    rows = []
    for seq in sequences:
        name = (seq.get("to_name") or "").strip()
        parts = name.split(maxsplit=1)
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""

        # Extract preview URL from touch 1 body if present
        body1 = seq["touches"][0]["body"]
        preview_url = ""
        for line in body1.splitlines():
            line = line.strip()
            if line.startswith("https://preview."):
                preview_url = line
                break

        row = {
            "email": seq["to_email"],
            "first_name": first,
            "last_name": last,
            "company_name": seq.get("business_name", ""),
            "custom_var_preview_url": preview_url,
            "custom_var_touch_1_subject": seq["touches"][0]["subject"],
            "custom_var_touch_1_body":    seq["touches"][0]["body"],
            "custom_var_touch_2_subject": seq["touches"][1]["subject"],
            "custom_var_touch_2_body":    seq["touches"][1]["body"],
            "custom_var_touch_3_subject": seq["touches"][2]["subject"],
            "custom_var_touch_3_body":    seq["touches"][2]["body"],
        }
        rows.append(row)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    return {"ok": True, "n_rows": len(rows), "out": str(out_path)}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sequences", required=True, help="Path to 04-sequences.json")
    p.add_argument("--out", default="instantly_upload.csv")
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
    print("  Next steps (Instantly):")
    print("    1. Log in at https://app.instantly.ai")
    print("    2. Create a campaign → name it 'SiteBoost-Boston-2026-06' (or similar)")
    print("    3. Add 3 email steps with 3-day gaps between each")
    print("       In each step, use the custom vars from the CSV:")
    print("         Step 1 subject: {{custom_var_touch_1_subject}}")
    print("         Step 1 body:    {{custom_var_touch_1_body}}")
    print("         Step 2 subject: {{custom_var_touch_2_subject}}")
    print("         Step 2 body:    {{custom_var_touch_2_body}}")
    print("         Step 3 subject: {{custom_var_touch_3_subject}}")
    print("         Step 3 body:    {{custom_var_touch_3_body}}")
    print(f"    4. Click 'Add leads' → 'Upload CSV' → select {result['out']}")
    print("    5. Confirm column mapping (Instantly auto-detects standard headers)")
    print("    6. Daily cap: 50/day until warmup complete (Day 28+)")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
