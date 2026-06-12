#!/usr/bin/env bash
# scripts/ship_nai.sh — one-command Path 2 deploy for NAI.
#
# What this does (idempotent, safe to re-run):
#   1. Validates the working tree is clean (refuses to ship dirty).
#   2. Verifies the three NAI Path 2 branches exist locally.
#   3. Merges them into the target deploy branch (default:
#      feat/app-store-readiness-check) with an octopus merge — no
#      partial state if any merge fails.
#   4. Runs a fast in-process smoke test (TestClient + mocked Supabase)
#      to confirm the merged tree boots and answers as NAI.
#   5. Prints the post-deploy checklist (static-host upload, env vars,
#      uvicorn restart, pilot URL).
#
# What this DOES NOT do:
#   - Push to remote. Pushes require your explicit `git push`.
#   - Restart your production uvicorn. The watchdog handles that on file
#     change, or you can `kill -HUP <pid>` yourself.
#   - Upload frontend/nai/ to Cloudflare Pages / Netlify. Run your
#     existing static-host pipeline after this script succeeds.
#
# Exit codes:
#   0  — merged + smoke passed; ready to deploy.
#   1  — pre-flight failed (dirty tree, missing branch, etc.).
#   2  — merge conflict. Tree is left in conflict state; resolve and
#        commit, or `git merge --abort`.
#   3  — smoke test failed after merge. Inspect /tmp/ship_nai.log.

set -euo pipefail

# ── Config (override via env) ────────────────────────────────────────────────
TARGET_BRANCH="${SHIP_NAI_TARGET:-feat/app-store-readiness-check}"
BRANCHES=(
  "feat/nai-route-on-monorepo"
  "feat/nai-auth-hybrid"
  "feat/nai-pwa-supabase-auth"
)
LOG=/tmp/ship_nai.log
: >"$LOG"

# ── Helpers ──────────────────────────────────────────────────────────────────
say()  { printf "\033[1;36m▶\033[0m %s\n" "$*"; }
ok()   { printf "\033[1;32m✓\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!\033[0m %s\n" "$*" >&2; }
die()  { printf "\033[1;31m✗\033[0m %s\n" "$*" >&2; exit "${2:-1}"; }

cd "$(git rev-parse --show-toplevel)" 2>/dev/null \
  || die "Not in a git repository."

# ── 1. Pre-flight ─────────────────────────────────────────────────────────────
say "Pre-flight: working tree must be clean"
if [[ -n "$(git status --porcelain)" ]]; then
  warn "Working tree is dirty. Showing top items:"
  git status --short | head -10
  die "Refusing to ship a dirty tree. Stash, commit, or revert first." 1
fi
ok "Working tree clean."

say "Pre-flight: target branch exists ($TARGET_BRANCH)"
git rev-parse --verify "$TARGET_BRANCH" >/dev/null 2>&1 \
  || die "Target branch missing: $TARGET_BRANCH" 1
ok "Target branch present."

say "Pre-flight: NAI feature branches exist"
for b in "${BRANCHES[@]}"; do
  git rev-parse --verify "$b" >/dev/null 2>&1 \
    || die "Missing feature branch: $b" 1
done
ok "All three NAI branches present."

# ── 2. Already-merged check (idempotent) ─────────────────────────────────────
git checkout "$TARGET_BRANCH" >>"$LOG" 2>&1
remaining=()
for b in "${BRANCHES[@]}"; do
  if git merge-base --is-ancestor "$b" HEAD; then
    ok "$b already merged into $TARGET_BRANCH."
  else
    remaining+=("$b")
  fi
done

