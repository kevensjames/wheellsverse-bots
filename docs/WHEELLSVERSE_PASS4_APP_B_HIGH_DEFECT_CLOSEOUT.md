# WHEELLSVERSE — Functional Certification Pass 4
## Close App B HIGH defects before any deployment

**Scope:** App B (`backend/app/main.py`, the governed KAI brain runtime) only.
**Branch:** `feat/kai-capability-fabric` · **head** `9f0b118`
**Production:** App A (`core/api.py`, app.wheellsverse.com) **UNCHANGED — NOT deployed this pass.**
**Constraints honored:** no cloud LLM key used or faked; no production deploy; no governance/RBAC/approval gate weakened; no destructive/money action.

---

## 1. Defects addressed

Pass 3 left App B **RUNTIME-RECOVERED** but flagged **two HIGH defects** blocking full certification. Both are now fixed in-repo.

### HIGH-1 — Alembic chain could not build a standalone database
**Symptom:** `alembic upgrade head` failed on a fresh isolated DB — `relation "profiles"/"conversations" does not exist` (0003 FKs to `profiles`, 0005 ALTERs `conversations`/`messages`). Those base tables are **Supabase-owned in prod** ("Path X") and were assumed pre-existing, so local/staging could only be stood up with a `create_all` + `stamp head` workaround — an un-migrated, drift-prone schema.

**Fix (`c78c3de`):** new base migration `0000_base_compat_supabase_tables.py` (`down_revision=None`) creates `profiles`/`conversations`/`messages` **idempotently** (`CREATE TABLE IF NOT EXISTS`, `CREATE EXTENSION IF NOT EXISTS pgcrypto`); `0001_initial` re-parented `None → 0000_base_compat`. Columns mirror `app/models/{profile,conversation}.py` incl. the 0005 additions (whose `ADD COLUMN IF NOT EXISTS` then no-op).

**Prod safety:** production DBs are already stamped past this revision so it never re-runs; even if it did, `IF NOT EXISTS` makes it a no-op against the real Supabase tables — it never drops, alters, or conflicts with real identity/chat data. `downgrade()` is an intentional non-destructive no-op (documented irreversible per migration-safety policy).

**Evidence:** on an empty database, `alembic upgrade head` now runs the full chain clean; App B boots and serves governed routes without the create_all/stamp workaround.

### HIGH-2 — Governed-call audit/usage drift
**Symptom:** governed LLM calls did not reliably persist their `llm_call_log` usage rows on the standalone runtime.

**Fix (`c78c3de`):** the usage/call-log path now writes and persists against the migrated schema; a **successful** governed `kai-chat` call produces its `llm_call_log` row (verified live via local ollama).

---

## 2. Adversarial review — 0 CRITICAL / 0 HIGH

A multi-lens, refute-biased review was run against the two fixes. **One confirmed finding, MEDIUM — now fixed.**

### MEDIUM (confirmed, FIXED `9f0b118`) — failed governed calls lost their `llm_call_log` evidence
**Root cause:** failure telemetry was written on the **shared request Session** (`autocommit=False`), committed only by `Brain.chat` on **success**. On a terminal failure with no fallback (e.g. ollama-only, no cloud brain), the exception propagates → `get_db()` closes without commit → **rollback erases the failure row**. The row proving "execution was attempted and failed" disappeared. (My Pass-3 "failed calls retain evidence" claim was a false positive — the unit tests commit manually, masking it.)

**Not affected:** governance `audit_log` (JSONL, `record_action`) — intact throughout. Only the usage-table *failure* telemetry was at risk.

**Fix:** `Router._log_failure_safe` now writes on an **isolated short-lived `SessionLocal()` that commits immediately**, independent of the request transaction. All five raise-sites already routed through this one helper; the streaming `except` branch (still calling `self.spend.log_call` inline) is now routed through it too. Best-effort `try/except` preserved — a logging hiccup must never defeat the runtime fallback or mask the original adapter error. Success paths (`log_result` / `log_call(success=True)`) unchanged.

**Verified live:** forced a terminal failure (`OLLAMA_MODEL=bogus-model-does-not-exist` → 404), sent a governed `kai-chat` request with the owner cookie:
```
failure rows: before=0 after=1  PASS — failure evidence RETAINED
persisted row: ollama | success=f | "Client error '404 Not Found' for url 'http://127.0.0.1:11434/api/chat'"
```
**Regression guard:** `backend/app/services/router/test_failure_log_durable.py` — asserts the failure write opens a fresh session, `execute`s the insert, `commit`s, `close`s, and never touches the shared request session. `1/1 passed`.

### LOW (ollama tool path) — already closed
`OllamaAdapter.complete()` accepts `tools=None` and raises a **clean `ValueError`** on a real tool schema (ollama is tool-incapable) instead of a raw `TypeError`/500. The `chat()` orchestrator swaps SIMPLE-intent/tool-incapable adapters to a tool-capable brain when tools are requested. No governance weakening.

---

## 3. Governance / security invariants — held

- **RBAC/auth unchanged.** `require_kai_ultra` (App B) and the unified `wv_session` owner gate remain enforced; the fix touched only *where a failure row is written*, never *who may call*.
- **No cloud key used or faked.** All live verification used the local ollama brain. Tool-using KAI queries that need a cloud tool-capable brain remain the one **external** blocker (credential), not a code defect.
- **Data honesty preserved.** App A registry snapshot unchanged: **39 systems** (HEALTHY 12 · DEGRADED 5 · DORMANT 18 · LOCAL 2 · PRE_DEPLOY 1 · HISTORICAL 1 — no UNKNOWN→HEALTHY), registry guard suite **11/11**.
- **No production deploy.** App A (app.wheellsverse.com) untouched this pass.

---

## 4. Gate

**APP B INTERNALLY CERTIFIED — READY FOR FULL STAGING CERTIFICATION.**

- Both HIGH defects fixed in-repo and verified (`c78c3de`).
- Adversarial review: **0 CRITICAL / 0 HIGH**; the one MEDIUM found is fixed, verified live, and guarded by a regression test (`9f0b118`).
- Governed success **and** failure paths both persist their `llm_call_log` evidence.
- Alembic builds a standalone DB from empty to head.

**Remaining before production (operator / external, not code):**
1. Cloud tool-capable LLM credential (openai/anthropic) — needed **only** for tool-using KAI queries; local chat is fully governed and working.
2. Isolated Railway staging environment for App B + full hosted-edge streaming certification (`HOSTED_EDGE_CERTIFICATION`).
3. Operator go/no-go for any production deploy — **not** performed in this pass.
