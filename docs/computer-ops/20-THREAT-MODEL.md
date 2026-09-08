# KAI Computer Operations — Permission and Threat Model

Scope: the pinned DeepSeek Harness runtime, the KAI ACP connector, and the macOS
desktop bridge. Written against measured behaviour at commit
`c389f96bf3a9b6807cb71ed6bdad5849be0df6d8`, not against documentation.

## 1. Trust boundaries

```
  [ Operator ]  ← the only source of authority
        │  owner session, fresh bound approvals, macOS TCC grants
        ▼
  [ KAI backend ]  ← SOLE authority: identity, missions, policy, budgets, evidence
        │  authenticated OUTBOUND pull (no inbound port on the device)
        ▼
  [ KAI local connector ]  ← THE POLICY POINT. Owns the harness child's stdio.
        │                     Answers session/request_permission from KAI policy.
        ├──────────────► [ Harness child ]  ← UNTRUSTED execution provider
        │                  stdio only, no listener, per-mission, dies with the mission
        └──────────────► [ Desktop bridge ] ← closed verb set, deterministic gate
                              ▲
                              └── NOT reachable from the harness
```

The single most important property: **the harness and the desktop bridge are siblings,
never parent and child.** The bridge is reachable only from the connector. If the
harness could reach the bridge — or could reach `screencapture`/`osascript` directly —
every bridge control would be bypassable.

## 2. What the harness does and does not enforce (measured)

| Control | Reality |
|---|---|
| `sandbox-policy: read-only` | Denies **file writes only**. The generated Seatbelt profile is `(version 1) (allow default) (deny file-write*)` (`packages/sandbox/sandbox-local/src/profiles.ts:52`). Process execution, network egress and reads of any user-readable file remain permitted. |
| `approval: ask` | Routes each request to the composed answerer — over ACP, the KAI connector. With no answerer it **fails closed**. |
| `approval: never` | Deterministic reject of every approval request. |
| `packages/guard` | **Not** an enforcement package: loop hygiene only (repeat-call reminder, cooperative timeout). Do not cite it as a policy seam. |
| `ctx.tools.guard` | Synchronous, so an async KAI policy round trip cannot be expressed as a guard. This is a further reason the policy point is the connector. |
| Upstream's own position | `SAFETY.md`: not security-audited, "do not rely on DeepSeek Harness as the sole security control". |

**Consequence:** containment comes from *which plugins are mounted*, not from the
sandbox. That is why the containment overlay removes capability rather than restricting it.

## 3. Attacks considered

### A1 — Prompt injection from a page, document, screenshot or tool output
*Treated as data, never as instruction.* The harness has no independent fetch or search
(`tool-web`, `web-fetch-http`, `web-search-deepseek` disabled) and no filesystem-sourced
skill loading (`skill-filesystem`, `tool-skill` disabled), so injected text cannot enter
except through content KAI itself supplied. Anything read back from the desktop or a
workspace is normalised through KAI's existing `scan_for_injection` /
`neutralize_untrusted_context` before reaching a model. Policy lives outside the model
and outside harness prompts, so a successful injection still cannot widen scope.

### A2 — Model escapes containment via a shell
**This attack succeeded during development and is now closed.** With `tool-bash`
mounted, the model executed `echo` with zero approval requests reaching KAI; the same
path reaches `curl`, `screencapture`, `osascript`, `~/.ssh` and browser cookie stores.
Closed by removing `tool-bash`. Re-tested: the model reports the tool unavailable, then
*spontaneously attempts* a `write` workaround, which the read-only sandbox rejects.
Residual: any change that re-mounts a shell silently reopens egress and desktop reach —
which is why `tool-bash` is an asserted attestation invariant, not a convention.

### A3 — Silent cloud egress under LOCAL_ONLY
Three independent paths were found and closed:
1. *Fallback.* The cloud adapter is disabled in the same overlay that installs the local
   route, so no cloud route exists to fall back to.
2. *Ambient credential.* A route with no credential reference lets pi-ai pick up an
   unrelated ambient key. A placeholder reference is named explicitly instead.
3. *Post-attestation override.* The on-disk settings document overrides composed LLM
   routing; with it mounted the local route did not register at all. The settings seam
   is disabled so the composition is authoritative.
Residual: a `--patch` file is trusted input. Overlays are version-controlled and
reviewed like code.

### A4 — Approval replay, or approval for a different action
Approvals are minted and burned by KAI's existing
`action_confirmation.mint()/verify_and_consume()`, binding subject, principal, action
digest, environment and expiry, with a Postgres `jti` burned via
`INSERT..ON CONFLICT DO NOTHING RETURNING` — single-use, and failing closed when the
store is unreachable. The bridge never self-approves: mutating verbs return
`REQUIRE_APPROVAL` upward.

### A5 — Approving an action through the automation being approved
Structurally prevented: the approval surface is the hosted Holding Command panel
authenticated as the owner, on a different device from the automated desktop. The bridge
has no verb that can click an approval dialog, and `interpret_confirmation()` already
refuses voice/gesture channels and ambiguous confirmations.

### A6 — Stale or duplicated work after reconnect
KAI's `holding_worker_jobs` channel provides leased, exactly-once claim
(`UPDATE..WHERE id=(SELECT..FOR UPDATE SKIP LOCKED)`, 300s lease, heartbeat, bounded
attempts, crash reclaim). On reconnect the connector must revalidate authorization and
approvals rather than resume: an approval may have expired or been revoked while
disconnected, and the harness child from the previous connection is already dead.

### A7 — Credential theft from the desktop
Credential paths (`.ssh`, `.aws`, `.gnupg`, Keychains, `.netrc`, `*.pem`, cookie stores)
are denied by the bridge regardless of any allowlist. Password-manager windows are
**blocked** for capture rather than masked, because masking cannot be guaranteed across
window moves and Spaces changes. The harness cannot reach these paths at all now that
the shell is removed.

### A8 — Runaway autonomous work
`tool-ralph` (64-round loop driver), subagent spawn/fork, workflows and background jobs
are all disabled. KAI owns decomposition and budgets. The harness child is per-mission
and dies with it.

### A9 — Telemetry / data exfiltration by the provider
The default profile ships an OTLP exporter to
`https://harness-telemetry.deepseeksvc.com/v1/logs`. Pinned to `DISABLED` and asserted
by attestation.

### A10 — Supply-chain compromise of the harness
Pinned to an exact commit; `--frozen-lockfile`; pnpm denies dependency build scripts by
default with a 5-entry reviewed allowlist; install runs with `CI=true` so the harness
does not rewrite this checkout's git hooks. `status` reports pin drift explicitly.
Residual, operator decision: a plain install pulls large third-party agent binaries as
ordinary dependencies of `packages/subagent/*`; the overlay disables those TOOLS but
does not remove the payload from disk.

## 4. Residual risks accepted or deferred

| Risk | Status |
|---|---|
| Harness reads any user-readable file within its mounted `tool-fs` policy | Confined by `fs-sandbox` + workspace root; the shell path that bypassed it is removed. Container isolation would be stronger but `colima` is not running (operator action). |
| A `--patch` overlay is trusted input | Version-controlled and reviewed as code; attestation verifies the *result*, not the intent. |
| Upstream is a developer preview with breaking changes expected | The seam is narrow (5 ACP methods) and the harness is replaceable; attestation fails loudly on a renamed plugin id. |
| No device pairing exists yet | Blocker; no credential is issued to any device until enrollment and revocation policy exist. |
