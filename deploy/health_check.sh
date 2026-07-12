#!/bin/bash
# KAI operational health check + alerter.
#
# Runs every 5 minutes via the com.wheellsverse.healthcheck LaunchDaemon
# (StartInterval). Supersedes the old log-only "Phase A" check. It verifies:
#   1. the local API   (http://127.0.0.1:8001/health)
#   2. the public tunnel (https://kai.wheellsverse.com/health)
#   3. disk headroom   (full disk once kernel-panicked this box)
#   4. restart loops   (launchd flapping the daemon)
# and raises a Telegram alert on failure — rate-limited so an outage can't spam
# the operator into muting the channel. Every run also appends to health.log.
#
# All thresholds/paths are env-overridable (see below) so the logic is testable:
#   KAI_HEALTHCHECK_DRY_RUN=1  logs alerts instead of sending them.
set -uo pipefail

APP_ROOT="${KAI_APP_ROOT:-/Users/jhonwheeler/wheellsverse_bots}"
LOG_DIR="${KAI_LOG_DIR:-/Users/jhonwheeler/Library/Logs/wheellsverse}"
STATE_DIR="${KAI_STATE_DIR:-$LOG_DIR}"
LOCAL_URL="${KAI_HEALTH_LOCAL_URL:-http://127.0.0.1:8001/health}"
PUBLIC_URL="${KAI_HEALTH_PUBLIC_URL:-https://kai.wheellsverse.com/health}"
DISK_PATH="${KAI_DISK_PATH:-/}"
DISK_THRESHOLD="${KAI_DISK_THRESHOLD_PCT:-85}"
ALERT_MIN_INTERVAL="${KAI_ALERT_MIN_INTERVAL:-3600}"
# Restart-loop window/threshold. The check samples the PID once per run (~300s
# via StartInterval), so it detects at most one restart per interval; these
# defaults ("3 restarts within an hour") are chosen to be REACHABLE at that
# sampling rate. (A tighter signal would read launchd's LastExitStatus directly.)
RESTART_WINDOW="${KAI_RESTART_WINDOW:-3600}"
RESTART_THRESHOLD="${KAI_RESTART_THRESHOLD:-3}"
PROC_PATTERN="${KAI_PROC_PATTERN:-app.main:app}"
DRY_RUN="${KAI_HEALTHCHECK_DRY_RUN:-0}"

mkdir -p "$LOG_DIR" "$STATE_DIR"
LOG="$LOG_DIR/health.log"
TS="$(date '+%Y-%m-%d %H:%M:%S')"
NOW="$(date +%s)"

# ── Telegram creds: env first, else read the app's .env ───────────────────
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"
ENV_FILE="$APP_ROOT/backend/.env"
_env_val() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"; }
[ -z "$TG_TOKEN" ] && [ -f "$ENV_FILE" ] && TG_TOKEN="$(_env_val TELEGRAM_BOT_TOKEN)"
[ -z "$TG_CHAT" ]  && [ -f "$ENV_FILE" ] && TG_CHAT="$(_env_val TELEGRAM_CHAT_ID)"

log() { echo "$TS  $*" >> "$LOG"; }

