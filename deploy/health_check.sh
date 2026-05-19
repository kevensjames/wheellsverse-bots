#!/bin/bash
# Health check — log-only, runs from cron every 5 minutes.
# Phase B replaces this with real alerting (Pushover / email / status page).
set -uo pipefail

LOG="/Users/jhonwheeler/Library/Logs/wheellsverse/health.log"
TS="$(date '+%Y-%m-%d %H:%M:%S')"

check() {
    local name="$1" url="$2"
    if curl -sf -m 5 "$url" >/dev/null; then
        echo "$TS  $name  OK"
    else
        echo "$TS  $name  FAIL"
    fi
}

{
    check "nai    " "http://127.0.0.1:8001/docs"
    check "ollama " "http://127.0.0.1:11434/api/tags"
} >> "$LOG" 2>&1
