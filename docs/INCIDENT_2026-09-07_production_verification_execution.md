# Incident: a release verifier executed an owner-approved proposal on production

**Classification:** production verification-process incident. Read-only action, no data loss.
**Status:** RECORDED. Authorization boundary fixed on `hotfix/kai-holding-ceo-truth`.
**This record is preserved, not corrected away.** The execution happened; the proposal remains
`executed`; nothing below is deleted or rewritten.

---

## 1. What happened

| Field | Value |
|---|---|
| When | 2026-09-07, during post-deployment verification of production merge `5e767a4e8df9e49f4a43a69c07e3464e8477a04f` |
| Actor | The release verifier (an AI assistant conducting the operator's approved verification procedure) |
| Credential used | The **production owner** `API_KEY`, read from Railway `wheellsverse-v2` |
| Session | An owner-role session cookie minted from that key minutes earlier |
| Request | `POST https://app.wheellsverse.com/admin/kai/holding/proposals/9/execute` |
| Intent | Verify the control **failed closed** while `KAI_CAPABILITY_EXECUTION_ENABLED=false` |
| Result | **HTTP 200 — it succeeded** |
| Proposal | `#9`, "Confirm 62 operator data field(s) across the portfolio", entity `holding` |
| Prior state | `approved` (a genuine, earlier owner approval) |
| Resulting state | `executed` |
| Action performed | The proposal's **read-only** action via `executor.execute_approved` → `_RUNNERS[action_class]`; evidence recorded with `read_only: true` |
| Writes / money / deploys | **None.** The executor's contract is read-only: re-probe and gather evidence |
| Audit | `holding.proposal.executed` emitted with proposal id, action class and evidence |
| Correlation | Verification run of deployment `c81a3b11-d096-4fa5-8c1c-53215ae2e568` (App A) against merge `5e767a4e8df9e49f4a43a69c07e3464e8477a04f` |
| Idempotency | Held. The immediately repeated call returned `409`: *"proposal is 'executed', not 'approved' — execution requires a prior approval"* |

**No autonomous or background execution occurred.** `autonomy.last_cycle` was `null`, `missions` was
empty, and `kai_working.currently_working` was empty before and after. The system did not act; a human
process did.

## 2. Why it was possible — the actual defect

The shallow reading is "the verifier made a mistake". That is true and insufficient.

The real defect is that **a release verifier held a credential that could execute**. The verification
procedure needed to read protected admin data and run non-mutating checks. It was handed the owner key,
because that is the only credential the platform offers for reading those surfaces. Owner authority and
read-verification authority were the same thing.

Two independent controls were missing:

1. **No least-privilege verification identity.** `ROLE_OWNER` carries every scope. There was no role
   that could read protected admin JSON and health surfaces while being refused every mutating route.
2. **No action-bound confirmation on execution.** A proposal approved at some earlier time could be
   executed later by any generic owner-authenticated session. Approval and execution were separated in
   time with nothing binding them together — no fresh confirmation, no action digest, no environment
   binding, no expiry.

`KAI_CAPABILITY_EXECUTION_ENABLED=false` did not prevent this, and correctly so: that flag governs the
*capability execution* subsystem, not the read-only proposal executor. Expecting it to block this path
was the verifier's second error, and the state axes now make that distinction visible.

## 3. What was NOT compromised

- No credential was exposed by this incident.
- No customer, financial or personal data was read, written or transmitted.
- No production code, configuration, flag, branch or deployment was changed by the execution.
- No money moved. `MONEY_MODE` is `MOCK`; the executor cannot move money regardless.
- The eight authority flags were OFF before and remain OFF.

## 4. Remediation

Implemented on `hotfix/kai-holding-ceo-truth`:

1. **`ROLE_RELEASE_VERIFIER`** — a least-privilege identity holding `read` and a new `verify` scope
   only. It is refused approve, execute, defer, deploy, finance, messaging, policy and
   authority-changing routes with **403**. Automated production smoke tests must use this identity and
   never an owner-execution credential.
2. **Action-bound owner confirmation** — executing an approved proposal now requires a fresh
   confirmation bound to the authenticated owner, the proposal id, a digest of the exact action, the
   environment, and a short expiry. A previously approved proposal can no longer be executed through a
   generic stale session. One-time execution and idempotency are preserved.
3. Tests for role confusion, stale approval, replay, changed action digest, wrong environment, forged
   identity and expired confirmation.

**Execution behaviour is proven in isolated tests and on staging. No further real production proposal
was executed to test this.**

## 5. Disposition of proposal #9

Left as `executed`, with its evidence and audit record intact. It is a truthful record of what
happened. It is **not** reverted, because reverting it would require writing false state into the
store to make an incident look like it did not occur — the precise failure this system exists to
prevent.

## 6. Follow-ups

1. Provision a `RELEASE_VERIFIER_READ_ONLY` credential in production and staging so verification never
   again requires the owner key. **Operator action — not done by this hotfix.**
2. Review whether any other route reachable with a generic owner session performs a consequential
   action without fresh confirmation.
3. Consider recording verification runs as first-class evidence with their own actor identity, so an
   action taken during verification is attributable without reading request logs.
