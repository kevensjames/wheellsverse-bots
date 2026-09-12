# Framework & Capability Matrix

Durable capability matrix. Referenced by `KAI_GOVERNED_WORKFORCE_MASTER_PLAN.md`.

**Principle:** framework expertise is a **catalog capability a character may
declare** — it does NOT authorize installing that framework into KAI. Use the
repository's existing stack wherever it already solves the problem; never add a
dependency merely because an agent knows it. Every install is a governed
supply-chain admission event (separate decision).

## Declarable expertise

- **Frontend:** Angular 22 standalone architecture · TypeScript 6 · React · Next.js
  · Vue/Nuxt · Svelte/SvelteKit · Solid · Astro · Web Components · Tailwind ·
  Material UI · Ant Design · Chakra UI · shadcn/ui · React Aria · accessibility/WCAG.
- **Mobile/Desktop:** Flutter · React Native · Swift/SwiftUI · Kotlin/Compose ·
  Electron · Tauri.
- **Backend:** FastAPI · Python · Pydantic · SQLAlchemy · Alembic · Django · Flask
  · Node.js · NestJS · Express · Go · Rust · Java/Spring · .NET.
- **Data/AI:** PostgreSQL · pgvector · Redis · SQL · object storage · event/outbox
  patterns · RAG · embeddings · knowledge graphs · evaluation harnesses · model
  routing · local models/Ollama (where separately admitted).
- **Infrastructure:** Docker · Kubernetes · CI/CD · OpenTelemetry · Prometheus/
  Grafana · Sentry · cloud platforms · MCP servers.
- **Testing:** pytest · Playwright · Angular testing · Vitest/Jest · contract
  testing · property testing · security testing · mutation testing · accessibility
  testing.

## Pinned constraints for the existing dark Angular pilot (`frontend-pilots/kai-angular`)

- **Angular 22.1.x** and **TypeScript 6.0.3** (repository-pinned; matches the
  Stage-0 repin). rxjs 7.8.x, zone.js 0.16.x, node `^22.22.3 || ^24.15 || >=26`.
- **Do NOT install dependencies on the host.** Dependency installation remains a
  governed supply-chain admission event (sandbox + SBOM + scan).
- During the workforce **catalog phase**, the Angular console renders only static
  catalog data + inert status; **no execution controls function**.

## Repository-stack-first rule

Prefer what already exists: FastAPI + Pydantic + SQLAlchemy + Alembic + PostgreSQL
(+ pgvector) + governance (policy/approval/audit) + supabase_auth (identity) +
`tenancy` (workspace membership) + `capability_exchange` (registry, catalog-only
after the approved split). Do not introduce a second backend framework, a second
operator-UI framework beside Angular, Kubernetes before scale requires it, a second
queue/workflow engine, or a separate vector DB before pgvector is measured
insufficient. No autonomous-agent framework that bypasses KAI missions/policy.
