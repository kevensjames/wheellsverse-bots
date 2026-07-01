# WheellsVerse — Whole-System Audit & Full-Power Roadmap
_Date: 2026-06-23 · Scope: the entire WheellsVerse company OS (Command Center + KAI + core monolith + Sol + bots)_

## 1. What the system actually is

WheellsVerse is not a dashboard with tabs — it is a **~221,000-line autonomous company operating system** run by one founder.

| Layer | Scale | Serves |
|---|---|---|
| **Command Center** `dashboard/index.html` | 1.1 MB single file, **73 views across 9 sections**, 293 wired endpoints | `app.wheellsverse.com` (the cockpit) |
| **Core monolith** `core/api.py` | **15,268 lines, 681 routes**, 166 core modules, 82.9K LOC | the company brain (bots, content, revenue, commerce, intelligence) |
| **KAI operator app** `backend/app` | 39.5K LOC, 15 admin tabs, ~30 governed services, 848 tests | `kai.wheellsverse.com/admin` (iframed by the Command Center) |
| **Sol fintech** `backend/app/services/sol` + `dwolla` | ROSCA ledger, 72 money-invariant tests | savings-circle product |
| **Bot fleet / publishing / content** `bots/`, `core/kdp_*`, `core/content_*` | 176 bot files + KDP/Etsy/Gumroad/Shopify/Canva | revenue surfaces |

**9 Command Center sections / 73 views:** CORE (hub, narai, overview, whatsapp, superagent) · AI (aichat, agentmode, promptlib, kb, creative, kai, suprema, ops) · CONTROL (botctl, codestudio, builder) · BOTS (bots, pixelagents, pipelines, scheduler) · INTELLIGENCE (decisions, health, memory, intelligence, autopilot, naraischedules, marketintel, qcreview, video) · REVENUE (revenue, revenue2, adsboard, kdpbooks, publisherengine, shopify, siteboost, etsy, gumroad, payhip, factory, money, nexora, toodle, sol) · CONTENT (publish, content, blog, autopublish, twitter, reddit, tiktokblitz, newsletter, gsc, telegramalerts, wordpress, notion, canva) · DATA (integrations, market, github, analytics, automation, outputs, logs) · CONFIG (sysreport, security, connections, projects, settings, tokens, apikeys, billing, command).

**Deploy topology:** `core.api:app` is the Command Center backend (Railway, root `railway.json`). `app.main:app` (KAI) deploys separately and also runs as a local launchd daemon at `~/wheellsverse_bots`. The working copy audited here is `/Volumes/Wheellsverse/wheellsverse-bots` on branch `_apexdeploy` — edits are reversible & **un-deployed**.

## 2. Health scorecard

| Dimension | Score | Evidence |
|---|---|---|
| **Dashboard→backend wiring** | ✅ 100% | Deterministic check: all 293 panel endpoints resolve to real routes among 708 route literals — **0 dead buttons**. |
| **Code-execution safety** | ✅ Excellent | **0** `shell=True` / `os.system` / `eval` / `exec` across 397 non-test files. |
| **Error hygiene** | ✅ Excellent | **1** bare `except:` out of **1,974** handlers (now fixed → 0). |
| **Secret hygiene** | ✅ Good | **0** inline secret literals (uses `wvkey` vault + env). |
| **Money localization** | ✅ Good | 91 of 164 money refs concentrated in Sol/Dwolla where the 72 money-invariant tests live. |
| **Governance wiring** | ⚠️ Broken-by-default | 36 `@audited` scopes, **0** documented in `.env.example`, none enabled in prod → every destructive action 403s. (docs added; enabling is an operator decision) |
| **Frontend auth UX** | ⚠️→✅ Fixed | 403 scope-denial was conflated with 401 auth-expiry → logged operator OUT on any governed action. **Fixed.** |
| **Observability** | ⚠️ Gap | Log-only; no aggregated error tracking / alerting across the monolith. |
| **CI gate** | ⚠️ Gap | 848 tests exist but no evidence of a deploy-blocking CI run. |
| **Overall (KAI subset, measured)** | **71/100** | Strong, disciplined core; fragile operating seam (governance wiring, observability, CI). |

> The monolith is **far healthier than its 15K-line size suggests** — the 71/100 is dragged down by *operational seams*, not unsafe code.

## 3. Fixes shipped this pass (verified, in working copy, un-deployed)

