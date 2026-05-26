#!/usr/bin/env bash
# scripts/deploy_frontend.sh
# ─────────────────────────────────────────────────────────────────────────────
# Deploy the frontend/ directory to Cloudflare Pages (project: wheellsverse-bots).
#
# Origin (Gitea at 100.112.218.95) is for git history only — Cloudflare Pages
# cannot pull from a private LAN URL. So deploy is a direct wrangler push.
#
# Prerequisites (one-time):
#   $ cd frontend && npx wrangler login        # opens browser, OAuth, cached
# Or set CLOUDFLARE_API_TOKEN in your shell.
#
# After that, this script is one command and is safe to re-run.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="wheellsverse-bots"
FRONTEND="$ROOT/frontend"

if [ ! -f "$FRONTEND/blueprint.pdf" ]; then
  echo "✗ $FRONTEND/blueprint.pdf missing — run scripts/build_blueprint_pdf.py first." >&2
  exit 1
fi

echo "→ deploying $FRONTEND to Cloudflare Pages project '$PROJECT'…"
cd "$FRONTEND"
npx --yes wrangler@latest pages deploy . \
  --project-name="$PROJECT" \
  --commit-dirty=true

echo ""
echo "✓ deploy complete."
echo "  Verify the blueprint is live:"
echo "  curl -sI https://wheellsverse-bots.pages.dev/blueprint.pdf | head -3"
