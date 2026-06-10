"""NAI tool: local_prospect.

Exposes the SiteBoost outbound pipeline as a NAI-callable tool so the
companion AI can run prospecting autonomously on a schedule (e.g., weekly
scan against a new ZIP) and surface results for human review.

NAI tool contract:
    name: local_prospect
    schema: {
        "action": "scan" | "enrich" | "generate" | "compose" | "send" | "all" | "status",
        "location": str (required for scan/all),
        "radius_m": int (default 5000),
        "categories": list[str] (optional),
        "limit": int (default 50),
        "live": bool (default False — dry-run),
        "confirm": bool (only honored for send action),
    }

The tool is safe by default:
    - Dry-run unless live=True
    - Send action additionally requires confirm=True
    - Refuses GDPR regions
    - Refuses wheellsverse.com as outbound domain

Mount in NAI:
    from narai.tools.local_prospect_tool import LocalProspectTool
    tool_registry.register(LocalProspectTool())
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Make the repo's core/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core import places_scanner, email_enricher, site_generator, cold_outreach

logger = logging.getLogger("narai.local_prospect")

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = ROOT / "data" / "launches" / "siteboost" / "runs"


class LocalProspectTool:
    """NAI tool for autonomous local-prospect campaigns."""

    name = "local_prospect"
    description = (
        "Scan Google Maps for local businesses without websites, build personalized "
        "site previews, draft cold-email sequences, and (with explicit confirmation) "
        "dispatch them via the outbound email service. Use to grow SiteBoost revenue."
    )
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["scan", "enrich", "generate", "compose", "send", "all", "status"],
                "description": "Which stage to run.",
            },
            "location": {
                "type": "string",
                "description": "City+state or ZIP (US only). Required for scan/all.",
            },
            "radius_m": {"type": "integer", "default": 5000},
            "categories": {
                "type": "array", "items": {"type": "string"},
                "description": "Places category slugs to scan. Defaults to broad mix.",
            },
            "limit": {"type": "integer", "default": 50},
            "live": {"type": "boolean", "default": False},
            "confirm": {"type": "boolean", "default": False},
        },
        "required": ["action"],
    }

    # ── Public ──────────────────────────────────────────────────────────

    def call(self, args: dict[str, Any]) -> dict[str, Any]:
        action = args.get("action")
        live = bool(args.get("live", False))
        try:
            if action == "all":
                return self._run_all(args, live=live)
            if action == "scan":
                return self._run_scan(args, live=live)
            if action == "status":
                return self._run_status()
            return {"ok": False, "error": f"Unsupported action {action!r} for autonomous mode. "
                    f"Use action=all for full pipeline, or call CLI directly for per-stage."}
        except Exception as e:
            logger.exception("local_prospect tool error")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ── Implementations ─────────────────────────────────────────────────

    def _run_scan(self, args: dict, live: bool) -> dict:
        loc = args.get("location")
        if not loc:
            return {"ok": False, "error": "location required for scan action"}
        prospects = places_scanner.scan(
            location=loc,
            radius_m=int(args.get("radius_m", 5000)),
            categories=args.get("categories"),
            limit=int(args.get("limit", 50)),
            dry_run=not live,
        )
        return {
            "ok": True, "action": "scan",
            "n_targetable": len(prospects),
            "location": loc, "live": live,
            "next": "Call again with action=all to continue through compose stage.",
        }

    def _run_all(self, args: dict, live: bool) -> dict:
        loc = args.get("location")
        if not loc:
            return {"ok": False, "error": "location required for all action"}

        # Stage 1
        prospects = places_scanner.scan(
            location=loc, radius_m=int(args.get("radius_m", 5000)),
            categories=args.get("categories"),
            limit=int(args.get("limit", 50)),
            dry_run=not live,
        )
        slug = loc.lower().replace(",", "").replace(" ", "-")[:40]
        scan_path = places_scanner.SCANS_DIR / f"{time.strftime('%Y-%m-%d')}-{slug}.json"

        # Stage 2
        enr_path = email_enricher.enrich_scan(scan_path, dry_run=not live)

        # Stage 3
        manifest_path = site_generator.generate_previews(enr_path, dry_run=not live)

        # Stage 4
        seq_path = cold_outreach.compose_sequences(manifest_path, sender_name="Jay")

        return {
            "ok": True, "action": "all",
            "stages_completed": ["scan", "enrich", "generate", "compose"],
            "n_targetable": len(prospects),
            "files": {
                "scan": str(scan_path.relative_to(ROOT)),
                "enriched": str(enr_path.relative_to(ROOT)),
                "manifest": str(manifest_path.relative_to(ROOT)),
                "sequences": str(seq_path.relative_to(ROOT)),
            },
            "next": (
                "Sequences are queued. NAI will NOT auto-send — human review required. "
                "Review files above, then call CLI: "
                "`python scripts/local_prospect_run.py --send --sequences <path> --confirm --live`"
            ),
            "live": live,
        }

    def _run_status(self) -> dict:
        """Summarize recent campaigns. Useful for NAI to report 'what's been running'."""
        if not RUNS_DIR.exists():
            return {"ok": True, "runs": [], "note": "No campaigns yet."}
        runs = []
        for run_dir in sorted(RUNS_DIR.glob("*"), reverse=True)[:10]:
            if not run_dir.is_dir():
                continue
            report = run_dir / "05-report.md"
            manifest = run_dir / "03-previews-manifest.json"
            n_previews = 0
            if manifest.exists():
                try:
                    n_previews = json.loads(manifest.read_text())["_meta"]["n_previews"]
                except Exception:
                    pass
            runs.append({
                "name": run_dir.name,
                "n_previews": n_previews,
                "has_report": report.exists(),
            })
        return {"ok": True, "runs": runs}


# Convenience: importable singleton
local_prospect_tool = LocalProspectTool()

if __name__ == "__main__":
    # Smoke test (dry-run)
    result = local_prospect_tool.call({"action": "all", "location": "Boston, MA", "limit": 10})
    print(json.dumps(result, indent=2))
