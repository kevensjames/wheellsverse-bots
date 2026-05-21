#!/bin/bash
# Wrapper invoked by the NAI LaunchAgent. Loads .env, validates required
# secrets, then exec's uvicorn in the repo's venv.
#
# Why a wrapper? Secrets live in .env (mode 600), never in the plist (which
# is world-readable under ~/Library/LaunchAgents/). The plist runs this
# script; this script does the sourcing.
#
# Repo lives on the Mac mini's internal SSD (post-migration from
# /Volumes/Wheellsverse, see commit history). The original TCC concern
# from Stage 5 is moot now — internal-disk paths are always mounted before
# login and macOS does not gate them with the External-Volumes prompt.
# Override REPO_ROOT only if testing the wrapper from a different checkout.

set -euo pipefail

REPO_ROOT="${NAI_REPO_ROOT:-/Users/jhonwheeler/wheellsverse_bots}"
VENV="$REPO_ROOT/.venv"

cd "$REPO_ROOT"

# Source secrets. Two files, both contribute keys:
#   - root .env      → OPENAI_API_KEY, ANTHROPIC_API_KEY, etc. (~230 keys)
#   - backend/.env   → DATABASE_URL, JWT_SECRET_KEY (FastAPI's pydantic-settings
#                       loads this directly; the wrapper sources it too so the
#                       env-var assertions below catch a stale or missing value
#                       before uvicorn boots).
# Order matters: backend/.env LAST so its DATABASE_URL wins if both files
# define it.
#
# `set +e` during sourcing because root .env has some keys with unquoted
# spaces (e.g. EMAIL_FROM_NAME=WheellsVerse Bot) that make the shell treat
# the second word as a command. We tolerate those bad lines (the well-formed
# keys we care about — OPENAI_API_KEY, ANTHROPIC_API_KEY, DATABASE_URL,
# JWT_SECRET_KEY — all have no spaces and parse cleanly).
set +e
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env 2>/dev/null
    set +a
fi
if [ -f backend/.env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./backend/.env 2>/dev/null
    set +a
fi
set -e

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
