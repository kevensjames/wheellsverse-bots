#!/bin/bash
# Runs the security worker ONLY when an on-demand scan was requested.
set -euo pipefail
REPO="$HOME/wheellsverse_bots"
DIR="${KAI_SECURITY_DIR:-$REPO/data/security}"
if [ -f "$DIR/.request" ]; then
  # venv python (system python3 lacks pydantic + the app tree). PATH/scopes come
  # from the launchd plist's EnvironmentVariables.
  exec "$REPO/.venv/bin/python" "$REPO/scripts/security_worker.py"
fi
