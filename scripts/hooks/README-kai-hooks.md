# KAI governance hooks

Project-scoped Claude Code hooks that turn recurring KAI-ops lessons into automatic guardrails.
They run **alongside** the global OMC hooks and the existing Semgrep `pre-commit-scan.sh`, and
all **fail open** (a hook error never blocks — only a positive match does). Wired in
`.claude/settings.json`. Self-tests: `python3 scripts/hooks/test_kai_hooks.py` (33 cases) and
`python3 scripts/hooks/test_kai_ops_guard.py` (20 cases).

| Script | Event / matcher | Blocks? | What |
|---|---|---|---|
| `kai_bash_guard.py` | PreToolUse · Bash | yes | ad-hoc codesign/TCC; token-in-URL; secret-file egress; `KAI_*_ENABLED=true`; deploy/soak-service while soak active; shared `git stash`; prod device-enroll |
| `kai_ops_guard.py` | PreToolUse · Bash | 2 rules | CORRECTNESS traps (vs the safety rules above): `--skip-deploys` inertness; log-stream truncation; zsh `--include=*` / `$var:` / backtick-in-`-m`; unnamed upload deploy (blocks); force-push to a deploy branch (blocks); trusting a self-reported `git_sha` |
| `kai_file_guard.py` | PreToolUse · Write/Edit | yes | `KAI_*_ENABLED=True` in config; new `*.py` shadowing stdlib; secret value into a doc/evidence file |
| `kai_posttool_guard.py` | PostToolUse · Write/Edit | no (reminds) | migration reversibility; browser egress-channel checklist; dead cert invariant; route-completeness; payment/SOL scope; run-the-test |
| `kai_stop_guard.py` | Stop | no (reminds) | a hard "CERTIFIED/production-verified/deployed" claim with no evidence in the turn; status above the recorded ceiling. WARN-only (it reasons over prose; hard-blocking misfires on meta-discussion/negations — it skips those) |
| `kai_session_start.py` | SessionStart | no | prints status ceiling, active markers, HEAD |
| `kai_precompact.py` | PreCompact | no | saves SHA/status/markers to `.remember/kai-precompact.md` |

## Markers (gitignored local toggles — a human flips these deliberately)

- `.kai-status` — the recorded status ceiling (read by the Stop guard + banner).
- `.kai-soak-active` — while present, the Bash guard blocks deploy/teardown/prod-push/soak-service.
- `.kai-allow-enable` — permit setting a `KAI_*_ENABLED` flag on (deliberate enablement).
- `.kai-allow-shadow` — permit a new module that shadows a stdlib name.
- `.kai-allow-egress` — permit sending a secret-looking file over the network.
- `.kai-allow-device-enroll` — permit a production device-enrollment call.
- `.kai-allow-inert-set` — permit a `--skip-deploys` set without the staleness warning.
- `.kai-allow-blind-up` — permit an upload deploy that does not name its target service.

Remove `.kai-soak-active` only after the 72h soak completes and its counters are confirmed at zero.

## kai_ops_guard — why each rule exists

Added 2026-09-11. Every rule is a real incident from the governed-ops sessions, not a hypothetical.
Most WARN rather than block: the operation is usually legitimate, and the failure is believing the
wrong thing about its effect.

| Rule | The incident | Cost |
|---|---|---|
| `--skip-deploys` inertness | a Railway cron run inherits its deployment's env SNAPSHOT; a briefing run still attempted an HTTP send 63 min after the flag was stored false | hit **3×**; produced a containment claim that was not true |
| log stream into `head` | a verdict script matched audit id 286 — a run predating the test window — because capture began 18s before the real run finished | right answer from the wrong evidence |
| zsh `--include=*` | unquoted glob → zsh aborts with "no matches found" before the program runs | silent empty search |
| zsh `$var:` | `:r` is a parameter modifier, not a literal colon | mangled a git refspec |
| zsh backtick in `-m` | command substitution executed the word and deleted it from the message | a commit message lost a word |
| unnamed upload deploy | the link command failed **silently**, leaving the CLI on another project; an unnamed upload began pushing one app into an unrelated project | killed mid-upload |
| force-push to a deploy branch | `production` is protected (force pushes and deletions prohibited) | — |
| self-reported `git_sha` | production reports a SHA two releases old while running the current one (upload deploys read a stale env var) | any check trusting it concludes falsely |

### Mention vs invocation

`kai_ops_guard` matches only at a **command position** (start of line, or after `;` `&&` `||` `|`)
and skips matches inside quoted arguments. This matters: the companion guard's substring matching
produced **three** false positives in a single session, each blocking legitimate read-only work —

1. a `grep` whose *search pattern* contained a deploy command,
2. a read-only status query naming the soak service,
3. **editing this very README**, because the text contains the words `device`, `enroll` and
   `production` near each other.

`_is_invocation()` is the shared helper; its negative cases are covered in
`test_kai_ops_guard.py` ("grepping FOR the deploy string is NOT blocked", etc.).

A guard that fires on a mention teaches people to work around it, which is worse than not having
it. If the companion guard is revised, rules 5 and 7 are the ones to make invocation-aware.

## Scope note: frameworks

Rules are written for the stack that exists here — Python (~1330 files, two FastAPI apps), static
HTML dashboards, shell, and one React/Vite/Tailwind app (`trade-app`). **There is no Angular in
this estate** (no `angular.json`, no `@angular/core` in any repo checked), so no Angular-specific
rules were written; the zsh/git/deploy rules are framework-agnostic and apply regardless. If an
Angular or other framework app lands, add framework rules then rather than speculatively now.

## Operational note

**Hook changes take effect at the next session start.** Claude Code reads `.claude/settings.json`
when the session begins, so a newly wired hook does not guard the session that added it. Verify a
new hook by invoking it directly with hook JSON on stdin (see the self-tests) rather than assuming
the live session picked it up.
