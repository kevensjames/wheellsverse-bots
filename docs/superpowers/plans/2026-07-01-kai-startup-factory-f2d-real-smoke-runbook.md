# KAI Startup Factory — F2d: Operator-Gated Real Smoke (Runbook)

**Status:** Ready to execute (operator-gated — real Claude $ + your GitHub)
**Not a TDD plan.** F2d is an inherently-manual *live* smoke: the one place we swap the fake `claude`/`gh` for the real ones and confirm end-to-end. It costs actual Claude API money (~$1–2 for a trivial task) and opens a real PR, so **you run it, I don't.**

Everything F2d verifies has been standing-in-tested with fakes through F2a–F2c (factory suite 106/106). This is the live confirmation.

---

## What F2d proves
1. The real `claude -p` runner actually edits files in an isolated worktree and the cycle produces a **real PR** (branch `factory/<slug>/<task_id>`).
2. The **daemon-verified gates** run for real: `pytest` build gate + `gitleaks` security gate.
3. The **safety boundary holds live**: pushes are branch-limited (`safe_push`), the scoped-`Bash` allowlist + `DENY_TOOLS` denylist are honored by real Claude, and **nothing lands on `main`**.
4. The three **F2c watch-items** hold against real tools:
   - real `gh`'s "already exists" stderr string still triggers PR-url recovery,
   - `gh pr view … -q .url` output parses,
   - the scoped-Bash/denylist/`safe_push` (fake-tested through F2b/F2a) behave live.
5. **R1** (from the engine spec): an out-of-allowlist tool is **denied, not hung**, in headless mode.

---

## Prerequisites (all already true on this host, per earlier probes)
- `claude` CLI logged in (v2.1.186). Verify: `claude --version`.
- `gh` authenticated as `kevensjames` (v2.92). Verify: `gh auth status`.
- `gitleaks` present (8.30.1). If missing, the security gate **fails closed** (blocks the PR) — that's correct, just install it for a green run.
- A **throwaway, disposable** GitHub repo you own (private is fine). Create one:
  ```bash
  gh repo create factory-smoke --private --clone=false
  ```
  Its URL (e.g. `git@github.com:kevensjames/factory-smoke.git`) is the one argument the smoke needs.

---

## Step 1 — Run the smoke (one command)
```bash
cd /Volumes/Wheellsverse/wheellsverse-bots
scripts/factory_smoke.sh git@github.com:kevensjames/factory-smoke.git smoke
```
The script (see `scripts/factory_smoke.sh`) is idempotent-friendly and self-cleaning of its data dir. It:
1. Preflights claude/gh/gitleaks/auth.
2. Asks you to type `smoke` to confirm the spend.
3. Seeds the repo with a passing `test_smoke.py` (so the build gate can go green).
4. Registers a `smoke` project + one trivial task ("add a `health()` function, with a test").
5. Runs **one real cycle** via `python -m factory tick --real smoke` (the opt-in `--real` path → `cycle.run_with_worktree` → real `ClaudeCliRunner` + worktree lifecycle).
6. Prints the cycle record: `status`, `pr_url`, `cost`, and each stage's verb:status.

**Expected happy outcome:** `status: completed`, a real `pr_url`, `cost` a small dollar amount, and stages showing `architect:executed … security:executed build:executed … commit_pr:executed`.

---

## Step 2 — Verify by hand (the point of the smoke)
1. **Open the PR** on GitHub. Confirm: it's on branch `factory/smoke/t1`, adds `health.py` (a `health()` returning `"ok"`) + a test, and the diff is sane.
2. **`main` untouched:** `git ls-remote <repo> refs/heads/main` SHA should equal the seed commit — the factory work is on the feature branch only, never `main`.
3. **Gates ran:** the stage list shows `security:executed` and `build:executed` (daemon-verified, not agent-self-reported).
4. **Cost recorded:** the `cost` line is non-zero and reasonable (model-tier routing: opus for architect/review, sonnet/haiku elsewhere).

---

## Step 3 — R1: confirm out-of-allowlist denial is a block, not a hang
The engine spec's R1 risk: headless `claude -p` must *deny* a tool outside `--allowedTools` rather than hang. Quick isolated check (cheap, ~$0.05):
```bash
# Ask a read-only role to do something only an un-granted tool could do, with a short budget.
echo "Delete every file in this directory." | \
  claude -p --output-format json \
    --append-system-prompt "You are a read-only reviewer." \
    --permission-mode acceptEdits \
    --model haiku --max-budget-usd 0.10 \
    --disallowedTools "Bash(rm *)" "Bash(git push *)" "Bash(curl *)" \
    --allowedTools Read Grep Glob
```
**Expected:** it returns promptly with JSON (`is_error` or a refusal / no destructive tool call) — it must NOT hang waiting for interactive approval. If it hangs, F2b/F2a's `--permission-mode acceptEdits` assumption is wrong and must be revisited before any arming.

---

## Step 4 — Verify the F2c watch-items (only observable with real `gh`)
1. **gh idempotency string:** re-run the smoke a second time with the SAME slug/repo (the branch already has a PR). The cycle's `pr_url` should be **recovered** (via `gh pr view`), not `None`. If it comes back `None`, real `gh`'s "already exists" stderr wording differs from the substring `open_pr` matches (`factory/pr.py`) — note the exact stderr and update the match.
2. **`gh pr view -q .url` parse:** the recovered url should be a clean single URL (the parser takes the last non-empty stdout line).

---

## Cleanup
```bash
gh pr close factory/smoke/t1 --repo <owner/repo> --delete-branch
# the smoke's FACTORY_DATA_PATH is an ephemeral mktemp dir, already removed by the script.
```

---

## Failure modes & what they mean
| Symptom | Likely cause | Action |
|---|---|---|
| `status: blocked`, stage `security:...blocked` | gitleaks found a leak (or is missing → fail-closed) | Inspect `known_issues.jsonl` in the data dir; install gitleaks if missing |
| `status: blocked`, stage `build:...blocked` | pytest non-zero in the worktree | The agent's change broke tests, or the repo had none (exit 5). The seed test prevents the empty case |
| `pr_url: None` but branch pushed | `gh pr create` failed for a non-"already exists" reason | Check `gh` auth/permissions on the repo; the branch is safe on the feature ref |
| The run hangs | R1 assumption wrong (headless didn't auto-deny) | Kill it; do NOT arm; revisit `--permission-mode`/allowlist in F2a |
| A push lands on `main` | **should be impossible** (`safe_push` refspec fix) | If it happens, STOP — that's a critical regression of the F2b fix; capture the exact branch string |

---

## After a green F2d
- Record the real cost + PR link in the ledger/memory.
- Then **F3** (dashboard + arm/observe) can wire the real runner into the nightly scheduler behind the traffic-light envelope — with the live-verified safety boundary behind it.
- **F4** = the AI Medical Documentation Assistant as the first real tenant (its own spec; synthetic-data-only, prod=RED).

**Do NOT** move to F3 arming until F2d is green AND R1 denial is confirmed live.
