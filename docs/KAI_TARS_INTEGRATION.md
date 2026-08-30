# KAI × UI-TARS Execution Worker — Integration (Phase 1: governance foundation)
## 2026-08-30 · branch feature/kai-tars-execution-worker · NOT deployed · fail-closed

TARS is an **execution worker**, never a second assistant. KAI keeps planning, model
abstraction, prompts, memory, auth, governance, spend, audit, redaction, the Capability
Fabric, and the emergency stop. This phase adds the **governed seam** only — no install of
TARS, no worker running, no host access, no production change.

## Architecture (target)
```
User → KAI planning → KAI policy/authorization → approval gate → KAI TARS adapter
     → ISOLATED TARS worker (separate Node process) → browser / isolated desktop
     → screenshots+events+structured results → KAI audit log → user response
```
- **Integration surface (chosen):** Agent TARS **headless server / SDK** (`@agent-tars/cli` **v0.3.0**,
  Apache-2.0, Node ≥22) — structured task submission + streamed events + cancellation. NOT the desktop
  GUI, NOT screen-scraping. Rationale: narrowest supported programmatic interface; no need to expose
  KAI's DB/master creds; deterministic exit + health checks.
- **KAI (Python) ⇄ TARS worker (Node)** over authenticated HTTP. Hosted Railway KAI **cannot** control a
  Mac desktop → desktop control requires a **local worker** that registers with a signed `worker_id` and
  makes an **outbound** connection to KAI. No unauthenticated inbound port on the user's machine.
- **Runtime truth:** the capability is `AVAILABLE`/`READY` ONLY when a certified worker is online and every
  attestation holds; otherwise `UNAVAILABLE`/`DEGRADED`/`EXPERIMENTAL`. Never `READY` from config alone.

## What Phase 1 delivers (built + tested, dormant — not wired into the live fabric/governed path)
`backend/app/services/tars/`
- `provenance.py` — pinned upstream (@agent-tars/cli 0.3.0, Apache-2.0); `is_pinned()` rejects `latest`/mismatch.
- `policy.py` — action classes **READ_ONLY / WRITE(needs bound approval) / CONSEQUENTIAL(prohibited)**;
  unknown action ⇒ CONSEQUENTIAL (fail-closed); approvals bind to task/user/worker/action/target/expiry and
  **do not generalize**; page text is data, not authorization.
- `adapter.py` — `TarsTask`/`TarsResult` contracts; `derive_status()` runtime-truth; `TarsAdapter` fail-closed
  (`health→UNAVAILABLE` with no worker; `execute→denied` unless READY, and denied in this build regardless).
- `capability.py` — Capability Fabric record (reuses the existing schema): `computer_use`, provider `ui_tars`,
  runtime `LOCAL_WORKER`, `security_tier 3` / risk `RESTRICTED`, `automatic_activation_allowed=false`,
  availability **derived from the live adapter** (DISCOVERED+DISABLED with no worker). Consequential capabilities
  (purchase, financial, production_deployment) hard-`prohibited`.
- `test_tars.py` — 23/23: provenance, runtime-truth, fail-closed execute, policy/approval-binding,
  prompt-injection-as-data, capability record.

## Permission model
- READ_ONLY (open/navigate/read/screenshot) — allowed only in a pre-approved isolated env.
- WRITE (form/upload/download/submit/send/publish) — explicit bound approval + preview; one approval, one action.
- CONSEQUENTIAL (purchase, transfer, refund/payout, financial change, sign, delete, password/MFA, expose secret,
  production deploy, modify prod infra, disable security, shell, credential entry, irreversible external) — **prohibited**.

## NOT done (genuine external blockers / gated next phases)
1. **Isolated worker (Sections 4/9):** needs the **Docker daemon** (currently NOT running) for container
   isolation — network default-deny, per-task browser profile, fs limits, block metadata/socket/private nets.
2. **TARS model-provider credential (Section 8):** TARS needs its own vision/UI model (Doubao/Seed via
   Volcengine, or Claude). Operator decision + credential required.
3. **Local worker host (Section 4):** the Mac mini/Dell worker + signed `worker_id` + outbound registration.
4. Wiring the capability into the live fabric + the harmless-task **milestone** (approved read-only browser task →
   events → cancel → structured evidence → sanitized audit) — gated on 1–3 + operator go, on **staging only**.

## Invariants held this phase
No install/run of TARS · no host access · no capability enabled (fail-closed UNAVAILABLE) · no App A/B change ·
no production deploy · money MOCK · privileges unchanged · no secrets. The module is self-contained and not yet
imported by `main.py`/the fabric, so it adds zero runtime attack surface until deliberately wired.

## Removal
Delete `backend/app/services/tars/` + this doc; nothing else references it.
