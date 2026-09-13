# KAI Governed Frontend Capability — Angular (spec)

**Status:** design spec only. No code, no framework built, no dependency added, nothing deployed.
Flag-gated + dark when implemented. This does **not** disturb the running browser-ops soak.

## Decision & non-goals

- **Do NOT build a new framework.** Angular already is one; a bespoke KAI framework is pure YAGNI
  and violates the blueprint's "no second authority / don't build a second source of truth."
- **KAI is not "trained" to do this.** KAI is a governed orchestration layer; this adds a
  **capability** (a governed mission type), not a model change.
- **Not "adopt all frameworks."** A framework is admitted **per proven need**, pinned and reviewed
  — never auto-adopted wholesale. Angular is a deliberate, scoped pilot (one new app/panel), not a
  rewrite of the existing static-HTML admin + React presence surfaces.

## What it is

A governed capability family that lets KAI scaffold, build, test, and preview a frontend app
(Angular first) as a **mission**, reusing existing machinery: Capability Fabric registration,
ModelRouter (for any LLM code assist), the **governed browser runtime** (`ops/browser-ops`, now
`REVIEWED_AND_PASSING_LOCALLY`) for preview/e2e, the sandbox + egress controls, the evidence
system, approvals, and the Holding dashboard.

## Capability contract (Feature Registry entries)

```json
{ "capability_id": "kai.frontend.scaffold.v1", "risk_class": "CREATE", "execution_mode": "draft",
  "provider": "angular-cli@<pinned>", "input_schema": "{app_name, style, routing, ssr:bool}",
  "output_schema": "{workspace_path, files[], lockfile_digest}", "isolation": "sandbox",
  "network_domains": ["registry.npmjs.org"], "approval_policy": "none (draft)", "evidence_types": ["lockfile_digest","tree"] }
{ "capability_id": "kai.frontend.build.v1",   "risk_class": "ANALYZE", "execution_mode": "draft",
  "evidence_types": ["build_hash","bundle_budget","warnings"] }
{ "capability_id": "kai.frontend.test.v1",    "risk_class": "ANALYZE", "execution_mode": "draft",
  "evidence_types": ["unit_results","e2e_results","a11y","lighthouse"] }
{ "capability_id": "kai.frontend.preview.v1", "risk_class": "READ",    "execution_mode": "observe",
  "provider": "governed-browser-runtime", "evidence_types": ["screenshot","console","routes"] }
{ "capability_id": "kai.frontend.publish.v1", "risk_class": "CONSEQUENTIAL", "execution_mode": "approve/execute",
  "approval_policy": "named approval + fresh bound single-use approval + evidence", "rollback_target": "prev build" }
```

## Governed flow

```
intent -> scaffold (ng new, PINNED CLI) -> install (locked, allowlisted registry, SBOM+scan)
       -> build -> unit + e2e (e2e driven by the governed browser runtime) -> a11y/Lighthouse/bundle budget
       -> preview (browser runtime screenshot + route map) -> evidence envelope
       -> [publish/deploy ONLY with named approval + fresh bound approval]  (dark until then)
```

- **Sandbox + egress:** the Angular CLI + `npm ci` run inside the sandbox with **deny-by-default
  egress**, allowlisting only the package registry; the pinned CLI version and a committed lockfile
  are the supply-chain identity (SBOM + secret/malware/license scan on the dep tree). No ambient
  credentials in the workspace.
- **Preview/e2e reuse the browser runtime:** the built app is served locally and driven by
  `PlaywrightAdapter` under the same host-pin + route/WS/SW/WebRTC egress guards — so a scaffolded
  app's own network behavior is itself governed, and preview produces evidence (screenshot, console,
  route inventory).
- **Evidence envelope:** app name, pinned CLI/dep digests, build hash, bundle-size budget check,
  unit/e2e/a11y/Lighthouse results, preview screenshot, and (on publish) the destination + approval
  + rollback ref. Worker prose is never the evidence.
- **Approval classes:** scaffold/build/test/preview are **draft/observe** (produce artifacts, never
  ship). publish/deploy is **approve/execute** — named human approval + a fresh bound single-use
  approval (the same `PgApprovalStore` pattern from browser-ops) + evidence + rollback.

## Risks / caveats (why it's a scoped pilot)

- Introduces a **second frontend framework** beside static-HTML admin + the React presence layer —
  bundle, build pipeline, and design-system ownership must not fragment. Pilot **one** app/panel.
- SSR/hydration, routing, and auth integration with the existing App A/App B surfaces are real
  decisions to make explicitly, not by default.
- Angular CLI + npm pull a large dep tree — pin, lock, SBOM, and scan; treat every install as an
  admission event, re-certified on upgrade (never auto-update).

## Rollout (when authorized — a NEW mission, not now)

Stage-2 Engineering-Bench pilot: register the capabilities dark (flag off) → scaffold one pilot app
in the sandbox → build/test/preview with evidence → surface in Holding dashboard → publish/deploy
only behind named approval. Nothing here runs during the browser-ops soak; it's local dev-only.

**Bottom line:** yes, KAI can be given a governed capability to scaffold/build/adapt Angular (and,
by the same pattern, other frameworks on demand) — as a pinned, sandboxed, evidence-and-approval
mission. It should not be a bespoke framework, and it should be admitted one framework / one pilot
at a time.
