# KAI System Report — 2026-06-12

Point-in-time report. **Regenerate the live data anytime** via the **Audit** tab
(app.wheellsverse.com/admin → Audit → "run audit") or `GET /admin/audit/run`.
Live audit at time of writing: **9/9 scoped features ON · 116 records · 12
subsystems · 0 issues.**

---

## 1. What KAI is

KAI is an operator-owned autonomous AI companion running as a single FastAPI
daemon (`com.wheellsverse.nai` launchd agent → uvicorn :8001 → cloudflared →
`kai.wheellsverse.com`, embedded as a tab in `app.wheellsverse.com/admin`).
It is **multi-provider** (OpenAI / Anthropic / Cloudflare / Ollama / Perplexity
adapters behind an intent router), **governed** (every powerful action is
scope-gated + audit-logged), and **self-aware** (it can audit its own
subsystems).

Every capability follows one pattern: **sidecar storage (SQLite/JSONL, no
Supabase migration risk) + `@audited` scope gate + a read-only chat tool + an
operator dashboard tab.**

## 2. Capabilities (the 12 subsystems)

| # | Subsystem | Scope flag | Live | Records | What it does |
|---|---|---|---|---|---|
| 1 | Governance + audit log | (always on) | ✅ | 76 | `@audited` scope/approval gate; tamper-evident log of every action |
| 2 | Expert-agent presets | `presets` | ✅ | 5 personas | SWE/Marketing/Finance/Research/Legal personas + tool whitelists |
| 3 | Knowledge graph | `kg` | ✅ | 2 | SQLite entity+relation store KAI can query ("Jhon owns KAI") |
| 4 | Failure memory | (always on) | ✅ | 1 | remembers + warns about past tool failures |
| 5 | Continuous research | `research` | ✅ | 14 | daily HN+arXiv+GH scan → digest (08:00 UTC cron) |
| 6 | Self-correction | `self_correction` | ✅ | 4 | critic+reviser pass on KAI's drafts (opt-in per chat) |
| 7 | **Long-term planning** | `planning` | ✅ | 1 | goal→steps, execute one at a time, revise on failure (Plans tab) |
| 8 | **Computer-control / browser** | `browser` | ✅ | 15 | read + propose + **(approved) execute** writes, allowlisted + SSRF-guarded |
| 9 | **Continuous learning** | `learning` | ✅ | 1 | feedback→lessons→operator-approved injection into the system prompt |
| 10 | **Digital twin** | `twin` | ✅ | 2 | operator self-model injected always-on + draft-in-your-voice |
| 11 | Daily brief | `briefing` | ✅ | 0 | operator daily brief (audited) |
| 12 | Supreme scanner | (always on) | ✅ | — | 15-min empire health scan (process/port/log/api/disk/git) |

Bold = shipped this session (features 7–10 + browser **envelope B** = approved
write execution). All 9 scoped features are **enabled in production**.

## 3. The rest of the stack

- **Chat tools (13 registered):** web_search, web_fetch, memory, trading_signal,
  kg_query, failure_lookup, plan_query, learning_query, twin_query, browser,
  audit_query, notion, composio. KAI calls these inside a chat turn.
- **Dashboard (13 tabs):** Stats · Chat · Scanner · Brief · Knowledge ·
  Failures · Research · Self-Correction · Plans · Browser · Learning · Twin ·
  **Audit**. All operator-token gated.
- **LLM routing:** intent classifier → OpenAI / Anthropic / Cloudflare (cheap) /
  Ollama (local) / Perplexity (realtime), with spend tracking + a daily cap and
  graceful fallback.
- **Prompt assembly** (`build_system_prompt`): persona (preset) → **twin profile**
  → **learning lessons** → memory → base. The twin + learning layers are
  scope-gated + fail-open, so KAI's behavior is shaped by approved self-model +
  lessons on every reply.
- **Auth/infra:** Supabase JWT for public users + tier gates; `X-Admin-Token`
  for the operator dashboard; pgvector memory; sidecar SQLite/JSONL per feature.

## 4. What's working (verified live this run)

- **All 12 subsystems live, 9/9 scopes on, 0 audit issues.**
- **Planning:** create→approve→execute-next + branch directives — endpoints +
  gates verified (409 no-approval, scope gates).
- **Browser:** real headless-chromium navigation (read example.com / your
  homepage), allowlist + SSRF blocks (evil.com → 400), and **envelope B real
  execution** (clicked HN "More" → paginated; example.com link → navigated).
- **Learning loop closed:** 👎 feedback → synthesized lesson "Provide concise
  answers…" → approved → injects into the prompt.