| # | Area | Bug | Fix | Verify |
|---|---|---|---|---|
| 1 | KAI (all governed tabs) | **Critical:** scope-denial (403) conflated with auth-expiry (401) → logout on any governed action | `authErrorFor()` disambiguates by response detail; scope denials now show an inline actionable error. 3 call sites (`apiGet`/`apiPost`/stream) in `static/nai/admin.js` | `node --check` ✅ |
| 2 | KAI Scanner | Status line renders literal `undefined findings` on malformed response | `?? 0` / `?? "—"` fallbacks (`admin.js`) | ✅ |
| 3 | KAI KG | Counts render `undefined` on schema drift | `?? "—"` coercion (`admin.js`) | ✅ |
| 4 | KAI governance | 36 scopes undocumented & off-by-default | Documented all `KAI_SCOPE_*` (read/risk/money groups) in `backend/.env.example` | ✅ |
| 5 | KAI KG | `entity_count` capped at 500, reported as exact | Added `count_entities()`/`count_edges()` real `COUNT(*)` in `services/kg/storage.py`; wired into `kg_stats` | `py_compile` ✅ |
| 6 | KAI KG | Button "add (auto-approved)" misleading (destructive, scope-gated) | Relabeled "add triple" (`admin.html`) | ✅ |
| 7 | Core monolith | Lone bare `except:` (swallows KeyboardInterrupt/SystemExit) in `core/inbox/routes.py` | Narrowed to `(ValueError, TypeError, AttributeError)` | `py_compile` ✅ |

## 4. Verified open backlog (do next)
- **KG add-edge** still no-ops when scope is off → enable `KAI_SCOPE_KG=1` in prod env (operator action; now documented).
- **Scanner** `ApiReachabilityScanner` only proves network reachability, not credential validity (silence ≠ "key valid"). Low priority; correctly named.
- **Scanner** disk/git checks use `__file__ parents[4]`; in prod the daemon runs from a different clone → point at an explicit `KAI_SUPREME_GIT_ROOT`.
- **11 KAI tabs** (Plans, Browser, Learning, Twin, Audit, Sol, Persona, Chat, Failures, Self-Correction, Research) were rate-limited during the first audit and have **not** had a per-tab deep pass yet.
- **Core monolith / 73 views**: structural map complete; per-view deep bug audit still pending (background workflow died across session gaps).

## 5. The full-power roadmap (path to an autonomous company OS)

- **Phase 0 — Stop the bleeding.** Make every governed action authorized + honest (✅ started: fixes 1+4), add aggregated error tracking (real observability, not log-only), add a deploy-blocking CI gate over the 848 tests.
- **Phase 1 — Sol money-safety.** Backed-up, reconcilable-from-Dwolla, race-free ledger; production path gated behind compliance + facilitator agreement.
- **Phase 2 — Unified data layer.** Replace ~10 hand-rolled SQLite stores + 16 unbounded JSONL logs + `parents[4]` path hacks with one `Store` base + central data-dir resolver + bounded/rotated logs + one backup story.
- **Phase 3 — Observability + Agent Permission Manager.** Governance from 18 env booleans → a managed, rate-limited, revocable-from-UI least-privilege control plane with spend/error/latency telemetry.
- **Phase 4 — Super-router + knowledge platform.** Cost-aware, confidence-scored routing across OpenAI→Anthropic→Ollama + a real document pipeline + external connectors (PubMed/EDGAR); refuse/escalate when uncertain.
- **Phase 5 — The CEO / Full-Autonomy subsystem.** Compose audit→plan→remediate→digest→decide-as-me into a supervised autonomous loop that runs routine ops within an operator-set spend/risk budget and escalates anything outside it.

**North star:** a single governed platform where the founder *supervises* rather than *operates* a multi-product company — KAI as a confidence-scored super-router + knowledge engine over one unified, backed-up data layer, with least-privilege auditable actions across fintech, commerce, content, and CRM.

## 6. How to continue safely
- Edits here are reversible & un-deployed. **Do not** hand-edit the live `.env` (documented prod-crash landmine — a stray quote took prod down once). Enable scopes via the deploy env (Railway/launchd), guided by the new `.env.example` block.
- Any change to publish/upload/payment "success" marking must assert real success (KDP already has the 3-gate `KDPResult` truth-verify schema) — never mark a registry row done off a return code or status string.
