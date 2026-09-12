# Upstream Intake Report — agency-agents (Workforce Phase 2)

**Status:** `WORKFORCE_IMPORTED_IN_QUARANTINE` — read-only, quarantined, nothing
normalized/activated/imported-as-code. Phase 3 NOT started (awaits owner review).

## Source & provenance

| Field | Value |
|---|---|
| Repository | `https://github.com/msitarzewski/agency-agents` |
| Pinned commit | `6d29a9b08785a0e49ffc9818bbdd381164c2df5f` |
| Retrieved (UTC) | `2026-09-12T10:51:06Z` |
| License | **MIT** — "Copyright (c) 2025 AgentLand Contributors" (preserved) |
| Quarantine path | `/Users/jhonwheeler/kai-upstream-quarantine/agency-agents` (OUTSIDE the KAI repo and all agent config dirs) |
| Machine-readable inventory | `backend/app/services/workforce/generated/upstream_inventory.json` (sha256 `a3873dfb6b76a67105ceba8bc9ae539e2e5b3b74d4b2863651a7fa6b5e61b15e`) |

## Method (read-only; no upstream code executed)

- Pinned via `git ls-remote` then `git clone --depth 1 --no-tags` with
  `GIT_LFS_SKIP_SMUDGE=1`, `core.hooksPath=/dev/null`, **no submodule recursion**.
- Enumeration/hashing/static-scan done by a stdlib-only script reading bytes only.
- **`install.sh` / `convert.sh` / any upstream code: never run.** No dependency
  install. No git hooks/submodules/LFS smudge. Nothing copied into `~/.claude`,
  `~/.codex`, `~/.config/claude`, or `~/.cursor` (verified: 0 files each).
- Only two generated artifacts + one test were added to the feature branch.

## Counts (derived from files)

| Metric | Value |
|---|---|
| Declared divisions (divisions.json) | 18 |
| **Agent files (frontmatter `.md` under the 18 divisions)** | **264** |
| Excluded non-agent `.md` (no frontmatter) | 0 |
| Duplicate stable-ids / collisions | **0** |
| Symlinks found | 0 |
| Flagged for review (reason-coded) | 45 |

The upstream README advertises "230+"; the true count at this pinned commit is
**264**, derived from the files (not hard-coded — the test re-derives it).

## Filesystem ↔ divisions.json reconciliation

- **Clean.** `declared_not_on_disk = []`, `on_disk_not_declared = []` — the 18
  directories on disk exactly match the 18 declared divisions.
- Non-division directories present and correctly excluded: `.github`, `examples`,
  `integrations` (conversion outputs), `scripts`, `strategy` (playbooks, no agent
  frontmatter) — per divisions.json's own `_note` and `NON_DIVISION_DIRS`.
- Every included file is in `agents[]` with path + SHA-256; every excluded file is
  in `excluded[]` with a reason. No file silently dropped.

## Quarantine findings (45) — reason-coded, none imported

Conservative static scans flagged 45 files. Manual review of the non-`EXEC` matches
(and a sample of `EXEC`) shows **all are benign agent content — no genuine
prompt-injection, secret-exfiltration, or install directive targeting KAI:**

| Reason code | Count | Characterization |
|---|---|---|
| `EXEC_CONTENT_PRESENT` | 39 | ```` ```bash ````/shell snippets + `npm/pip install` *examples* in dev-oriented agents. Documentation, not executed. |
| `SECRET_EXFIL_PATTERN` | 5 | False positives: security agents discussing credential handling (e.g. "no long-lived secret to leak", a `UPLOADPOST_TOKEN` env-var table, a support "send a password reset link" script, an SSO/account-takeover discussion). |
| `INJECTION_PATTERN` | 1 | `engineering-prompt-engineer.md` — an agent that **tests for** "Ignore all previous instructions" (it defends against injection; the phrase is an example). |
| `PATH_ANOMALY` | 0 | none |

These are recorded (with per-file reason codes) in the inventory's
`quarantine_findings`. They are **review annotations, not imports** — Phase 2
imports no behavior; every character stays a quarantined declaration until KAI
admits it in a later, separately-authorized phase.

## Required-evidence checklist

- ✅ pinned SHA + retrieval timestamp · ✅ exact agent count derived from files (264)
- ✅ filesystem↔divisions.json reconciliation (clean) · ✅ every included/excluded file accounted
- ✅ source path + SHA-256 per candidate (inventory `agents[]`) · ✅ duplicate/collision report (0)
- ✅ quarantine findings with reason codes (45) · ✅ license/provenance (MIT, preserved)
- ✅ proof no upstream executable ran · ✅ proof user agent dirs + KAI tree received no unreviewed files
- ✅ tests + negative controls (`backend/tests/test_workforce_intake.py`)

## NOT done (by authorization)

No normalization, KAI-display-naming, ≥270 expansion, manifest generation,
catalog registration, adapter/handler/router/worker, migration, merge, or deploy.
**Phase 3 must not begin until the owner reviews these intake results.**
