# KAI Intelligence Source Inventory (Phase 6A)

Ground truth for the Intelligence Center. **No fake live news** (§6A). Provenance
per source: `REAL` (live external, real URL) · `DERIVED` (KAI/LLM-computed, no
hard source provenance) · `DEMO` (fixture) · `UNAVAILABLE`.

## The one REAL primary source: the research digest
`backend/app/services/research/` — fetches **arXiv (cs.AI), Hacker News, GitHub
trending** live via urllib (no LLM), served by `GET /admin/research/latest`
(admin-token gated). Per item (`sources.py:33-44`, persisted `digest.py:216`):

| field | reality | provenance |
|---|---|---|
| `title` | REAL original headline (unmodified) | REAL |
| `url` | REAL canonical source URL | REAL → PRIMARY_SOURCE |
| `summary` | the SOURCE's own text (arXiv abstract / repo description / HN stat line) — NOT a KAI rewrite | REAL (source fact) |
| `source` | hn / arxiv / gh_trending (the only "category") | REAL |
| **`published_at`** | **DROPPED at ingest** — only the digest's `generated_at` (cycle run time) is stored | **UNAVAILABLE** |

**Honesty consequences (enforced in the UI):**
- These display as **PRIMARY_SOURCE** with a real clickable URL.
- Freshness shows **"fetched Nm ago"** (from `generated_at`), and the published
  time is **UNKNOWN** — we do NOT fabricate a `published_at`. (Fix is ~1 line per
  fetcher: arXiv `<published>`, HN `time`, GH `created_at` are in every response
  but not captured — `github_scout.py:194` already does it right for repos.)
- Category is derived from `source` (arxiv→AI, hn→TECH, gh→STARTUPS) — marked DERIVED.
- The digest does **no dedup** (same story across cycles = duplicates) → the
  client dedupes (D10).

## DERIVED — must NOT be shown as primary news
- `tool.web_search` (Perplexity) — LLM answer + real citation URLs, no published_at, SECONDARY. Needs `PERPLEXITY_API_KEY`.
- `tool.trading_signal` — RSI/MACD vote from real prices; a computation, "not financial advice".
- `svc.digest` (Operator Digest) — LLM synthesis over KAI's own state.
- `svc.supreme.scanner` — **local host health** (pgrep/port/disk), internal Findings — NOT external security intel.
- `svc.audit` — internal governance audit.

## REAL-DATA but NOT news
- `svc.market_data` — yfinance OHLCV bars with real timestamps (prices, no article URL).
- `tool.github_scout` — real repo url + `pushed_at` (repos, not news).

## Does NOT exist — do not fake
- **No security/CVE/GHSA/NVD feed** (`sources.py:12-14` cut it from MVP). Cyber
  signals in the Nexus are **DEMO-only, DEMO-tagged** — never presented as live.
- No `/api/market/status`; no stored reports/citations tables.

## Exercise status (§6Y)
The digest fetchers run without Docker (plain urllib), but reaching them through
the app needs App B + admin auth (Docker down). The Intelligence Center ships the
REAL adapter (`GET /admin/research/latest`) fail-soft; live exercise is
**BLOCKED** until the stack runs. Nothing claims a successful live connection
until exercised.
