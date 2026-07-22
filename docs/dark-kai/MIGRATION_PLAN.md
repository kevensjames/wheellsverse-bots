# Dark KAI — Migration Plan

**Repo:** `/Users/jhonwheeler/wheellsverse-kai-audit`
**Written from:** branch `feat/kai-swe-agent`, HEAD `4850b0d`
**Baseline:** `origin/istanbul` = `2fe6e46` ("Fix/kai critical reliability (#33)")

**Scope caveat, stated up front:** there is no "Dark KAI" spec, module, or
migration anywhere in this repo. `grep -rin "dark kai\|dark_kai"` over the tree
returns nothing, and `docs/dark-kai/` was an empty directory before this file.
**UNVERIFIED: the Dark KAI product definition.** Everything in §4 below is
therefore written as *proposed* schema derived from gaps that ARE verified in
the existing code (untenanted tables, no retention path, an unaudited tool
loop). Nothing in §4 describes code that exists. §1–§3 and §5–§6 describe real
files and are cited.

---

## 1. The alembic chain as it actually stands

Linear, one file per revision, `backend/alembic/versions/`:

```
0001_initial_schema
  → 0002_stripe_customer_id
  → 0003_add_memories_table
  → 0004_add_llm_call_log_table
  → 0005_stage4_enhance_conv_msg
  → 0006_add_kai_api_keys
```

- **Head on merged `istanbul` is `0006_add_kai_api_keys`.** Verified:
  `backend/alembic/versions/0006_add_kai_api_keys.py:19-20` sets
  `revision = "0006_add_kai_api_keys"`, `down_revision = "0005_stage4_enhance_conv_msg"`,
  and `git diff --name-only origin/istanbul...HEAD` lists
  `backend/alembic/versions/0007_add_kai_swe_tasks.py` as **added by this
  branch** — so istanbul carries 0001–0006 only.
- `0001_initial_schema.py:22` creates the `pgcrypto` extension;
  `0003_add_memories_table.py:23` creates `vector`. Both are prerequisites for
  anything below (`gen_random_uuid()`, `Vector(1536)`).
- Runner config: `backend/alembic.ini` + `backend/alembic/env.py`. `env.py:19`
  pulls the URL from `settings.DATABASE_URL` (no separate alembic URL), and
  `env.py:14` imports `app.models` so `Base.metadata` is populated.
- **Tests do not use alembic.** `backend/tests/conftest.py:141` builds the schema
  with `Base.metadata.create_all(eng)`. Consequence: *a migration can be wrong
  and the whole 966-test suite still passes.* Every step below needs a real
  `alembic upgrade head` against a scratch database as its check — the test
  suite is not that check.

## 2. THE KNOWN COLLISION — two competing `0007`s

Both open PRs add a migration file numbered 0007 chained off the same parent:

| PR | Branch | File | `revision` | `down_revision` |
|---|---|---|---|---|
| **#40** code intelligence | `fix/kai-code-intelligence` | `backend/alembic/versions/0007_add_kai_code_chunks.py` | `0007_add_kai_code_chunks` (`:19`) | `0006_add_kai_api_keys` (`:20`) |
| **#42** swe agent | `feat/kai-swe-agent` | `backend/alembic/versions/0007_add_kai_swe_tasks.py` | `0007_add_kai_swe_tasks` (`:25`) | `0006_add_kai_api_keys` (`:26`) |

**PR #39 (`fix/kai-governed-tool-loop`) and PR #41 (`fix/kai-swe-sandbox`) add no
migrations** — verified with `git diff --name-only origin/istanbul...<branch>`;
neither diff contains a path under `alembic/versions/`.

### What actually breaks

The `revision` *ids* differ, so alembic will not error on a duplicate id. The
failure is subtler and worse: after the second merge the versions directory
contains two revisions whose `down_revision` is `0006_add_kai_api_keys`, which
alembic reads as a **branch**. `alembic upgrade head` then fails with
`Multiple head revisions are present ... please specify a specific target
revision`. Deploy stops. Neither table gets created. The app boots against a
schema missing whichever table merged second, and the first symptom is a
runtime `relation "kai_code_chunks" does not exist` (or `kai_swe_tasks`) rather
than a migration error, because nothing at boot asserts the head matches.

