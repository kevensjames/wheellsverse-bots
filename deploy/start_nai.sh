#!/bin/bash
# Wrapper invoked by the NAI LaunchAgent. Loads .env, validates required
# secrets, then exec's uvicorn in the repo's venv.
#
# Why a wrapper? Secrets live in .env (mode 600), never in the plist (which
# is world-readable under ~/Library/LaunchAgents/). The plist runs this
# script; this script does the sourcing.
#
# TCC note: this script is committed inside the repo at /Volumes/Wheellsverse,
# but macOS may block LaunchAgents executing from external volumes. If
# `launchctl list | grep wheellsverse` shows a non-zero exit status, either:
#   1. Grant "External Volumes" access to the LaunchAgent in System
#      Settings → Privacy & Security → Files and Folders.
#   2. Copy this script to ~/bin/start_nai.sh and point the plist there.
#   3. Pivot to the existing Login Item .app pattern (see 0006 decision log).

set -euo pipefail

REPO_ROOT="${NAI_REPO_ROOT:-/Volumes/Wheellsverse/wheellsverse_bots}"
VENV="$REPO_ROOT/.venv"

cd "$REPO_ROOT"

# Source .env so every key becomes a real env var (allexport).
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

# Fail loudly + early if any of these are missing.
: "${DATABASE_URL:?DATABASE_URL missing — fix .env}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY missing}"
: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY missing}"
: "${JWT_SECRET_KEY:?JWT_SECRET_KEY missing}"

# Keep PATH sane for any subprocess uvicorn spawns.
export PATH="$VENV/bin:$PATH"

# Exec — launchd captures stdout/stderr to the plist's *Path entries.
exec "$VENV/bin/uvicorn" app.main:app \
    --host 127.0.0.1 \
    --port 8001 \
    --workers 1 \
    --app-dir backend \
    --no-access-log
