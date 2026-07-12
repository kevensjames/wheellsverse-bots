#!/bin/bash
# Install KAI's operational supervision as system LaunchDaemons:
#   com.wheellsverse.kai          — the API, boot-started, always-on, runs as user
#   com.wheellsverse.cloudflared  — the public tunnel, supervised
#   com.wheellsverse.healthcheck  — 5-min health probe + Telegram alerting
#
# Run once, with sudo, from the repo root:
#     sudo deploy/install_supervision.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/Library/LaunchDaemons
DAEMONS=(com.wheellsverse.kai com.wheellsverse.cloudflared com.wheellsverse.healthcheck)

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0" >&2
    exit 1
fi

# ── Stop the legacy per-user LaunchAgent FIRST ────────────────────────────
# com.wheellsverse.nai holds 127.0.0.1:8001. If it's still loaded, the new KAI
# daemon (RunAtLoad + KeepAlive) would crash-loop on EADDRINUSE. The agent lives
# in the invoking user's GUI domain, which root can only reach via `sudo -u`.
if [ -n "${SUDO_USER:-}" ]; then
    _uid="$(id -u "$SUDO_USER")"
    if sudo -u "$SUDO_USER" launchctl bootout "gui/${_uid}/com.wheellsverse.nai" 2>/dev/null; then
        echo "stopped legacy LaunchAgent com.wheellsverse.nai"
    else
        echo "legacy com.wheellsverse.nai not loaded (ok)"
    fi
else
    echo "WARN: SUDO_USER unset — cannot auto-stop the legacy nai LaunchAgent." >&2
    echo "      If it is loaded it will fight the new daemon for :8001. Stop it with:" >&2
    echo "      launchctl bootout gui/\$(id -u)/com.wheellsverse.nai" >&2
fi

# ── Install + (re)bootstrap each daemon ───────────────────────────────────
for d in "${DAEMONS[@]}"; do
    src="$REPO/deploy/launchd/$d.plist"
    if [ ! -f "$src" ]; then
        echo "missing plist: $src" >&2
        exit 1
    fi
    # Make sure the scripts these daemons call are executable.
    chmod +x "$REPO/deploy/health_check.sh" "$REPO/deploy/start_nai.sh" 2>/dev/null || true

    cp "$src" "$DEST/$d.plist"
    chown root:wheel "$DEST/$d.plist"
    chmod 644 "$DEST/$d.plist"

    launchctl bootout "system/$d" 2>/dev/null || true
    # bootout is asynchronous — a bootstrap fired immediately after can lose the
    # race ("Operation already in progress"). Retry a few times before giving up.
    _ok=0
    for _try in 1 2 3; do
        if launchctl bootstrap system "$DEST/$d.plist" 2>/dev/null; then
            _ok=1
            break
        fi
        sleep 1
    done
    if [ "$_ok" -ne 1 ]; then
        # Final attempt WITHOUT swallowing the error so the real cause surfaces
        # (and set -e aborts the install).
        launchctl bootstrap system "$DEST/$d.plist"
    fi
    echo "installed + bootstrapped: $d"
done

echo
echo "Verify:   sudo launchctl list | grep wheellsverse"
echo "Health:   tail -f /Users/jhonwheeler/Library/Logs/wheellsverse/health.log"
echo
echo "RECOMMENDED: add an EXTERNAL uptime monitor on https://kai.wheellsverse.com/health"
echo "so total-host or tunnel death is noticed even when this Mac mini is down."
