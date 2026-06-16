# SUPREMA autorepair

Workspace-wide auto-healing system. Detects known issue patterns across the
six SUPREMA projects and applies safe fixes automatically. Risky findings
are recorded for human review.

**Version 0.3** — adds smoke-test gating, LLM-assisted triage, pre-commit
hooks, GitHub Actions integration, and kill switches.

## Why this exists

This system encodes the diagnostic playbook I had to run by hand every
time something broke in the workspace — endpoint 404s, malformed `api()`
helper calls, stale `git_sha` in `/api/health`, dep-conflict-blocked
builds, deploy chain stalls. Each pattern here corresponds to a real bug
that cost real time. The next time one of these classes shows up, the
nightly run catches it and either fixes it or pages a human.

## What's in scope

Six SUPREMA projects:

| Project | Stack | Live URL |
| --- | --- | --- |
| `narai` | spec-kit (constitution only) | — |
| `wheellsverse-bots` | FastAPI + huge inline HTML dashboard | `app.wheellsverse.com` |
| `nexora` | spec-kit (constitution only) | — |
| `sol` | spec-kit (constitution only) | — |
| `toodle` | spec-kit (constitution only) | — |
| `kdp-autopilot` | spec-kit (constitution only) | — |

Only `wheellsverse-bots` has a deployed surface for now, so scanners that
need a live URL only fire there. As the other projects get implemented,
their endpoints get added to `LIVE_URLS` in `engine.py` and the same
scanners apply.

## Patterns catalogued

The catalog is `CATALOG` in `engine.py`. Each entry: scanner module +
optional fixer module + safety tier.

| Pattern | Safety | Real-world origin |
| --- | --- | --- |
| `missing_pwa_manifest` | auto-safe | 6 console errors per page load for 30 days before this pattern existed |
| `missing_service_worker` | auto-safe | `/sw.js` 404 silently swallowed by `.catch(() => {})` |
| `missing_favicon` | auto-safe | Browser auto-requests `/favicon.ico`; 404 clutters logs |
| `malformed_api_helper_call` | auto-safe | `api(url, {method:'POST'})` silently fails because the helper expects positional `method` arg |
| `stale_git_sha_health` | review | `/api/health` reported the same `git_sha` for 30 days — hand-set env var override |
| `dep_resolution_blocker` | review | `pip` ResolutionImpossible (litellm vs openai vs httpx) bricked the build chain |
| `frontend_backend_diff` | review | Frontend calls endpoints with no matching backend route — now also counts mounted APIRouter prefixes, `add_api_route`, and bulk-path loops |
| `deploy_stale` | blocked | Production uptime > 30 days while commits keep landing — chain is broken |
| `hardcoded_localhost` | review | `fetch('http://localhost:8000/health')` worked in dev, silently broke for every real user in production |
| `fastapi_deprecated_event_handler` | review | Build log warnings: "FastAPI object has no attribute add_event_handler" — three startup hooks silently un-registered |
| `committed_runtime_state` | auto-safe | `git add .` accidentally committed Playwright session cookies + 911 lines of logs. Auto-fix untracks + adds .gitignore; refuses to touch DBs |

### Safety tiers

- **`auto-safe`** — engine applies the fixer automatically and creates a `chore(autorepair):` commit. Idempotent; safe to run on a healthy project.
- **`review`** — engine records the finding but never modifies files. Surfaces in Telegram / file log; human triages.
- **`blocked`** — informational only. No fixer ever runs (e.g. anything that would touch production env or run destructive ops).

## Daily install

One-shot install of the launchd job (runs every day at 06:00 local):

```bash
cd /Volumes/Wheellsverse
PYTHONPATH=. python3 -m suprema.autorepair.cli install
```

This writes `~/Library/LaunchAgents/com.suprema.autorepair.plist`,
loads it into launchd, and creates `state/` + `logs/` under the
autorepair directory. Logs:

- `logs/autorepair-YYYYMMDD.log` — engine + scanner + fixer trace
- `logs/notify-YYYYMMDD.log` — what was sent to Telegram (and whether it was actually sent)
- `logs/launchd.out` + `logs/launchd.err` — launchd-level stdio

Unload at any time:

```bash
launchctl unload ~/Library/LaunchAgents/com.suprema.autorepair.plist
```

