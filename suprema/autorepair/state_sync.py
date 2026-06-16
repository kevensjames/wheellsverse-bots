"""State sync — pushes the latest scan state into the wheellsverse-bots
repo so the prod /admin SUPREMA panel can render real data.

Without this, the Mac mini's cron writes state locally but Railway
containers can't see it — the panel shows the "no scan yet" empty
state forever. With this, every cron run commits the freshest state
JSON into wheellsverse-bots/data/suprema-latest.json, pushes it, and
Railway redeploys (or just serves the new file on next request via
the standard fastapi file-read path).

Design:
  - Run after run_cycle() completes
  - Copy state/last-run.json → wheellsverse-bots/data/suprema-latest.json
  - git add + commit + push (with skip if no actual content change)
  - Failure is non-fatal: state still written locally, just won't reach prod
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("suprema.autorepair")

WBOTS_REPO = Path("/Volumes/Wheellsverse/wheellsverse-bots")
SYNCED_STATE_FILE = WBOTS_REPO / "data" / "suprema-latest.json"


def _git(args: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def sync_to_wheellsverse_bots(state_source: Path,
                              push: bool = True) -> dict[str, str | bool]:
    """Copy the latest state JSON into wheellsverse-bots/data/ and optionally
    commit + push. Returns a status dict for logging.

    Safe to call when wheellsverse-bots isn't reachable (e.g. SSD ejected) —
    will return ok=False without raising."""
    if not state_source.is_file():
        return {"ok": False, "reason": "state source missing"}
    if not WBOTS_REPO.is_dir():
        return {"ok": False, "reason": f"wheellsverse-bots not at {WBOTS_REPO}"}

    SYNCED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Compute hash of source content to detect no-op changes (avoid empty commits)
    try:
        new_bytes = state_source.read_bytes()
    except Exception as e:
        return {"ok": False, "reason": f"read source failed: {e}"}

    # If the destination already has the same content, skip the whole sync
    if SYNCED_STATE_FILE.is_file():
        try:
            if SYNCED_STATE_FILE.read_bytes() == new_bytes:
                return {"ok": True, "no_change": True,
                        "message": "state identical to last sync — skipped"}
        except Exception:
            pass

    # Add a small wrapper indicating sync metadata
    try:
        payload = json.loads(new_bytes)
        payload["_sync"] = {
            "source": str(state_source),
            "synced_at": payload.get("started_at"),
        }
        SYNCED_STATE_FILE.write_text(json.dumps(payload, indent=2))
    except Exception as e:
        # Fall back to raw copy if JSON manipulation fails
        try:
            shutil.copyfile(state_source, SYNCED_STATE_FILE)
        except Exception as e2:
            return {"ok": False, "reason": f"copy failed: {e2} (json: {e})"}

    if not push:
        return {"ok": True, "message": "state copied; push skipped"}

    # git add + commit + push
    try:
        _git(["add", "data/suprema-latest.json"], WBOTS_REPO)

        # Anything to commit?
        diff = _git(["diff", "--cached", "--quiet"], WBOTS_REPO)
        if diff.returncode == 0:
            return {"ok": True, "no_change": True,
                    "message": "nothing staged after add (idempotent)"}

        n_findings = 0
        try:
            n_findings = int(json.loads(new_bytes).get("findings_count", 0))
        except Exception:
            pass

        commit_msg = (
            f"chore(suprema): state sync — {n_findings} findings\n\n"
            "Synced by SUPREMA autorepair after a scan cycle. The prod /admin "
            "SUPREMA panel reads this file to display real data.\n\n"
            "Generated-By: suprema-autorepair-state-sync"
        )
        cmt = _git(["commit", "-m", commit_msg, "--no-verify"], WBOTS_REPO)
        if cmt.returncode != 0:
            return {"ok": False, "reason": f"commit failed: {cmt.stderr[:200]}"}

        # Try pushing to github first (the deploy chain), then gitea (mirror)
        results = {}
        for remote in ("github", "origin"):
            r = _git(["push", remote, "main"], WBOTS_REPO, timeout=60)
            results[remote] = "ok" if r.returncode == 0 else r.stderr[:120]
        log.info(f"state sync pushed: {results}")
        return {"ok": True, "pushes": results}

    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "git operation timed out"}
    except Exception as e:
        return {"ok": False, "reason": f"git operation crashed: {e}"}
