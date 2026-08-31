# KAI Holding Operator — Autonomy Runbook

Operational runbook for the persistent, read-only holding operator. **Money mode is MOCK; no financial
writes.** No secret values appear in this doc.

Loop: **watch → propose → owner approve → dispatch → isolated worker executes → evidence → UI updates → Telegram**.
Every consequential step is human-gated; the worker plane is read-only and isolated.

---

## 1. Persistent worker runner (launchd, on the Mac/colima host)

The runner is a launchd LaunchAgent that claims approved worker jobs and runs them in isolated
containers. It reads the runtime secret from the **macOS Keychain** (never plaintext on disk).

**Prerequisite:** colima running — `colima status` (start: `colima start --cpu 2 --memory 4`).
Worker images present — `docker images | grep wv-` (build under `ops/github-worker`, `ops/browser-worker` if missing).

**Install / start** (from the repo root):
```
ops/holding-worker-runner/install.sh install
```
Prompts once for `SESSION_SIGNING_SECRET` (copy from Railway → kai-prod → Variables; input is hidden,
stored in Keychain only), then loads the agent (`KeepAlive` auto-restarts it; `RunAtLoad` starts at login).

**Health / status:**  `ops/holding-worker-runner/install.sh status`  (also visible in the UI → Workers panel)
**Logs:**            `ops/holding-worker-runner/install.sh logs`   (`.omc/logs/kai-holding-worker.{out,err}.log`)
**Restart:**         `ops/holding-worker-runner/install.sh restart`
**Uninstall:**       `ops/holding-worker-runner/install.sh uninstall`  (Keychain secret left intact)

**Manual one-shot** (no launchd, injects env via Railway):
```
BASE_URL=https://kai-prod-production.up.railway.app WORKER_RUNNER_ONESHOT=1 \
  railway run --service kai-prod python3 ops/holding-worker-runner/run.py
```

## 2. Upgrade / rollback the runner
- **Upgrade:** `git pull` (or check out the new SHA) in the repo, then `install.sh restart`.
- **Rollback:** check out the previous SHA, `install.sh restart`. The plist path is stable; only the code changes.

## 3. Colima recovery
If colima is down, jobs stay `queued`/`running` and their leases expire → the server reclaims them
(bounded by max_attempts). Recover: `colima start`, then `install.sh restart`. No duplicate execution —
the lease + `claimed_by` guards prevent two workers running one job.

## 4. Job recovery (crash / stuck)
- A crashed worker's job lease expires and is **reclaimed** to `queued` automatically on the next claim
  (or `POST /admin/holding/worker-jobs/reclaim`). After `max_attempts` it becomes `expired` (no infinite retry).
- Inspect: UI → Workers/Jobs, or `GET /admin/holding/worker-jobs`. Every job carries a `correlation_id`
  linking proposal → approval → dispatch → claim → execution → evidence → completion.

## 5. Telegram (alerts + daily briefing) — operator-only, Railway secrets
The real `TELEGRAM_BOT_TOKEN` must exist **only** in Railway service variables — never in git/docs/logs/Claude.
Copy it (and `TELEGRAM_CHAT_ID`) from **kai-prod-monitor → Variables** onto **kai-briefing-cron** and
**kai-watch-cron** (dashboard copy, no typing). The UI shows `telegram: CONNECTED / DEGRADED / UNAVAILABLE`
(presence only, never the value).

## 6. Cron schedules (Railway dashboard)
- **kai-watch-cron** → Cron Schedule `*/15 * * * *` (every 15 min), Restart Policy = Never.
- **kai-briefing-cron** → Cron Schedule `0 11 * * *`. **Timezone:** Railway cron runs in **UTC**;
  `0 11` = 11:00 UTC = 07:00 America/New_York (EDT). For a different local time, adjust the hour
  (`KAI_HOLDING_BRIEFING_UTC_HOUR` governs the in-process default too).

## 7. Flags (all default OFF; set on the relevant service)
`KAI_HOLDING_ENABLED` (endpoints), `KAI_HOLDING_BRIEFING_ENABLED` (briefing cron),
`KAI_HOLDING_WATCH_ENABLED` (watch cron), `KAI_HOLDING_DELIVERY_ENABLED` (Telegram send). Instant
rollback of the whole feature: `KAI_HOLDING_ENABLED=false` on kai-prod.

## 8. Money mode
`MONEY_MODE=MOCK` throughout. KAI never spends, transfers, pays out, refunds, deploys to prod, deletes
data, or exports secrets. Worker actions are read-only + typed-allowlisted. This is by design, not a gap.

## 9. Observability
Search any of `proposal_id · job_id · worker_id · correlation_id · mission_id` to reconstruct the full
chain. Decisions + executions + completions are written to the AuditLog.
