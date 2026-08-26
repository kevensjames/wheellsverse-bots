# KAI Capability Fabric — Ledger (§71) + Certification (§74)

Honest state, per directive §73/§74: **cloning/verifying an upstream is not success**, and no
row is forced to PASS. As of **2026-08-26**, branch `feat/kai-capability-fabric`.

## Fabric core certification (§74)

The governed **core is built and tested** (48 pure tests, 0 failures). Live integrations that
require a running KAI runtime, real installs, or a browser are honestly PENDING/EXTERNAL_BLOCKED.

| component | state | evidence |
|-----------|-------|----------|
| Capability Registry (§15) | **PASS** | `registry.py`, tests |
| Capability Brain (§16) | **PASS** | `brain.py`, routing tests |
| Capability Graph (§17) | **PASS** | `graph.py`, closure/cycle/conflict tests |
| Automatic Selection (§28) | **PASS** | weighted scoring + observable rationale, §65 tests |
| Automatic Activation (§18/§20) | **PASS (logic)** | lifecycle state machine; live activation needs a runtime |
| Automatic Deactivation (§19) | **PASS** | `deactivate()` maps every trigger to a teardown |
| Dependency Resolution (§60) | **PASS** | REQUIRES closure, deps-first ordering |
| Conflict Resolution (§61) | **PASS** | conflict/alternative collapse |
| Resource Policy (§26) | **PASS (logic)** | resource filter; live metering not wired |
| Security Policy (§25) | **PASS** | `evaluate_policy` + tests |
| RBAC (§22) | **PASS** | scope/role gating in the policy |
| Approval Gates (§25) | **PASS** | REQUIRE_APPROVAL tiers |
| Prompt Injection (§24) | **PASS** | untrusted-by-default + `scan_for_injection` (all fields) + inert proposals |
| Principal Propagation (§17) | **PASS** | `invocation.py` — every call carries principal/mission/correlation; no anonymous calls; forged request scopes ignored |
| Plugin-to-plugin control (§18) | **PASS** | `route_capability_proposal` — a proposal is gated by policy, never a direct A→B grant |
| Governed invocation (§16) | **PASS** | `governed_invoke` — DENY never executes, REQUIRE_APPROVAL returns inert proposal, oversized result clamped |
| Secret Isolation (§50) | **PARTIAL** | broker designed in docs; not wired to a live secret store |
| Audit (§59) | **PARTIAL** | event taxonomy defined; sink wiring EXTERNAL_BLOCKED (App B down) |
| Nexus Integration (§54–58) | **PARTIAL** | `kai-nexus-capabilities.js` panel + honest catalog snapshot built + tested (no fake READY, credential-redacted inspector, §57 categories); live Nexus tab wiring pending |
| Mission Integration (§58) | **PARTIAL** | correlation model defined; live mission wiring pending |
| Claude Code Integration (§32/§72) | **PARTIAL** | CLAUDE.md routing section added; MCP installs EXTERNAL_BLOCKED |

## Per-capability ledger (§71)

`UV`=upstream-verified · `SR`=security-reviewed (doc-level) · `INS`=installed · `ADP`=adapter
built · `CC`=Claude-Code-available · `KAI`=KAI-runtime-available · `AR`=auto-routing ·
`TST`=integration-tested · `CERT`=§74 final. `—`=no, `✓`=yes, `~`=partial.

| capability | UV | SR | INS | ADP | CC | KAI | AR | TST | CERT |
|-----------|----|----|-----|-----|----|----|----|-----|------|
| kai-memory (native) | ✓ | ✓ | ✓ | ~ | — | ✓ | ✓ | ~ | **CERTIFIED** |
| claude-code (native) | ✓ | ✓ | ✓ | ~ | ✓ | ✓ | ✓ | ~ | **CERTIFIED** |
| context7 | ✓ | ✓ | ✓* | — | ✓ | — | ~ | ✓* | **PARTIAL** (connected + **exercised**) |
| playwright | ✓ | ✓ | ✓* | — | ✓ | — | ~ | ✓* | **PARTIAL** (connected + exercised) |
| sequential-thinking | ✓ | ~ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** (absent — not configured) |
| filesystem | ✓ | ~ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** (absent — native file tools) |
| github | ✓ | ✓ | — | — | — | — | — | — | **AUTH_PENDING** (Copilot MCP configured; failed to connect — §36) |
| focus-output (i-have-adhd) | ✓ | ✓ | — | — | — | — | — | — | **EXPERIMENTAL** |
| book-to-skill | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** |
| reverse-skill | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** (RESTRICTED, vet-only) |
| ai-fundamentals | ✓ | ✓ | — | — | — | — | — | — | **EXPERIMENTAL** (reference-only) |
| tencentdb-memory | ✓ | ✓ | — | — | — | — | — | — | **EXPERIMENTAL** (arch-dependent; not adopted) |
| openwork | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** |
| buzz | ✓ | ✓ | — | — | — | — | — | — | **EXPERIMENTAL** (resolved, disabled) |
| airllm | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** |
| ollama | ~ | ✓ | — | — | — | — | — | — | **EXPERIMENTAL** (incumbent, not re-verified) |
| jcode | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** (HIGH — curl\|bash) |
| geolibre | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** |

\* context7 / playwright are **live in the Claude Code session** (used this session), not in the
KAI runtime (App B Docker-down).

## Adversarial review (§67)

A 4-lens (authority-boundary / policy-bypass / fake-success / correctness) refute-biased
review ran against the core. It **hit the session usage limit mid-verification** (8 verify
agents finished, 13 could not run), so it is **partial** — a re-run of the remaining lenses is
advised. Of the completed verifications, **2 confirmed + 1 correctly refuted**; a 3rd,
finder-flagged and independently confirmed by re-reading the code, was also fixed:

- **MEDIUM (confirmed)** — `risk.py`: the mission pre-approval path allowed FINANCIAL/DESTRUCTIVE/
  HIGH_IMPACT with no authorized-target check (asymmetric with RESTRICTED). **Fixed** — the
  authorized-target gate now applies even to a pre-approved capability.
- **LOW (confirmed)** — `results.py`: `scan_for_injection` scanned only `summary`, so a payload in
  `data`/`proposed_action` evaded the audit signal (authority invariant held; detection missed).
  **Fixed** — the default scan covers every untrusted field.
- **(independently confirmed)** — `brain.py`: dependency steps were hardcoded `ALLOW`. **Fixed** —
  a required dependency now passes the same policy gate (a RESTRICTED/HIGH_IMPACT dep is
  approval-gated or BLOCKED, never auto-allowed).

3 regression tests added (51 capability tests total). The correctly-refuted finding
(`authorize_action` accepts any approver) has **zero production callers** and an inert flag (no
executor exists yet) — noted as a hardening TODO for when a live executor is wired.

## What blocks CERTIFIED for the external capabilities

1. **No network in the Bash sandbox** → cannot install (pip/npm/git clone/`claude mcp add`).
2. **KAI runtime (App B) is Docker-down** → no live host to wire adapters into.
3. **Env-mutation + credentials require operator approval** (§1/§76) → `claude mcp add`,
   `curl|bash` installers, and GitHub/OpenWork/Buzz credentials are not autonomous actions.

The path to CERTIFIED per capability: install (approved) → build adapter → health check →
auto-routing verified live → integration-tested → certify. None may be forced (§74).
