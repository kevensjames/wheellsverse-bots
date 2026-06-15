# SUPREMA Workspace — Session Handoff

**Status as of 2026-06-15:** Workspace autorepair system live in production
at `app.wheellsverse.com/admin → SUPREMA tab`, ~30 atomic commits shipped
across the wheellsverse-bots repo, 14-pattern catalog scanning 6 SUPREMA
projects daily at 06:00 local.

## What this document is for

If you start a new session and want to know "what's the state of SUPREMA,
what's working, what needs my attention" — read this. It captures the
ship list, the architecture, the open items, and the future roadmap.

---

## 1. What's running in production

### Live URL

`https://app.wheellsverse.com/admin → 🛡️ SUPREMA tab` (violet, right under
KAI in the sidebar). Reads `data/suprema-latest.json` from the deployed
repo and renders findings with filters, drill-down, per-finding Fix
button, and Suppress (✕ Hide) action.

### Daily cron

`com.suprema.autorepair` launchd job runs at 06:00 local on the Mac mini.
Pipeline:

1. `suprema-autorepair fix --commit --notify` — scans all 6 projects,
   auto-fixes patterns where safety=auto-safe, commits per-project with
   `chore(autorepair):` prefix
2. `state_sync.py` — copies `state/last-run.json` into
   `wheellsverse-bots/data/suprema-latest.json`, commits with
   `chore(suprema): state sync — N findings`, pushes to **both** github
   and origin remotes
3. Railway redeploys from the GitHub push (when Actions is enabled)

### Pre-commit hooks

All 6 SUPREMA project repos (narai, wheellsverse-bots, nexora, sol, toodle,
kdp-autopilot) have `.git/hooks/pre-commit` installed. Blocks commits
that reintroduce auto-safe pattern bugs in staged files. Bypass with
`git commit --no-verify` or env var `SUPREMA_PRECOMMIT_DISABLE=1`.

### Telegram notifications

Daily summary posted to operator's Telegram via the same
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` env vars the rest of the workspace
uses. Falls back to `wheellsverse-bots/.env` if env unset.

---

## 2. The 14-pattern catalog

| Pattern | Safety | First-run impact |
|---|---|---|
| `missing_pwa_manifest` | auto-safe | Killed 6 console errors per `/admin` page load |
| `missing_service_worker` | auto-safe | Restored PWA install enhancement; killed `/sw.js` 404 |
| `missing_favicon` | auto-safe | Clean console + visible tab icon |
| `malformed_api_helper_call` | auto-safe | **24 silent UI bugs fixed in `frontend/sol/admin.html` + `app.html`** (single biggest win of the session) |
| `committed_runtime_state` | auto-safe | Caught operator's accidental `git add .` that committed Playwright session cookies; untracked + .gitignored 980 lines |
| `stale_git_sha_health` | review | Caught the 30-day stale `git_sha` env var override |
| `dep_resolution_blocker` | review | Caught the litellm 1.83 vs openai 1.x conflict blocking builds |
| `frontend_backend_diff` | review | Surfaced 84 missing handlers; led to 13 routers mounted + 5 endpoint aliases added this session |
| `hardcoded_localhost` | review | Found 4 deployed nexora pages calling `http://localhost:5050` (since fixed) |
| `fastapi_deprecated_event_handler` | review | 5 `@app.on_event("startup")` usages — DeprecationWarnings, low priority |
| `deploy_stale` | blocked | Info-only |
| `sync_io_in_async_handler` | review | **AST-based — found 2 real prod bugs in `core/api.py:895` + `core/toodle_dispatcher.py:201`; both fixed** |
| `anthropic_credit_low` | review | Probes Anthropic API daily; surfaces credit-exhausted state |
| `deploy_freshness_diff` | review | Diffs local main HEAD vs prod `/api/health` git_sha; flags unshipped commits |

### Safety tiers

- **auto-safe (5)**: engine applies fixer, commits per-project, no human approval
- **review (8)**: engine reports, never modifies. Operator triages via panel
- **blocked (1)**: informational only — fixers never offered

---

## 3. The architecture

