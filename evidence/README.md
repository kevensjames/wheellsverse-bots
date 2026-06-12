# evidence/ — Append-only Audit Trail

**Purpose:** Independent, timestamped, hash-signed proof of what was actually verified at each stage. This is how trust is rebuilt after an agent claims something that turned out to be false.

---

## The principle

> **The agent does not get to be the source of truth. The evidence directory does.**

Claude Code (or any LLM agent) can claim a stage is done. The user runs `./deploy/verify_stage.sh N`, which writes a file here. That file is the source of truth.

When future-you (or a new Claude session) asks "is Stage 3 really done?", the answer is not "Claude said so." The answer is: read `evidence/stage_3_*.log` and check its SHA256.

---

## How to use

### After Claude Code claims a stage is done

```bash
# 1. Run the independent verifier
./deploy/verify_stage.sh 3

# 2. Read the verdict at the bottom of the new log file
tail -20 evidence/stage_3_*.log | tail -10

# 3. Commit the evidence
git add evidence/
git commit -m "Evidence: Stage 3 verification ($(date -u +%Y%m%dT%H%M%SZ))"
git push
```

### To audit a past claim

```bash
# List all verifications for a stage
ls -la evidence/stage_3_*.log

# Read the most recent
cat "$(ls -t evidence/stage_3_*.log | head -1)"

# Verify the SHA256 wasn't tampered with
LOG="$(ls -t evidence/stage_3_*.log | head -1)"
STORED_HASH=$(grep "SHA256 of log above" "$LOG" | awk '{print $NF}')
COMPUTED_HASH=$(head -n -4 "$LOG" | shasum -a 256 | awk '{print $1}')
[ "$STORED_HASH" = "$COMPUTED_HASH" ] && echo "INTACT" || echo "TAMPERED"
```

---

## Verdict codes

`verify_stage.sh` exits with:

| Code | Meaning |
|------|---------|
| `0`  | All checks passed. Stage is verified done. |
| `1`  | At least one check failed. Stage is NOT done. |
| `2`  | Usage error (no stage number, bad input). |
| `3`  | No checks defined for that stage. |
| `4`  | All run checks passed, but some were DEFERRED. Stage is incomplete pending preconditions. |

**Important:** exit code `4` is NOT a pass. A deferred check is unfinished work. Treat it the same as a failure for the purpose of "is the stage done?"

---

## File naming convention

```
evidence/stage_<N>_<UTC_TIMESTAMP>.log

Examples:
  evidence/stage_0_20260519T180530Z.log
  evidence/stage_3_20260519T231245Z.log
```

Timestamps are UTC, ISO 8601 basic format. Sortable alphabetically.

---

## What's in each file

Every evidence file contains:

1. **Header** — script name, stage number, timestamp, repo path, user, host
2. **Environment baseline** — git HEAD, branch, clean-tree check, Python version, venv state
3. **Per-check blocks** — for each verification:
   - Check number and name
   - Exact command run
   - Raw stdout + stderr
   - Exit code
   - PASS / FAIL / DEFERRED verdict
4. **Summary** — totals + names of failed/deferred checks
5. **Integrity footer** — SHA256 hash of everything above it

The hash makes after-the-fact editing detectable. If anyone (including Claude Code) modifies a committed evidence file, the stored hash won't match the recomputed one.

---

## Rules

1. **Evidence files are append-only.** Never edit a committed evidence file. If you need to re-verify, run the script again — it creates a new file.

2. **Every stage-completion commit must include a passing evidence file.** Use this git pre-commit hook (optional but recommended):

   ```bash
   # .git/hooks/pre-commit
   #!/bin/bash
   if git diff --cached --name-only | grep -q "docs/decisions/0[0-9]*-"; then
     if ! git diff --cached --name-only | grep -q "evidence/stage_"; then
       echo "ERROR: committing a decision log without evidence."
       echo "Run: ./deploy/verify_stage.sh <N> && git add evidence/"
       exit 1
     fi
   fi
   ```

3. **Claude Code does NOT generate evidence files.** Only `verify_stage.sh` does. If you see an evidence file that wasn't produced by the script, treat it as suspicious.

4. **Reading is free; running is required.** Anyone (Claude, you, future-you) can read evidence to know past state. But to claim *current* state, run the verifier again.

---

## When evidence and Claude Code disagree

**The evidence wins. Always. No exceptions.**

If Claude Code says "Stage 3 done" but the latest evidence file says `FAILED: smoke_test_tools`, then Stage 3 is not done. Period. The agent's job is to reconcile its claims with what the verifier produces, not to argue.

Common reconciliation paths:

- **Claude was right, verifier was wrong** → Almost never. If it happens, the verifier has a bug. Fix the verifier and re-run.
- **Claude was wrong** → Common. Acknowledge, fix the underlying issue, re-run the verifier, commit the new evidence.
- **Both were right, env differs** → Common with deferred checks. Document the env precondition in the decision log; do not pretend the check was run.

---

## Cleanup policy

Evidence files are small (typically <50 KB). Don't delete them. Git history of `evidence/` is part of the project's audit trail.

If the directory gets very large after months of use, archive (don't delete):

```bash
mkdir -p evidence/archive
mv evidence/stage_*_2026*.log evidence/archive/
git add evidence/
git commit -m "Archive 2026 evidence files"
```

---

## See also

- `HONESTY.md` — operating rules Claude Code must follow
- `deploy/verify_stage.sh` — the verifier itself
- `docs/decisions/` — per-stage architectural decisions

---

**Version:** 1.0
**Established:** Stage 5 retrospective (after the trust incident)
