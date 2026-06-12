#!/usr/bin/env bash
# Deploy a campaign's site previews to Cloudflare Pages.
#
# Reads the previews-manifest, deploys the matching HTML directory to
# preview.wheellsverse.com, and prints the live URLs back so you can
# verify a few before the sequences go out.
#
# Usage:
#   bash scripts/deploy_previews.sh data/launches/siteboost/runs/2026-06-02-boston-ma/03-previews
#
# Prerequisites:
#   - wrangler CLI installed (`npm install -g wrangler`)
#   - `wrangler login` completed
#   - Cloudflare Pages project `siteboost-previews` exists
#   - Custom domain `preview.wheellsverse.com` mapped to that project

set -euo pipefail

PREVIEWS_DIR="${1:-}"

if [ -z "$PREVIEWS_DIR" ] || [ ! -d "$PREVIEWS_DIR" ]; then
    echo "Usage: $0 <previews-dir>"
    echo ""
    echo "Available campaigns:"
    find data/launches/siteboost/runs -name "03-previews" -type d 2>/dev/null | sort
    exit 1
fi

if ! command -v wrangler &>/dev/null; then
    echo "ERROR: wrangler not installed. Run: npm install -g wrangler"
    exit 2
fi

PREVIEWS_COUNT=$(find "$PREVIEWS_DIR" -name "*.html" -type f | wc -l | tr -d ' ')
if [ "$PREVIEWS_COUNT" -eq 0 ]; then
    echo "ERROR: no .html files in $PREVIEWS_DIR"
    exit 3
fi

echo ""
echo "  ── SiteBoost preview deploy ──"
echo "  Source: $PREVIEWS_DIR"
echo "  Previews to deploy: $PREVIEWS_COUNT"
echo ""

read -p "  Deploy now? [y/N] " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "  Canceled."
    exit 0
fi

echo ""
echo "  Deploying to preview.wheellsverse.com..."
cd "$PREVIEWS_DIR"
wrangler pages deploy . --project-name=siteboost-previews --commit-dirty=true

echo ""
echo "  ✓ Deployed. Sample preview URLs:"
find . -maxdepth 1 -name "*.html" -type f | head -5 | while read -r f; do
    slug="${f#./}"
    slug="${slug%.html}"
    echo "    https://preview.wheellsverse.com/$slug"
done

echo ""
echo "  Verify one in browser before sending sequences:"
SAMPLE=$(find . -maxdepth 1 -name "*.html" -type f | head -1)
SAMPLE_SLUG="${SAMPLE#./}"
SAMPLE_SLUG="${SAMPLE_SLUG%.html}"
echo "    open https://preview.wheellsverse.com/$SAMPLE_SLUG"
echo ""
