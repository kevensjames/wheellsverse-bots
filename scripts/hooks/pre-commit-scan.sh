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
#   Primary gate (REQUIRED): Semgrep CLI on staged files. Always runs the
#                            local rules in .semgrep/rules.yml (offline);
#                            adds the p/default registry ruleset when
#                            semgrep.dev is reachable. Findings block the
#                            commit. So does a Semgrep that cannot run
#                            (missing, bad config, crash), reported as
#                            "could not run", never as findings.
#   Optional fallback:       Opsera. The agent may call its MCP tool by
#                            hand if needed; the hook does NOT require it.
#                            When the tool is reachable, the agent gets a
#                            second-opinion scan; when it isn't (the common
#                            case in MCP-light sessions), the hook logs
#                            `scan-skipped: opsera-unavailable` and proceeds.
#
# Two stages, one script:
#
#   PreToolUse (default): runs before the Bash command, so it only sees what
#     is already staged. On the first commit in a clone it arms the git
#     stage below (core.hooksPath=scripts/hooks/git), unless the clone has a
#     hooks setup of its own. Once armed, it leaves the scan to git, except
#     for commands that skip git hooks (--no-verify, -n, core.hooksPath).
#   Git pre-commit (--git-hook, via scripts/hooks/git/pre-commit): runs
#     inside `git commit`, after git has built the commit's index, so it
#     scans exactly what gets committed, including files the command stages
#     itself (`git commit -a`, `git commit <paths>`, `git add x && git
#     commit`). Any non-zero exit blocks the commit.
#
# Emergency bypass: `touch /tmp/.brain-precommit-passed` in a SEPARATE bash
# call (not the same one that contains "git commit" — the hook regex would
# fire first). Single-use, ≤ 5-minute mtime: the stage that scans consumes
# it. Use only when the dev is certain Semgrep is wrong; document the reason
# in the commit body.
#
# See docs/precommit-hooks.md for full mechanics + the three quirks that
# bit the Phase A/B work (regex matches command substring; flag file is
# single-use ≤5 min; MCP tools are not reachable from bash).

set -euo pipefail

GIT_HOOK=0
if [ "${1:-}" = "--git-hook" ]; then
  GIT_HOOK=1
fi

if [ "$GIT_HOOK" -eq 0 ]; then
  # ── 1. Read tool input from stdin (Claude PreToolUse contract) ───────────
  #
  # Git-hook mode skips this: git gives the hook no payload, and from a
  # terminal `cat` would sit waiting for input.

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

  # ── 2. Filter: only act on git commit invocations ────────────────────────

  # Here-string, not `printf | grep -q`: under pipefail, grep -q exiting
  # early can SIGPIPE a long printf and turn a match into exit 141.
  if ! grep -qE 'git[[:space:]]+commit' <<<"$COMMAND"; then
    exit 0
  fi
fi

# From here on the gate is ruling on a commit. An unexpected failure in
# this script must block it: under `set -e` it would otherwise exit with
# the failing command's status, and Claude Code lets the tool call through
# on any exit code other than 2. (Git blocks on any non-zero exit.)
trap 'echo "[brain-precommit] FATAL: hook error near line $LINENO; commit blocked (the gate did not finish)." >&2; exit 2' ERR

# Work from the repo root. `git diff --cached --name-only` prints
# root-relative paths; from a subdirectory the [ -f ] check below would
# drop every file and the gate would pass without scanning anything.
# (Git already runs hooks from the root.)
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$REPO_ROOT" ]; then
  cd "$REPO_ROOT"
fi

# ── 2b. PreToolUse: arm the git stage, then let it do the scan ─────────────
#
# This stage runs before the Bash command, so it can't see files the command
# stages itself. The git stage can. Arming sets core.hooksPath for this clone
# only, and only when nothing else claims git hooks here: core.hooksPath
# unset, and no hooks of its own in .git/hooks (setting it would silently
# switch those off). Undo with `git config --unset core.hooksPath`.

GIT_HOOKS_DIR="scripts/hooks/git"

git_stage_armed() {
  [ -x "$GIT_HOOKS_DIR/pre-commit" ] &&
    [ "$(git config --get core.hooksPath 2>/dev/null || true)" = "$GIT_HOOKS_DIR" ]
}

