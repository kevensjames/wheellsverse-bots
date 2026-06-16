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
# Load .env with a LITERAL parser — NOT `. ./.env`. Shell-sourcing under set -u
# aborts on the first $-bearing value (e.g. NARAI_PASSWORD_HASH=$2b$… ) and
# silently drops EVERY key after it; brace/word-splitting also mangles JSON
# values (OLLAMA_MODEL_MAP) and unquoted spaces (EMAIL_FROM_NAME=WheellsVerse Bot).
# This reads KEY=VALUE literally — no shell evaluation — so every key reaches the
# daemon regardless of position or content. (Fixes the long-standing "key trapped
# below the landmine" problem: Composio, Supabase, Shopify, Runway, etc.)
load_env() {
    local f="$1" line key val
    [ -f "$f" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            ''|'#'*) continue ;;            # blank or comment
            [A-Za-z_]*=*) ;;                # KEY=VALUE shape
            *) continue ;;                  # anything else (stray lines)
        esac
        key="${line%%=*}"
        val="${line#*=}"
        case "$val" in                      # strip optional surrounding quotes
            \"*\") val="${val#\"}"; val="${val%\"}" ;;
            \'*\') val="${val#\'}"; val="${val%\'}" ;;
        esac
        export "$key=$val"
    done < "$f"
}
load_env .env
load_env backend/.env

# Fail loudly + early if any of these are missing.
: "${DATABASE_URL:?DATABASE_URL missing — fix .env}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY missing}"
: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY missing}"
# Admin auth: ADMIN_TOKEN is the canonical name. JWT_SECRET_KEY is the
# legacy fallback path (Path X transition). At least one must be set.
if [ -z "${ADMIN_TOKEN:-}" ] && [ -z "${JWT_SECRET_KEY:-}" ]; then
    echo "ADMIN_TOKEN (or legacy JWT_SECRET_KEY) missing — fix .env" >&2
    exit 1
fi

# Keep PATH sane for any subprocess uvicorn spawns.
export PATH="$VENV/bin:$PATH"

# Re-stamp static asset cache-busters with each asset's current mtime.
# Prevents the "user has cached old JS but HTML still points at it" class
# of bug (see commit b2b9af2 + scripts/stamp_static_assets.py header).
# Failure here is non-fatal — old stamps still work, just less aggressively.
"$VENV/bin/python" scripts/stamp_static_assets.py || \
    echo "WARNING: stamp_static_assets.py failed; cache-busters may be stale" >&2

# Exec — launchd captures stdout/stderr to the plist's *Path entries.
exec "$VENV/bin/uvicorn" app.main:app \
    --host 127.0.0.1 \
    --port 8001 \
    --workers 1 \
    --app-dir backend \
    --no-access-log
