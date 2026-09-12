#!/usr/bin/env python3
"""KAI PreCompact state-save — writes the current SHA + status ceiling + active markers to
.remember/kai-precompact.md so the governance context survives a context compaction (the
"commit/handoff after every phase" lesson). Read-only w.r.t. the repo; fails open."""
import json
import os
import subprocess
import sys


def main():
    try:
        json.load(sys.stdin)
    except Exception:
        pass
    root = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    lines = ["# KAI pre-compact state", ""]
    try:
        sha = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        branch = subprocess.run(["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        lines.append(f"- HEAD: {sha} ({branch})")
    except Exception:
        pass
    try:
        lines.append("- status ceiling: " + open(os.path.join(root, ".kai-status")).read().strip())
    except Exception:
        pass
    active = [m for m in os.listdir(root) if m.startswith(".kai-")] if os.path.isdir(root) else []
    if active:
        lines.append("- active markers: " + ", ".join(sorted(active)))
    lines.append("- reminder: keep KAI_*_ENABLED off; no deploy while a soak is active; "
                 "claim only what has evidence.")
    try:
        d = os.path.join(root, ".remember")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "kai-precompact.md"), "w") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