if [[ ${#remaining[@]} -eq 0 ]]; then
  say "All NAI branches already merged. Skipping merge step."
else
  say "Merging ${#remaining[@]} branch(es) into $TARGET_BRANCH (octopus)…"
  if git merge --no-ff "${remaining[@]}" \
      -m "merge: NAI Path 2 deploy (route + hybrid auth + Supabase PWA)" \
      >>"$LOG" 2>&1; then
    ok "Merge succeeded."
  else
    warn "Merge failed. See $LOG. Tree is in conflict state."
    die "Resolve manually or \`git merge --abort\` to roll back." 2
  fi
fi

# ── 3. Smoke test ─────────────────────────────────────────────────────────────
# Prefer the project venv (has PyJWT, fastapi, etc.) over system python3.
if [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  die "No python interpreter found." 1
fi

say "Smoke test: in-process TestClient hits /api/nai/config + /api/v2/nai/chat ($PY)"
SMOKE_OUT=$(NARAI_FAST_MODEL=ollama/llama3.2 NARAI_DEEP_MODEL=ollama/llama3.2 \
            SUPABASE_URL=https://test.supabase.co \
            SUPABASE_ANON_KEY=test-anon-key \
            NARAI_JWT_SECRET="test-secret-for-smoke-32-bytes-min" \
            "$PY" - <<'PY' 2>>"$LOG"
import os, json, jwt
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from core.api import app
client = TestClient(app)

# 1. /api/nai/config
r = client.get("/api/nai/config")
assert r.status_code == 200, f"config: {r.status_code} {r.text[:200]}"
cfg = r.json()
assert cfg.get("supabaseUrl") and cfg.get("supabaseAnonKey"), "config shape wrong"

# 2. /api/v2/nai/chat via legacy JWT (hybrid auth fallback — no Supabase needed)
token = jwt.encode(
    {"sub": "owner", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
    "test-secret-for-smoke-32-bytes-min", algorithm="HS256",
)
r = client.post("/api/v2/nai/chat",
    headers={"Authorization": f"Bearer {token}"},
    json={"message": "Smoke."},
    timeout=120)
assert r.status_code == 200, f"chat: {r.status_code} {r.text[:200]}"
body = r.json()
assert body.get("reply"), "empty reply"
assert body.get("model"), "no model in response"

# 3. 401 path
r = client.post("/api/v2/nai/chat",
    headers={"Authorization": "Bearer garbage"},
    json={"message": "should reject"})
assert r.status_code == 401, f"invalid token: expected 401 got {r.status_code}"

print(json.dumps({
    "config_ok": True,
    "chat_status": 200,
    "chat_model": body["model"],
    "chat_tokens": body.get("tokens", 0),
    "auth_reject": 401,
}))
PY
) || die "Smoke test failed. Tail of $LOG:"$'\n'"$(tail -20 "$LOG")" 3

ok "Smoke test passed: $SMOKE_OUT"

# ── 4. Post-deploy checklist ─────────────────────────────────────────────────
cat <<EOF

────────────────────────────────────────────────────────────────────
✅ Path 2 merged into $TARGET_BRANCH and smoke-passed.

Next steps (do these yourself — this script never pushes/deploys):

  1. Push the deploy branch when you're ready:
       git push origin $TARGET_BRANCH

  2. Verify production .env has BOTH:
       SUPABASE_URL=https://<your-project>.supabase.co
       SUPABASE_ANON_KEY=<eyJ…>
     (the anon key, NOT the service-role key)

  3. Restart core/api.py so the new routes register:
       # if the watchdog auto-restarts, this happens for you
       # otherwise: kill -HUP \$(lsof -ti :5050)

  4. Upload frontend/nai/ to your static host
     (Cloudflare Pages or Netlify, mirroring frontend/ deploy):
       wrangler pages deploy frontend
       # or your existing pipeline

  5. Create a Supabase user for yourself in the dashboard,
     then open the URL on your phone:
       https://<your-domain>/nai/
     → Share → Add to Home Screen → sign in → chat.

  6. When NAI works for you, invite 5-10 pilot users via Supabase
     (Authentication → Users → "Invite user").

  7. After 3 days, check by_mode["nai"] telemetry for return-rate.
     The 14-day plan's Day-13 exit criterion: did 3+ of 10 pilot
     users come back unprompted on Day 2?
────────────────────────────────────────────────────────────────────
EOF