```
/Volumes/Wheellsverse/                    ← canonical workspace
├── suprema/                              ← canonical autorepair package
│   └── autorepair/
│       ├── engine.py                     ← scan/fix orchestration, CATALOG
│       ├── cli.py                        ← scan / fix / status / install / install-hooks
│       ├── auto_commit.py                ← per-project atomic commits
│       ├── notify.py                     ← Telegram + file log
│       ├── installer.py                  ← launchd plist installer
│       ├── precommit.py                  ← pre-commit hook installer
│       ├── state_sync.py                 ← cron → repo → prod state sync
│       ├── suppressions.py               ← operator "Won't fix" mechanism
│       ├── triage.py                     ← LLM triage via Anthropic
│       ├── safety/
│       │   ├── smoke_test.py             ← pre-commit build verification
│       │   └── kill_switch.py            ← env-var disables
│       ├── scanners/  (14 modules)       ← one per catalog pattern
│       ├── fixers/    (5 auto-safe)      ← apply(project, finding) → FixResult
│       ├── ci/suprema-scan.yml           ← GitHub Actions template
│       └── SUPREMA_HANDOFF.md            ← this file
│
├── wheellsverse-bots/                    ← live FastAPI server, Railway-deployed
│   ├── suprema/                          ← vendored copy of /Volumes/Wheellsverse/suprema
│   ├── core/api.py                       ← FastAPI app + /api/suprema/* endpoints
│   ├── dashboard/index.html              ← SUPREMA tab + panel UI
│   └── data/
│       ├── suprema-latest.json           ← state synced by daily cron
│       └── suprema-suppressions.json     ← operator-dismissed findings
│
├── narai / nexora / sol / toodle / kdp-autopilot/   ← other SUPREMA projects
│   └── .git/hooks/pre-commit             ← installed in all 6
```

### Vendoring policy

The canonical suprema/ package at `/Volumes/Wheellsverse/suprema/` is the
source of truth. The vendored copy at `wheellsverse-bots/suprema/` ships
with the Docker image so the prod FastAPI process can `import suprema.
autorepair.*` for the panel's `/api/suprema/scan` and `/fix` endpoints.

When you change a module in canonical, mirror it to vendored:

```bash
cp /Volumes/Wheellsverse/suprema/autorepair/scanners/foo.py \
   /Volumes/Wheellsverse/wheellsverse-bots/suprema/autorepair/scanners/foo.py
```

Future work: replace manual `cp` with a `make vendor` target or a git hook.

---

## 4. /api/suprema/* endpoint surface

All require `X-API-Key` auth (`authH()` from dashboard JS handles this).

| Endpoint | Purpose |
|---|---|
| `GET /api/suprema/status` | Read last-run.json state for the panel |
| `POST /api/suprema/scan` | Trigger a fresh scan (shells to CLI, 180s timeout) |
| `POST /api/suprema/fix` | Apply one auto-safe fix for a specific finding |
| `POST /api/suprema/suppress` | Mark a finding "Won't fix" (operator decision) |
| `POST /api/suprema/unsuppress` | Reverse a suppression |
| `GET /api/suprema/suppressions` | List all current suppressions |

---

## 5. Current state of findings

After 30+ commits this session, the panel sits at:

```
14 patterns, ~22 findings (after cleaning, may be ~14-18 after suppressions land)

By pattern:
  frontend_backend_diff           ~15  (long tail of v1→v2 migrations, dead UI)
  fastapi_deprecated_event_handler  5  (deferred — lifespan refactor risky)
  committed_runtime_state           3  (the 3 narai DBs — operator decision)
  anthropic_credit_low              1  (HIGH — top up credit)

By project:
  wheellsverse-bots               100%   (other 5 SUPREMA projects scan clean)
```

---

## 6. Open items needing operator action

These can't be auto-fixed — they need a human decision or external action.

| Action | Why | Where |
|---|---|---|
| **Top up Anthropic credit** | Trend-scan + LLM triage both blocked | console.anthropic.com/settings/billing |
| **Re-enable GitHub Actions** | Auto-deploy chain is broken; manual `railway up` required each deploy | github.com/settings → Billing & plans |
| **Decide on the 3 tracked DBs** | `narai/data/chroma/chroma.sqlite3`, `narai/data/narai.db`, `narai/marketing/autopilot.db` — operator must decide if these are seed data (keep) or runtime state (untrack) | local repo |
| **Set `OPERATOR_EMAIL` env var** | `GET /api/stripe/portal` needs an email to create a Stripe Customer Portal session | Railway dashboard env vars |
| **Rotate Stan + IG credentials** | They briefly hit git history in commit `de0e37e` before it was scrubbed via `git gc --aggressive` | Stan.store + Instagram login flows |
| **Triage the ~15 remaining `frontend_backend_diff`** | Each needs "implement OR delete frontend" decision. Many are stale or v1→v2 migrations | SUPREMA panel + ✕ Hide button |

---

## 7. What was NOT done this session and why