- **Twin:** KG-suggested entry ("Jhon is the owner of KAI") + draft-in-voice
  produced a real reply.
- **LLM:** all of the above ran on the **OpenAI gpt-4o-mini fallback** — proving
  multi-provider routing works when Anthropic is unavailable.
- **Tests:** 590 pass across the suite; the 4 new feature suites + audit are
  green (planning 74, browser 50, learning 30, twin 34, audit 7).

## 5. What's NOT working / risks

- **Anthropic billing** — was blocked ("credit balance too low") this run, so
  everything ran on the OpenAI fallback. Functional, but not Claude-class
  quality. *Highest-leverage operator fix.* (An `ANTHROPIC_DAILY_BUDGET_USD` is
  now set — verify Claude routing resumes.)
- **15 pre-existing test failures** (not regressions): ~12 need `OPENAI_API_KEY`
  in the shell (memory/brain embeddings, admin_chat) — they pass for the daemon;
  **2 `test_security_headers` are stale** — they assert `frame-ancestors 'none'`
  but commit `48ddb16` deliberately changed CSP to allow the app.wheellsverse.com
  iframe. The 2 stale tests should be updated to match reality.
- **`.env` landmine (PARTIALLY addressed 2026-06-12)** — WORDPRESS_TOKEN (line
  ~246) has an unescaped `(` that aborts `set -a; . .env`. **Do NOT just "quote
  it"** — that unblocks the rest of `.env`, which contains other shell-hostile
  values (`NARAI_PASSWORD_HASH=$2b$…` bcrypt → `set -u` unbound-var → silent
  wrapper crash); it took prod down 2026-06-12 and was reverted. WORDPRESS_TOKEN
  is unused by the daemon anyway. The only daemon-relevant trapped var
  (`TELEGRAM_BOT_TOKEN`/`CHAT_ID`) was **moved above the landmine** → Telegram
  alerts now send. Proper full fix = a literal dotenv loader in
  `deploy/start_nai.sh` (no shell eval), deferred. See
  memory/kai_env_landmine_2026_06_12.md.
- **Browser envelope B v1 limit** — the allowlist gates the *entry* URL only; a
  click can navigate off-allowlist (post-nav targets aren't re-checked). Safe in
  v1 (operator approves each sequence; no autonomous loop) but the obvious v2.
- **Leaked credentials** in chat history (flagged earlier) still need rotation.
- **Branch not merged** — all work is on `feat/kdp-fillers` (pushed to Gitea);
  not merged to `main`.

## 6. What to work on next (no high-value roadmap items remain)

The AGI roadmap (`kai_agi_roadmap_2026_06_09.md`) is complete — planning,
computer-control, learning, twin shipped; openai-2.x + Gitea-registry resolved
as no-ops. Optional upgrades, in rough value order:

1. **Top up Anthropic** (operator) — lifts quality across every feature.
2. **Fix the 2 stale CSP tests** — makes the suite trustworthy (small). (Note:
   do NOT "quote WORDPRESS_TOKEN" — it crashes startup; the proper `.env` fix is
   a literal dotenv loader in `start_nai.sh`. Telegram alerts already freed
   2026-06-12 by moving those tokens above the landmine.)
3. **Browser envelope B v2** — re-validate post-click navigation against the
   allowlist.
4. **Learning auto-tuning / extra inputs** — feed failures + self-correction
   events into lesson synthesis; A/B testing.
5. **Twin "decide as operator"** (autonomous) — deferred for risk; revisit with
   a strong approval model.
6. **Merge `feat/kdp-fillers` → main** + rotate leaked creds.

## 7. The audit system (how to regenerate this)

Shipped this session (`97b3c91`): `services/audit/auditor.py` introspects the
declarative `SUBSYSTEMS` registry — reads each scope flag, counts each sidecar
store, reports runtime + dynamic issues.

- **Dashboard:** Audit tab → "run audit" — subsystem table, runtime chips, issues.
- **API:** `GET /admin/audit/run` (admin-token).
- **In chat:** "KAI, audit yourself" → the `audit_query` tool.
- **Keep it accurate:** when a new feature ships, add a row to `SUBSYSTEMS` in
  `auditor.py`.

## 8. Production facts (for the next session)

- Code: `/Users/jhonwheeler/wheellsverse_bots` (home dir). Restart:
  `launchctl kickstart -k gui/$(id -u)/com.wheellsverse.nai`.
- Gitea push: `git push origin feat/kdp-fillers` (resolves to localhost:3000).
- This session's commits: `6eb7df3 → 9f14e28 → 2a39581 → 2306da0 → 9e6ad44 →
  a34e244 → 75a3045 → 97b3c91`.
