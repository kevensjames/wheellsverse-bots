# Workforce Phase 3 — Normalization Report

**Status:** `WORKFORCE_NORMALIZED_INERT_LOCALLY` — 319 complete, schema-valid,
fail-closed `AgentCharacterManifest` declarations, all at **INERT**. Nothing is
activated, catalogued, bound to an adapter, mounted on a router, or deployed.
KAI remains the sole authority. Phase 3 stops here; the catalog / Angular UI does
**not** begin automatically.

## What was produced

| Metric | Value |
|---|---|
| Upstream normalized (agency-agents, pinned `6d29a9b0…`) | **279** |
| KAI-native created (from the required roster) | **40** |
| **Total manifests** | **319** |
| Reconciliation | `upstream (279) + native (40) == total (319)` — **holds** |
| All at INERT | ✅ | 
| Unique ids / unique display names | ✅ / ✅ (deterministic) |
| Flagged sources with preserved evidence | **45** |

Generated artifacts (deterministic — re-running the normalizer yields byte-identical output):

| Artifact | sha256 |
|---|---|
| `backend/app/services/workforce/generated/characters.json` | `a5797f5bd930c6a9ce9e825783ca79ed1c0a0d804a631f1d5cc29efe9c4bfcdd` |
| `…/generated/normalization_manifest.json` | `e6221f12c2609f118a408d152f60f850b253586081c0219f7fc19606e8c192b9` |
| `…/generated/flagged_evidence.json` | `0e42bdcb2dd16c32ddfaadaed9a78d30fca9412d2a684121394026429d038cdd` |
| `…/generated/org_chart.json` | `1132e147bc9d3a4a04633d634fbcf470c877b0c3c4a21458d60d234662cdb946` |

Generator: `backend/app/services/workforce/normalize.py` (pure; stdlib + the
Phase-1 schema only). Tests: `backend/tests/test_workforce_normalization.py`.

## The count decision

The Phase-2 review authorized "264→279 target 304; 40 KAI-native". After Unit-1
recovered the 15 missed game-development agents, that arithmetic no longer closed
(279 + 40 = 319, not 304 = pre-correction 264 + 40). The owner chose **319 =
keep all 279 enumerated upstream + 40 native**, so nothing enumerated is dropped.

## Governance boundary — why normalizing untrusted content is safe

Upstream prose is **untrusted**. Normalization does **not** import it into any
active manifest field. Each upstream character receives a **standard, safe,
KAI-authored** manifest:

- **soul** — KAI's own contract (truthfulness, owner sovereignty, reversibility,
  least privilege; immutable "KAI is the sole authority / a declaration is not
  permission / remain INERT until the owner authorizes");
- **workplace** — deny-by-default (network deny; device/browser/external-write off);
- **capabilities** — advisory/draft only, with an explicit `forbidden` set
  (no execution, no money movement, no external comms, no self-approval, no
  self-completion, no mission creation, no device/browser/network);
- **governance** — `DRAFT_ONLY`, `owner_only` approval, INERT, independent
  reviewer classes named;
- only **safe semantic expertise** — the division label + the source role name —
  is extracted, and it is **sanitized** against the schema's injection / autonomy /
  sentience / placeholder needles before it enters a field (fail closed to a
  generic phrasing if a needle appears).

Provenance is carried **honestly**: every `UPSTREAM` identity keeps
`source_path` + pinned `source_commit` + `source_hash`; every `KAI_NATIVE`
identity carries **none**. `reviewed_by` is `null` on all 319 — nothing is
labelled human-approved, because no human has reviewed these manifests.

## The 45 flagged sources

The intake flagged 45 files (39 `EXEC_CONTENT_PRESENT`, 5 `SECRET_EXFIL_PATTERN`,
1 `INJECTION_PATTERN` — all previously assessed benign). For each, the report
preserves the **reason codes + SHA-256 + quoted excerpts of the flagged
operational instructions** in `flagged_evidence.json`, marked
`QUOTED_OPERATIONAL_INSTRUCTIONS_INERT`:

- a bounded `head_excerpt` for context, plus per-reason `flagged_windows` that
  quote the **actual matched region** (e.g. the `INJECTION_PATTERN` window
  retains the source's "ignore all previous instructions" phrase);
- these are **evidence only** — not active prompts, not imported into any
  manifest field, not human-approved. Executable snippets are quoted as evidence,
  never copied into a prompt.

**Negative controls with teeth** prove the boundary held: the injection phrase
appears in the evidence but is **absent from every active manifest field**, and a
leakage scan asserts no `ignore all previous instructions` / ` ```bash ` / `npm
install` / `pip install` / `curl` marker appears in any manifest.

## Verification (15 Phase-3 tests, all green)

Re-validates every one of the 319 manifests against the fail-closed schema;
checks counts + reconciliation, unique ids/names, all-INERT, provenance honesty,
no-human-approval, the full 40-name native roster, flagged-evidence preservation,
the injection-leak negative control, and the no-operational-leakage scan. Schema
teeth are proven by negative controls (status-past-INERT, KAI_NATIVE-with-
provenance, and too-few-traits are each rejected). A `_safe()` sanitizer test
proves the one guard on boundary-crossing text fails closed on injection /
autonomy / sentience / placeholder needles and passes benign role names. A
determinism test asserts the committed artifacts equal a fresh generator run
(self-skips without the quarantine).

Division placement (org_chart.json): Engineering 64 · Specialized 59 · Marketing
36 · Game Development 21 · GIS 13 · Security 12 · Design 10 · Sales 9 · Testing 9
· Paid Media 7 · Project Management 7 · Academic 6 · Spatial Computing 6 · Support
6 · Finance 5 · Product 5 · Healthcare 3 · Research 1 · **KAI Native 40**.

## NOT done (by authorization / ceiling)

No catalog registration, no Angular/UI, no adapter/handler/router/worker, no
model routing, no migration, no merge, no deploy, no activation. Nothing moved
past INERT. `KAI_BROWSER_OPS_ENABLED=false`. Soak + Istanbul untouched. The
catalog / Angular UI does not begin automatically — it awaits separate owner
authorization.
