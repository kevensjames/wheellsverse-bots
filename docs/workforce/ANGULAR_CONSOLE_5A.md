# Workforce Phase 5A — DARK Angular console (source-only)

**Status:** `WORKFORCE_UI_DARK_LOCALLY` — Angular **source only**. No dependency
was installed, no `ng build`/`ng test`/`ng serve` was run. The console is written
to render the inert catalog and **stops before any install/build step**, awaiting
independent review and a separate governed dependency-install authorization.

## What it is

A dark operator console over the 319 INERT workforce characters, under the existing
pinned Angular pilot (`frontend-pilots/kai-angular`, Angular **22.1.x** / TypeScript
**6.0.3**). It renders **static, generated catalog data** and can activate, assign,
execute, deploy, or call a model/tool/network — **none of these**.

Views (lazy routes under a shell with a DARK/INERT banner + nav):

- **Characters** (`/characters`) — all 319, filterable by division / source / risk /
  framework / workplace / flagged + search; inline detail shows identity, provenance,
  risk & workplace policy, quarantine review, frameworks, capabilities.
- **Org & workplaces** (`/org`) — KAI at the top; divisions and workplace
  isolation/policy profiles (deny-by-default shown).
- **Matrices** (`/matrices`) — capability matrix, framework coverage, risk/source tallies.
- **Simulated team** (`/teams`) — pre-computed example proposals from the backend
  catalog; a proposal is a description only.
- **Capabilities** (`/capabilities`) — the Stage-0 frontend-capability view, INERT.

## Why it is inert by construction

- **No backend call.** `app.config.ts` provides the router only — **no
  `HttpClient`**, no network provider. Data is a compile-time import
  (`workforce-data.ts`), not a fetch.
- **No second brain.** The console carries **no planning logic**. Team proposals
  are produced by the authoritative Python `WorkforceCatalog.propose_team`
  (`backend/app/services/workforce/catalog.py`) and exported verbatim by
  `ui_export.py`; the UI re-computes nothing.
- **Every action is the disabled governed control.** The only way an action renders
  is `<app-governed-action>` — a permanently-`disabled` button carrying
  **"NOT AVAILABLE — GOVERNED EXECUTION NOT ADMITTED"**, with no click handler and
  no event output. The inert state is structural: the UI cannot offer a working
  action even by mistake.
- **Honest data.** `workforce-data.ts` declares `actionsAdmitted: false`, all 319
  at `INERT`, provenance honest (KAI_NATIVE carries none; `reviewedBy` null — nothing
  human-approved).

## Data pipeline (read-only)

`catalog.py` (inert) → `ui_export.py` (read-only consumer; `ensure_ascii=False`
UTF-8) → `src/app/workforce/workforce-data.ts` (generated; **do not edit by hand**).
Regenerate with `ui_export.main()`. Deterministic: re-export is byte-identical and a
test asserts the committed module matches a fresh export.

## Verification runnable now (no Angular toolchain)

- `backend/tests/test_workforce_ui_export.py` — the generated data: 319 INERT,
  `actionsAdmitted` false, every example proposal `executesAnything`/`assignsAnyone`
  false, a feasible **and** a gap example, provenance honest, matrices/org present,
  deterministic, committed-TS-matches-fresh-export.
- `backend/tests/test_workforce_console_honesty.py` — static scan of the Angular
  source: no `@angular/common/http`/`HttpClient`/`fetch`/`WebSocket`/`EventSource`/
  `localStorage`/`eval`/… ; no `(click)` handler invokes an action verb; the
  canonical label is present in the action control and the shell; the governed action
  is always disabled with no output; `app.config.ts` provides no HttpClient; routes
  have no IO guards/resolvers.

The governed sandbox's `ng build` / `ng test` (which run the `*.spec.ts` honesty
specs) is the **later, separately-authorized** gate.

## Deferred (needs separate authorization)

- Angular **dependency installation** + offline build/test in the governed sandbox
  (SBOM + scan). Not done here.
- The production build initial-bundle budget was raised (1.5mb warn / 3mb error) to
  accommodate the generated `workforce-data` module (static view-model for 319
  characters; internal governance console, not a perf-sensitive public site).

## Ceiling

No API router, model/tool call, activation, assignment, execution, migration, or
deployment. No dependency installed. Nothing past `INERT`.
`KAI_BROWSER_OPS_ENABLED=false`. Browser soak + Istanbul untouched.
