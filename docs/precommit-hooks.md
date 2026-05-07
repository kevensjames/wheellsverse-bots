# Pre-commit hook architecture

This repo ships its own pre-commit security gate at
`scripts/hooks/pre-commit-scan.sh`, wired via `.claude/settings.json` as a
Claude Code `PreToolUse` hook on the `Bash` tool. It **replaces** the
Opsera-devsecops plugin's pre-commit hook, which is disabled at the
project level via `.claude/settings.local.json`.

---

## Why this exists

During the Phase A / Phase B audit work (PR #2) the Opsera plugin's
pre-commit hook produced four blocking failure modes that weren't visible
from its error message. This document captures the mechanics so they
don't ambush the next person:

### Quirk 1 — the regex matches anywhere in the command

The hook checks `grep -qE 'git\s+commit'` against the **entire bash
command string**, not the executable name. A command like
`gh pr create --body "...git commit..."` triggers the gate because the
PR body text contains the literal substring `git commit`. Workaround:
either rephrase the body or pre-touch the bypass flag in a *separate*
bash call.

### Quirk 2 — the bypass flag is single-use, ≤ 5-min mtime

The legacy Opsera flag (`/tmp/.opsera-pre-commit-scan-passed`) and the
new repo flag (`/tmp/.brain-precommit-passed`) both:

- get `rm -f`'d the moment the hook sees them (so each `touch` covers
  exactly one commit attempt),
- only count if their mtime is < 300 seconds old,
- must be created in a **separate** Bash invocation that does *not*
  contain `git commit` in the command string — otherwise the hook fires
  before `touch` runs and the flag never appears.

In practice: 1 Bash call to `touch /tmp/.brain-precommit-passed`, then
1 separate Bash call to `git commit ...`.

### Quirk 3 — MCP tools are not reachable from bash

The original Opsera hook demanded
`mcp__plugin_opsera-devsecops_opsera__security-scan` *as an MCP tool
call from the agent context*. A bash script cannot invoke an MCP tool
directly. When the agent session doesn't have the tool surfaced (the
common case in MCP-light sessions, including Claude Code with no
`claude mcp add` for opsera-agent), the hook had no graceful path —
every commit blocked.

The replacement script never depends on an MCP tool. Semgrep is invoked
as a CLI binary (`/usr/local/bin/semgrep`), which is reachable from any
bash context.

---

## How the new hook works

### Primary gate (REQUIRED): Semgrep

1. Reads tool input from stdin (Claude `PreToolUse` contract).
2. If the command doesn't match `git\s+commit`, exit 0 (no-op).
3. Honor the bypass flag if present and ≤ 5 min old (also accepts the
   legacy Opsera flag for muscle-memory back-compat).
4. Look up `semgrep` on `PATH`. **Missing Semgrep is fatal.** The
   primary gate intentionally does *not* graceful-degrade — if your
   developer environment can't run Semgrep, your commits should block
   until you fix that.
5. Collect staged files via `git diff --cached --name-only
   --diff-filter=ACMR`, filter to file extensions Semgrep's default
   rules cover (Python, JS/TS, Go, Ruby, Java/Kotlin, C/C++, C#, PHP,
   Rust, Swift, Scala, shell).
6. Run `semgrep scan --config auto --error --quiet --metrics off
   --timeout 30 <paths>`. Any finding → exit 2 with the Semgrep output
   in the failure message.

### Optional fallback: Opsera

The script logs `scan-skipped: opsera-unavailable (agent-level
optional)` and proceeds. This is the **graceful-degrade path** the
audit follow-up specified. If you want a second-opinion Opsera scan,
the agent can invoke its MCP tool directly during normal workflow —
the hook neither requires nor blocks on it.

### Aikido

Aikido has no pre-commit hook in this plugin set; the Aikido MCP tool
remains available for ad-hoc scans (`aikido scan` skill). No change.

---

## Behavior matrix

| Bash command kind                  | Hook action                              |
| ---------------------------------- | ---------------------------------------- |
| Anything not containing `git commit` | exit 0 immediately (no-op)             |
| `git commit ...`, no staged files  | exit 0 with "no staged files" log        |
| `git commit ...`, only non-code staged | exit 0 with "no scannable file types" |
| `git commit ...`, code staged, Semgrep clean | exit 0 with file-count log         |
| `git commit ...`, code staged, Semgrep findings | exit 2, prints findings, blocks |
| `git commit ...`, fresh bypass flag | exit 0 with `bypass flag honored`        |
| `git commit ...`, no semgrep on PATH | exit 2 with install instructions       |

---

## Wiring

`.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/scripts/hooks/pre-commit-scan.sh"
          }
        ]
      }
    ]
  }
}
```

`.claude/settings.local.json` (per-developer, gitignored on most
projects but tracked here so the plugin disable is reproducible):

```json
{
  "enabledPlugins": {
    "opsera-devsecops@claude-plugins-official": false
  }
}
```

---

## Operating it

| Need                                          | Action                                                                              |
| --------------------------------------------- | ----------------------------------------------------------------------------------- |
| Skip the gate for a single commit (emergency) | `touch /tmp/.brain-precommit-passed` in a *separate* bash call, then commit         |
| Find what's about to fail                     | `semgrep scan --config auto --error --quiet $(git diff --cached --name-only)`       |
| Suppress a false-positive finding             | Add a `# nosemgrep: <rule-id>` comment on the offending line                        |
| Re-enable the Opsera plugin globally          | Remove the `enabledPlugins` entry — the plugin's own hook will take over again      |
| Ship a new tool that triggers a Semgrep rule  | Add a Semgrep config override under `.semgrep.yml` (don't edit the script)          |

---

## What this hook does NOT do

- It does **not** scan the entire repo on every commit — only staged
  files. A finding in `narai/data/` won't surface on a PR that touches
  `infra/brain/`.
- It does **not** call any MCP tool. The MCP-tool absence quirk that
  blocked Phase A/B is structurally impossible here.
- It does **not** check secrets. For that, use the Aikido or Semgrep
  secrets ruleset via dedicated workflow (see `.github/workflows/`).
- It does **not** run the wider Brain test suite. `brain-tests.yml`
  handles that on push/PR.

---

## See also

- `~/.claude/projects/.../memory/project_opsera_precommit_hook.md` —
  per-developer notes on the original Opsera mechanics that this
  document supersedes.
- `~/.claude/projects/.../memory/project_brain_test_venv.md` — the
  parallel chromadb-venv blocker that prevents running the wider Brain
  suite locally.
- `scripts/hooks/pre-commit-scan.sh` — the script itself, ~120 lines,
  read it before making changes here.