arm_git_stage() {
  local current hooks_dir f
  [ -x "$GIT_HOOKS_DIR/pre-commit" ] || return 1
  current="$(git config --get core.hooksPath 2>/dev/null || true)"
  if [ -n "$current" ]; then
    echo "[brain-precommit] note: core.hooksPath is '$current'; not arming $GIT_HOOKS_DIR. Scanning here instead." >&2
    return 1
  fi
  hooks_dir="$(git rev-parse --git-path hooks 2>/dev/null || true)"
  [ -n "$hooks_dir" ] || return 1
  for f in "$hooks_dir"/*; do
    case "$f" in *.sample) continue ;; esac
    if [ -f "$f" ]; then
      echo "[brain-precommit] note: $hooks_dir has hooks of its own; not arming $GIT_HOOKS_DIR. Scanning here instead." >&2
      return 1
    fi
  done
  git config --local core.hooksPath "$GIT_HOOKS_DIR" || return 1
  echo "[brain-precommit] armed the git pre-commit stage for this clone (core.hooksPath=$GIT_HOOKS_DIR)." >&2
}

# Commands that skip git hooks: --no-verify (git accepts --no-v...), a -n
# in a short-flag cluster, or a core.hooksPath override. Over-matching is
# harmless (it only means this stage scans too).
skips_git_hooks() {
  grep -qE -- '--no-v|(^|[[:space:]])-[a-zA-Z]*n[a-zA-Z]*([[:space:]]|$)|hooksPath' <<<"$COMMAND"
}

if [ "$GIT_HOOK" -eq 0 ]; then
  if git_stage_armed || arm_git_stage; then
    if ! skips_git_hooks; then
      echo "[brain-precommit] git pre-commit stage armed; Semgrep runs inside git commit." >&2
      exit 0
    fi
    echo "[brain-precommit] command skips git hooks; scanning what is staged now." >&2
  fi
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

# Collect staged files. Inside a git hook, git points GIT_INDEX_FILE at the
# commit's own index, so `git commit -a` and `git commit <paths>` show up
# here too. --diff-filter=ACMR catches Adds, Copies, Modifies,
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
      if [ -f "$f" ]; then SCAN_PATHS+=("$f"); fi
      ;;
  esac
done <<< "$STAGED"

if [ "${#SCAN_PATHS[@]}" -eq 0 ]; then
  echo "[brain-precommit] no scannable file types in staged set; skipping Semgrep." >&2
  echo "[brain-precommit] scan-skipped: opsera-unavailable (agent-level optional)" >&2
  exit 0
fi

# Rules. The local ruleset always runs and needs no network. The p/default
# registry ruleset is added only when semgrep.dev answers a quick probe.
#
#   Not `--config auto`: Semgrep refuses it under --metrics off ("Cannot
#   create auto config when metrics are off", exit 2), and metrics stay off.
#
#   Why probe first: Semgrep does not fail fast on a registry it cannot
#   reach. It retries the download with long backoff (~100 s measured with
#   Semgrep 1.183.0 behind a proxy that refuses semgrep.dev). curl honors
#   the same HTTPS_PROXY / NO_PROXY variables Semgrep does, so it takes the
#   same network path, and it gives up after 5 s.
#
#   BRAIN_PRECOMMIT_OFFLINE=1 skips the probe and the registry entirely.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_RULES="$(cd "$SCRIPT_DIR/../.." && pwd)/.semgrep/rules.yml"
REGISTRY_RULESET="p/default"

registry_reachable() {
  local code
  command -v curl >/dev/null 2>&1 || return 1
  code="$(curl -sS -o /dev/null --head --connect-timeout 3 --max-time 5 \
    -w '%{http_code}' "https://semgrep.dev/c/$REGISTRY_RULESET" 2>/dev/null)" || return 1
  case "$code" in
    429|5??) return 1 ;;  # Semgrep would sit in its retry loop on these.
    [234]??) return 0 ;;  # Any other answer: the network path works.
    *) return 1 ;;
  esac
}

CONFIGS=(--config "$LOCAL_RULES")
if [ "${BRAIN_PRECOMMIT_OFFLINE:-0}" = "1" ]; then
  RULES_DESC="local rules only (BRAIN_PRECOMMIT_OFFLINE=1)"
elif registry_reachable; then
  CONFIGS+=(--config "$REGISTRY_RULESET")
  RULES_DESC="local rules + $REGISTRY_RULESET"
else
  RULES_DESC="local rules only (semgrep.dev unreachable)"
fi

# Run Semgrep on the staged paths.
#
#   --error                  — exit 1 when there are findings.
#   --quiet                  — findings only; errors land in the JSON report.
#   --metrics off            — don't phone home from a developer machine.
#   --disable-version-check  — same. It also matters for speed: where
#                              semgrep.dev is blocked, the version check
#                              alone stalls every run by ~100 s.
#   --timeout 30             — per-rule, per-file cap; the hook is on the
#                              hot path.
#   --json-output            — machine-readable copy, used below to tell
#                              findings apart from errors.
SCAN_LOG="$(mktemp -t brain-precommit-XXXXXX.log)"
SCAN_JSON="$(mktemp -t brain-precommit-XXXXXX.json)"
trap 'rm -f "$SCAN_LOG" "$SCAN_JSON"' EXIT

rc=0
semgrep scan "${CONFIGS[@]}" \
  --error --quiet --metrics off --disable-version-check --timeout 30 \
  --json-output="$SCAN_JSON" \
  "${SCAN_PATHS[@]}" >"$SCAN_LOG" 2>&1 || rc=$?

# Read the JSON report: the number of findings on the first line, then one
# "  - <message>" line per error Semgrep reported. Prints nothing if
# Semgrep died before writing the report.
read_report() {
  python3 - "$1" <<'PY' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1]) as fh:
        report = json.load(fh)
except (OSError, ValueError):
    sys.exit(0)
print(len(report.get("results", [])))
for err in report.get("errors", []):
    text = str(err.get("message") or err.get("type") or "unknown error").strip()
    print("  - " + "\n    ".join(text.splitlines()))
PY
}
REPORT="$(read_report "$SCAN_JSON")"
FINDINGS="$(sed -n '1p' <<<"$REPORT")"
ERRORS="$(sed -n '2,$p' <<<"$REPORT")"
SCAN_OUTPUT="$(cat "$SCAN_LOG")"

# Exit codes, confirmed against Semgrep 1.183.0 (semgrep/error.py): 0 clean,
# 1 findings (with --error), anything else means Semgrep failed (2 fatal,
# 4 rule parse error, 5 bad YAML, 7 missing or invalid config, ...).
# Exit 1 only counts as findings when the report lists some: a Python crash
# before Semgrep's own error handling also exits 1.
if [ "$rc" -eq 1 ] && [ "${FINDINGS:-0}" -gt 0 ]; then
  cat >&2 <<EOF
[brain-precommit] FATAL: Semgrep found policy violations in staged files
($FINDINGS finding(s); rules: $RULES_DESC).

--- Semgrep output ---
$SCAN_OUTPUT
----------------------

To remediate: fix the findings above and re-stage. For a reviewed false
positive, add "# nosemgrep: <rule-id>" on that line and say why in the
commit body. To bypass in an emergency (NOT recommended), touch
/tmp/.brain-precommit-passed in a separate bash invocation, then re-run
the commit. Document the reason in the commit body.
EOF
  exit 2
fi

if [ "$rc" -ne 0 ]; then
  {
    echo "[brain-precommit] FATAL: Semgrep could not run (exit $rc), so nothing was scanned."
    echo "This is a problem with the gate, not a finding in your code."
    echo
    echo "Rules: $RULES_DESC"
    if [ -n "$ERRORS" ]; then
      echo "Semgrep reported:"
      echo "$ERRORS"
    fi
    if [ -n "$SCAN_OUTPUT" ]; then
      echo
      echo "--- Semgrep output ---"
      echo "$SCAN_OUTPUT"
      echo "----------------------"
    fi
    echo
    echo "Fix the error above; a broken .semgrep/rules.yml or Semgrep install is"
    echo "the usual cause. If the p/default download failed, export"
    echo "BRAIN_PRECOMMIT_OFFLINE=1 before starting Claude Code to scan with the"
    echo "local rules only. Emergency bypass: touch /tmp/.brain-precommit-passed"
    echo "in a separate bash invocation, then re-run the commit."
  } >&2
  exit 2
fi

# ── 5. Optional fallback: Opsera ──────────────────────────────────────────
#
# Bash hooks cannot invoke MCP tools directly. Whether Opsera is reachable
# is decided by the agent's MCP context, not by this script. We log the
# absence so audit trails are honest and move on.

echo "[brain-precommit] Semgrep clean (${#SCAN_PATHS[@]} file(s) scanned; rules: $RULES_DESC)." >&2
if [ -n "$ERRORS" ]; then
  echo "[brain-precommit] note: Semgrep passed but reported problems; some checks may not have run:" >&2
  echo "$ERRORS" >&2
fi
echo "[brain-precommit] scan-skipped: opsera-unavailable (agent-level optional)" >&2

exit 0
