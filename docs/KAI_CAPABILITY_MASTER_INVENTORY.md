# KAI — Master Capability Inventory (§3)

Every candidate the operator supplied appears **exactly once**, reconciled against the **126 already
cataloged** (see `KAI_CAPABILITY_LEDGER.md`). No duplicate is silently omitted. Names normalized.

**Totals:** supplied ≈ 150 · **already cataloged ≈ 90** (do NOT re-adopt) · **genuinely new ≈ 55**
(live-web **VERIFIED**: workflow `wf_94db2ea5-2f2`, 8 agents → **66 canonical records** with authoritative dispositions in §B).

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

## B. GENUINELY NEW — live-web VERIFIED (workflow `wf_94db2ea5-2f2`, 8 agents, 66 records)

Every candidate verified live against its GitHub source (owner, license, maintenance, network/creds/execution, supply-chain risk). **66 canonical records** (some supplied names split into multiple repos). None auto-installs (§57): each is `DISCOVERED` → supply-chain gate (§6) before any use.

**License:** 42 clear · 14 review-required · 10 service-isolation (AGPL/GPL copyleft). **Supply-chain risk:** 26 LOW · 29 MEDIUM · 11 HIGH.

### Must-gate (never auto-adopt; RESTRICTED, sandbox + human-gate; never in the always-on holding loop)
- **wanshuiyin/Auto-claude-code-research-in-sleep** (EXPERIMENTAL) — Autonomous ML-research orchestrator: idea discovery, cross-model review loops, experiment execution, paper pre
- **PleasePrompto/notebooklm-skill** (REJECT_SECURITY) — Drives Google NotebookLM via browser automation to get source-grounded, citation-backed answers from your note
- **bytedance/UI-TARS-desktop** (COMPUTER_USE_WORKER) — Multimodal AI agent stack: Agent TARS (CLI/Web, MCP tools) + UI-TARS-desktop (native GUI agent driving mouse/k
- **jackwener/opencli** (BROWSER_WORKER) — Turn any website into a CLI and run 'Browser Use' on your logged-in Chrome - a Browser Bridge extension + daem
- **Fosowl/agenticSeek** (REJECT_DUPLICATE) — 100%-local 'Manus AI' alternative - a voice-enabled autonomous agent that browses the web (Selenium), writes/d
- **activeloopai/hivemind** (MEMORY_PROVIDER) — Auto-learning memory that captures coding-agent session traces and mines repeated patterns into reusable cross
- **tinyhumansai/openhuman** (HUMAN_INTERACTIVE_ONLY) — Local-first personal-AI 'brain' desktop app: builds life-memory (Memory Tree + Obsidian wiki + SQLite), orches
- **crowdsecurity/crowdsec** (SECURITY_ACTIVE) — Crowdsourced host/IP intrusion-detection & remediation engine (IDS/IPS + WAF).
- **duixcom/Duix-Avatar** (MEDIA_TOOL) — Offline AI avatar / digital-human toolkit — appearance + voice cloning and text/voice-driven video generation.
- **usestrix/strix** (SECURITY_ACTIVE) — Autonomous open-source AI penetration-testing agent (recon, exploitation, PoC validation) over OWASP Top 10.

### Reject (already covered by the live KAI stack — do NOT re-adopt)
- **PleasePrompto/notebooklm-skill** (REJECT_SECURITY) → playwright / browser-use / stagehand (existing KAI browser workers)
- **Mintplex-Labs/anything-llm** (REJECT_DUPLICATE) → open-webui / lobe-chat / dify + KAI-native RAG (pgvector), Nexus chat UI, Holdin
- **KnockOutEZ/wigolo** (REJECT_DUPLICATE) → firecrawl
- **Fosowl/agenticSeek** (REJECT_DUPLICATE) → openhands / goose
- **massgen/MassGen** (REJECT_DUPLICATE) → autogen / crewai / metagpt
- **tirth8205/code-review-graph** (REJECT_DUPLICATE) → codegraph / codebase-memory-mcp
- **activepieces/activepieces** (REJECT_DUPLICATE) → n8n
- **ItzCrazyKns/Vane** (REJECT_DUPLICATE) → ragflow / open-webui / dify + KAI-native RAG (pgvector) + Nexus chat UI

### Full disposition table (sorted HIGH→LOW risk)

| risk | license | disposition | repo | SPDX |
|---|---|---|---|---|
| HIGH | clear | BROWSER_WORKER | `jackwener/opencli` | Apache-2.0 |
| HIGH | clear | COMPUTER_USE_WORKER | `bytedance/UI-TARS-desktop` | Apache-2.0 |
| HIGH | clear | EXPERIMENTAL | `wanshuiyin/Auto-claude-code-research-in-sleep` | MIT |
| HIGH | isolate | HUMAN_INTERACTIVE_ONLY | `tinyhumansai/openhuman` | GPL-3.0 |
| HIGH | review | MEDIA_TOOL | `duixcom/Duix-Avatar` | Custom 'Duix.Avatar mode |
| HIGH | clear | MEMORY_PROVIDER | `activeloopai/hivemind` | Apache-2.0 |
| HIGH | isolate | REJECT_DUPLICATE | `Fosowl/agenticSeek` | GPL-3.0 |
| HIGH | clear | REJECT_SECURITY | `PleasePrompto/notebooklm-skill` | MIT |
| HIGH | clear | SECURITY_ACTIVE | `crowdsecurity/crowdsec` | MIT |
| HIGH | clear | SECURITY_ACTIVE | `usestrix/strix` | Apache-2.0 |
| MEDIUM | clear | AGENT_SKILL | `AgriciDaniel/claude-seo` | MIT |
| MEDIUM | clear | BROWSER_WORKER | `alibaba/page-agent` | MIT |
| MEDIUM | review | EXPERIMENTAL | `Lifeforge-app/lifeforge` | CC BY-NC-SA 4.0 |
| MEDIUM | clear | HUMAN_INTERACTIVE_ONLY | `Andyyyy64/whichllm` | MIT |
| MEDIUM | isolate | HUMAN_INTERACTIVE_ONLY | `LostRuins/koboldcpp` | AGPL-3.0 |
| MEDIUM | isolate | HUMAN_INTERACTIVE_ONLY | `oobabooga/text-generation-webui` | AGPL-3.0 |
| MEDIUM | isolate | HUMAN_INTERACTIVE_ONLY | `yuka-friends/Windrecorder` | GPL-2.0 |
| MEDIUM | clear | MCP | `t8y2/dbx` | Apache-2.0 |
| MEDIUM | clear | MEDIA_TOOL | `cosmicstack-labs/lazy-frames` | MIT |
| MEDIUM | clear | MEDIA_TOOL | `presenton/presenton` | Apache-2.0 |
| MEDIUM | clear | MODEL_ROUTER | `BerriAI/litellm` | MIT |
| MEDIUM | review | MODEL_RUNTIME | `modular/modular` | Repo + Mojo language: Ap |
| MEDIUM | clear | OUTPUT_STYLE | `xr0zv/no-ai-slop` | MIT |
| MEDIUM | review | REJECT_DUPLICATE | `activepieces/activepieces` | MIT |
| MEDIUM | clear | REJECT_DUPLICATE | `ItzCrazyKns/Vane` | MIT |
| MEDIUM | isolate | REJECT_DUPLICATE | `KnockOutEZ/wigolo` | AGPL-3.0-only |
| MEDIUM | clear | REJECT_DUPLICATE | `massgen/MassGen` | Apache-2.0 |
| MEDIUM | clear | REJECT_DUPLICATE | `Mintplex-Labs/anything-llm` | MIT |
| MEDIUM | review | SELF_HOSTED_SERVICE | `baidu/Unlimited-OCR` | Repo code MIT |
| MEDIUM | isolate | SELF_HOSTED_SERVICE | `bitwarden/server` | AGPL-3.0 |
| MEDIUM | review | SELF_HOSTED_SERVICE | `chatwoot/chatwoot` | MIT Expat |
| MEDIUM | clear | SELF_HOSTED_SERVICE | `every-app/open-seo` | MIT |
| MEDIUM | isolate | SELF_HOSTED_SERVICE | `gitroomhq/postiz-app` | AGPL-3.0 |
| MEDIUM | review | SELF_HOSTED_SERVICE | `goauthentik/authentik` | MIT |
| MEDIUM | review | SELF_HOSTED_SERVICE | `medusajs/medusa` | MIT |
| MEDIUM | review | SELF_HOSTED_SERVICE | `nocodb/nocodb` | Sustainable Use License |
| MEDIUM | clear | SELF_HOSTED_SERVICE | `usekaneo/kaneo` | MIT |
| MEDIUM | clear | TOKEN_OPTIMIZER | `microsoft/LLMLingua` | MIT |
| MEDIUM | clear | TOKEN_OPTIMIZER | `zilliztech/GPTCache` | MIT |
| LOW | review | AGENT_SKILL | `anthropics/skills` | Apache-2.0 |
| LOW | clear | AGENT_SKILL | `XBuilderLAB/cheat-on-content` | MIT |
| LOW | clear | DESIGN_TOOL | `excalidraw/excalidraw` | MIT |
| LOW | clear | DESIGN_TOOL | `Nutlope/hallmark` | MIT |
| LOW | review | DESIGN_TOOL | `op7418/guizang-ppt-skill` | AGPL-3.0 |
| LOW | clear | ENGINEERING_POLICY | `DietrichGebert/ponytail` | MIT |
| LOW | clear | ENGINEERING_POLICY | `github/spec-kit` | MIT |
| LOW | clear | ENGINEERING_POLICY | `goldbergyoni/javascript-testing-best-practices` | MIT |
| LOW | clear | ENGINEERING_POLICY | `ryanmcdermott/clean-code-javascript` | MIT |
| LOW | clear | EXPERIMENTAL | `karpathy/nanoGPT` | MIT |
| LOW | clear | HUMAN_INTERACTIVE_ONLY | `dlvhdr/gh-dash` | MIT |
| LOW | clear | HUMAN_INTERACTIVE_ONLY | `janhq/jan` | Apache-2.0 |
| LOW | clear | INFRA_TOOL | `DioxusLabs/dioxus` | MIT OR Apache-2.0 |
| LOW | review | KNOWLEDGE_PACK | `awesome-selfhosted/awesome-selfhosted` | CC-BY-SA-3.0 |
| LOW | clear | KNOWLEDGE_PACK | `vinta/awesome-python` | CC-BY-4.0 |
| LOW | clear | MCP | `haris-musa/excel-mcp-server` | MIT |
| LOW | clear | MODEL_RUNTIME | `dottxt-ai/outlines` | Apache-2.0 |
| LOW | review | OUTPUT_STYLE | `alexgreensh/attention-span` | AGPL-3.0 |
| LOW | clear | REFERENCE_PACK | `ComposioHQ/awesome-claude-skills` | Apache-2.0 |
| LOW | clear | REFERENCE_PACK | `muratcankoylan/Agent-Skills-for-Context-Engineering` | MIT |
| LOW | clear | REFERENCE_PACK | `realworld-apps/realworld` | MIT |
| LOW | clear | REJECT_DUPLICATE | `tirth8205/code-review-graph` | MIT |
| LOW | isolate | SELF_HOSTED_SERVICE | `chartdb/chartdb` | AGPL-3.0 |
| LOW | isolate | SELF_HOSTED_SERVICE | `knadh/listmonk` | AGPL-3.0 |
| LOW | review | SELF_HOSTED_SERVICE | `languagetool-org/languagetool` | LGPL-2.1-or-later |
| LOW | clear | SELF_HOSTED_SERVICE | `louislam/uptime-kuma` | MIT |
| LOW | clear | TOKEN_OPTIMIZER | `openai/tiktoken` | MIT |

## C. Intake rules applied (§4–8, §57–58)
- **No candidate auto-installs.** DISCOVERED → source-verify → license → static inspect → dependency review → **Bumblebee/supply-chain scan (§6)** → sandbox install → network observation → health → tests → promotion.
- **No `curl|bash` / `irm|iex`** for certified installs (§6, §81) — package-manager / source-build only.
- **Duplicates** of the 126 (Section A) are REJECT_DUPLICATE for intake — they are already governed; no second copy.
- **AGPL/copyleft** (e.g. many self-hosted services) → `SERVICE_ISOLATION_REQUIRED` / `LICENSE_REVIEW_REQUIRED`; run isolated, never bundle into a shipped proprietary product without review (§5). No legal claims beyond the license text.
- Every skill/README/MCP-description = **UNTRUSTED_EXTERNAL_INSTRUCTION** (§58) — cannot override policy/security/financial gates.
