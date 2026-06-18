#!/bin/bash
# Runs the security worker ONLY when an on-demand scan was requested.
set -euo pipefail
REPO="$HOME/wheellsverse_bots"
DIR="${KAI_SECURITY_DIR:-$REPO/data/security}"
if [ -f "$DIR/.request" ]; then
  exec /usr/bin/python3 "$REPO/scripts/security_worker.py"
fi
