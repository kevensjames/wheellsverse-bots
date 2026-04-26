# WheellsVerse — Autonomous Analysis & Fix Report

**Generated:** 2026-04-26 by Claude (autonomous mission while user was out)
**Scope:** /admin surface, all 145 bots, dashboards, Toodle, NarAI, Sol, Shopify integrations
**Approach:** Surgical fixes only — no refactors, no behavior changes beyond bug fixes

---

## Executive summary

| Category | Count |
|---|---|
| Endpoints probed | 54 |
| 200 OK | 37 |
| Auth-gated 401 (working as intended) | 8 |
| **404 (real bugs)** | **6** |
| **405 (method mismatch — needs check)** | **3** |
| Bots with Python syntax errors | 0 / 145 |
| Bots failing to load at runtime | 1 (`bug_hunter` — abstract class) |
| Total Railway log errors (last 1000 lines) | 1 distinct |
| **Surgical fixes applied & pushed** | **TBD (in progress)** |
| **Findings flagged for your decision** | **2** |

---

## ✅ FIXED (safe, surgical, pushed to prod)

*To be filled in as fixes ship.*

---

## 🚨 NEEDS YOUR DECISION (not auto-fixed)

### 1. `/marketing/*` endpoints are unauthenticated (write actions exposed)

**Where:** [narai/marketing/api.py](narai/marketing/api.py) — router included at [core/api.py:13216](core/api.py#L13216) without `dependencies=[]`.

**Why it's not under the `/api/*` middleware guard:** The router is mounted at root `/marketing/*`, not `/api/marketing/*`, so the `api_key_middleware` at [core/api.py:735](core/api.py#L735) doesn't apply to it.

**Exposed POST endpoints (anyone can hit these):**
- `POST /marketing/run` — triggers all pending marketing tasks in background → **paid Anthropic/OpenAI calls** can be triggered by anyone
- `POST /marketing/approve/{task_id}` — anyone can approve/unapprove tasks
- `POST /marketing/reload-schedule` — anyone can reload the schedule

**Exposed GET endpoints:**
- `GET /marketing/status` — leaks all marketing task data (lower risk, may be intentional)
- `GET /marketing/task/{id}` — leaks specific task content

**Why I didn't auto-fix:** I don't know if your Toodle UI polls `/marketing/status` without auth. Adding `dependencies=[Depends(verify_api_key)]` to the include_router would break the UI if it does. **Need to confirm Toodle UI's auth pattern before changing this.**

**Recommended fix when you're back:**
```python
# core/api.py:13216 — current
app.include_router(_marketing_router)
# Replace with: gate just the POST endpoints, OR rewrite router with per-route Depends
app.include_router(_marketing_router, dependencies=[Depends(verify_api_key)])
# Then move the router under /api/marketing for consistency.
```

**Quick mitigation if you want it now:** rate-limit `/marketing/*` to 10 req/min per IP via the existing rate_limit_middleware.

---

### 2. Railway → GitHub auto-deploy is broken

**Symptom:** Push to `main` on GitHub no longer triggers a Railway build. Last GitHub-driven deploy was `04a3bbc` at 02:30 today. Everything since (including the just-shipped `8214b21`) had to be deployed manually via `railway up`.

**Why I didn't auto-fix:** This is a Railway dashboard config issue (GitHub App connection, branch trigger settings) — not a code change.

**Manual fix steps:**
1. Open https://railway.com/project/5407586d-e648-4dd1-a442-ea0f805f2e0e
2. Service: `wheellsverse-v2` → Settings → Source
3. If "GitHub Repo" shows disconnected/red: click Reconnect, choose `kevensjames/wheellsverse-bots`, branch `main`
4. Verify "Auto-deploy on push" is ON
5. Test: push an empty commit (`git commit --allow-empty -m "trigger deploy"`) — Railway should pick it up within 30s

---

## 📊 Endpoint probe summary (54 routes tested)

### 200 OK — working
```
/, /api/health, /landing, /admin, /admin/hub, /admin/legacy, /admin/shopify,
/admin/toodle, /admin/second-brain-inbox, /sol, /sol/admin, /sol/app,
/dashboard, /chat, /login, /signup, /pricing, /nexora, /blog, /store,
/terms, /privacy, /disclaimer,
/api/overview, /api/factory/status, /api/qc/stats, /api/qc/results,
/api/factory/alltime, /api/narai/memory/stats, /api/narai/status,
/api/v2/narai/health, /api/inbox/digest, /api/inbox/search,
/api/narai-autopilot/status, /api/narai-autopilot/queue,
/marketing/status, /api/public/crypto
```

### 401 Unauthorized — auth gates working correctly
```
/api/bots, /api/categories, /api/jobs,
/api/narai/profile, /api/narai/memory, /api/narai/conversations,
/api/inbox/items, /api/narai/shopify/merchants
```

### 404 Not Found — real bugs
| URL | Status | Root cause | Fix complexity |
|---|---|---|---|
| `/sitemap.xml` | 404 | File exists at `frontend/sitemap.xml` but no route serves it | Trivial — add 2 routes |
| `/robots.txt` | 404 | File exists at `frontend/robots.txt` but no route serves it | Trivial |
| `/api/v2/narai/voice/ws` | 404 | Voice router exists in `narai/api/main.py` but never `include_router`'d in `core/api.py` | Trivial — add 2 lines |
| `/api/inbox` | 404 | No handler for the bare prefix (only sub-paths) | Cosmetic — Toodle UI doesn't call this |
| `/api/narai/shopify/billing` | 404 | Handler is at `/api/narai/shopify/billing/*` (sub-paths). Bare path 404 is correct | None needed |
| `/api/nx/status` | 404 | NEXORA status endpoint not implemented | Needs design — what should it return? |

### 405 Method Not Allowed — needs verification
| URL | Status | Likely cause |
|---|---|---|
| `/api/lead` | 405 | Probably POST-only — getting a 405 on GET is correct |
| `/api/nx/register` | 405 | POST-only |
| `/api/public/chat` | 405 | POST-only |

These are likely correct. No fix needed.

### 307 Redirect
- `/narai` → 307 (redirects to login) — correct behavior

---

## 🤖 Bot health (145 bots)

### Static analysis
- **0 syntax errors** across all 145 `bot.py` files
- **0 syntax errors** in `core/*.py`
- Clean Python parse across the whole monorepo

### Runtime load failures
- **1 bot fails to load**: `core/bug_hunter`
- Error: `Can't instantiate abstract class BugHunterBot with abstract method 'run'`
- Root cause: [bots/core/bug_hunter/bot.py:88-92](bots/core/bug_hunter/bot.py#L88) — class subclasses `BaseBot` (which requires `run()`) but only defines `execute()`
- **Fix scheduled below.**

### Bot category distribution
```
26  specialized          8  business          3  customer_support     1  campaigns
25  marketing            6  seo_autopilot     3  assistant            1  core
13  agent_workforce      5  sales             3  aeo                  1  narai
10  revenue              3  seo_command       2  time_management      1  tool_catalog
10  books                                     2  prompt_intel
 9  social_media                              2  problem_solving
 8  writing                                   2  ecommerce
```

---

## 🔧 Fixes being applied this session

(Filled in as each fix lands.)

1. **bug_hunter** — add missing `run()` method (delegate to `execute()`)
2. **/sitemap.xml + /robots.txt** — add explicit GET routes to `core/api.py`
3. **/api/v2/narai/voice/ws** — include the voice router in `core/api.py`

Each fix:
- Makes ONE small change (no refactors)
- Verified locally before push
- Pushed via `railway up` (since GitHub auto-deploy is broken)
- Committed to `main` for git history

---

## 📝 What I did NOT touch (and why)

| Thing | Why I left it |
|---|---|
| The 60+ uncommitted bot files (already in your working tree) | They were already shipped to prod via `railway up` for the admin restoration — but never `git commit`'d. **You should `git status`, review, and commit them yourself** so prod and git history don't diverge further. |
| Pre-existing semgrep findings (96 in `core/api.py`) | All on lines you didn't change. Most are SSRF false-positives in old request handlers. Not in scope of "fix bugs" — needs design review. |
| Pre-existing gitleaks findings (4,241, mostly in `logs/system.log.*`) | Logs are leaking secrets in plaintext. Big finding, but the fix (logger redaction) is a project unto itself. Documented for follow-up. |
| Marketing endpoints | Documented above — needs your decision before changing. |
| Railway↔GitHub link | Documented above — needs dashboard click, not code. |
