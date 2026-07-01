# W-MOS — Full Upgrade Plan: All 10 Businesses Run Their Loops Perfectly

**Goal:** Every one of the 10 businesses executes its complete 9-step loop end-to-end,
correctly, in **propose/dry-run mode** — consuming its own GTM kit + niche, producing real
per-business artifacts (leads, drafts, demos) — and the orchestrator can sweep all 10
reliably. Real sends/deploys/spend stay **gated** behind arming + the legal/registration
unlock. "Works perfectly on loops" = the loops execute + verify correctly for all 10, ready
to arm.

---

## Current state (honest)

| Piece | State |
|---|---|
| Loop engine (`loops.tick`, envelope, preconditions, orchestrator sweep) | ✅ built, generic, tested |
| 10 businesses defined (offer/price/ICP/niche/build_step) | ✅ `registry.py` |
| 10 GTM kits (brief · pack · outreach · landing · proposal) | ✅ `core/portfolio/gtm_kits/` |
| Per-business `loop.json` (9 steps) | ✅ `seed_all_loops()` |
| Adapters wired for all 10 | ❌ **the gap** |

### The 5 real gaps
1. **8 of 10 `build_*` verbs no-op.** Only `build_workflow_pack` has an adapter; the other 9 (`build_migration_blueprint`, `build_listmonk_pack`, …) fall to `NoopAdapter`.
2. **`ctx_for(step)` returns `{}`.** Adapters have no idea which business/niche/kit they serve.
3. **Lead-gen is not niche-aware per business.** The loop's `generate_lead_list` doesn't scan each business's `lead_niche` + `lead_geo`.
4. **The loop ignores the GTM kits.** `research/draft_outreach/publish_landing/draft_proposal` regenerate from scratch instead of consuming the kit we already produced.
5. **No per-business loop verification.** No proof each of the 10 ticks through all 9 steps.

---

## The plan (8 phases, each with a hard verification gate)

### Phase 0 — Loop context object (the spine)
Define `LoopContext(business, kit_path, niche, geo, offer, price, artifacts_dir)`. Make
`ctx_for(step)` return it (populated from `registry` + `gtm_kits/<slug>.md`). Every adapter
now receives real business context. **Verify:** unit test that `ctx_for` for each of the 10
returns the right offer/niche/kit path.

### Phase 1 — Generic build-pack adapter (fix the 9 no-ops)
One `BuildPackAdapter` that handles **any** `build_*` verb: it reads the business's GTM-kit
"Service Pack" section (already generated) and writes a per-business `pack.json` artifact.
Register it for all 10 build_step verbs (registry lookup, not one-per-verb). **Verify:** tick
the build step for all 10 → each writes a non-empty pack artifact; 0 no-ops.

### Phase 2 — Niche-aware lead-gen + enrich
`LeadsAdapter` scans the business's `lead_niche` in `lead_geo` via the existing reach-100
metro sweep (`core.portfolio.leadgen`), writing `leads.json` per business. `EnrichAdapter`
runs Hunter (gated on quota). **Verify:** dry-run for all 10 returns a lead list scoped to
that business's niche/geo (no cross-contamination); enrich flagged real vs dry-run honestly.

### Phase 3 — Content adapters consume the GTM kit
`research_niche / draft_outreach / publish_landing_page(copy) / draft_proposal` read their
section from `gtm_kits/<slug>.md` instead of regenerating. (The kit is the source of truth;
the loop distributes it.) **Verify:** each content step's artifact matches the kit section.

### Phase 4 — Operational adapters (gated, real)
The steps that actually *do* things, each gated + per-business:
- `run_outreach_campaign` → `cold_outreach.send_sequences` (confirm+live+warmup+DNS gates).
- `publish_landing_page` → `site_builder` publish (page_approved_once + unpublish_handle).
- `deploy_demo_instance` → per-business OSS demo (first_of_kind_approved + cost ceiling +
  teardown_handle). **Hardest** — each business deploys a *different* OSS; scope this to a
  "demo blueprint" artifact first (what/how), real provisioning behind arming.
**Verify:** default dry-run returns `blocked/needs-arming` for all 10; nothing fires.

### Phase 5 — Full per-business loop run (the "works perfectly" proof)
Drive each business through all 9 steps (dry-run/propose), asserting each step
executes-or-queues correctly and leaves the expected artifact. **Verify:** a
`loop_run(slug)` harness produces a green/pending/blocked matrix for all 10; a golden test
per business.

### Phase 6 — Orchestrator sweep hardening
`run_once` over all 10 with the real adapters; add per-tick error isolation (one business
failing never stalls the sweep), budget-ceiling enforcement (the deferred gate), and a
resumable cursor. **Verify:** kill-switch halts mid-sweep; a thrown adapter drops that
business to `null` and the others still tick; budget cap blocks over-spend.

### Phase 7 — Surface loop health in Portfolio HQ
Add to the toodle: per-business **loop status** (which of the 9 steps done/pending/blocked)
+ a **"Run tick (dry-run)"** button + the artifacts. **Verify:** `/api/narai/portfolio/loop/{slug}`
returns the step matrix; the HQ renders all 10.

### Phase 8 — Arm-readiness (documented, NOT armed)
Write the arm checklist per business (legal/registration, real creds present, warmup done,
teardown handles) and a single `arm_business(slug)` gate. Keep the orchestrator **dormant**.
**Verify:** arming is refused unless every precondition + `VOICE/BUSINESS_REGISTERED`-style
flag is set; a dormant sweep still returns `{"status":"dormant"}`.

---

## Safety posture (unchanged, enforced)
- Everything runs **dry-run / propose** by default. The 5-color envelope (GREEN/AUTO_CAPPED/
  AMBER/RED) is intact; `deploy_demo_instance` + `run_outreach_campaign` are AUTO_CAPPED with
  preconditions.
- **Nothing real fires** (outreach send, landing publish, demo deploy, spend) until the
  operator arms *and* the legal/registration gate is cleared.
- Adversarial verification each phase (bad kit, missing niche, envelope bypass attempts).

## Sequencing & effort (rough)
- Phases 0–3 (context + build-pack + niche leads + kit consumption): the core — makes all 10
  loops actually *do* their acquisition work in dry-run. ~biggest value.
- Phase 4–5 (operational gating + full-loop proof): medium.
- Phase 6–8 (sweep hardening + HQ + arm-readiness): polish + operator control.

Recommend executing **0→5 first** (the loops become real + verified for all 10), then 6→8.
Each phase ends with tests green + a dry-run artifact, committed. Deploy after Phase 5 and
again after Phase 7.
