# 0006 — Mac mini daemonization decisions

Date: 2026-05-19
Stage: 5
Status: locked
Phase: A — capstone (artifacts shipped; reboot test is operator-side)

## Decisions
1. **launchd LaunchAgent** (`~/Library/LaunchAgents/`), not LaunchDaemon. Runs as the user, can read `.env`, has access to the user's venv.
2. **Wrapper script (`deploy/start_nai.sh`) sources `.env` then exec's uvicorn.** Secrets stay out of the plist (which is world-readable under `~/Library/LaunchAgents/`).
3. **Single worker (`--workers 1`).** Phase A is single-user; more workers = more API spend with zero throughput gain.
4. **Bind `127.0.0.1:8001` only.** No public exposure. Cloudflare Tunnel is Phase B.
5. **`KeepAlive` is a dict, not a bare boolean.** `SuccessfulExit=false` lets `launchctl stop` actually stop the daemon; `Crashed=true` restarts on nonzero exit. Without this, every `stop` triggers an immediate restart — maintenance impossible.
6. **`ThrottleInterval = 10`** prevents tight restart loops when uvicorn fails repeatedly (bad `.env`, port collision, broken import).
7. **`ProcessType = Interactive`** so macOS power-management treats NAI like a foreground app and keeps the API responsive.
8. **Ollama: custom plist on this Mac mini** because `which ollama` is `/usr/local/bin/ollama` (manual install), not the Homebrew default. On a Homebrew install, `brew services start ollama` is preferred and ships its own plist.
9. **newsyslog** handles log rotation — 10 MB cap, keep 5 rotated copies, gzip them. Built into macOS, zero extra deps. Health log is smaller (2 MB cap, keep 3).
10. **Health check via cron** every 5 min, log-only. Phase B adds alerting (Pushover / Slack / email).
11. **Mac mini sleep disabled while on power** via `pmset -c sleep 0`. Display sleep is fine.
12. **Postgres = Supabase managed.** Nothing local to daemonize.
13. **Redis skipped.** Not used by any current code path. Stage 1's spend tracker and Stage 2's router don't need it.
14. **Phase A tag (`phase-a-complete`) deferred to the operator-side reboot verification.** Tagging code that hasn't survived a reboot is premature.

## TCC + external-volume reality
The repo lives on `/Volumes/Wheellsverse/`. macOS may block LaunchAgents whose executable path is on an external volume — the operator's own memory `feedback_macos_tcc_volumes.md` warned about this exact situation when working with `~/Applications/NarAI Supreme.app`.

Three resolution paths (see `deploy/README.md` for the runbook details):

1. **Grant External Volumes access** in System Settings → Privacy & Security → Files and Folders. Keeps the LaunchAgent pattern intact.
2. **Move the wrapper to `~/bin/start_nai.sh`** and point the plist's `ProgramArguments` there. The wrapper still operates on the `/Volumes/` repo. Sidesteps TCC entirely.
3. **Pivot to a Login Item .app bundle**, matching the existing NarAI Supreme v1 pattern. More overhead, but most TCC-friendly.

The committed plists assume option 1 or 2. The decision of which to use is operator-time.

## Reversible?
- Move to LaunchDaemon for pre-login boot: yes, one config swap (gets you root, which you don't want).
- Swap brew-managed Ollama for the custom plist (or vice versa): yes, both are committed.
- Add alerting to `health_check.sh`: yes — one `curl` to Pushover/Slack at the bottom.
- More workers: trivial `--workers 2` in `start_nai.sh`. Watch API spend.
- Switch from /Volumes/ to a home-directory location: copy the repo, adjust two absolute paths in the plists and the runbook.

## Artifacts shipped (Stage 5)
- `deploy/start_nai.sh` — wrapper (sources `.env`, validates secrets, exec's uvicorn).
- `deploy/launchd/com.wheellsverse.nai.plist` — NAI LaunchAgent.
- `deploy/launchd/com.wheellsverse.ollama.plist` — Ollama LaunchAgent (manual-install path `/usr/local/bin/ollama`).
- `deploy/health_check.sh` — cron-driven log-only check.
- `deploy/status.sh` — one-shot Phase A snapshot.
- `deploy/newsyslog.wheellsverse.conf` — log rotation config (`sudo cp` to `/etc/newsyslog.d/`).
- `deploy/README.md` — full install runbook including the TCC mitigation section.

## Verification status
- [x] All six artifacts written. Shell scripts use `set -e`/`set -u` discipline. Plists use modern `KeepAlive` dict shape.
- [x] Paths match the actual Mac mini: `/Users/jhonwheeler/` (not `/Users/jhon/`), `/usr/local/bin/ollama` (not `/opt/homebrew/bin/ollama`), `/Volumes/Wheellsverse/wheellsverse_bots/` (not `…/admin`).
- [ ] **Manual pre-flight (uvicorn + browser sanity) — NOT RUN.** Depends on the carried-forward operator gap (`DATABASE_URL`, three API keys exported, JWT issuance via `/auth/login`).
- [ ] **`launchctl load -w` + endpoint curls — NOT RUN.** Same gap.
- [ ] **Reboot test — NOT RUN.** Operator only.
- [ ] **`phase-a-complete` git tag — NOT APPLIED.** Will be applied after the operator validates the reboot test.

## Out of scope for Stage 5 / Phase A
- Public exposure (Cloudflare Tunnel) — Phase B
- HTTPS — Phase B
- HttpOnly cookie auth replacing query-param JWT on `/nai/chat/stream` — Phase B
- Stripe / signups / multi-user — Phase B
- Real monitoring (Pushover, email, status page) — Phase B
- Backup / disaster recovery — Phase B
- Migration off Mac-mini SPOF (Fly.io / Railway / Hetzner) — Phase B

## Operator follow-ups
This stage closes the build side of Phase A. The remaining work is hands-on
ops on the Mac mini itself, in this order:

1. **Close the Stage 1–4 verification gap first.**
   - Export `DATABASE_URL` and `DIRECT_DATABASE_URL` (Supabase pooler/direct + password).
   - Export the three API keys.
   - Run `smoke_test_memory` → `smoke_test_router` → `smoke_test_tools` → boot uvicorn → `smoke_test_nai`.
   - Open `http://127.0.0.1:8001/nai-ui/`, paste JWT, send a few messages including the memory save/recall flow with **Use tools** on.

2. **Daemonize via `deploy/README.md`.** Pick the Ollama strategy (brew vs custom plist) and the TCC mitigation (access grant vs wrapper-relocation vs Login Item).

3. **Reboot.** Verify both endpoints survive. Run `./deploy/status.sh`.

4. **Tag `phase-a-complete`** once the reboot test is green:
   ```bash
   git tag phase-a-complete
   git push --tags
   ```

5. **Stop building Phase B prematurely.** Phase B's activation trigger is the first paying customer on KDP or Whop. Until then, let NAI run and use it personally — every chat sharpens what Phase B should actually optimize.
