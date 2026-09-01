# KAI — Master Capability Inventory (§3)

Every candidate the operator supplied appears **exactly once**, reconciled against the **126 already
cataloged** (see `KAI_CAPABILITY_LEDGER.md`). No duplicate is silently omitted. Names normalized.

**Totals:** supplied ≈ 150 · **already cataloged ≈ 90** (do NOT re-adopt) · **genuinely new ≈ 55**
(live-web verification running: workflow `wf_94db2ea5-2f2`, 8 category agents — dispositions land in §B when it returns).

---

## A. ALREADY CATALOGED — map to an existing capability (REJECT_DUPLICATE for intake; already governed)

| supplied name | existing id | existing disposition |
|---|---|---|
| Ollama | `ollama` | MODEL_RUNTIME (incumbent local) |
| vLLM | `vllm` | ADOPT (GPU serving) |
| llama.cpp | `llama-cpp` | ADOPT (CPU-ok) |
| AirLLM | `airllm` | MODEL_RUNTIME |
| Transformers | `transformers` | ADOPT (heavy) |
| LangChain | `langchain` | REUSE_LIBRARY |
| n8n | `n8n` | ADAPTER_ONLY (isolated) |
| Dify | `dify` | REFERENCE (dup orchestration) |
| Langflow | `langflow` | REFERENCE (RCE history) |
| OpenClaw | `openclaw` | REJECT_DUPLICATE (rival brain) |
| MetaGPT | `metagpt` | REFERENCE |
| AutoGen | `autogen` | UNMAINTAINED→REFERENCE |
| CrewAI | `crewai` | REUSE_LIBRARY |
| Aider | `aider` | USE_AS_WORKER |
| jcode / Roo / Gemini CLI / Windsurf | `jcode`/`roo`/`gemini-cli`/`windsurf` | coding pool |
| Claude Code / Codex / Cline | `claude-code`/`codex`/`cline` | coding pool |
| MarkItDown | `markitdown` | **CERTIFIED (live)** |
| Maigret | `maigret` | ADOPT (OSINT) |
| TradingAgents | `tradingagents` | RESTRICTED (research only) |
| Stagehand | `stagehand` | REFERENCE (over Playwright) |
| Browser Use | `browser-use` | REFERENCE (cloud-stealth caution) |
| Firecrawl | `firecrawl` | ADOPT (web→RAG) |
| iFixAI | `ifixai` | RESTRICTED |
| LlamaIndex | `llama-index` | REJECT_DUPLICATE |
| RAGFlow | `ragflow` | REJECT_DUPLICATE |
| Supermemory | `supermemory` | REJECT_DUPLICATE (kai-memory) |
| Mem0 | `mem0` | REJECT_DUPLICATE (kai-memory) |
| Codebase Memory / code-graph | `codebase-memory-mcp` / `codegraph` | PARTIAL (built-from-source) / REFERENCE |
| ComfyUI | `comfyui` | ADOPT (vetted nodes) |
| Lobe Chat | `lobe-chat` | REJECT_DUPLICATE (Nexus) |
| Open WebUI | `open-webui` | REJECT_DUPLICATE (Nexus) |
| Pipecat | `pipecat` | ADOPT (voice transport) |
| Bumblebee | `bumblebee` | ADOPT (supply-chain gate §6) |
| Context7 / Playwright / GitHub / Filesystem / Sequential-Thinking MCP | `context7`/`playwright`/`github`/`filesystem`/`sequential-thinking` | MCPs |
| Plausible | `plausible` | SERVICE_CONNECTOR (read-only) |
| DeepSeek org/models | `deepseek-v4` | REFERENCE (hosted-only) |
| FreeLLMAPI | `free-llm-api-resources` | **UPSTREAM_UNRESOLVED — ⚠ canonical removed** |
| HERO / ARIS | `hero` (+ ARIS→§B verify) | AGENT_BEHAVIOR_POLICY |
| awesome-hacking / PayloadsAllTheThings / SecLists / awesome-osint / Ultimate Cybersecurity Ref | `awesome-hacking`/`payloads-all-the-things`/`seclists`/`awesome-osint`/`cybersecurity-reference` | SECURITY_REFERENCE/DATA (tier-gated) |
| Build Your Own X, Developer Roadmap, Free Programming Books, System Design Primer, Coding Interview University, Art of Command Line, Project Based Learning, You Don't Know JS, Book of Secret Knowledge, Tech Interview Handbook, JavaScript Algorithms, 30 Seconds of Code, gitignore, freeCodeCamp | `build-your-own-x` … `gitignore-templates`, `freecodecamp` | KNOWLEDGE_PACK / REFERENCE_ONLY |
| book-to-skill, marketingskills(=ai-marketing-skills), OpenWiki, Meetily, Penpot | `book-to-skill`/`ai-marketing-skills`/`openwiki`/`meetily`/`penpot` | as cataloged |

