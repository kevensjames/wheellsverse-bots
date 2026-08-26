# KAI Capability Fabric — Architecture

**KAI is the brain. Everything else is a capability KAI can call when it is useful, then turn
off when finished.** External repositories, MCP servers, Agent Skills, model runtimes, coding
workers, memory systems, security routers, and geospatial tools do not become independent
brains competing with KAI — they sit behind one registry, one decision brain, and one
governance gate.

```
USER → KAI → INTENT+CONTEXT → CAPABILITY BRAIN → GOVERNANCE → CAPABILITY FABRIC
```

## Modules (backend/app/services/capability/)

Pure-logic Python (no FastAPI/DB import at load), each testable as a plain `python3` script —
the same discipline as `reasoning_sanitizer`. 48 tests, 0 failures.

| module | role | key sections |
|--------|------|--------------|
| `manifest.py` | normalized capability manifest + taxonomy (13 types, risk/action/activation/certification/availability enums) | §13, §14 |
| `registry.py` | the **single** CapabilityRegistry — register / list / enable / disable / quarantine | §15 |
| `results.py` | 5 normalized result kinds + the **prompt-injection boundary** | §23, §24 |
| `risk.py` | the policy gate → ALLOW / REQUIRE_APPROVAL / DENY from KAI governance inputs only | §25, §22 |
| `graph.py` | typed capability graph (REQUIRES / CONFLICTS_WITH / ALTERNATIVE_TO / FALLBACK_FOR / …) + dependency closure | §17, §60, §61 |
| `lifecycle.py` | explicit 11-state lifecycle; no READY without health; deactivate() tears down every §19 trigger | §19, §20, §51 |
| `brain.py` | the **CapabilityBrain** — intent → candidates → policy → resources → rank → plan | §16, §28, §29, §63 |
| `adapter.py` | the transport boundary; `ExternalBlockedAdapter` reports OFFLINE honestly | §21, §22 |
| `seed.py` | the honest catalog (18 capabilities) with verified provenance | §14, §53, §74 |

## The decision pipeline (§16)

```
REQUEST
  → classify_intent()          coarse tags from observable keywords (not an LLM hunch)
  → candidate search           selectable capabilities whose triggers appear in the request
  → policy filter (risk.py)    DENY drops a candidate; RESTRICTED/HIGH_IMPACT → approval
  → resource filter            drop what the machine can't run (VRAM/RAM); prefer light under pressure
  → rank (§28 weighted)        task_fit .30 / security .20 / reliability .15 / data .10 / latency .10 / resource .05 / financial .05 / context .05
  → conflict + alternatives    keep the highest-ranked of a conflicting/interchangeable set
  → dependency resolution      REQUIRES closure, deps emitted first; a missing dep → BLOCKED + fallback
  → EXECUTION PLAN             ordered steps, each with decision + needs_approval + concise rationale
```

Every selection is **observable** (a numeric score + a one-line rationale like *"Selected
context7 — matched documentation."*). No hidden chain-of-thought is ever surfaced (§63).

## Hard invariants

- **One registry, one brain** (§12). MCP is one transport among many, not its own brain.
- **KAI is the authority** (§22). No capability calls another capability directly — all
  cross-capability orchestration returns through the Brain. A capability may *propose* an
  action; the proposal is inert until governance authorizes it.
- **No fake availability** (§73/§74). A capability the machine can't run is `EXTERNAL_BLOCKED`
  and is never selected. Nothing reaches READY without a passing health check.
- **Nothing runs forever** (§19/§69). "Automatic" means *selected when needed, stopped after* —
  not started at boot. Heavy runtimes (model servers, coding workers) are torn down explicitly.
- **One source of truth for memory** (§31). Two memory systems can never co-own canonical
  long-term memory; `tencentdb-memory` CONFLICTS_WITH `kai-memory` in the graph.

## Current status (honest)

The governed **core is built and tested**. **No external capability is installed or live** in
this environment (sandboxed network + App B down) — the catalog is upstream-verified and the
routing logic is proven against fixtures, but every external capability is `DISCOVERED` /
`EXTERNAL_BLOCKED`, so the live Brain plans only the native `kai-memory` / `claude-code`. See
[KAI_CAPABILITY_LEDGER.md](KAI_CAPABILITY_LEDGER.md).