## Manual usage

```bash
cd /Volumes/Wheellsverse
PYTHONPATH=. python3 -m suprema.autorepair.cli scan                # all projects
PYTHONPATH=. python3 -m suprema.autorepair.cli scan --json         # machine-readable
PYTHONPATH=. python3 -m suprema.autorepair.cli --project wheellsverse-bots scan
PYTHONPATH=. python3 -m suprema.autorepair.cli fix --dry-run       # show what would change
PYTHONPATH=. python3 -m suprema.autorepair.cli fix --commit        # write + atomic per-project commits
PYTHONPATH=. python3 -m suprema.autorepair.cli fix --commit --notify  # also send Telegram summary
PYTHONPATH=. python3 -m suprema.autorepair.cli status              # last-run summary
```

`--project` is a top-level argument (must come BEFORE the subcommand) and is repeatable.

## Telegram notifications

The notifier reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from the
process env, falling back to `wheellsverse-bots/.env` if they aren't
already set. If neither is configured, the summary is still written to
`logs/notify-YYYYMMDD.log` with a `[telegram NOT sent]` prefix so the
forensic trail is preserved.

## Per-project commits

When `--commit` is passed, each successful fix is batched per project
into a single `chore(autorepair):` commit. Example:

```text
commit dfe5a12...
Author: ...
Date:   2026-06-15 03:02:43 -0400

    chore(autorepair): malformed_api_helper_call

    Applied automatically by SUPREMA autorepair.
    - malformed_api_helper_call: rewrote 18 malformed api() call(s) in frontend/sol/admin.html
    - malformed_api_helper_call: rewrote 6 malformed api() call(s) in frontend/sol/app.html

    Generated-By: suprema-autorepair
```

The trailer `Generated-By: suprema-autorepair` makes these easy to filter
in `git log` (e.g. `git log --grep "Generated-By: suprema-autorepair"`).

## Adding a new pattern

1. Add a scanner under `scanners/your_pattern.py`. Export
   `scan(project_path: Path, live_url: str | None = None) -> list[dict|Finding]`.
   A dict result should have `severity`, `location`, `evidence`, optional `fix_payload`.

2. (Optional) Add a fixer under `fixers/your_pattern.py`. Export
   `apply(project_path: Path, finding: Finding) -> FixResult|dict`.

3. Add an entry to `CATALOG` in `engine.py`:

   ```python
   "your_pattern": {
       "scanner": "scanners.your_pattern",
       "fixer":   "fixers.your_pattern",  # or None for review-only
       "safety":  "auto-safe",            # or "review" / "blocked"
       "title":   "Human-readable description",
   },
   ```

4. Syntax-check + run a scan once to confirm it loads:

   ```bash
   PYTHONPATH=. python3 -m suprema.autorepair.cli scan --json | jq '.[] | select(.pattern == "your_pattern")'
   ```

## State + history

- `state/last-run.json` — most recent cycle's full summary
- `state/history.jsonl` — one JSON line per cycle; useful for trending
  ("git_sha hasn't moved in N days")

## v0.3 features (new since v0.1)

### Smoke-test gating

Before any fixer's changes get committed, the engine runs a project-specific
smoke test. If it fails, the working tree is restored from a pre-fix `git
stash create` snapshot and the fix is recorded as failed.

Default smoke test (auto-detected per project):

```python
python -c "from core.api import app"   # FastAPI projects
```

Override per project with `<project>/.suprema/smoketest.sh` — runs with the
project as CWD and must exit 0 to allow the fix.

Disable globally: `SUPREMA_SKIP_SMOKE_TEST=1`.

### LLM-assisted triage

For review-tier findings (e.g. `frontend_backend_diff`, `hardcoded_localhost`),
the engine can call the Anthropic API to vote real-bug / false-positive /
uncertain on each one. Drastically cuts manual triage work.

```bash
PYTHONPATH=. python3 -m suprema.autorepair.cli fix --llm-triage --commit
```

The triage module looks for `ANTHROPIC_API_KEY` in this order:

1. Process env
2. `wheellsverse-bots/.env`
3. `wheellsverse_bots.OLD_PRE_MIGRATION/.env` (legacy)
4. `narai/.env`
5. `~/.anthropic/api_key`