> Ponytail is **already active as a user-scope Claude Code plugin** (engineering-scope policy) — see §B for its formal fabric disposition + collapse-with-HERO decision (§12).

## B. GENUINELY NEW — live-web verification IN PROGRESS (`wf_94db2ea5-2f2`)
Preliminary category guess in parentheses; **authoritative disposition + license_class + supply-chain risk land here when the workflow returns.** None auto-installs (§57): each enters `DISCOVERED_UNVERIFIED` → supply-chain gate (§6).

- **Output-style / engineering-policy / skills:** Hallmark (DESIGN_SKILL §10) · Attention Span (OUTPUT_STYLE §11) · Ponytail (ENGINEERING_POLICY §12, collapse-with-HERO) · no-ai-slop (OUTPUT_STYLE) · ARIS (ENGINEERING_POLICY) · spec-kit (AGENT_SKILL) · Anthropic Skills / Awesome Claude Skills / Agent-Skills-for-Context-Engineering (skill catalogs) · notebooklm-skill · guizang-ppt-skill
- **Model runtimes / routers / optimization:** LiteLLM (MODEL_ROUTER §17 — adapter *beneath* the existing router, no big-bang) · Modular MAX/Mojo (MODEL_RUNTIME) · Jan (LOCAL_MODEL_UI, HUMAN_INTERACTIVE) · text-generation-webui · KoboldCpp (MODEL_RUNTIME specialist) · tiktoken (TOKEN_OPTIMIZER, always-safe) · GPTCache (cache — deterministic-only) · LLMLingua (compression — never code/legal/safety §20) · Outlines (structured gen — schema-only) · whichllm · AnythingLLM (RAG/UI dup?)
- **Computer-use / browser:** UI-TARS/Agent TARS (COMPUTER_USE_WORKER, HIGH §14 — sandbox, never banking/prod/passwords) · Wigolo · Page Agent · OpenCLI · AgenticSeek · MassGen
- **Memory / code-intel / recording:** Hivemind (MEMORY_PROVIDER_EXPERIMENTAL §13 — egress review before any use) · OpenHuman · code-review-graph · Windrecorder (screen memory — privacy HIGH)
- **Self-hosted services:** Authentik (§33 auth — INFRA_CHANGE, plan+rollback) · Chatwoot (support §82) · Listmonk (email §83) · Kaneo · Medusa · Bitwarden (§33 secrets — INFRA_CHANGE) · NocoDB (§31 read-only first) · CrowdSec (security) · Uptime Kuma (§26 monitoring — reuse if deployed) · Activepieces (§32 vs n8n — pick one) · dbx (§31 read-only DB) · ChartDB (§31 schema-only) · LifeForge
- **Design / media / docs / OCR:** Excalidraw (DESIGN) · Presenton (presentations) · Duix-Avatar (avatar) · Unlimited OCR · Dioxus (UI framework) · Vane · LanguageTool (writing quality)
- **SEO / marketing / social:** open-seo · claude-seo · Postiz (§25 social — draft-first, no auto-publish) · Cheat on Content
- **Security / spreadsheet / dev-tools / reference:** Strix (SECURITY_ACTIVE, RESTRICTED §15 — never in the always-on loop) · excel-mcp-server (§30 file mutation, root-scoped) · gh-dash · lazy-frames · nanoGPT (REFERENCE) · RealWorld (REFERENCE app) · Awesome Self-Hosted (§99 DISCOVERY_CATALOG) · Awesome Python (catalog) · Clean Code JavaScript / JavaScript Testing Best Practices (REFERENCE)

## C. Intake rules applied (§4–8, §57–58)
- **No candidate auto-installs.** DISCOVERED → source-verify → license → static inspect → dependency review → **Bumblebee/supply-chain scan (§6)** → sandbox install → network observation → health → tests → promotion.
- **No `curl|bash` / `irm|iex`** for certified installs (§6, §81) — package-manager / source-build only.
- **Duplicates** of the 126 (Section A) are REJECT_DUPLICATE for intake — they are already governed; no second copy.
- **AGPL/copyleft** (e.g. many self-hosted services) → `SERVICE_ISOLATION_REQUIRED` / `LICENSE_REVIEW_REQUIRED`; run isolated, never bundle into a shipped proprietary product without review (§5). No legal claims beyond the license text.
- Every skill/README/MCP-description = **UNTRUSTED_EXTERNAL_INSTRUCTION** (§58) — cannot override policy/security/financial gates.
