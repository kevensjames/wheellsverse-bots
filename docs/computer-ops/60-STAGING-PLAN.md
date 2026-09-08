# KAI Computer Operations — Staging Deployment Plan (PREPARED, NOT EXECUTED)

**Nothing in this document has been run.** No staging or production deployment occurred
during this work. It is written so the deployment is a review-then-execute exercise
rather than a set of decisions made under time pressure at the console.

Prerequisite that is NOT satisfied: an isolated staging environment currently running
THIS branch. The recorded last staging deploy was a different branch, so staging cannot
certify this code until it is redeployed from `feat/kai-computer-operations`.

## 0. Operator approval gate

Do not begin without an explicit decision on:

1. **Device credential policy** — who may enroll a device, what elevated scopes are ever
   granted, and who revokes. Enrollment is deliberately not permission to act; the
   elevated scopes are where the real decision lives.
2. **Whether staging gets a device at all.** The backend and panel can be certified in
   staging with zero devices enrolled. A device means a real machine takes real work.
3. **TCC.** Not applicable in staging: the helper is unsigned, so desktop control is
   unreachable regardless.

## 1. Database

```sh
# BACKUP FIRST. 0008 is additive, but a backup is what makes the decision reversible.
pg_dump "$STAGING_DATABASE_URL" -Fc -f kai-staging-pre-0008-$(date +%Y%m%d-%H%M).dump
cd backend && alembic current              # expect 0007_add_holding_action_nonces
alembic upgrade 0008_add_kai_devices
alembic current                            # expect 0008_add_kai_devices
```

Verified locally on disposable databases (28/28), including downgrade and re-upgrade.
Note the downgrade is PARTIAL by design — see `50-ROLLBACK.md`.

## 2. Deploy with both flags OFF

```
KAI_COMPUTER_OPS_ENABLED=false
KAI_CAPABILITY_EXECUTION_ENABLED=false
```

Both default false. With them off the routers are not mounted at all, so the deploy adds
**zero** HTTP surface and is a pure code change. Confirm before going further:

```sh
curl -s $STAGING/health | jq '.status, .subsystems'
# expect status "ok"; computer_operations.state "DISABLED"
curl -s -o /dev/null -w '%{http_code}\n' $STAGING/admin/kai/computer-operations/devices
# expect 404 — the route does not exist while the flag is off
```

## 3. Enable computer operations, still with no device

```
KAI_COMPUTER_OPS_ENABLED=true
```

Authenticated route probes (expect the codes in brackets):

```sh
curl -s -o /dev/null -w 'anon devices=%{http_code}\n'  $STAGING/admin/kai/computer-operations/devices        # [401/403]
curl -s -o /dev/null -w 'anon stop=%{http_code}\n' -X POST $STAGING/admin/kai/computer-operations/stop        # [401/403]
curl -s -o /dev/null -w 'anon device api=%{http_code}\n' -X POST $STAGING/api/kai/device/heartbeat            # [401]
curl -s -H "X-Admin-Token: $STAGING_ADMIN" $STAGING/admin/kai/computer-operations/runtime | jq '.feature_state'
# expect "UNPAIRED" — no device enrolled
```

**Externally verify the anonymous probes from outside the deployment network.** A local
test proves the code; only an external probe proves the deployed edge.

## 4. Panel

Open `/admin/computer-ops` as the owner. Expected with no device:

- feature state `UNPAIRED`, connector `OFFLINE`, no fabricated readiness
- desktop `DESKTOP_CONTROL_NOT_VERIFIED` + `IDENTITY REFUSED`, TCC `NOT GRANTED`
- browser `UNAVAILABLE — LOCAL CONNECTOR PLAYWRIGHT NOT INSTALLED`
- voice `VOICE_ENTRY_UNAVAILABLE`
- containment `macOS Seatbelt + per-mission APFS volume` / `NOT A HYPERVISOR BOUNDARY`

If any of these render READY, stop: the panel is inferring rather than reporting.

## 5. Optional — enroll a staging device

Only if step 0 approved it, and only on a machine the operator controls:

```sh
# operator, in the panel: Devices -> Enroll a device  (pairing code, 10 min)
python3 ops/computer-ops/connector/kai_connector.py enroll \
    --pairing-code <CODE> --base-url https://<staging-host>
# COMPARE the fingerprint the connector prints with the one the panel shows.
# If they differ, do NOT confirm.
python3 ops/computer-ops/connector/kai_connector.py run --once
```

Grant `computer.workspace.read` only. Do not grant desktop, browser, workspace-write or
runtime-control scopes in staging.

## 6. Health, readiness and logs

- `/health` must stay `ok`; a `degraded` status names the failing subsystem and reason.
- A broken optional subsystem must not take down unrelated routes — proven locally by
  the 25/25 capability-route suite, which includes the missing-module case.
- **Log redaction:** the device signature, pairing code and Keychain material must never
  appear. Evidence payloads pass through `scan_for_injection` and are stored with the
  findings attached rather than the raw content being trusted.

## 7. Rollback

Feature-flag disable is the primary control and needs no deploy:

```
KAI_COMPUTER_OPS_ENABLED=false
```

Then follow `docs/computer-ops/50-ROLLBACK.md` in order: preserve a tag, disable flags,
stop the connector, revoke the device credential, `git revert` merged commits, and only
then consider the database. Never `git reset --hard`.

## 8. Explicitly out of scope for staging

- Production deployment.
- TCC grants of any kind.
- Loading the launchd agent / persistent startup.
- Enabling `KAI_CAPABILITY_EXECUTION_ENABLED`.
- Desktop control, which is unreachable while the helper is unsigned.
