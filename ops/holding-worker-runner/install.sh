#!/usr/bin/env bash
# Install / manage the persistent Holding worker-runner as a launchd LaunchAgent (macOS).
# The runtime secret is stored ONLY in the macOS Keychain (never plaintext on disk / git / logs).
#
#   ./install.sh install     # store secret in Keychain + load the LaunchAgent (auto-starts, KeepAlive)
#   ./install.sh status      # is it loaded + running? tail recent logs
#   ./install.sh restart     # bounce the service
#   ./install.sh uninstall   # unload + remove the LaunchAgent (Keychain secret left intact)
#   ./install.sh logs        # tail the runner logs
#
# Requires: colima running (the runner launches the isolated worker container).
set -euo pipefail

LABEL="com.wheellsverse.kai-holding-worker"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SRC_PLIST="$REPO/ops/holding-worker-runner/$LABEL.plist"
DEST_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
KEYCHAIN_SVC="kai-holding-worker"; KEYCHAIN_ACCT="SESSION_SIGNING_SECRET"
mkdir -p "$REPO/.omc/logs" "$HOME/Library/LaunchAgents"

cmd="${1:-status}"
case "$cmd" in
  install)
    if ! security find-generic-password -s "$KEYCHAIN_SVC" -a "$KEYCHAIN_ACCT" -w >/dev/null 2>&1; then
      echo "Paste the kai-prod SESSION_SIGNING_SECRET (from Railway → kai-prod → Variables)."
      echo "It is stored in the macOS Keychain only — never printed, never written to disk."
      read -r -s -p "SESSION_SIGNING_SECRET: " SECRET; echo
      [ -n "$SECRET" ] || { echo "empty — aborting"; exit 1; }
      security add-generic-password -s "$KEYCHAIN_SVC" -a "$KEYCHAIN_ACCT" -w "$SECRET" -U
      unset SECRET
      echo "stored in Keychain."
    else
      echo "Keychain secret already present (leaving as-is)."
    fi
    sed "s#__REPO__#$REPO#g" "$SRC_PLIST" > "$DEST_PLIST"
    launchctl unload "$DEST_PLIST" 2>/dev/null || true
    launchctl load -w "$DEST_PLIST"
    echo "loaded $LABEL. It auto-starts + restarts (KeepAlive)."
    ;;
  status)
    if launchctl list | grep -q "$LABEL"; then echo "LOADED:"; launchctl list | grep "$LABEL";
    else echo "NOT loaded."; fi
    echo "--- recent out log ---"; tail -n 8 "$REPO/.omc/logs/kai-holding-worker.out.log" 2>/dev/null || echo "(none)"
    ;;
  restart)
    launchctl unload "$DEST_PLIST" 2>/dev/null || true; launchctl load -w "$DEST_PLIST"; echo "restarted."
    ;;
  uninstall)
    launchctl unload "$DEST_PLIST" 2>/dev/null || true; rm -f "$DEST_PLIST"
    echo "unloaded + removed (Keychain secret kept; delete with: security delete-generic-password -s $KEYCHAIN_SVC)."
    ;;
  logs)
    tail -n 40 -f "$REPO/.omc/logs/kai-holding-worker.out.log" "$REPO/.omc/logs/kai-holding-worker.err.log"
    ;;
  *) echo "usage: $0 {install|status|restart|uninstall|logs}"; exit 1 ;;
esac
