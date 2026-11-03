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

- get `rm -f`'d by the stage that runs the scan (so each `touch` covers
  exactly one commit attempt; once the git stage is armed, that's the git
  stage, see [Two stages](#two-stages-claude-code-then-git)),
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

1. PreToolUse stage: reads tool input from stdin (Claude `PreToolUse`
   contract). If the command doesn't match `git\s+commit`, exit 0 (no-op).
2. `cd` to the repo root. PreToolUse stage: arm the git stage if it can,
   and once it's armed, hand the scan to git (see
   [Two stages](#two-stages-claude-code-then-git)).
3. Honor the bypass flag if present and ≤ 5 min old (also accepts the
   legacy Opsera flag for muscle-memory back-compat).
4. Look up `semgrep` on `PATH`. **Missing Semgrep is fatal.** The
   primary gate intentionally does *not* graceful-degrade — if your
   developer environment can't run Semgrep, your commits should block
   until you fix that.
5. Collect staged files via `git diff --cached --name-only
   --diff-filter=ACMR`, filter to file extensions Semgrep's
   default rules cover (Python, JS/TS, Go, Ruby, Java/Kotlin, C/C++, C#,
   PHP, Rust, Swift, Scala, shell).
6. Pick rules (see [Rules](#rules-local-first-registry-when-reachable)):
   `.semgrep/rules.yml` always; `p/default` too when semgrep.dev answers
   a 5-second `curl` probe.
7. Run `semgrep scan --config .semgrep/rules.yml [--config p/default]
   --error --quiet --metrics off --disable-version-check --timeout 30
   --json-output=<tmp> <paths>`.
8. Read the result:
   - exit 0 → pass.
   - exit 1 *and* the JSON report lists findings → exit 2, "Semgrep found
     policy violations", with the findings.
   - anything else → exit 2, "Semgrep could not run", with Semgrep's own
     error messages. Nothing was scanned; this is a broken gate, not a
     finding.

After the `git commit` match, any unexpected error inside the script also
exits 2 ("hook error … commit blocked"). Claude Code only blocks on exit
2, so without this an internal failure would let the commit through
unscanned.

### Two stages: Claude Code, then git

The same script runs at two points:

| Stage | Runs | Sees |
| ----- | ---- | ---- |
| PreToolUse (Claude Code hook) | before the Bash command | only files already staged when the call starts |
| Git pre-commit (`scripts/hooks/git/pre-commit`, which runs the script with `--git-hook`) | inside `git commit`, after git builds the commit's index | exactly what gets committed, including `git commit -a`, `git commit <paths>` and `git add x && git commit` |

On the first commit in a clone, the PreToolUse stage arms the git stage
with `git config --local core.hooksPath scripts/hooks/git`. It only does
this when nothing else claims git hooks in that clone: `core.hooksPath`
unset, and no hooks of its own in `.git/hooks` (setting it would silently
switch those off). Otherwise it says so and keeps scanning itself.

Once armed, the PreToolUse stage hands off: it exits 0 and git runs the
scan. It still scans itself when the command skips git hooks
(`--no-verify`, a `-n` in a short-flag cluster, or a `core.hooksPath`
override), so those commits get at least the files staged in advance.

Arming covers every commit in that clone, including ones you make in your
own terminal. Skip the gate for one commit with `git commit --no-verify`.
Disarm it with `git config --unset core.hooksPath`.

### Rules: local first, registry when reachable

**Local rules: `.semgrep/rules.yml`.** Always run, need no network. A
small, high-signal set; every finding blocks:

| Rule ID                            | Catches                                                              |
| ---------------------------------- | -------------------------------------------------------------------- |
| `python-shell-injection`           | `subprocess` with `shell=True`, `os.system`, `os.popen` on a non-literal command |
| `python-eval-exec-dynamic`         | `eval` / `exec` on a non-literal value                               |
| `python-yaml-unsafe-load`          | `yaml.load` without `SafeLoader`, `yaml.unsafe_load`                 |
| `python-tls-verification-disabled` | `verify=False`, `ssl._create_unverified_context()`, `CERT_NONE`      |
| `python-jwt-verification-disabled` | `jwt.decode` with `verify_signature: False` or the `none` algorithm  |
| `js-eval-dynamic`                  | JS/TS `eval` / `new Function` on a non-literal value                 |
| `hardcoded-credential`             | AWS, GitHub, Slack, Stripe, Anthropic, OpenAI, Shopify keys; private keys |
| `hardcoded-telegram-bot-token`     | Telegram bot tokens                                                  |

**Registry rules: `p/default`.** Added when semgrep.dev is reachable.
Much broader coverage, needs the network.

Why it works this way (measured with Semgrep 1.183.0):

- **Not `--config auto`.** Semgrep refuses it under `--metrics off`
  (`Cannot create auto config when metrics are off`, exit 2), and metrics
  stay off. This used to fail every commit that staged a code file.
- **Probe before using the registry.** When Semgrep cannot reach
  semgrep.dev it does not fail fast: it retries the download with
  backoff, about 100 s before giving up. A `curl` probe with a 5 s cap
  decides first. `curl` reads the same `HTTPS_PROXY` / `NO_PROXY`
  variables Semgrep does, so it takes the same network path.
- **`--disable-version-check`.** Semgrep checks semgrep.dev for a newer
  version after every scan. Where semgrep.dev is blocked, that check
  alone stalls each run by about 100 s, even with local rules only.
- **`BRAIN_PRECOMMIT_OFFLINE=1`** skips the probe and the registry, so the
  gate scans with local rules only. The hook inherits Claude Code's
  environment, so export it before starting `claude`.

Semgrep exit codes the hook relies on (`semgrep/error.py` in 1.183.0): 0
clean, 1 findings (with `--error`), 2 fatal error, 4 rule parse error, 5
unparseable YAML, 7 missing or invalid config. With `--quiet`, config
errors print nothing to the terminal, so the hook reads them from the JSON
report. Exit 1 alone is not trusted as "findings": a Python crash before
Semgrep's own error handling also exits 1.

### Claude Code cloud sessions

- Semgrep is not preinstalled. Add it to the environment's **Setup
  script** (cloud environment menu in the session title bar → Edit).
  This is the install the gate was verified with:

  ```bash
  python3 -m venv /opt/semgrep-venv && /opt/semgrep-venv/bin/pip install semgrep==1.183.0 && ln -sf /opt/semgrep-venv/bin/semgrep /usr/local/bin/semgrep
  ```

- If the environment's network policy doesn't allow semgrep.dev (the
  proxy answers 403), the gate scans with local rules only. To get
  `p/default` there too, add `semgrep.dev` under **Allowed domains** in
  the environment's network settings.

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
| `git commit ...`, code staged, Semgrep clean | exit 0 with file-count + rules log |
| `git commit ...`, code staged, Semgrep findings | exit 2, "found policy violations", prints findings |
| `git commit ...`, Semgrep could not run (bad rules, crash, failed download) | exit 2, "could not run", prints Semgrep's errors |
| `git commit ...`, semgrep.dev unreachable | scans with local rules only; pass/block as above |
| `git commit ...`, `BRAIN_PRECOMMIT_OFFLINE=1` | scans with local rules only, no probe |
| `git commit ...`, unexpected error inside the hook | exit 2, "hook error", blocks |
| `git commit ...`, fresh bypass flag | exit 0 with `bypass flag honored`        |
| `git commit ...`, no semgrep on PATH | exit 2 with install instructions       |
| `git commit ...`, git stage armed (PreToolUse stage) | exit 0, "Semgrep runs inside git commit"; the git stage scans |
| `git commit --no-verify ...`, git stage armed | PreToolUse stage scans what is staged now |
| Git stage: findings, or Semgrep could not run | git aborts the commit with the same messages |

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

The git stage needs no settings file. The PreToolUse stage arms it per
clone with `core.hooksPath=scripts/hooks/git` (see
[Two stages](#two-stages-claude-code-then-git)).

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
| Find what's about to fail                     | `semgrep scan --config .semgrep/rules.yml --config p/default --error --metrics off --disable-version-check $(git diff --cached --name-only --diff-filter=ACMR)` (drop `--config p/default` offline) |
| Suppress a false-positive finding             | Add `# nosemgrep: <rule-id>` on the offending line (short ID works, e.g. `python-shell-injection`); say why in the commit body |
| Scan with local rules only                    | `export BRAIN_PRECOMMIT_OFFLINE=1` before starting `claude`                         |
| Arm the git stage by hand                     | `git config core.hooksPath scripts/hooks/git`                                       |
| Disarm the git stage                          | `git config --unset core.hooksPath`                                                 |
| Re-enable the Opsera plugin globally          | Remove the `enabledPlugins` entry — the plugin's own hook will take over again      |
| Add or tune a local rule                      | Edit `.semgrep/rules.yml` (don't edit the script), then run `python -m pytest tests/test_precommit_scan_hook.py` |

---

## What this hook does NOT do

- It does **not** scan the entire repo on every commit — only staged
  files. A finding in `narai/data/` won't surface on a PR that touches
  `infra/brain/`.
- It does **not** call any MCP tool. The MCP-tool absence quirk that
  blocked Phase A/B is structurally impossible here.
- It is **not** a secrets scanner. The local rules catch a few
  well-known credential formats, and only inside staged code files;
  `.env`, JSON, YAML and Markdown are never scanned. For real secrets
  coverage use a dedicated scanner (Aikido, or Semgrep's `p/secrets`).
- It scans the **working-tree** copy of each staged file, not the staged
  blob. With partial staging (`git add -p`), unstaged edits get scanned
  too.
- Where the git stage can't be armed (a clone with its own hooks setup),
  the PreToolUse stage alone does **not** see files the commit command
  stages itself: in `git add x && git commit ...` or `git commit -a`,
  those changes aren't staged yet when it runs. Stage in a separate Bash
  call there, then commit.
- `--no-verify` skips the git stage. The PreToolUse stage then only sees
  what was staged before the call.
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
- `scripts/hooks/pre-commit-scan.sh` — the script itself, ~390 lines,
  read it before making changes here.
- `scripts/hooks/git/pre-commit` — the git stage's entry point.
- `.semgrep/rules.yml` — the local ruleset.
- `tests/test_precommit_scan_hook.py` — hook tests: stubbed decisions
  (no network, no Semgrep), real `git commit` runs through the git stage,
  and real-Semgrep checks of every local rule.
