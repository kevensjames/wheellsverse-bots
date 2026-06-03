#!/usr/bin/env bash
# scripts/finish_toodle_launch.sh
# ─────────────────────────────────────────────────────────────────────────────
# Runs the entire post-Kit-UI portion of the Toodle launch in one command.
#
# PRECONDITION (the one thing only you can do):
#   You've clicked "New Sequence" three times in https://app.kit.com with
#   these exact names:   KDP Launch   Welcome   KDP Long-Tail
#   (Kit v4 has no create-sequence API — verified via 403 from
#   POST /v4/sequences with a real key.)
#
# After that precondition, this script does, in order:
#   1. Flip KIT_DRY_RUN=true → false in .env
#   2. Run the populator → creates all 10 emails across the 3 sequences
#   3. Run the verifier → confirms all three sequences resolve by name
#   4. Start NarAI's FastAPI server in the background
#   5. POST a live smoke-test capture
#   6. Print where to look in Kit to confirm
#
# Re-runs are safe: dupe emails are skipped, the server-start is no-op if
# already running, and the smoke-test address is uniquely-tagged each run.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV_PY="/Users/jhonwheeler/wheellsverse_venv/bin/python"
ENV_FILE=".env"
SERVER_PORT="${NARAI_PORT:-5051}"
SERVER_LOG="${ROOT}/data/toodle_server.log"
SMOKE_EMAIL_BASE="kevens.james48029"
SMOKE_TAG="toodlelive_$(date +%s)"

say()  { printf "\n\033[1;36m▶ %s\033[0m\n" "$1"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }
warn() { printf "  \033[1;33m⚠\033[0m %s\n" "$1"; }
err()  { printf "  \033[1;31m✗\033[0m %s\n" "$1"; }

# ── Precondition check ──────────────────────────────────────────────────────
say "Step 0/6 — checking preconditions"
[ -f "$ENV_FILE" ] || { err ".env missing — see .env.example"; exit 2; }
grep -q '^KIT_API_KEY=' "$ENV_FILE" || { err "KIT_API_KEY not set in .env"; exit 2; }
ok ".env present, KIT_API_KEY set"

# ── Step 1: flip DRY_RUN ────────────────────────────────────────────────────
say "Step 1/6 — flipping KIT_DRY_RUN=true → false in .env"
if grep -q '^KIT_DRY_RUN=true' "$ENV_FILE"; then
    sed -i '' 's/^KIT_DRY_RUN=true/KIT_DRY_RUN=false/' "$ENV_FILE"
    ok "flipped to false"
elif grep -q '^KIT_DRY_RUN=false' "$ENV_FILE"; then
    ok "already false (no change)"
else
    warn "no KIT_DRY_RUN line — appending KIT_DRY_RUN=false"
    printf "\nKIT_DRY_RUN=false\n" >> "$ENV_FILE"
fi

# ── Step 2: populate emails ─────────────────────────────────────────────────
say "Step 2/6 — populating Kit sequences with 10 emails"
if ! "$VENV_PY" scripts/populate_kit_sequences.py; then
    err "populator failed or some sequences missing — check output above"
    err "If 'missing' was reported, create the empty containers in Kit's UI and re-run."
    exit 1
fi

# ── Step 3: verifier ────────────────────────────────────────────────────────
say "Step 3/6 — verifying all three sequences resolve by name"
if ! "$VENV_PY" scripts/toodle_kit_check.py >/tmp/toodle_verify.log 2>&1; then
    cat /tmp/toodle_verify.log
    err "verifier failed — fix and re-run"
    exit 1
fi
grep -E "(✓|✗)" /tmp/toodle_verify.log | head -10
ok "all sequences resolved"

# ── Step 4: start NarAI server ──────────────────────────────────────────────
say "Step 4/6 — starting NarAI FastAPI server on port $SERVER_PORT"
if curl -fsS "http://127.0.0.1:${SERVER_PORT}/api/v2/narai/health" >/dev/null 2>&1; then
    ok "server already running"
else
    mkdir -p "$(dirname "$SERVER_LOG")"
    nohup "$VENV_PY" -m narai.api.main > "$SERVER_LOG" 2>&1 &
    SERVER_PID=$!
    ok "server PID $SERVER_PID, logs → $SERVER_LOG"
    # Wait up to 12s for /health to respond
    for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
        if curl -fsS "http://127.0.0.1:${SERVER_PORT}/api/v2/narai/health" >/dev/null 2>&1; then
            ok "server ready (took ${i}s)"
            break
        fi
        sleep 1
    done
    if ! curl -fsS "http://127.0.0.1:${SERVER_PORT}/api/v2/narai/health" >/dev/null 2>&1; then
        err "server did not become ready in 12s — check $SERVER_LOG"
        exit 1
    fi
fi

# ── Step 5: live smoke test ─────────────────────────────────────────────────
say "Step 5/6 — POST a live smoke-test capture"
SMOKE_EMAIL="${SMOKE_EMAIL_BASE}+${SMOKE_TAG}@gmail.com"
echo "  smoke email: $SMOKE_EMAIL"
RESPONSE=$(curl -sS -X POST "http://127.0.0.1:${SERVER_PORT}/toodle/capture" \
    -H 'Content-Type: application/json' \
    -d "{\"email_address\":\"$SMOKE_EMAIL\",\"source\":\"finisher_smoke\",\"product_interest\":\"kdp\",\"first_name\":\"Kevens\"}")
echo "  response: $RESPONSE"
if echo "$RESPONSE" | grep -q '"status":"subscribed"'; then
    ok "capture landed in Kit"
elif echo "$RESPONSE" | grep -q '"dry_run":true'; then
    err "still dry_run — .env did not pick up; restart server"
    exit 1
else
    warn "capture returned non-subscribed status — review response"
fi

# ── Step 6: where to look ───────────────────────────────────────────────────
say "Step 6/6 — done. Verify in Kit dashboard:"
echo "  1. https://app.kit.com → Subscribers → search for: $SMOKE_EMAIL"
echo "     (should be tagged 'finisher_smoke' and 'kdp')"
echo "  2. https://app.kit.com → Sequences → KDP Launch → Subscribers tab"
echo "     (should show the smoke address in queue for Email 1)"
echo "  3. Open Kit's UI and click 'Publish' on each email in each sequence"
echo "     once you're happy with the rendering."
echo ""
echo "  Server PID file: pgrep -f 'narai.api.main'    (kill when done)"
echo "  Server logs    : tail -f $SERVER_LOG"
