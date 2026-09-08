# PR70_RELEASE_RECORD_FROZEN

```text
PR70_RELEASE_RECORD_FROZEN
production:            073c9a46c39f2fa9969f8126f9c06bf004a75cf3
unexpected mutations:  0
rollback required:     NO
phase0 branch authorized: YES
```

## Scheduled-cycle gate

Observation window **2026-09-08 07:17:02Z → 09:01:31Z**, spanning one completed hourly cron slot
(08:11:17Z). The window closed before the 09:11 slot, so exactly one cycle is measured.

| # | Condition | Observed |
|---|---|---|
| 1 | exactly the expected briefing audit event | **1** new row: `220 holding.morning_briefing.generated`, `actor_type=system`, 08:11:17.109Z |
| 2 | proposal count remains 11 | 11 |
| 3 | statuses remain 2 executed / 9 proposed | `{executed: 2, proposed: 9}` |
| 4 | full proposal digest unchanged | `93db424a013a4b6b79438b76450d2b4718e1080284098819302b2a186adf8b65` |
| 5 | proposal events remain 4 | 4 |
| 6 | nonce rows remain 0 | 0 |
| 7 | migration remains 0007 | `0007_add_holding_action_nonces` |
| 8 | eight authority flags remain OFF | 0 ON (App A, 191 vars read; App B, 27 — non-empty reads, not a vacuous pass) |
| 9 | both services remain HTTP 200 | App A 200 · App B 200 |
| 10 | no unexplained timeline, mission, execution or credential event | timeline 15 (unchanged) · worker jobs 0 · audit action delta exactly `{holding.morning_briefing.generated: 1}` |

The cron signature was established from six consecutive prior hours (02:11:32, 03:14:23, 04:11:19,
05:15:53, 06:11:09, 07:11:59 — one `system` briefing event each, drifting :11–:15). That span brackets
the release and the credential rotation, so the expected-event shape was fixed *before* this cycle was
judged rather than fitted to it.

**Method note.** A first attempt to observe the cycle from a detached background shell collected
nothing — `railway ssh` does not function there, and every poll returned `audit_max=0`. That run
proved nothing and was discarded rather than reported; the gate above was measured in the foreground.

## Carried forward, unresolved

Two Phase 0 defects were confirmed by evidence, not closed:

1. **Deployment truth is process-local.** `hosted_route_verified()` reads an in-process set, so a
   separate process reports all 19 features `PRE_DEPLOY`. Hosted verification must become durable and
   bound to environment, release SHA, route and timestamp.
2. **Money truth is split.** `deployment_view()` fabricates `MOCK` via
   `getattr(settings, "MONEY_MODE", "MOCK")` while the certified resolver correctly answers
   `UNAVAILABLE`. Every money reader must route through the single resolver.

Neither enables money movement or autonomous authority; neither indicates rollback.

## Scope explicitly excluded from Phase 0

Workers Builds failure (fails identically to baseline), the stale `.railwayignore` comment, the absent
`data/store_payment_links.json`, Cloudflare apex-proxy repair, and credential-platform hardening.

## Attestation scope

The App B attestation binds **application code** — 1006 files, zero content mismatches, zero untracked
runtime files. It is not a reproducible proof of the whole image: base layers, installed wheels and OS
packages are outside it. Reproducible image provenance needs a pinned digest or build attestation, and
is not Phase 0 work.
