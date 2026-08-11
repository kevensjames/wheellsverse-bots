# KAI Merge Handoff

The ten-PR integration is verified and staged. The harness correctly blocked a
direct mainline push; the operator performs (or authorizes) the protected merge.
This document is the deterministic handoff. All hashes live in
[`MERGE_MANIFEST.json`](./MERGE_MANIFEST.json) — read them there, never from memory.

## Verified state

| | |
|---|---|
| base (`istanbul`) | `2fe6e46` |
| verified integration commit | `40fdf90` (fast-forward of base; every PR head is an ancestor) |
| tests | **1020 passed, 18 skipped, 0 failed** (`pytest tests/ -q`, DB env set) |
| migration head | `0008_add_kai_swe_tasks` — single head, applied AND downgraded on real PostgreSQL |
| CI | **DEGRADED** — 2 pre-existing infra fails tracked in #49, #50 (not regressions) |

## Merge order (mandatory)

Remediation first, then the foundation stack:

```
#43  #46  #44  #45  #47  #48        # remediation
#39  #41  #40  #42                  # foundation (39 → 41 → 40 → 42)
```

`#42` depends on `#41` (stacked). `#40` and `#42` both touch `main.py`, `.env.example`,
`requirements.txt`, and both introduced a `0007` migration — the collision is already
resolved in the integration commit (see [`CONFLICT_RESOLUTION_PATCHES.md`](./CONFLICT_RESOLUTION_PATCHES.md)).

## Method 1 — GitHub PR merge (preferred; auditable)

Merge each PR through the GitHub UI in the order above. When you reach `#40` and `#42`,
GitHub will report conflicts in `main.py` / `.env.example` / `requirements.txt` — resolve
them as **additive unions** (keep both sides; the resolution is documented and already
present in commit `40fdf90`). Renumber `#42`'s migration to `0008` if GitHub's editor
doesn't carry the rename (it is `0008_add_kai_swe_tasks`, `down_revision = 0007_add_kai_code_chunks`).

This path preserves per-PR review, status checks, and merge audit trail.

## Method 2 — fast-forward the verified commit (requires explicit approval)

Only if the repo explicitly permits fast-forward integration pushes and per-PR review is
already satisfied. Use the **immutable commit**, fast-forward only, no force:

```bash
git push origin 40fdf90662900f7a56dc0d39eae372014c20186f:refs/heads/istanbul
```

This bypasses per-PR merge semantics (review, status-check gating, per-PR audit). It is
acceptable only as a deliberate, one-time, operator-approved mechanism. Prefer Method 1.

## After merging

```bash
cd backend
export DATABASE_URL=postgresql://localhost:5432/wheellsverse_test
export TEST_DATABASE_URL=postgresql://localhost:5432/wheellsverse_test   # separate lines
export ADMIN_TOKEN=<any non-empty >=32-char test token>
python ../scripts/verify_post_merge.py --ref origin/istanbul --suite
```

Expect `RESULT: PASS`.

## Tag the verified foundation (immediately after PASS, before deploy)

Once the verifier passes on `origin/istanbul`, cut an immutable recovery point — a
known-good baseline for regression, benchmarking, and rollback before Dark KAI expands:

```bash
git tag -a v1.0.0-foundation <merged istanbul commit> \
  -m "Verified KAI foundation: 10 PRs, 1020 tests, migration head 0008"
git push origin v1.0.0-foundation
```

Use the exact merged `istanbul` commit (not a moving branch name). This tag is the
rollback target referenced in [`ROLLBACK_RUNBOOK.md`](./ROLLBACK_RUNBOOK.md).

## Then: deployment gate

Proceed to [`DEPLOYMENT_GATE.md`](./DEPLOYMENT_GATE.md) — **do not deploy** until every
`UNVERIFIED` prerequisite (Railway/Cloudflare/backup/rollback/money-mode) is resolved.
