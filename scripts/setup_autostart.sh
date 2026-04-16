#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# WheellsVerse — Install daily automation (runs at 6 AM via macOS launchd)
# Usage: bash scripts/setup_autostart.sh
# ─────────────────────────────────────────────────────────────────────────────

REPO="/Users/jhonwheeler/Downloads/wheellsverse_bots"
PLIST_SRC="$REPO/scripts/com.wheellsverse.daily.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.wheellsverse.daily.plist"

echo "Installing WheellsVerse daily scheduler..."

# Make scripts executable
chmod +x "$REPO/scripts/daily_run.sh"
chmod +x "$REPO/scripts/auto_publish.py"

# Install plist
cp "$PLIST_SRC" "$PLIST_DEST"

# Load it (unload first in case it was previously loaded)
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo ""
echo "✅ Daily automation installed — runs every day at 6:00 AM"
echo ""
echo "Commands:"
echo "  Run now:    launchctl start com.wheellsverse.daily"
echo "  Check log:  tail -f $REPO/logs/daily_run.log"
echo "  Stop:       launchctl unload $PLIST_DEST"
echo "  Uninstall:  launchctl unload $PLIST_DEST && rm $PLIST_DEST"
echo ""
echo "Before automation works, save your Twitter session once:"
echo "  cd $REPO && source .venv/bin/activate"
echo "  python core/browser.py --twitter-login"
echo ""
