#!/bin/bash
# WheellsVerse Dashboard — persistent launcher for launchd
# Waits for the Wheellsverse volume, then starts the dashboard.

BOTS_DIR="/Volumes/Wheellsverse/wheellsverse_bots"
PYTHON="$BOTS_DIR/venv/bin/python"
LOG="$BOTS_DIR/logs/dashboard.log"

# Wait up to 60s for the external volume to mount
for i in $(seq 1 60); do
    if [ -f "$PYTHON" ]; then
        break
    fi
    sleep 1
done

if [ ! -f "$PYTHON" ]; then
    echo "$(date): ERROR — volume not mounted, aborting" >> "$LOG"
    exit 1
fi

cd "$BOTS_DIR"
# Load .env if it exists
if [ -f "$BOTS_DIR/.env" ]; then
    set -a
    source "$BOTS_DIR/.env"
    set +a
fi

echo "$(date): Starting WheellsVerse dashboard on port 5050" >> "$LOG"
exec "$PYTHON" "$BOTS_DIR/main.py" --dashboard --port 5050