The #42 author already knew — `0007_add_kai_swe_tasks.py:15-18` carries the
warning verbatim:

> NOTE: if the sibling fix/kai-code-intelligence branch (which also introduces a
> 0007) merges first, renumber this to 0008 and rechain down_revision AT MERGE
> TIME — do not guess now.

### A third 0007 exists but is out of scope

`origin/feat/sol-v1` carries `0007_sol_v1_data_model` (also off
`0006_add_kai_api_keys`) and continues `0008_sol_payment_method_nullable`
through `0020_sol_late_policy` — 14 more files. Verified with
`git show origin/feat/sol-v1:backend/alembic/versions/`. **This branch must not
be merged in the same window as #40/#42.** It does not just collide at 0007; it
claims the entire 0008–0020 range, so renumbering #40/#42 into 0008/0009 and
*then* merging sol-v1 produces a second, much larger collision. Sequence
sol-v1 separately and renumber its whole tail at that time.

## 3. Merge order and the exact renumber procedure

### 3.1 Order

```
1. #39  fix/kai-governed-tool-loop     (no migration)
2. #41  fix/kai-swe-sandbox            (no migration)
3. #40  fix/kai-code-intelligence      (keeps 0007_add_kai_code_chunks)
4. #42  feat/kai-swe-agent             (RENUMBER to 0008)
```

Rationale, each point cited:

- **#39 first.** It is the only change that closes the ungoverned tool loop.
  `grep -rn "@audited" backend/app/services/tools/` returns 0 matches on
  istanbul; the single model-driven execution point is
  `backend/app/services/router/router.py:374`
  (`tool_result = tool_registry.execute(tc.name, tc.arguments, tool_context)`)
  reaching `backend/app/services/tools/registry.py:58-83`, which does a dict
  lookup and calls `tool.execute(ctx, **arguments)` with no scope check, no
  approval check and no audit record. #39's diff touches exactly
  `registry.py`, `base.py`, `brain.py`, `admin_chat.py`, `mcp_tools.py`,
  `composio_generic.py`, `composio_notion.py`, `twenty_crm.py`, `video_gen.py`
  and adds `tests/test_tool_governance.py`. Zero overlap with #40/#41/#42 except
  `mcp_tools.py`/`tools/__init__.py`, and it is the prerequisite for any claim
  that new Dark KAI tables are audited.
- **#41 before #42.** #42 is stacked on #41 — `feat/kai-swe-agent` contains
  #41's whole file set (`swe_runtime/config.py`, `policy.py`, `runtime.py`,
  `sandbox.py`, `admin_swe.py`) plus its own. Merging #42 first makes #41 empty
  and loses the review record.
- **#40 before #42, and #40 keeps 0007.** Arbitrary but must be *decided*, and
  #40 is the cheaper one to leave untouched: its migration is declarative
  (`op.create_table`/`op.create_index`) and its downgrade at
  `0007_add_kai_code_chunks.py:61-66` drops policy, RLS, both indexes and the
  table. #42's is raw `op.execute` DDL with a two-line downgrade
  (`0007_add_kai_swe_tasks.py:73-74`, `DROP TABLE IF EXISTS kai_swe_tasks`).
  Renumbering #42 is a two-line edit plus a rename.

### 3.2 The renumber procedure — run this on #42 before merging it

Precondition: #40 is merged to `istanbul`, so
`backend/alembic/versions/0007_add_kai_code_chunks.py` is on the base branch.

```bash
cd /Users/jhonwheeler/wheellsverse-kai-audit
git checkout feat/kai-swe-agent
git fetch origin && git merge origin/istanbul     # brings in 0007_add_kai_code_chunks

# 1. rename the file (git mv, so history follows)
git mv backend/alembic/versions/0007_add_kai_swe_tasks.py \
       backend/alembic/versions/0008_add_kai_swe_tasks.py
```

