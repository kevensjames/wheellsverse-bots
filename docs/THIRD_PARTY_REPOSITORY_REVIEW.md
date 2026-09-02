# Mission-2 Third-Party Repository Review (Phase 0, READ-ONLY)

**Authorized scope:** read-only web/source inspection only. **Installs: 0 · external auth: 0 · code executed: 0 · production changes: 0.** Every source treated as UNTRUSTED (§37). Implementation is BLOCKED — Mission-2 spec arrived truncated (§40, SPEC_INCOMPLETE).

## Secret presence (names only — values never read/printed, §38/§39)
| secret | status |
|---|---|
| AIKIDO_CLIENT_ID / AIKIDO_CLIENT_SECRET | ABSENT |
| AIKIDO_API_KEY | ABSENT |
| DataForSEO (login/password/key) | ABSENT |

> No external authentication attempted. Aikido/DataForSEO integration cannot proceed until the operator provisions these secrets (referenced by name, never inlined).

## Per-source disposition
| source | license | risk | recommended disposition |
|---|---|---|---|
| `aikido.dev` | SaaS: proprietary / commercial ToS | MEDIUM | ADAPTER_ONLY + RESTRICTED. Integrate as a thin outbound HTTPS REST adapter using OAuth client-credentials, credentials a |
| `trycompai/crm` | MIT (LICENSE present; package.json | HIGH | REFERENCE (primary). Study the evidence-ledger / observed-fact / strong-vs-weak-evidence design and the eve durable-agen |
| `every-app/open-seo` | MIT — Copyright (c) 2026 Ben Senes | HIGH | ISOLATED_SERVICE + ADAPTER_ONLY + SEO_COST_GATED. Do NOT vendor the code into KAI. If pursued: run the upstream MCP serv |
| `dgtlmoon/changedetection.io` | Apache-2.0 | HIGH | ISOLATED_SERVICE — run only as a separate container behind an ADAPTER, never in-process with KAI. Enforce default-deny e |
| `JCodesMore/ai-website-cloner-templ` | MIT | HIGH | ISOLATED_SERVICE (sandboxed) — REFERENCE first. Adopt the extraction/spec methodology as REFERENCE now; do NOT wire the  |
| `hugohe3/ppt-master` | MIT | MEDIUM | ISOLATED_SERVICE — if adopted, run inside a sandboxed container with: (1) update_repo.py auto-update DISABLED and the re |
| `D4Vinci/Scrapling` | BSD-3-Clause | HIGH | ISOLATED_SERVICE (adapter-only). If ever integrated: run behind a narrow adapter inside the existing egress-controlled b |
| `PaddlePaddle/PaddleOCR` | Apache-2.0 | MEDIUM | ISOLATED_SERVICE, consumed via ADAPTER_ONLY from KAI. Run PaddleOCR behind a network-egress-restricted container/service |

## Key findings (all UNTRUSTED until a full supply-chain gate at integration time)

### aikido.dev — risk MEDIUM
- **License:** SaaS: proprietary / commercial ToS (not open-source). Official MCP client @aikidosec/mcp: AGPL (AGPL-3.0 family per npm metadata). Community lasergoat/aikido-mcp: license not verified.
- **Runtime/exec:** None for the pure REST adapter (KAI only issues HTTP requests). The official MCP client (@aikidosec/mcp, node bin aikido-mcp) DOES execute locally: it downloads and decompresses a scanner artifact and
- **Network/creds:** Outbound HTTPS only for the REST path: token endpoint https://app.aikido.dev/api/oauth/token then https://app.{,us.,me.}aikido.dev/api/publi · OAuth 2.0 client-credentials: Client ID + Client Secret (issued on the Aikido integration page), sent as HTTP Basic to t
- **KAI overlap:** Low/complementary. Aikido is a code/dep/cloud security-scanning SaaS; KAI is an operator/ops-governance platform, not a scanner — net-new capability, not a dupl
- **Disposition:** ADAPTER_ONLY + RESTRICTED. Integrate as a thin outbound HTTPS REST adapter using OAuth client-credentials, credentials as a secret-ref, region pinned (EU or US). Scope to READ endpoints (issues/vulns/SBOM/compliance); gate all mutating endpoints (ignore-issue,

### trycompai/crm — risk HIGH
- **License:** MIT (LICENSE present; package.json/README confirm).
- **Runtime/exec:** YES — autonomous code/task execution. The agent (eve) runs on its own deployment, own schedule, and own work queue, executing research/enrichment tasks without user prompting (recurring rechecks, ledg
- **Network/creds:** HEAVY outbound. LLM via Vercel AI Gateway (AI_GATEWAY_API_KEY); Perplexity web-research API (PERPLEXITY_API_KEY); "Context API" for company/ · BROAD, HIGH-VALUE credential surface: DATABASE_URL/DIRECT/TEST Postgres; BETTER_AUTH_SECRET; Google/Microsoft/Slack OAut
- **KAI overlap:** HIGH conceptual overlap — this is a competing full application, not a complementary component. Its "observed-facts, no-guessing, evidence-ledger" model overlaps
- **Disposition:** REFERENCE (primary). Study the evidence-ledger / observed-fact / strong-vs-weak-evidence design and the eve durable-agent patterns; do NOT adopt as a KAI dependency or capability adapter (it is a whole app that duplicates KAI's DigitalTwin + autonomous engine)

### every-app/open-seo — risk HIGH
- **License:** MIT — Copyright (c) 2026 Ben Senescu
- **Runtime/exec:** Yes. Cloudflare Workers runtime + Docker docker-entrypoint.sh (shell). Playwright (@playwright/test) drives a headless browser. Site-audit crawler executes network fetches and parses untrusted remote 
- **Network/creds:** Broad egress. Outbound to: DataForSEO (primary SEO data API), OpenRouter (LLM), Cloudflare APIs, PostHog (analytics), autumn-js (billing), G · Credential-heavy. Requires DataForSEO API key (mandatory to function). Also: better-auth + @better-auth/api-key (user au
- **KAI overlap:** Meaningful. Ships an MCP server (@modelcontextprotocol/sdk/server/client) + reusable agent skills explicitly for Claude Code — same integration surface KAI's ca
- **Disposition:** ISOLATED_SERVICE + ADAPTER_ONLY + SEO_COST_GATED. Do NOT vendor the code into KAI. If pursued: run the upstream MCP server as an isolated, network-restricted service pinned to a tag (v0.1.7); consume only via a thin KAI adapter over its MCP tools; disable Post

### dgtlmoon/changedetection.io — risk HIGH
- **License:** Apache-2.0
- **Runtime/exec:** Meaningful execution surface (not host RCE by design): runs headless Chromium via selenium/pyppeteer-ng and renders/executes remote page JS; supports user-defined browser automation steps and JS-in-br
- **Network/creds:** HEAVY by design. Outbound: fetches arbitrary user-configured URLs on a schedule (inherent SSRF surface — can be pointed at internal/metadata · Stores multiple secrets in its datastore: notification tokens/webhook URLs, optional per-watch HTTP/basic auth for monit
- **KAI overlap:** MODERATE-to-HIGH conceptual overlap but complementary. KAI already has a deterministic material-change reconciler + DigitalTwin (NO_MATERIAL_CHANGE = no busy-wo
- **Disposition:** ISOLATED_SERVICE — run only as a separate container behind an ADAPTER, never in-process with KAI. Enforce default-deny egress with an explicit allowlist (SSRF containment), give it throwaway isolated secrets, keep the optional LLM feature off unless explicitly

### JCodesMore/ai-website-cloner-template — risk HIGH
- **License:** MIT
- **Runtime/exec:** YES — this is a code-generation + code-execution orchestration pipeline, not a static library. It runs `npm run build` repeatedly, `npx tsc --noEmit`, executes self-generated .mjs asset-download scrip
- **Network/creds:** HEAVY and outbound to arbitrary hosts. The workflow REQUIRES a headless-browser MCP (Playwright/Puppeteer/Chrome/Browserbase) that it points · None required for cloning public sites. ATLASCLOUD_API_KEY (env) required ONLY if the optional Atlas Cloud image-generat
- **KAI overlap:** Partial. KAI Capability Fabric already has a sandboxed browser-worker (SOCKS5 default-deny egress) that overlaps the reconnaissance/asset-fetch layer, and site/
- **Disposition:** ISOLATED_SERVICE (sandboxed) — REFERENCE first. Adopt the extraction/spec methodology as REFERENCE now; do NOT wire the live pipeline into governed KAI. If operationalized later, run only as an isolated, sandboxed service in a disposable worktree with (a) egre

### hugohe3/ppt-master — risk MEDIUM
- **License:** MIT
- **Runtime/exec:** Runs local Python scripts (finalize_svg.py, image_gen.py, image_search.py, update_repo.py) plus skia-pathops/uharfbuzz native libs and a Flask web server. update_repo.py runs `git status`/`git rev-par
- **Network/creds:** Broad outbound egress when configured. edge-tts -> Microsoft TTS; image search -> Openverse/Wikimedia (zero-config), Pexels, Pixabay; image  · Many OPTIONAL API keys via .env (OPENAI_, GEMINI_/google-genai, PEXELS_API_KEY, PIXABAY_API_KEY, QWEN_, ZHIPU_, VOLCENGI
- **KAI overlap:** Low. KAI has no native PPTX/deck-generation capability; the capability fabric catalog is dormant/DISCOVERED and does not cover native python-pptx object-model o
- **Disposition:** ISOLATED_SERVICE — if adopted, run inside a sandboxed container with: (1) update_repo.py auto-update DISABLED and the ref pinned to a reviewed SHA (no live git pull/pip install); (2) egress allowlist restricted to only the chosen provider(s); (3) no access to 

### D4Vinci/Scrapling — risk HIGH
- **License:** BSD-3-Clause
- **Runtime/exec:** HIGH. Launches headless browsers and executes full remote DOM + arbitrary JavaScript from scraped sites; renders untrusted third-party pages. StealthyFetcher runs a patched Firefox (Camoufox). Ships a
- **Network/creds:** HEAVY / CORE FUNCTION. Fetches arbitrary user-supplied URLs over HTTP/HTTPS/HTTP3; TLS-fingerprint impersonation via curl_cffi; DNS-over-HTT · None required for basic operation. No API keys or auth built in. Optional user-supplied proxy credentials and target-sit
- **KAI overlap:** Overlaps existing KAI browser capability: ops/browser-worker (SOCKS5 egress default-deny) already provides sandboxed browser fetching, and a turnstile-spin skil
- **Disposition:** ISOLATED_SERVICE (adapter-only). If ever integrated: run behind a narrow adapter inside the existing egress-controlled browser-worker sandbox, expose a minimal fetch/parse interface to KAI, and DO NOT enable or expose its bundled MCP server. Also RESTRICTED: t

### PaddlePaddle/PaddleOCR — risk MEDIUM
- **License:** Apache-2.0
- **Runtime/exec:** Runs ML inference; loads model weight/param files. PRIMARY CONCERN: model artifacts are downloaded from a remote CDN and deserialized by the framework — untrusted-weight / deserialization exposure if 
- **Network/creds:** HAS network capability. `requests` is a declared dependency. Default behavior downloads pretrained model weights on first use from Baidu Obj · NONE required for local OCR/structure inference. No API keys, tokens, or accounts for the classic pipeline. (Only if ope
- **KAI overlap:** LOW overlap / ADDITIVE. KAI inventory shows a browser-worker and document/report capabilities but no existing OCR / image-and-PDF-to-structured-data capability.
- **Disposition:** ISOLATED_SERVICE, consumed via ADAPTER_ONLY from KAI. Run PaddleOCR behind a network-egress-restricted container/service: pre-download and pin model weights (SHA-verified), disable framework telemetry, mount no host credentials, expose only a narrow file-in/JS

## Cross-cutting conclusions
- **Nothing is vendored/installed.** All would be ISOLATED_SERVICE + ADAPTER_ONLY behind KAI's governance if ever adopted — none runs in-process in App B.
- **Aikido** = SaaS via versioned REST API + OAuth client-credentials; ADAPTER_ONLY + RESTRICTED (read endpoints only; mutations owner-gated). Do NOT vendor the AGPL official client; the local-scan MCP path downloads+executes a binary → sandbox only if ever wanted.
- **HIGH-risk (browser/code execution):** open-seo, changedetection.io, ai-website-cloner, Scrapling, trycompai/crm (autonomous agent). Each needs sandboxed isolation + egress allowlist + SSRF/robots/ToS guards before any use; several are REFERENCE-first.
- **MEDIUM:** Aikido (broad org-wide secret), ppt-master (local scripts), PaddleOCR (model-artifact provenance — pin weights, verify checksums).
- **Licenses:** mostly MIT/Apache/BSD (clear) + Aikido SaaS proprietary + AGPL official client (isolate, never link).

## Status
**Mission 2: BLOCKED_SPEC_INCOMPLETE.** Phase-0 review COMPLETE. Next requires: the truncated spec remainder, operator go-ahead per source, and provisioned credentials — then a full supply-chain gate (static inspect → dependency review → Bumblebee/scan → sandbox) before any install.
