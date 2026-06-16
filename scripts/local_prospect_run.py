#!/usr/bin/env python3
"""SiteBoost CLI — orchestrates the 5-stage pipeline end-to-end.

Default mode is dry-run (no API spend, no emails sent). Live mode requires
explicit --live flag PER STAGE. Send stage additionally requires --confirm.

Quick start (dry-run end-to-end):
    python scripts/local_prospect_run.py --all --location "Boston, MA"

Stage-by-stage:
    python scripts/local_prospect_run.py --scan     --location "Boston, MA"
    python scripts/local_prospect_run.py --enrich   --scan <scan-file>
    python scripts/local_prospect_run.py --generate --enriched <enriched-file>
    python scripts/local_prospect_run.py --compose  --manifest <manifest>
    python scripts/local_prospect_run.py --send     --sequences <seq> --confirm --live
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Allow `python scripts/...` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import places_scanner, email_enricher, site_generator, cold_outreach

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("siteboost")


def stage_scan(args) -> Path:
    log.info(f"=== Stage 1: SCAN ({'LIVE' if args.live else 'DRY-RUN'}) ===")
    cats = args.categories.split(",") if args.categories else None
    prospects = places_scanner.scan(
        location=args.location, radius_m=args.radius,
        categories=cats, limit=args.limit, dry_run=not args.live,
    )
    log.info(f"  → {len(prospects)} targetable prospects")
    slug = args.location.lower().replace(",", "").replace(" ", "-")[:40]
    return places_scanner.SCANS_DIR / f"{time.strftime('%Y-%m-%d')}-{slug}.json"


def stage_enrich(args, scan_path: Path) -> Path:
    log.info(f"=== Stage 2: ENRICH ({'LIVE' if args.live else 'DRY-RUN'}) ===")
    return email_enricher.enrich_scan(scan_path, dry_run=not args.live)


def stage_generate(args, enriched_path: Path) -> Path:
    log.info(f"=== Stage 3: GENERATE ({'LIVE' if args.live else 'DRY-RUN'}) ===")
    return site_generator.generate_previews(enriched_path, dry_run=not args.live)


def stage_compose(args, manifest_path: Path) -> Path:
    log.info("=== Stage 4: COMPOSE ===")
    return cold_outreach.compose_sequences(manifest_path, sender_name=args.sender)


def stage_send(args, sequences_path: Path) -> dict:
    log.info(f"=== Stage 5: SEND ({'LIVE' if args.live else 'DRY-RUN'}) ===")
    result = cold_outreach.send_sequences(
        sequences_path, confirm=args.confirm, live=args.live,
        max_per_day=args.max_per_day,
    )
    log.info(f"  → {result}")
    return result


def write_run_report(run_dir: Path, scan_path: Path, enriched_path: Path,
                      manifest_path: Path, sequences_path: Path,
                      send_result: dict | None) -> Path:
    """05-report.md — campaign summary."""
    scan = json.loads(scan_path.read_text())
    enr = json.loads(enriched_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    seqs = json.loads(sequences_path.read_text()) if sequences_path.exists() else {"sequences": []}

    md = f"""# SiteBoost Campaign Report — {scan['_meta']['location']}

Generated: {time.strftime('%Y-%m-%d %H:%M')}

## Funnel

| Stage | Output |
|---|---|
| 1. Scanned | {scan['_meta']['n_total']} businesses in radius |
| 1a. Filtered (no website, US-only, has phone) | {scan['_meta']['n_targetable']} targetable |
| 2. Email enrichment hit | {enr['_meta']['n_enriched']} ({enr['_meta']['hit_rate']}) |
| 3. Site previews generated | {manifest['_meta']['n_previews']} |
| 4. Email sequences ready | {seqs.get('_meta', {}).get('n_sequences', 0)} |
| 5. Sent to Instantly | {send_result.get('n_sent_to_instantly', 0) if send_result else 'NOT SENT (dry-run or --confirm missing)'} |

## Expected outcomes

