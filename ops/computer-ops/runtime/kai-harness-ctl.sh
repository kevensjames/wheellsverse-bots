#!/usr/bin/env bash
# KAI Computer Operations - pinned harness runtime control.
#
# The harness is NOT a long-running daemon in this design. KAI spawns one short-lived
# `dsh --profile acp` child per mission, over stdio, and the child dies with the
# mission. That is deliberate: a per-mission process means no listening socket, no
# shared session state between missions, and a crash or STOP releases everything.
#
# So `start`/`stop` here manage a DIAGNOSTIC session for operators, not the production
# path. `status`, `upgrade`, `verify` and `uninstall` are the ones that matter
# operationally.
#
# No persistent startup is installed. A launchd plist template is provided at
# runtime/com.wheellsverse.kai-harness.plist.template and is deliberately NOT loaded --
# per the mission, persistent startup requires explicit operator approval.
set -euo pipefail

RUNTIME_ROOT="${KAI_HARNESS_ROOT:-/Users/jhonwheeler/kai-harness-runtime}"
HARNESS_DIR="$RUNTIME_ROOT/deepseek-harness"
DSH_HOME_DIR="${DSH_HOME:-$RUNTIME_ROOT/dsh-home}"
PINNED_COMMIT="c389f96bf3a9b6807cb71ed6bdad5849be0df6d8"
OVERLAY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../harness" && pwd)"
PID_FILE="$RUNTIME_ROOT/diagnostic-session.pid"

die() { echo "error: $*" >&2; exit 1; }

cmd_status() {
  echo "runtime root : $RUNTIME_ROOT"
  echo "harness dir  : $HARNESS_DIR"
  echo "DSH_HOME     : $DSH_HOME_DIR"
  if [ ! -d "$HARNESS_DIR/.git" ]; then
    echo "state        : NOT INSTALLED"
    return 0
  fi
  local head
  head="$(git -C "$HARNESS_DIR" rev-parse HEAD)"
  echo "pinned commit: $PINNED_COMMIT"
  echo "actual HEAD  : $head"
  if [ "$head" = "$PINNED_COMMIT" ]; then
    echo "pin state    : OK (matches pin)"
  else
    echo "pin state    : DRIFTED - the runtime is not the reviewed commit"
  fi
  echo -n "built        : "
  [ -f "$HARNESS_DIR/apps/cli/lib/bin.js" ] && echo "yes" || echo "NO (run: $0 upgrade)"
  echo -n "node         : "; node --version 2>/dev/null || echo "MISSING"
  echo -n "pnpm         : "; pnpm --version 2>/dev/null || echo "MISSING"
  echo -n "disk         : "; du -sh "$HARNESS_DIR" 2>/dev/null | cut -f1
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "diagnostic   : RUNNING (pid $(cat "$PID_FILE"))"
  else
    echo "diagnostic   : stopped"
  fi
  echo -n "launchd      : "
  launchctl list 2>/dev/null | grep -q com.wheellsverse.kai-harness \
    && echo "LOADED (persistent startup is enabled)" \
    || echo "not installed (persistent startup requires operator approval)"
}

# Assert the containment invariants against the tree the harness will actually run.
cmd_verify() {
  [ -d "$HARNESS_DIR" ] || die "harness not installed at $HARNESS_DIR"
  python3 "$OVERLAY_DIR/../probes/verify_modes.py"
}

cmd_start() {
  [ -f "$HARNESS_DIR/apps/cli/lib/bin.js" ] || die "not built; run: $0 upgrade"
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    die "diagnostic session already running (pid $(cat "$PID_FILE"))"
  fi
  : "${KAI_TASK_WORKSPACE:?set KAI_TASK_WORKSPACE to the mission workspace}"
  : "${KAI_LOCAL_LLM_BASE_URL:?set KAI_LOCAL_LLM_BASE_URL}"
  : "${KAI_LOCAL_LLM_MODEL:?set KAI_LOCAL_LLM_MODEL}"
  # OBSERVE is the only mode this diagnostic entry point will start: it is
  # read-only with deterministic-deny approvals, so an operator poking at the
  # runtime cannot accidentally launch a writing session.
  ( cd "$HARNESS_DIR" && CI=true DSH_HOME="$DSH_HOME_DIR" \
      node --import tsx/esm apps/cli/src/bin.ts --profile acp \
        --patch "$OVERLAY_DIR/00-containment.patch.yml" \
        --patch "$OVERLAY_DIR/10-model-local-only.patch.yml" \
        --patch "$OVERLAY_DIR/20-mode-observe.patch.yml" ) &
  echo $! > "$PID_FILE"
  echo "diagnostic ACP session started (OBSERVE + LOCAL_ONLY), pid $(cat "$PID_FILE")"
}

cmd_stop() {
  [ -f "$PID_FILE" ] || { echo "no diagnostic session recorded"; return 0; }
  local pid; pid="$(cat "$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    echo "stopped pid $pid"
  else
    echo "pid $pid not running"
  fi
  rm -f "$PID_FILE"
}

cmd_restart() { cmd_stop; cmd_start; }

# Re-materialise the runtime AT THE PIN. Also the rollback path: change PINNED_COMMIT
# and re-run to return to a previous reviewed commit.
cmd_upgrade() {
  [ -d "$HARNESS_DIR/.git" ] || die "harness not installed; clone it first"
  cmd_stop || true
  local backup="$RUNTIME_ROOT/backup-$(git -C "$HARNESS_DIR" rev-parse --short HEAD)"
  echo "recording rollback point: $backup"
  mkdir -p "$backup"
  git -C "$HARNESS_DIR" rev-parse HEAD > "$backup/COMMIT"
  cp "$HARNESS_DIR/pnpm-lock.yaml" "$backup/pnpm-lock.yaml" 2>/dev/null || true
  git -C "$HARNESS_DIR" fetch --quiet origin
  git -C "$HARNESS_DIR" checkout --detach "$PINNED_COMMIT"
  # CI=true suppresses the harness postinstall that rewrites git hooks in the checkout.
  ( cd "$HARNESS_DIR" && CI=true pnpm install --frozen-lockfile && CI=true pnpm run build )
  echo "now at $(git -C "$HARNESS_DIR" rev-parse HEAD)"
  cmd_verify
}

cmd_uninstall() {
  cmd_stop || true
  launchctl list 2>/dev/null | grep -q com.wheellsverse.kai-harness \
    && launchctl bootout "gui/$(id -u)/com.wheellsverse.kai-harness" 2>/dev/null || true
  cat <<EOF
This removes the harness runtime and ALL local session data:
  $HARNESS_DIR
  $DSH_HOME_DIR   (sessions, storages, profiles)
It does NOT touch the KAI repository, and it revokes no macOS TCC grants -- remove
those by hand in System Settings > Privacy & Security.
EOF
  read -r -p "Type REMOVE to confirm: " ans
  [ "$ans" = "REMOVE" ] || die "aborted"
  rm -rf "$HARNESS_DIR" "$DSH_HOME_DIR"
  echo "removed. corepack's pnpm shim and node were left alone (shared with other projects)."
}

case "${1:-}" in
  status)    cmd_status ;;
  verify)    cmd_verify ;;
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  restart)   cmd_restart ;;
  upgrade)   cmd_upgrade ;;
  uninstall) cmd_uninstall ;;
  *) echo "usage: $0 {status|verify|start|stop|restart|upgrade|uninstall}" >&2; exit 2 ;;
esac
