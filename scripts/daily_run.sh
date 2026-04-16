#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# WheellsVerse Daily Revenue Run
# Runs full_revenue_blast pipeline then auto-publishes content everywhere.
# Called by launchd at 06:00 daily, or run manually:
#   bash scripts/daily_run.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

REPO="/Users/jhonwheeler/Downloads/wheellsverse_bots"
LOG="$REPO/logs/daily_run.log"
VENV="$REPO/.venv/bin/activate"

mkdir -p "$REPO/logs"

echo "" >> "$LOG"
echo "═══════════════════════════════════════════" >> "$LOG"
echo "$(date '+%Y-%m-%d %H:%M:%S') — Daily run started" >> "$LOG"
echo "═══════════════════════════════════════════" >> "$LOG"

cd "$REPO"
source "$VENV"

# ── Step 1: Run full revenue blast pipeline ──────────────────────────────────
echo "$(date '+%H:%M:%S') Running full_revenue_blast..." | tee -a "$LOG"
python main.py --pipeline full_revenue_blast 2>&1 | tee -a "$LOG"

# ── Step 2: Publish latest content to all platforms ──────────────────────────
echo "$(date '+%H:%M:%S') Auto-publishing to Twitter, blog, email..." | tee -a "$LOG"
python scripts/auto_publish.py --hours 2 2>&1 | tee -a "$LOG"

echo "$(date '+%H:%M:%S') Daily run complete ✅" | tee -a "$LOG"