At industry reply rates for personalized site-preview cold outreach (~5-8%):
- {seqs.get('_meta', {}).get('n_sequences', 0)} sequences × 7% = **~{int(seqs.get('_meta', {}).get('n_sequences', 0) * 0.07)} replies expected over 14 days**
- Of replies, ~30% convert to a paid site at $497 = **~{int(seqs.get('_meta', {}).get('n_sequences', 0) * 0.07 * 0.3)} sales × $497 = ${int(seqs.get('_meta', {}).get('n_sequences', 0) * 0.07 * 0.3 * 497)}**
- Plus $49/mo recurring per closed sale

## Files

- Scan: `{scan_path.relative_to(scan_path.parent.parent.parent.parent)}`
- Enriched: `{enriched_path.relative_to(enriched_path.parent.parent.parent.parent)}`
- Previews manifest: `{manifest_path.relative_to(manifest_path.parent.parent.parent.parent.parent)}`
- Sequences: `{sequences_path.relative_to(sequences_path.parent.parent.parent.parent.parent)}`

## Next steps

1. **Review** the 4 stages of output. Adjust copy in any sequence that needs tweaking.
2. **Verify** outbound domain warmup status on Instantly.ai (min 14 days warm).
3. **Run send** with: `python scripts/local_prospect_run.py --send --sequences {sequences_path.name} --confirm --live`
4. **Wait 7 days**, then re-run with `--report-only` to pull reply stats from Instantly.
"""
    report = run_dir / "05-report.md"
    report.write_text(md)
    log.info(f"  → wrote {report}")
    return report


def main():
    p = argparse.ArgumentParser(description="SiteBoost — local-prospect outbound pipeline")
    # Stage selectors
    p.add_argument("--all", action="store_true", help="Run stages 1-4 (compose). Send is separate.")
    p.add_argument("--scan", action="store_true")
    p.add_argument("--enrich", action="store_true")
    p.add_argument("--generate", action="store_true")
    p.add_argument("--compose", action="store_true")
    p.add_argument("--send", action="store_true")
    # Stage inputs (autodetected if --all)
    p.add_argument("--scan-file", dest="scan_file", help="Path to scan JSON for --enrich")
    p.add_argument("--enriched", help="Path to enriched JSON for --generate")
    p.add_argument("--manifest", help="Path to preview manifest for --compose")
    p.add_argument("--sequences", help="Path to sequences JSON for --send")
    # Scan params
    p.add_argument("--location", default="Boston, MA")
    p.add_argument("--radius", type=int, default=5000)
    p.add_argument("--categories", default=None,
                   help="Comma-separated. Default uses DEFAULT_CATEGORIES in places_scanner.py")
    p.add_argument("--limit", type=int, default=50)
    # Compose params
    p.add_argument("--sender", default="Jay")
    # Send params
    p.add_argument("--max-per-day", dest="max_per_day", type=int, default=50)
    p.add_argument("--confirm", action="store_true", help="Required to actually send")
    # Mode flags
    p.add_argument("--live", action="store_true",
                   help="Use real APIs. Default = dry-run with fake data.")

    args = p.parse_args()

    if args.all:
        scan_path = stage_scan(args)
        enr_path = stage_enrich(args, scan_path)
        manifest_path = stage_generate(args, enr_path)
        seq_path = stage_compose(args, manifest_path)
        run_dir = manifest_path.parent
        write_run_report(run_dir, scan_path, enr_path, manifest_path, seq_path, None)
        print(f"\n✓ Pipeline complete (compose stage). Run --send --confirm --live to dispatch.")
        return

    if args.scan:
        stage_scan(args)
    if args.enrich:
        if not args.scan_file:
            print("--scan-file required for --enrich", file=sys.stderr); sys.exit(1)
        stage_enrich(args, Path(args.scan_file))
    if args.generate:
        if not args.enriched:
            print("--enriched required for --generate", file=sys.stderr); sys.exit(1)
        stage_generate(args, Path(args.enriched))
    if args.compose:
        if not args.manifest:
            print("--manifest required for --compose", file=sys.stderr); sys.exit(1)
        stage_compose(args, Path(args.manifest))
    if args.send:
        if not args.sequences:
            print("--sequences required for --send", file=sys.stderr); sys.exit(1)
        stage_send(args, Path(args.sequences))


if __name__ == "__main__":
    main()
