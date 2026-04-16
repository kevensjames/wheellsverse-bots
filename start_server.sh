#!/bin/bash
# WheellsVerse — Auto-start server
# Waits for the SSD volume to be mounted, then launches the API.
# Used by the macOS Launch Agent (com.wheellsverse.bots.plist).

VOLUME="/Volumes/Wheellsverse"
PROJECT="$VOLUME/wheellsverse_bots"
PYTHON="$PROJECT/venv/bin/python3"
LOG="$PROJECT/logs"

mkdir -p "$LOG"

echo "[$(date)] Waiting for volume $VOLUME..." >> "$LOG/startup.log"

# Wait up to 60s for the SSD to mount
for i in $(seq 1 60); do
    if [ -d "$PROJECT" ] && [ -f "$PYTHON" ]; then
        echo "[$(date)] Volume ready after ${i}s — starting server" >> "$LOG/startup.log"
        break
    fi
    sleep 1
done

if [ ! -f "$PYTHON" ]; then
    echo "[$(date)] ERROR: Volume never mounted. Server not started." >> "$LOG/startup.log"
    exit 1
fi

cd "$PROJECT"
exec "$PYTHON" -m uvicorn core.api:app \
    --host 0.0.0.0 \
    --port 5050 \
    --workers 1 \
    2>> "$LOG/service_error.log"
