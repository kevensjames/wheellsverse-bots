# KAI Computer Operations — Production Plan (PREPARED FOR REVIEW, NOT EXECUTED)

**Nothing in this document has been run.** No production deploy, merge, migration, flag flip,
device enrollment, or TCC grant has occurred. Production (`kai-production` / `kai-prod`) is
untouched. This is a review-then-execute, phase-gated go/no-go — each phase needs an explicit
operator decision, and any phase can stop the rest.

Certifications that make this plan eligible to *exist* (all local/isolated, prod untouched):
SIGNED_HELPER_VERIFIED, DEVICE_CONTROL_VERIFIED (bounded TextEdit-only, local), STAGING_VERIFIED
(isolated App-B staging + workspace-read-only device). Production deployment is a SEPARATE
authorization and is NOT granted by any of them.

## P-0. Operator approval gate (decide before ANY phase)

1. **Deploy mechanism + branch compatibility (BLOCKER).** `feat/kai-computer-operations` branched
   from `origin/production` earlier; production has since moved on (capability-fabric etc.).
   Deploying this branch as-is could REGRESS prod. Decision: rebase/merge
   `feat/kai-computer-operations` ONTO the current `production` branch so the change is purely
   ADDITIVE (computer-ops routers + migration 0008), re-run the suites, and deploy that — via the
   git-integrated `production` branch (preferred, matches how prod deploys today) rather than a
   raw `railway up`. Confirm the merged head is byte-reviewed before deploy.
2. **Does production get a DEVICE at all?** Default NO. The governed backend can go to prod DARK
   and then enabled with ZERO devices — that adds the HTTP surface but grants zero desktop
   capability. Real desktop control in prod is Phase P-B and is its own decision.
3. **Identity for any prod device (BLOCKER for P-B).** Only an Apple Development cert exists today
   (dev-only, ~1yr, not for distribution). A PRODUCTION helper must be **Developer ID + notarized
   + stapled**. Obtain a Developer ID Application cert first; `verify_signing.sh` must exit 0
   against the Developer-ID-signed, notarized bundle before any prod TCC discussion.
4. **Device credential policy (for P-B).** Who may enroll, who revokes, and which elevated scopes
   (desktop.observe / desktop.interact / browser.test / workspace.write / runtime.control) are
   ever granted — each is a separate activation, never a bundle.

## P-A. Governed BACKEND to production, DARK then enabled, NO device

Prereqs: P-0.1 (merged/reviewed head), a **production DB backup**, and confirmation that
`KAI_CAPABILITY_EXECUTION_ENABLED` in prod is left exactly as it is (do NOT toggle it here).

1. **Backup prod DB (makes the decision reversible).**
   `pg_dump "$PROD_DATABASE_URL" -Fc -f kai-prod-pre-0008-$(date +%Y%m%d-%H%M).dump`
2. **Migrate additive 0008.** The entrypoint runs `alembic upgrade head` on deploy; 0008 adds only
   `kai_devices`, `kai_device_pairings`, `kai_device_nonces` (no changes to existing tables).
   Verified reversible (downgrade 0008→0007) locally + on disposable DBs. Confirm prod is at 0007
   before, 0008 after.
3. **Deploy with flags OFF** (`KAI_COMPUTER_OPS_ENABLED=false`; leave capability-exec as-is).
   Verify: `/health` ok; `GET /admin/kai/computer-operations/devices` → 404 (zero surface). This
   deploy is a pure code change adding no computer-ops HTTP surface.
4. **Enable `KAI_COMPUTER_OPS_ENABLED=true`** (still no device). Verify FROM OUTSIDE the edge:
   anon `devices`/`stop` → 401/403, `device/heartbeat` → 401; runtime `feature_state UNPAIRED`,
   `computer_control DEVICE_CONTROL_NOT_VERIFIED`, `device_count 0`, no fabricated readiness.
5. **Panel** `/admin/computer-ops` as owner: honest UNPAIRED/NOT_VERIFIED, nothing shows READY.
6. **Edge limits:** oversized → 413; (429 concurrent-lease once a device/mission exists).
7. **Canary + monitor:** watch `/health` and logs; log redaction (no device signature, pairing
   code, or Keychain material). Rollback = `KAI_COMPUTER_OPS_ENABLED=false` (no deploy needed).

At the end of P-A prod has the governed computer-ops backend, dark-then-enabled, with ZERO devices
and ZERO desktop capability. This is a safe resting state.

## P-B. Production DEVICE + real desktop control (SEPARATE authorization, later)

Only after P-0.2/0.3/0.4 are decided and a Developer-ID-notarized helper exists.

1. Build the helper, sign with **Developer ID**, notarize + staple; `verify_signing.sh` exit 0.
2. Grant Screen Recording + Accessibility to THAT notarized bundle only — never to Terminal,
   python, node, Claude, or the harness.
3. Launch the helper as its OWN responsible process (disclaim_spawn) and keep it warm
   (beginActivity + connector keepalive) — the four macOS platform requirements proven in Session 6.
4. Enroll a device; COMPARE fingerprints out-of-band before confirming.
5. Grant elevated scopes ONE AT A TIME as separate decisions — start with none beyond baseline;
   `computer.desktop.observe`/`interact` only on explicit approval, EXECUTE_SCOPED, with fresh
   bound approvals, STOP, revocation, and evidence.
6. Certify with the bounded cert against a NEW throwaway document, exactly as DEVICE_CONTROL_VERIFIED.

## Out of scope / never (production)

Unrestricted desktop access; granting TCC to a generic interpreter; enabling all elevated scopes
at once; arbitrary shell/AppleScript; coordinate replay; background surveillance; loading a
launchd/login agent for persistent unattended control without a separate explicit decision;
enabling `KAI_CAPABILITY_EXECUTION_ENABLED` as part of THIS work.

## Rollback (blast-radius order — see 50-ROLLBACK.md)

1. `KAI_COMPUTER_OPS_ENABLED=false` (instant, no deploy — removes the HTTP surface).
2. Revoke the device credential; stop the connector.
3. `git revert` the merged commits (never `git reset --hard` on the shared branch).
4. DB last: 0008 is additive; downgrade drops only the three new tables; restore from the backup
   if ever needed.
