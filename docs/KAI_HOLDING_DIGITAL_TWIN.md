# KAI Holding Digital Twin (§3-10, §15, §17)

The canonical **normalized operational state** of Wheellsverse Holdings — assembled **live** over the
already-authoritative sources, never a second database of everything. Built on
`feat/kai-exec-appb-integration`; dormant (no route/UI wired yet — that is Wave 7).

## Modules
| File | Role |
|---|---|
| `backend/app/services/holding/digital_twin.py` | `HoldingDigitalTwin` + `StartupState` + `Fact` provenance + `SOURCE_MAP` |
| `backend/app/services/holding/state_reconciler.py` | `HoldingStateReconciler` — twin-snapshot diff → `MaterialChange[]` |
| tests | `test_digital_twin.py` (9/9), `test_state_reconciler.py` (9/9) — pure, DB-free |

## Design invariants
- **Not a store (§3).** The twin holds no facts of its own. Every field resolves through injectable
  sources that default to the real subsystems: `holding.registry` (companies + no-fabrication
  `report_value`), `holding.status` (autonomy/workers), `holding.priorities`, `proposals_store`
  (owner actions), `capability.seed` (capability health). Sources are fail-open — a broken subsystem
  yields empty/`UNAVAILABLE`, never a crash and never a guess.
- **Dynamic discovery (§5).** `companies()` iterates `registry.all_entities()` and keeps the
  startup-typed ones (`product`/`company`/`LLC`). Add an entity to the registry → the twin includes
  it with **zero code change here** (proven by `t_new_company_auto_included`).
- **Provenance on every datum (§7).** `Fact = {value, source, observed_at, freshness, status}`.
  `status` preserves the REAL / DERIVED / DEMO / **UNAVAILABLE** taxonomy (§58). Money & customers are
  read **only** through `registry.report_value` — an un-sourced field returns `None` → `UNAVAILABLE`;
  KAI never prints a fabricated revenue/customer/balance number.
- **Freshness has a defined basis (§7).** `FRESH`/`STALE`/`UNKNOWN` computed from `observed_at` vs a
  per-fact-type window in `SOURCE_MAP`; no `observed_at` ⇒ `UNKNOWN`. No invented confidence %.

## §6 Source-of-truth map (excerpt)
| fact type | canonical | fallback | window |
|---|---|---|---|
| company_identity | holding.registry | — | 30d |
| repository_state | configured git source | holding.registry | 1d |
| deployment | railway/deploy provider | holding.registry | 1d |
| worker_state | holding.status.list_workers | — | 1d |
| owner_actions | holding.proposals_store | — | 7d |
| money / customers | approved accounting/CRM source | — | 30d |

Conflicts are **not** reconciled by guessing (§6): the canonical source wins; provenance records it.

## §8-10, §17 Material-change engine
`reconcile(prev_snapshot, cur_snapshot) → MaterialChange[]` over a deterministic `fingerprint` of each
snapshot. Materiality is a **versioned formula** (`MATERIALITY_VERSION = 1.0.0`), never an opaque score:

- status / health / autonomy **transition** → always material (into a degraded status ranks HIGH)
- incident count ↑ → `INCIDENT_OPENED` CRITICAL · ↓ → `INCIDENT_RESOLVED` INFO
- owner-action count ↑ → `OWNER_BLOCKER_ADDED` HIGH · ↓ → `OWNER_BLOCKER_RESOLVED` INFO
- worker plane `>0 → 0` → `WORKER_PLANE_DEGRADED` HIGH; `3 → 2` (still online) → **not material**
- available capabilities ↓ → `CAPABILITY_UNAVAILABLE` HIGH
- company added/removed between cycles → typed change

**Baseline (no prior) and materially-identical cycles yield `NO_MATERIAL_CHANGE` (§17)** — a polling
tick alone creates no work. This is the required guard against autonomous busy-work.

## Portfolio view (§15)
`portfolio_view()` answers, from real state only: which companies need attention, which are healthy,
which are blocked, how much owner vs KAI work is outstanding. Coarse company `health` = NEEDS_OWNER
(open owner action/blocker) > INCIDENT > OK.

## Next
Wave 2 wires the twin + reconciler into the continuous OBSERVE→…→UPDATE cycle (§16) and the
A0/A1 Autonomous Work Engine; the `CurrentPlan` model (§11-13) and per-company plan reconciliation
land at the head of Wave 2 (they need a plan store the twin can normalize, which does not exist yet).
