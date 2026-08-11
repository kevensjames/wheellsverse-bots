# KAI Code Intelligence (semantic code search)

Native semantic code search on KAI's existing Postgres + pgvector — **no Milvus,
no MCP daemon, no external vector DB**. Built as integration #2 of the audit
program ([../../plans/PLAN-kai-code-intelligence.md] on the audit branch), using
`zilliztech/claude-context` (MIT) only as the design reference for the tree-sitter
AST chunker.

## Architecture
`CodeSearchProvider` (`app/services/code_intel/provider.py`) is the KAI-owned seam;
the concrete `PgVectorCodeSearchProvider` runs on pgvector. Pipeline:

```
walker (allowlist + realpath symlink jail + excludes)
  → chunking (tree-sitter AST for 9 langs; sliding-window fallback)
  → secrets (regex + entropy redaction BEFORE embedding)
  → embeddings (OpenAI, or local Ollama for zero egress)
  → kai_code_chunks (idempotent on (user_id, repo_id, path, content_sha))

search: embed query → cosine <=> ... WHERE user_id = ctx.user_id → cited hits
```

## Security model
- **Tenant isolation** is enforced in SQL: every read/write is scoped to
  `ctx.user_id`, set inside the provider and **never** an agent-supplied argument;
  `repo_id`/`lang` only narrow within the user's rows. Migration 0007 adds a
  Postgres RLS policy as defense-in-depth (activates under a least-privilege role
  + a per-request `SET app.user_id` — a follow-up wiring step).
- **Secret redaction** runs before any embedding/DB write: private keys drop the
  whole chunk; cloud keys / tokens / db-creds / inline `secret = "..."` are
  redacted; a conservative high-entropy sweep backstops unlabeled secrets.
- **Deny-by-default indexing**: `KAI_CODE_INTEL_ROOTS` allowlist + a realpath
  symlink jail + dir/file exclusions (`.git`, `node_modules`, `.env`, `*.pem`, …).
  Read-only — never runs build/hook/test scripts.
- **Governance**: `/admin/code-intel/{index,delete}` are `@audited(destructive=True)`
  + gated by `KAI_SCOPE_CODE_INTEL_*`; the `code_search` tool is read-only and
  returns retrieved code as reference **data**, never as instructions.
- **Local-embedding profile**: `KAI_CODE_INTEL_EGRESS=0` forces Ollama so code
  never leaves the host for residency-restricted tenants.

## Surfaces
- Tool `code_search(query, k, repo_id?, lang?)` — read-only, in the chat loop.
- Admin `POST /admin/code-intel/index|delete|search` — operator-triggered,
  token-gated; index/delete require scope + `approved=true`.

## Config
See `.env.example` (`KAI_CODE_INTEL_*`). Requires the `kai_code_chunks` table
(alembic migration `0007_add_kai_code_chunks`) and the pgvector extension.

## Tests
`tests/services/code_intel/` — walker jail, secret redaction, AST chunking,
**real-pgvector tenant isolation**, and the code_search tool (incl. a
prompt-injection-in-code case).