2. Edit `backend/alembic/versions/0008_add_kai_swe_tasks.py`, three lines:

```python
# was (0007_add_kai_swe_tasks.py:3)
Revision ID: 0007_add_kai_swe_tasks
# now
Revision ID: 0008_add_kai_swe_tasks

# was (:4)
Revises: 0006_add_kai_api_keys
# now
Revises: 0007_add_kai_code_chunks

# was (:25-26)
revision: str = "0007_add_kai_swe_tasks"
down_revision: Union[str, None] = "0006_add_kai_api_keys"
# now
revision: str = "0008_add_kai_swe_tasks"
down_revision: Union[str, None] = "0007_add_kai_code_chunks"
```

3. Delete the now-stale merge-time warning at
   `0007_add_kai_swe_tasks.py:15-18` ("if the sibling fix/kai-code-intelligence
   branch ... renumber this to 0008") — it has been acted on; leaving it makes
   the next reader think the work is still pending.

4. Verify — **this is the step that catches the collision, not pytest**:

```bash
cd backend
alembic heads          # MUST print exactly one line: 0008_add_kai_swe_tasks (head)
alembic history        # MUST show 0001..0008 as a single unbranched chain
alembic upgrade head   # against a SCRATCH database, never prod
alembic downgrade -1   # proves 0008's downgrade works
alembic upgrade head
```

`alembic heads` printing two lines means the rechain did not take. Do not merge.

5. Sanity-check the ORM/migration pairing that alembic cannot check for you.
   `backend/app/models/swe_task.py:1-9` states the ORM is the source of truth for
   the *test* schema while the migration is the prod path, and `:26-30` lists the
   9 states mirrored in three places (`SWE_TASK_STATES`, the model's
   `CheckConstraint`, and the migration's `VARCHAR(24)` + CHECK). Renumbering
   does not touch these, but confirm the CHECK survived the file move.

**If #40 ends up merging second instead**, the identical procedure applies with
the names swapped: `0007_add_kai_code_chunks.py` → `0008_add_kai_code_chunks.py`,
`revision = "0008_add_kai_code_chunks"`,
`down_revision = "0007_add_kai_swe_tasks"`. Pick one owner for the decision and
write it in the PR description; the failure mode here is two people each
assuming the other renumbered.

### 3.3 What NOT to do

Do **not** resolve this with `alembic merge` (a merge revision with two
`down_revision`s). It works, but it permanently bakes a branch point into a
chain that has been linear for six revisions and makes every future
`downgrade -1` ambiguous. Two edited lines beat a permanent fork.

## 4. Proposed Dark KAI tables and their tenant keys

**Everything in this section is proposed, not existing.** Each entry names the
verified gap it closes.

### 4.1 The tenant-key problem it has to solve

Verified untenanted state today:

- `kai_swe_tasks` has **no `user_id`** — deliberate, documented at
  `backend/app/models/swe_task.py:9` ("Single-operator model — no user_id / RLS")
  and in `0007_add_kai_swe_tasks.py:9-13`. Anyone past the single shared
  `X-Admin-Token` (`backend/app/dependencies/admin.py:99`) sees every task.
- `predictions` is global (`backend/app/models/prediction.py:13`).
- `audit_log` has only a nullable `actor_id` (`backend/app/models/admin.py:31`),
  and the actor written by the governance decorator defaults to the literal
  string `"operator"` (`backend/app/services/governance/actions.py:75`).
- Ten SQLite sidecars under `data/` carry **zero `user_id` columns** — including
  real PII: `sol.db members.email` / `dwolla_customer_id` /
  `funding_source_href` (`backend/app/services/sol/storage.py:150-161`).
- `memories` has no ORM-level FK to `profiles` — deliberately omitted at
  `backend/app/models/memory.py:26-28`, declared only in the migration.

The one table that gets tenancy right is #40's `kai_code_chunks`:
`user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE`
(`0007_add_kai_code_chunks.py:32-33`), a `UNIQUE (user_id, repo_id, path,
content_sha)` (`:45-46`), an index leading with `user_id` (`:47-48`), and RLS
(`:53-58`). Its own docstring is honest that the RLS policy is inert until a
per-request `SET app.user_id` is wired (`:7-10`). **Copy this shape.** Do not
copy `kai_swe_tasks`.

### 4.2 Proposed tables

All four take `user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE`.
`profiles` is the tenant root — `backend/app/models/profile.py:31`, and every
tenanted table already cascades from it (`subscription.py`, `conversation.py`,
`document.py`, `api_key.py`, `usage.py`, `alert.py`).

| Proposed table | Purpose | Tenant key | Replaces / closes |
|---|---|---|---|
| `kai_tool_invocations` | one row per model-chosen tool call: tool name, redacted args, scope, `allowed`/`denied`/`error`, latency, actor | `user_id` NOT NULL FK CASCADE, plus `conversation_id` FK | The `@audited` gap at `registry.py:58-83`. Gives the tool loop a **relational, per-tenant** audit trail instead of the single global JSONL at `KAI_AUDIT_LOG_PATH` (`backend/app/services/governance/audit_log.py:36`), which has no tenant field and is fail-soft (`:82-83`) so a write failure silently drops the record |
| `kai_swe_tasks.user_id` (ALTER, not a new table) | give SWE tasks an owner | add `user_id UUID NULL` first, backfill to the operator, then `SET NOT NULL` | `swe_task.py:9`'s single-operator assumption, which does not survive a multi-tenant Dark KAI |
| `kai_sol_members` (+ circles/cycles/contributions/payouts) | move the Sol ledger out of SQLite into Postgres | `user_id` NOT NULL FK CASCADE on every table | `data/sol/sol.db` — bank PII with no tenant key and no cascade-delete story (`sol/storage.py:138-196`) |
| `kai_retention_policy` | per-tenant TTL in days per data class (messages, memories, documents, tool invocations) | `user_id` PK/FK CASCADE | §5 — there is no retention machinery at all today |

Tenant-key rules for every one of them:

1. `user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE` — never a
   bare UUID column. `memories` (`memory.py:26-28`) is the counter-example: its
   tenant integrity depends entirely on the migration having created the FK in
   prod. **UNVERIFIED against the live database** — confirm with `\d memories`
   on prod before trusting it.
2. Every index leads with `user_id`, matching
   `ix_kai_code_chunks_user_repo` (`0007_add_kai_code_chunks.py:47-48`).
3. Every uniqueness constraint is scoped by `user_id`
   (`uq_kai_code_chunks_ident`, `:45-46`) — a global unique key is a
   cross-tenant collision channel.
4. RLS enabled in the same migration that creates the table
   (`0007_add_kai_code_chunks.py:53-58`), with the honest caveat that it is
   inert until `SET app.user_id` is wired per request. Ship it anyway; adding
   RLS later means an outage window or a table rewrite.

### 4.3 Sequencing

Numbers assume the §3.1 order landed, so the chain head is
`0008_add_kai_swe_tasks`:

```
0009_add_kai_tool_invocations     (depends on #39 being merged — pointless before)
0010_kai_swe_tasks_user_id        (3 sub-steps, see §6.4)
0011_add_kai_retention_policy
0012_add_kai_sol_tables           (schema only; data move is a separate script, §6.5)
```

Rule going forward, since it just cost a collision: **one migration per PR, and
the number is assigned at merge time, not authoring time.** Any PR adding an
`alembic/versions/` file must have `alembic heads` output (exactly one line)
pasted in its description.

## 5. Data retention and deletion

### 5.1 What exists

Almost nothing, and this is verified rather than assumed:
`grep -rn "retention|prune|VACUUM|DELETE FROM" backend/app` returns only a
comment in `backend/app/routers/billing.py:203`, the
`backend/app/models/cancellation_reason.py` docstring, and a step delete at
`backend/app/services/planning/storage.py:406`. The only other deletion surface
is `delete_memory(memory_id)` at `backend/app/services/memory/store.py:75`.

Meanwhile chat content (`messages.content`,
`backend/app/models/conversation.py:93`), uploads stored whole
(`kai_documents.full_text`, `backend/app/models/document.py:22`), and memories
plus their embeddings (`backend/app/models/memory.py:18`) are retained
indefinitely. The four JSONL sinks — governance audit
(`governance/audit_log.py:36`), `data/failures.jsonl`
(`failure_memory/storage.py:41`), `data/research/digests.jsonl`
(`research/digest.py:47`), `data/digest/digests.jsonl` (`digest/digest.py:25`) —
grow unbounded with no rotation.

### 5.2 What deletion actually does today

Deleting a `profiles` row cascades to `subscriptions`, `conversations`,
`messages`, `kai_documents`, `kai_doc_chunks`, `kai_api_keys`,
`cancellation_reasons`, `usage_log`, `watchlists`, `alerts`, `llm_call_log`
(`0004_add_llm_call_log_table.py:22-64`) and — if the FK exists in prod —
`memories`. It does **not** touch: the ten SQLite sidecars, any of the four
JSONL files, `kai_swe_tasks` (no tenant key), or `predictions`. A "delete my
account" today leaves the user's journal entries, mood samples, KG nodes,
persona/twin entries, check-ins, planning history, and — if they were a Sol
member — their email, Dwolla customer id and funding-source href on disk.

### 5.3 Plan

1. **Cascade is the mechanism.** Every new table cascades from `profiles`, so
   deletion needs no new code for anything in Postgres. This is the whole reason
   §4.2 insists on the FK.
2. **Migrate the SQLite sidecars into Postgres with `user_id`** rather than
   writing a bespoke deleter for each of ten files. Sol first (it holds bank
   PII), the rest by PII weight: journal, EQ, relationship, checkin, twin,
   persona, KG, learning, planning.
3. **`kai_tool_invocations` needs an explicit TTL**, because unlike chat it is
   pure operational exhaust. Default 90 days. It is also the one table where
   deletion fights auditability — resolve it by writing *retention* into
   `kai_retention_policy` per tenant and treating the shorter of (tenant policy,
   90 days) as authoritative, with a documented floor for anything that recorded
   a `destructive=True` action.
4. **Redaction before storage, not after.** `governance/audit_log.py:86-133`
   already redacts by key-name pattern and (PR-only, `tests/services/
   test_audit_value_redaction.py`) by value regex. `kai_tool_invocations` must
   reuse that exact function, not reimplement it — the key list there
   (`password|secret|token|api_key|apikey|auth|x-admin-token|cookie|bearer`)
   is the tested one. Note its documented limit: it misses any secret whose key
   is not in the list and whose value does not match the regex.
5. **Do not add a deletion endpoint before #39.** A deletion path is a
   side-effecting operation; until `registry.py` routes through governance,
   adding one to the tool registry hands every authenticated user an unaudited
   delete.

## 6. Rollback, per step

General rule: **every step here is reversible by a `downgrade` except the two
data moves in 6.4 and 6.5.** Those two need a backup, and the backup is the
rollback plan.

### 6.1 Merging #39 (no migration)
Rollback: `git revert` the merge. No schema change, no data change. The behavior
change is a default-deny (`allow_writes: bool = False` threaded through
`brain.py` into `ToolContext` on that branch), so the failure mode of #39 is
tools being refused, not data being corrupted — safe to leave in place while
diagnosing.

### 6.2 Merging #41 (no migration)
Rollback: `git revert`. The SWE routes are conditionally mounted behind
`swe_admin_enabled()` (`backend/app/main.py:192-200`, `swe_runtime/config.py:31-39`,
which vetoes on `ENV=production`) and `KAI_SWE_RUNTIME_ENABLED` defaults to 0,
so on the production daemon these routes do not exist. Rollback is a code
revert with no runtime surface to drain.

### 6.3 Merging #40, then #42-renumbered-to-0008
Rollback of #42: `alembic downgrade 0007_add_kai_code_chunks`, which runs
`DROP TABLE IF EXISTS kai_swe_tasks` (`0007_add_kai_swe_tasks.py:73-74`), then
revert the merge. **Destructive** — it drops every task row including approval
history. Take a `pg_dump -t kai_swe_tasks` first.
Rollback of #40: `alembic downgrade 0006_add_kai_api_keys`, which drops the RLS
policy, disables RLS, drops both indexes and the table
(`0007_add_kai_code_chunks.py:61-66`). Also destructive, but `kai_code_chunks`
is a derived cache — it can be re-embedded from source. Cheaper to lose.
**If both need rolling back, downgrade in reverse order (0008 then 0007).**
Rolling back #40 while #42's revision is still present orphans the chain.

### 6.4 `kai_swe_tasks.user_id` — the one that needs three migrations
Never add a `NOT NULL` column to a populated table in one step. Split it:

```
0010a  ADD COLUMN user_id UUID NULL REFERENCES profiles(id) ON DELETE CASCADE
       → rollback: DROP COLUMN. Zero data loss; no code reads it yet.
0010b  backfill:  UPDATE kai_swe_tasks SET user_id = :operator_id WHERE user_id IS NULL
       → the operator id comes from KAI_OPERATOR_USER_ID (already an existing
         env var). Rollback: UPDATE ... SET user_id = NULL. Reversible.
0010c  ALTER COLUMN user_id SET NOT NULL
       → rollback: DROP NOT NULL. Reversible.
```

Deploy 0010a and let the writer code populate it for a full cycle before
0010b/0010c. The state machine's conditional transitions
(`swe_runtime/task_store.py`, race-safe by design per
`admin_swe_tasks.py`'s approve paths) are unaffected by an added nullable column.

### 6.5 SQLite → Postgres data moves
Not an alembic step. The migration creates empty tables (reversible: drop them);
a separate one-shot script copies rows. Rollback plan:

1. Copy the SQLite file aside first (`cp data/sol/sol.db data/sol/sol.db.bak`).
2. Run the copier in **dual-write** mode — new writes to both, reads still from
   SQLite — for one cycle.
3. Flip reads to Postgres. Rollback at this point is flipping reads back; the
   SQLite file is still current because dual-write never stopped.
4. Only after a clean cycle, stop writing SQLite and archive the file.

Do not skip step 2 for Sol. `data/sol/sol.db` is the money ledger
(`sol/storage.py:34`, `KAI_SOL_DB_PATH`), and the contribution/payout rows carry
the idempotency identity that keeps a lost Dwolla response from double-debiting
(`backend/app/routers/sol.py:279-291` — retry keys advance `retry_count` only on
a *confirmed* transfer). A migration that renumbers or reissues those ids
converts the existing safe-retry behavior into a double-charge risk.

### 6.6 Rolling back a deploy, generally
The production daemon is launchd-supervised with `KeepAlive true`
(`deploy/launchd/com.wheellsverse.kai.plist`), single-worker uvicorn on
127.0.0.1:8001 (`deploy/start_nai.sh`), fronted by a cloudflared tunnel. There is
no blue/green — a rollback is: stop the daemon, `git checkout` the previous
commit, `alembic downgrade` to the matching revision, restart. Budget for the
downtime; `deploy/health_check.sh` will fire a Telegram alert during it, and its
restart-loop detector (3 restarts/hour) may trip on a bouncy rollback.
Single-worker is a **correctness** dependency, not just capacity — the admin
brute-force throttle (`dependencies/admin.py:34-35`) and the rate limiter
(`core/rate_limit.py`) hold state in process memory. Do not "roll forward" by
adding workers.

---

## Open items I could not verify

- The Dark KAI product definition (no spec in repo).
- Whether the `memories → profiles` FK exists in the production database
  (`backend/app/models/memory.py:26-28` omits it from the ORM). Needs `\d memories`
  on prod.
- Whether celery beat runs in production at all — `backend/app/workers/celery_app.py:27-39`
  defines a `beat_schedule`, but there is no Procfile or Dockerfile under
  `backend/` and no launchd plist for a worker. If it does not run, nothing
  consumes the ingest/predict schedule and any retention job hung off celery
  would silently never fire.