| Item | Why deferred |
|---|---|
| Lifespan migration for the 5 `@app.on_event("startup")` handlers | Would require restructuring `app = FastAPI(...)` instantiation in the 14k-line core/api.py — high risk for cosmetic warning elimination |
| Sentry / Datadog integration | Out of scope; the panel + Telegram already provide observability for SUPREMA's own scope |
| Pip-installable package distribution | The vendoring pattern works for now; pip distribution becomes valuable if a second workspace wants to use SUPREMA |
| VS Code extension | Future work — would surface findings inline in the editor |
| Web dashboard at localhost:3030 | The `/admin SUPREMA tab` already serves this purpose |

---

## 8. Future ideas (sorted by leverage)

**High leverage, low effort:**

- **`docker_image_bloat` scanner** — detect the ~8GB of nvidia/CUDA in requirements.txt that's never used
- **`unused_dependency` scanner** — pip-deptree / static analysis to find dead deps
- **`broken_internal_link` scanner** — find dashboard nav-items pointing to 404'd pages
- **Generic frontend stub-handler generator** — auto-fix that creates a 501-returning route for every `frontend_backend_diff` finding (silences UI 404s)

**High leverage, medium effort:**

- **AST upgrade to `hardcoded_localhost`** — properly detect dev-conditional gating instead of regex line-window heuristic
- **Confidence scoring** — each finding gets 0-100 confidence; operator filters by threshold
- **Time-series of "open findings"** — graph from history.jsonl to show whether you're trending up or down
- **Auto-create GitHub issues** for review-tier findings (with `gh issue create`)

**Strategic:**

- **Productize SUPREMA as a pip package** — `pip install suprema-autorepair` + per-project config in `.suprema/`
- **Pattern marketplace** — community-contributed scanners
- **VS Code / Cursor extension** — inline lint markers for findings + quick-fix

---

## 9. Key debug commands

```sh
# Manual scan from local
cd /Volumes/Wheellsverse
PYTHONPATH=. python3 -m suprema.autorepair.cli scan
PYTHONPATH=. python3 -m suprema.autorepair.cli status

# Force re-seed of prod panel state (after a code change)
PYTHONPATH=. python3 -c "
from suprema.autorepair import engine, state_sync
engine.run_cycle(do_fix=False)
state_sync.sync_to_wheellsverse_bots(engine.LAST_RUN, push=False)
"

# Disable any layer with one env var
SUPREMA_DISABLE=1 git commit ...            # bypass all autorepair
SUPREMA_SKIP=hardcoded_localhost ...        # skip specific patterns
SUPREMA_DRY_RUN=1 ...                       # force dry-run
SUPREMA_SKIP_SMOKE_TEST=1 ...               # skip post-fix smoke gating
SUPREMA_PRECOMMIT_DISABLE=1 git commit ...  # skip pre-commit hook

# Deploy manually (when GitHub Actions is disabled)
cd /Volumes/Wheellsverse/wheellsverse-bots
railway up --ci          # builds + deploys via Railway CLI
```

---

## 10. Commit log highlights (chronological)

This session's commits — most are atomic `chore(autorepair):` or
`fix(...)` so a future session can `git log --grep "SUPREMA"` to find
the full story.

Selected milestones:
- `fee4176` Phase A1: malformed `api()` call repair pattern → 24 SOL UI bugs fixed
- `c7d4a2a` Phase A2: `/sw.js` route + service worker shipped
- `8df9d11` Phase A3: honest `_GIT_SHA` via env + build_time + deploy_id
- `dfe5a12` first autorepair atomic commit (24 fixes in 2 files)
- `68d00d8` first `committed_runtime_state` fix (980 lines of secrets purged)
- `00f97b9` security: post-incident `.gitignore` runtime-state patterns
- `b1d47b12` first prod deploy with the SUPREMA panel live
- (current HEAD) — 14 patterns, suppress mechanism, 8 endpoint aliases

---

## 11. The handoff bottom line

The system **works** and is **load-bearing**. The daily cron has run
successfully, state syncs to prod, the panel is operator-usable.

What remains is **operator decisions** (DB tracking, Anthropic top-up,
GitHub Actions re-enable) and **catalog expansion** (more patterns = more
bugs caught early). Neither blocks current functionality.

If you're picking this up cold, start by:

1. Opening `app.wheellsverse.com/admin → SUPREMA tab` to see the current
   findings
2. Reading the last 7 days of `git log --grep "Generated-By: suprema"`
   to see what the cron has been doing autonomously
3. Glancing at `suprema/autorepair/state/history.jsonl` for the trend

If something looks weird, **check the kill switches** before suspecting a
bug — `SUPREMA_DISABLE=1` is a global off switch that survives across
machines.
