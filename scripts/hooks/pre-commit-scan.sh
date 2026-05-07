#!/bin/bash
# wheellsverse-bots — pre-commit security gate.
#
# Phase C (audit follow-up to Issues #1 + #2): replaces the Opsera plugin
# pre-commit hook with a repo-tracked, Semgrep-primary, gracefully-degrading
# scanner gate.
#
# Wired as a Claude Code PreToolUse hook on the Bash tool via
# .claude/settings.json. Fires on every Bash call but only acts when the
# command contains a literal `git commit` substring (regex `git\s+commit`,
# matching the original Opsera behavior). All other calls are no-ops.
#
# Architecture:
#
#   Primary gate (REQUIRED): Semgrep CLI on staged files. Non-zero findings
#                            block the commit. Missing Semgrep = fatal.
#   Optional fallback:       Opsera. The agent may call its MCP tool by
#                            hand if needed; the hook does NOT require it.
#                            When the tool is reachable, the agent gets a
#                            second-opinion scan; when it isn't (the common
#                            case in MCP-light sessions), the hook logs
#                            `scan-skipped: opsera-unavailable` and proceeds.
#
# Emergency bypass: `touch /tmp/.brain-precommit-passed` in a SEPARATE bash
# call (not the same one that contains "git commit" — the hook regex would
# fire first). Single-use, ≤ 5-minute mtime. Use only when the dev is
# certain Semgrep is wrong; document the reason in the commit body.
#
# See docs/precommit-hooks.md for full mechanics + the three quirks that
# bit the Phase A/B work (regex matches command substring; flag file is
# single-use ≤5 min; MCP tools are not reachable from bash).

set -euo pipefail

# ── 1. Read tool input from stdin (Claude PreToolUse contract) ─────────────

INPUT="$(cat || true)"
COMMAND="$(printf '%s' "$INPUT" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print('')
    sys.exit(0)
print(d.get('tool_input', {}).get('command', '') or d.get('command', ''))
" 2>/dev/null)"

# ── 2. Filter: only act on git commit invocations ──────────────────────────

if ! printf '%s' "$COMMAND" | grep -qE 'git[[:space:]]+commit'; then
  exit 0
fi

# ── 3. Emergency bypass via flag file ──────────────────────────────────────
#
# Same single-use, ≤ 5-minute mtime semantics as the legacy Opsera flag, but
# under a Brain-specific name to make the bypass surface obvious in audits.

FLAG="/tmp/.brain-precommit-passed"
if [ -f "$FLAG" ]; then
  if [ "$(uname)" = "Darwin" ]; then
    age=$(( $(date +%s) - $(stat -f %m "$FLAG") ))
  else
    age=$(( $(date +%s) - $(stat -c %Y "$FLAG") ))
  fi
  rm -f "$FLAG"
  if [ "$age" -lt 300 ]; then
    echo "[brain-precommit] bypass flag honored (age=${age}s); proceeding without scan." >&2
    exit 0
  fi
  # Stale flag — fall through to normal scan path.
fi

# Back-compat: the legacy Opsera flag still bypasses, since memory + previous
# commit messages reference its name. Same single-use semantics.
LEGACY_FLAG="/tmp/.opsera-pre-commit-scan-passed"
if [ -f "$LEGACY_FLAG" ]; then
  if [ "$(uname)" = "Darwin" ]; then
    age=$(( $(date +%s) - $(stat -f %m "$LEGACY_FLAG") ))
  else
    age=$(( $(date +%s) - $(stat -c %Y "$LEGACY_FLAG") ))
  fi
  rm -f "$LEGACY_FLAG"
  if [ "$age" -lt 300 ]; then
    echo "[brain-precommit] legacy opsera flag honored (age=${age}s); proceeding without scan." >&2
    exit 0
  fi
fi

# ── 4. Primary gate: Semgrep on staged files ───────────────────────────────

if ! command -v semgrep >/dev/null 2>&1; then
  cat >&2 <<EOF
[brain-precommit] FATAL: semgrep CLI not found on PATH.

Install it:
    pip install --user semgrep
or:
    brew install semgrep

Semgrep is the primary required gate. The hook intentionally does NOT
graceful-degrade on Semgrep absence — see docs/precommit-hooks.md.
EOF
  exit 2
fi

# Collect staged files. --diff-filter=ACMR catches Adds, Copies, Modifies,
# and Renames; deleted files (D) and unmerged (U) are excluded — Semgrep
# can't scan a path that no longer exists, and unmerged is a different
# error class.
STAGED="$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || true)"

if [ -z "$STAGED" ]; then
  # Nothing staged — this is usually an empty/amend operation. Let it
  # through; git itself will reject if there's truly nothing to commit.
  echo "[brain-precommit] no staged files; skipping Semgrep." >&2
  echo "[brain-precommit] scan-skipped: opsera-unavailable (agent-level optional)" >&2
  exit 0
fi

# Filter to file types Semgrep's default rules cover. We pass paths
# explicitly so semgrep doesn't walk the whole repo (which would scan
# vendored deps and slow the gate noticeably).
SCAN_PATHS=()
while IFS= read -r f; do
  case "$f" in
    *.py|*.js|*.jsx|*.ts|*.tsx|*.go|*.rb|*.java|*.kt|*.c|*.h|*.cpp|*.hpp|*.cs|*.php|*.rs|*.swift|*.scala|*.sh|*.bash)
      [ -f "$f" ] && SCAN_PATHS+=("$f")
      ;;
  esac
done <<< "$STAGED"

if [ "${#SCAN_PATHS[@]}" -eq 0 ]; then
  echo "[brain-precommit] no scannable file types in staged set; skipping Semgrep." >&2
  echo "[brain-precommit] scan-skipped: opsera-unavailable (agent-level optional)" >&2
  exit 0
fi

# Run Semgrep with its default ruleset on the staged paths.
#
#   --config auto      — uses Semgrep's default registry rules (matches
#                        the SessionStart probe behavior).
#   --error            — exit non-zero on any finding.
#   --quiet            — don't dump rule download chatter on stdout.
#   --metrics off      — don't phone home from a developer machine.
#   --timeout 30       — hard cap per file; the hook is on the hot path.
SCAN_LOG="$(mktemp -t brain-precommit-XXXXXX.log)"
trap 'rm -f "$SCAN_LOG"' EXIT
if ! semgrep scan \
      --config auto \
      --error \
      --quiet \
      --metrics off \
      --timeout 30 \
      "${SCAN_PATHS[@]}" >"$SCAN_LOG" 2>&1; then
  cat >&2 <<EOF
[brain-precommit] FATAL: Semgrep found policy violations in staged files.

--- Semgrep output ---
$(cat "$SCAN_LOG")
----------------------

To remediate: fix the findings above and re-stage. To bypass in an
emergency (NOT recommended), touch /tmp/.brain-precommit-passed in a
separate bash invocation, then re-run the commit. Document the reason
in the commit body.
EOF
  exit 2
fi

# ── 5. Optional fallback: Opsera ──────────────────────────────────────────
#
# Bash hooks cannot invoke MCP tools directly. Whether Opsera is reachable
# is decided by the agent's MCP context, not by this script. We log the
# absence so audit trails are honest and move on.

echo "[brain-precommit] Semgrep clean ($(echo "${SCAN_PATHS[@]}" | wc -w | xargs) file(s) scanned)." >&2
echo "[brain-precommit] scan-skipped: opsera-unavailable (agent-level optional)" >&2

exit 0
