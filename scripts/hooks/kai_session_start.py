#!/usr/bin/env python3
"""KAI SessionStart banner — surfaces governance state so a resumed session doesn't overstep:
recorded status ceiling, active markers (soak/enable/override), and the current SHA. Read-only,
stdout is added to context. Fails open."""
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
    bits = []
    try:
        st = open(os.path.join(root, ".kai-status")).read().strip()
        if st:
            bits.append("status ceiling: " + st.splitlines()[0])
    except Exception:
        pass
    active = [m for m in (".kai-soak-active", ".kai-allow-enable", ".kai-allow-shadow",
                          ".kai-allow-egress", ".kai-allow-device-enroll")
              if os.path.exists(os.path.join(root, m))]
    if ".kai-soak-active" in active:
        bits.append("SOAK ACTIVE — no deploy/teardown, don't touch costaging, keep flags off")
    overrides = [m for m in active if m.startswith(".kai-allow")]
    if overrides:
        bits.append("overrides present: " + ", ".join(overrides))
    try:
        sha = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        if sha:
            bits.append("HEAD: " + sha)
    except Exception:
        pass
    if bits:
        sys.stdout.write("KAI governance state — " + " | ".join(bits) + "\n")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