Cost control:

| Env var | Default | Purpose |
| --- | --- | --- |
| `SUPREMA_TRIAGE_MODEL` | `claude-haiku-4-5-20251001` | Cheap + fast for triage |
| `SUPREMA_TRIAGE_BUDGET` | `50000` | Hard cap on total tokens per cycle |

When credit / quota is exhausted, triage gracefully degrades to "uncertain"
findings — no destructive fixes are ever applied to ambiguous results.

### Pre-commit hook

Drops a `.git/hooks/pre-commit` script in each SUPREMA project. Blocks
commits that reintroduce known auto-safe pattern bugs in staged files.

```bash
PYTHONPATH=. python3 -m suprema.autorepair.cli install-hooks
```

Output when a commit is blocked:

```text
⛔ SUPREMA autorepair blocked this commit — 1 auto-safe finding(s) in staged files:
   • [malformed_api_helper_call]  dashboard/index.html:18605
       ↳ api("/test/bad", {method:"POST", body:JSON.stringify({x:1})})

To auto-fix:
   cd /Volumes/Wheellsverse
   PYTHONPATH=. /opt/homebrew/bin/python3 -m suprema.autorepair.cli --project wheellsverse-bots fix --commit

To bypass this hook (emergency only):
   git commit --no-verify
```

Disable per-project: `SUPREMA_PRECOMMIT_DISABLE=1 git commit ...`

### GitHub Actions integration

Copy `ci/suprema-scan.yml` into any SUPREMA-managed repo as
`.github/workflows/suprema-scan.yml`. The workflow:

- Runs on every PR + push to main
- Posts a comment on the PR summarizing findings
- Fails the PR check if any auto-safe finding lands on a changed file

Requires GitHub repo vars:

- `SUPREMA_PROJECT_NAME` (defaults to repo name)
- `SUPREMA_REPO` (defaults to `kevensjames/suprema-workspace`)

### Kill switches (OMC-style)

Environment-variable disables matching the existing OMC convention:

| Variable | Effect |
| --- | --- |
| `SUPREMA_DISABLE=1` | Disable autorepair entirely (scan returns empty) |
| `SUPREMA_SKIP=pattern1,pattern2` | Skip specific scanner patterns |
| `SUPREMA_SKIP_PROJECTS=narai,nexora` | Skip specific projects |
| `SUPREMA_DRY_RUN=1` | Force dry-run regardless of CLI flags |
| `SUPREMA_NO_COMMIT=1` | Apply fixes but never auto-commit |
| `SUPREMA_NO_NOTIFY=1` | Apply fixes but never send notifications |
| `SUPREMA_SKIP_SMOKE_TEST=1` | Skip post-fix smoke-test gating |
| `SUPREMA_PRECOMMIT_DISABLE=1` | Skip the pre-commit hook |
| `SUPREMA_STDOUT=0` | Suppress stdout log handler (useful in CI) |
| `SUPREMA_PYTHON=/path` | Override Python binary used in installed hooks |

### Per-project config

Each project may have `<project>/.suprema/config.yml` (or `.json`):

```yaml
enabled: true                        # default: true
skip_patterns:
  - missing_pwa_manifest             # don't scan this pattern in this project
safety_override:
  malformed_api_helper_call: review  # demote auto-safe → review for this project
```

### Per-project smoke test override

`<project>/.suprema/smoketest.sh`:

```bash
#!/usr/bin/env bash
# Custom smoke test for this project. Must exit 0 to allow a fix to be committed.
python -c "from myapp import app; print('ok')"
```

## Known limits

- Frontend/backend diff has a high false-positive rate on dynamic URLs
  built with template literals (`fetch(\`/api/foo/${id}\`)`). Kept at
  `severity: low` and review-only for that reason.
- Some projects have multiple FastAPI app objects (e.g. v1 + v2 routers
  in different files). The `_fastapi_route.py` helper only looks at
  `core/api.py` / `app/main.py` / `backend/main.py`. Add your project's
  layout to `find_main_api()` if it differs.
- The fixer regex for `malformed_api_helper_call` is case-sensitive on
  lowercase `api(` only. If your project has both `api()` and `Api()`
  helpers with different signatures, the capital-A variant is left
  untouched (which is the correct conservative behavior).