# Rate-limited Telegram alert. `key` dedups: no resend within ALERT_MIN_INTERVAL.
# The dedup stamp is written ONLY when the alert is actually handled (a
# successful send, a dry-run, or an unconfigured no-op) — a FAILED send does not
# stamp, so a real outage (when the network is often also flaky) is retried on
# the next run instead of being muted for an hour.
alert() {
    local key="$1" msg="$2" stamp="$STATE_DIR/alert_${1}.ts" last
    if [ -f "$stamp" ]; then
        last="$(cat "$stamp" 2>/dev/null || echo 0)"
        if [ $(( NOW - last )) -lt "$ALERT_MIN_INTERVAL" ]; then
            log "ALERT[$key] suppressed (within ${ALERT_MIN_INTERVAL}s): $msg"
            return
        fi
    fi
    log "ALERT[$key] $msg"
    if [ "$DRY_RUN" = "1" ]; then
        echo "$NOW" > "$stamp"   # dry-run: stamp so suppression can be exercised
        return
    fi
    if [ -n "$TG_TOKEN" ] && [ -n "$TG_CHAT" ]; then
        # Token goes via -K - (config on stdin) so it never appears in argv/`ps`.
        if printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$TG_TOKEN" \
            | curl -s -m 8 -K - \
                -d chat_id="${TG_CHAT}" \
                --data-urlencode "text=🚨 KAI health: ${msg}" >/dev/null; then
            echo "$NOW" > "$stamp"   # stamp ONLY on a confirmed send
        else
            log "telegram send failed — not stamping, will retry next run"
        fi
    else
        log "telegram not configured — alert not delivered: $msg"
        echo "$NOW" > "$stamp"   # config gap won't self-resolve; avoid log spam
    fi
}

# Clear a dedup stamp when the condition recovers, so the next failure re-alerts.
clear_alert() { rm -f "$STATE_DIR/alert_${1}.ts"; }

# ── 1) local API ──────────────────────────────────────────────────────────
LOCAL_OK=0
curl -sf -m 5 "$LOCAL_URL" >/dev/null && LOCAL_OK=1
if [ "$LOCAL_OK" = 1 ]; then
    log "local  OK"; clear_alert local
else
    log "local  FAIL"; alert local "local API $LOCAL_URL not responding"
fi

# ── 2) public tunnel ─────────────────────────────────────────────────────
PUBLIC_OK=0
curl -sf -m 8 "$PUBLIC_URL" >/dev/null && PUBLIC_OK=1
if [ "$PUBLIC_OK" = 1 ]; then
    log "public OK"; clear_alert tunnel
elif [ "$LOCAL_OK" = 1 ]; then
    # local up but public down ⇒ the tunnel, not the app, is the problem.
    log "public FAIL"; alert tunnel "public $PUBLIC_URL down but local OK → Cloudflare tunnel likely down"
else
    log "public FAIL (attributed to local outage, already alerted)"
fi

# ── 3) disk headroom ─────────────────────────────────────────────────────
USED="$(df -P "$DISK_PATH" | awk 'NR==2 {gsub("%","",$5); print $5}')"
if [ -n "$USED" ]; then
    log "disk   ${USED}% used (threshold ${DISK_THRESHOLD}%)"
    if [ "$USED" -ge "$DISK_THRESHOLD" ]; then
        alert disk "disk ${USED}% ≥ ${DISK_THRESHOLD}% on ${DISK_PATH} (full-disk kernel-panic risk)"
    else
        clear_alert disk
    fi
fi

# ── 4) restart-loop detection ────────────────────────────────────────────
PID="$(pgrep -f "$PROC_PATTERN" | head -1 || true)"
PID_FILE="$STATE_DIR/kai_pid.state"
RST_FILE="$STATE_DIR/kai_restarts.state"
LAST_PID=""
[ -f "$PID_FILE" ] && LAST_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
[ -n "$PID" ] && echo "$PID" > "$PID_FILE"
if [ -n "$PID" ] && [ -n "$LAST_PID" ] && [ "$PID" != "$LAST_PID" ]; then
    echo "$NOW" >> "$RST_FILE"   # the PID changed since last check → a restart happened
fi
if [ -f "$RST_FILE" ]; then
    awk -v now="$NOW" -v win="$RESTART_WINDOW" 'now-$1 < win' "$RST_FILE" > "${RST_FILE}.tmp" \
        && mv "${RST_FILE}.tmp" "$RST_FILE"
    COUNT="$(wc -l < "$RST_FILE" | tr -d ' ')"
    if [ "${COUNT:-0}" -ge "$RESTART_THRESHOLD" ]; then
        alert restarts "KAI restarted ${COUNT}× in ${RESTART_WINDOW}s — crash loop"
    fi
fi

exit 0
