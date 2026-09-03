#!/usr/bin/env bash
# Install / manage the persistent STAGING Holding worker-runner as a launchd LaunchAgent (macOS).
# SEPARATE from prod: distinct Label, staging BASE_URL, and a DISTINCT Keychain service. Persistence is
# NOT authority — this brings the worker ONLINE; A2 write authority stays a server-side brake
# (KAI_A2_EXECUTION_ENABLED on kai-staging-appb), OFF by default.
#
#   ./install-staging.sh install     # store staging secret in Keychain + load the LaunchAgent
#   ./install-staging.sh status      # loaded + running? recent logs
#   ./install-staging.sh start|stop|restart
#   ./install-staging.sh uninstall   # unload + remove (Keychain secret kept)
#   ./install-staging.sh logs
#
# The worker runs from a DEDICATED stable checkout (never the operator's normal worktree, never /tmp):
#   KAI_WORKER_REPO   (default: $HOME/kai-worker/repositories/wheellsverse)
#   KAI_WORKER_EXPECTED_SHA  (optional: assert the checkout is pinned to this commit)
set -euo pipefail

LABEL="com.wheellsverse.kai-holding-worker-staging"
KEYCHAIN_SVC="kai-holding-worker-staging"; KEYCHAIN_ACCT="SESSION_SIGNING_SECRET"
WORKER_REPO="${KAI_WORKER_REPO:-$HOME/kai-worker/repositories/wheellsverse}"
SRC_PLIST="$(cd "$(dirname "$0")" && pwd)/$LABEL.plist"
DEST_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

die(){ echo "REFUSE: $*" >&2; exit 1; }

validate(){
  # 1. staging target only — refuse if the plist BASE_URL is a production host (§10 defense-in-depth)
  local base; base="$(grep -A1 '>BASE_URL<' "$SRC_PLIST" | grep -o 'https://[^<]*' || true)"
  echo "target BASE_URL: ${base:-<none>}"
  [ -n "$base" ] || die "no BASE_URL in plist"
  case "$base" in *kai-prod*|*kai-production*) die "plist targets PRODUCTION ($base) — staging installer will not touch prod" ;; esac
  case "$base" in *staging*) : ;; *) die "plist BASE_URL is not a recognizable staging host ($base)" ;; esac
  # 2. dedicated stable checkout — never the operator's normal checkout / conductor worktree / tmp
  local rp; rp="$(cd "$WORKER_REPO" 2>/dev/null && pwd -P || true)"
  [ -n "$rp" ] || die "worker repo not found: $WORKER_REPO (clone it first)"
  case "$rp" in "$HOME/kai-worker/"*) : ;; *) die "worker repo must live under \$HOME/kai-worker/ (got $rp) — not the operator's checkout" ;; esac
  case "$rp" in *conductor*|/tmp/*|/private/tmp/*) die "worker repo is an ephemeral/operator path ($rp)" ;; esac
  [ -e "$rp/.git" ] || die "no .git in $rp (need a real checkout for worktree ops)"
  [ -f "$rp/ops/holding-worker-runner/run.py" ] || die "run.py missing in $rp"
  local head; head="$(git -C "$rp" rev-parse HEAD)"
  echo "worker checkout: $rp @ ${head:0:12}"
  if [ -n "${KAI_WORKER_EXPECTED_SHA:-}" ]; then
    git -C "$rp" merge-base --is-ancestor "$KAI_WORKER_EXPECTED_SHA" HEAD 2>/dev/null \
      || [ "$head" = "$(git -C "$rp" rev-parse "$KAI_WORKER_EXPECTED_SHA" 2>/dev/null || echo x)" ] \
      || die "checkout HEAD ${head:0:12} does not contain expected SHA $KAI_WORKER_EXPECTED_SHA"
  fi
  command -v python3 >/dev/null || die "python3 not on PATH"
  echo "validation: OK"
}

cmd="${1:-status}"
case "$cmd" in
  install)
    validate
    mkdir -p "$WORKER_REPO/.omc/logs" "$HOME/Library/LaunchAgents"
    if ! security find-generic-password -s "$KEYCHAIN_SVC" -a "$KEYCHAIN_ACCT" -w >/dev/null 2>&1; then
      echo "Paste the kai-STAGING SESSION_SIGNING_SECRET (Railway -> kai-staging-appb -> Variables)."
      echo "Stored in the macOS Keychain ($KEYCHAIN_SVC) only — never printed, never on disk."
      read -r -s -p "SESSION_SIGNING_SECRET: " SECRET; echo
      [ -n "$SECRET" ] || die "empty secret"
      security add-generic-password -s "$KEYCHAIN_SVC" -a "$KEYCHAIN_ACCT" -w "$SECRET" -U
      unset SECRET; echo "stored in Keychain ($KEYCHAIN_SVC)."
    else
      echo "Keychain secret already present ($KEYCHAIN_SVC) — leaving as-is."
    fi
    sed "s#__REPO__#$WORKER_REPO#g" "$SRC_PLIST" > "$DEST_PLIST"
    launchctl unload "$DEST_PLIST" 2>/dev/null || true
    launchctl load -w "$DEST_PLIST"
    sleep 1
    launchctl list | grep -q "$LABEL" && echo "LOADED $LABEL (KeepAlive + RunAtLoad)." || die "launchd did not register $LABEL"
    ;;
  start)   launchctl load -w "$DEST_PLIST"; echo "started." ;;
  stop)    launchctl unload "$DEST_PLIST" 2>/dev/null || true; echo "stopped." ;;
  restart) launchctl unload "$DEST_PLIST" 2>/dev/null || true; launchctl load -w "$DEST_PLIST"; echo "restarted." ;;
  status)
    if launchctl list | grep -q "$LABEL"; then echo "LOADED:"; launchctl list | grep "$LABEL"; else echo "NOT loaded."; fi
    echo "--- recent out log ---"; tail -n 10 "$WORKER_REPO/.omc/logs/kai-holding-worker-staging.out.log" 2>/dev/null || echo "(none)"
    ;;
  uninstall)
    launchctl unload "$DEST_PLIST" 2>/dev/null || true; rm -f "$DEST_PLIST"
    echo "unloaded + removed (Keychain secret kept; delete with: security delete-generic-password -s $KEYCHAIN_SVC)."
    ;;
  logs)
    tail -n 40 -f "$WORKER_REPO/.omc/logs/kai-holding-worker-staging.out.log" "$WORKER_REPO/.omc/logs/kai-holding-worker-staging.err.log"
    ;;
  validate) validate ;;
  *) echo "usage: $0 {install|start|stop|restart|status|uninstall|logs|validate}"; exit 1 ;;
esac
