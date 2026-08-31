# KAI Capability Fabric — Ledger (§71) + Certification (§74)

Honest state, per directive §73/§74: **cloning/verifying an upstream is not success**, and no
row is forced to PASS. As of **2026-08-26**, branch `feat/kai-capability-fabric`.

## Fabric core certification (§74)

The governed **core is built and tested** (48 pure tests, 0 failures). Live integrations that
require a running KAI runtime, real installs, or a browser are honestly PENDING/EXTERNAL_BLOCKED.

| component | state | evidence |
|-----------|-------|----------|
| Capability Registry (§15) | **PASS** | `registry.py`, tests |
| Capability Brain (§16) | **PASS** | `brain.py`, routing tests |
| Capability Graph (§17) | **PASS** | `graph.py`, closure/cycle/conflict tests |
| Automatic Selection (§28) | **PASS** | weighted scoring + observable rationale, §65 tests |
| Automatic Activation (§18/§20) | **PASS (logic)** | lifecycle state machine; live activation needs a runtime |
| Automatic Deactivation (§19) | **PASS** | `deactivate()` maps every trigger to a teardown |
| Dependency Resolution (§60) | **PASS** | REQUIRES closure, deps-first ordering |
| Conflict Resolution (§61) | **PASS** | conflict/alternative collapse |
| Resource Policy (§26) | **PASS (logic)** | resource filter; live metering not wired |
| Security Policy (§25) | **PASS** | `evaluate_policy` + tests |
| RBAC (§22) | **PASS** | scope/role gating in the policy |
| Approval Gates (§25) | **PASS** | REQUIRE_APPROVAL tiers |
| Prompt Injection (§24) | **PASS** | untrusted-by-default + `scan_for_injection` (all fields) + inert proposals |
| Principal Propagation (§17) | **PASS** | `invocation.py` — every call carries principal/mission/correlation; no anonymous calls; forged request scopes ignored |
| Plugin-to-plugin control (§18) | **PASS** | `route_capability_proposal` — a proposal is gated by policy, never a direct A→B grant |
| Governed invocation (§16) | **PASS** | `governed_invoke` — DENY never executes, REQUIRE_APPROVAL returns inert proposal, oversized result clamped |
| Secret Isolation (§50) | **PARTIAL** | broker designed in docs; not wired to a live secret store |
| Audit (§59) | **PARTIAL** | event taxonomy defined; sink wiring EXTERNAL_BLOCKED (App B down) |
| Nexus Integration (§54–58) | **PARTIAL** | `kai-nexus-capabilities.js` panel + honest catalog snapshot built + tested (no fake READY, credential-redacted inspector, §57 categories); live Nexus tab wiring pending |
| Mission Integration (§58) | **PARTIAL** | correlation model defined; live mission wiring pending |
| Claude Code Integration (§32/§72) | **PARTIAL** | CLAUDE.md routing section added; MCP installs EXTERNAL_BLOCKED |

## Per-capability ledger (§71)

`UV`=upstream-verified · `SR`=security-reviewed (doc-level) · `INS`=installed · `ADP`=adapter
built · `CC`=Claude-Code-available · `KAI`=KAI-runtime-available · `AR`=auto-routing ·
`TST`=integration-tested · `CERT`=§74 final. `—`=no, `✓`=yes, `~`=partial.

| capability | UV | SR | INS | ADP | CC | KAI | AR | TST | CERT |
|-----------|----|----|-----|-----|----|----|----|-----|------|
| kai-memory (native) | ✓ | ✓ | ✓ | ~ | — | ✓ | ✓ | ~ | **CERTIFIED** |
| claude-code (native) | ✓ | ✓ | ✓ | ~ | ✓ | ✓ | ✓ | ~ | **CERTIFIED** |
| context7 | ✓ | ✓ | ✓* | — | ✓ | — | ✓ | ✓* | **CERTIFIED (Claude Code layer)** — connected + exercised + auto-routes; caveats: unpinned npx (§3/§9), KAI-runtime EXTERNAL_BLOCKED (§13) |
| playwright | ✓ | ✓ | ✓* | — | ✓ | — | ✓ | ✓* | **CERTIFIED_LOCAL_STAGING** — exercised at 3440/1920/390 (no overflow); auto-routes; inspection READ_ONLY, prod mutation approval-gated; unpinned npx (§3), KAI EXTERNAL_BLOCKED (§13) |
| sequential-thinking | ✓ | ✓ | ✓ | — | ✓(connected) | — | — | — | **PARTIAL** — configured+connected (pinned 2026.7.4); exercise + CERTIFIED_INTERNAL pending restart |
| filesystem | ✓ | ✓ | ✓ | — | ✓(connected) | — | — | — | **PARTIAL** — configured+connected (pinned 2026.7.10, root-scoped); traversal tests + CERTIFIED_SCOPED pending restart |
| github | ✓ | ✓ | — | — | — | — | — | — | **AUTH_PENDING** — remote Copilot MCP fails; replace with local stdio `github/github-mcp-server` (operator: binary + OAuth) |
| focus-output (i-have-adhd) | ✓ | ✓ | — | — | — | — | — | — | **EXPERIMENTAL** |
| book-to-skill | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** |
| reverse-skill | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** (RESTRICTED, vet-only) |
| ai-fundamentals | ✓ | ✓ | — | — | — | — | — | — | **EXPERIMENTAL** (reference-only) |
| tencentdb-memory | ✓ | ✓ | — | — | — | — | — | — | **EXPERIMENTAL** (arch-dependent; not adopted) |
| openwork | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** |
| buzz | ✓ | ✓ | — | — | — | — | — | — | **EXPERIMENTAL** (resolved, disabled) |
| airllm | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** |
| ollama | ~ | ✓ | — | — | — | — | — | — | **EXPERIMENTAL** (incumbent, not re-verified) |
| jcode | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** (HIGH — curl\|bash) |
| geolibre | ✓ | ✓ | — | — | — | — | — | — | **EXTERNAL_BLOCKED** |

\* context7 / playwright are **live in the Claude Code session** (used this session), not in the
KAI runtime (App B Docker-down).

## Adversarial review (§67)

**Round 1 (partial — hit the session usage limit):** 2 confirmed + 1 independently confirmed →
risk.py pre-approval target gate, results.py summary-only scan, brain.py dependency ALLOW bypass.

**Round 2 — COMPLETE §67 battery re-run** at SHA `68f6c49` (5 lenses × ~30 vectors, refute-biased,
21 agents, 0 errors): **13 confirmed (1 critical, 3 high, 8 medium, 1 low), 3 correctly refuted,
0 unverified.** All 13 fixed with a regression test each (reproduce → fix → re-run). Highlights:

- **CRITICAL** `invocation.py::route_capability_proposal` — a malicious plugin could label a
  DESTRUCTIVE proposal `READ_ONLY` (fail-open default) and get it ALLOWed with no target/approval.
  **Fixed** — the action tier now comes from the TRUSTED manifest (`_trusted_action_class`): a
  proposal may only escalate; a missing label uses the declared class; an invalid one → PROHIBITED.
- **HIGH** `invocation.py::governed_invoke` — a hostile adapter could return `authorized=True` /
  `trust='TRUSTED'` / empty flags. **Fixed** — `sanitize_external_result` forces every adapter
  result UNTRUSTED + unauthorized and re-scans it; the fabric, never the adapter, owns trust.
- **HIGH** `lifecycle.py` quarantine split-brain — a lifecycle-quarantined capability could still
  run. **Fixed** — `governed_invoke` consults lifecycle state and DENYs QUARANTINED/FAILED/STOPPING/OFFLINE.
- **HIGH** `brain.py` — the §26 resource filter was skipped for dependencies. **Fixed** — deps face
  the same VRAM/RAM/GPU + §61 conflict + §25 policy gates, or are BLOCKED with a fallback.
- **MEDIUM** — structured/nested/zero-width injection evaded `repr()` scanning (**fixed** — recursive
  leaf walk + NFKC + cross-element concat); adapter crashes propagated with secrets in the message
  (**fixed** — caught, redacted to the exception type only, failure audit emitted); no timeout
  (**fixed** — `manifest.timeout_ms` enforced under a deadline + deactivation); GPU never enforced;
  oversized `data`/`evidence` unbounded; `deactivate` no teardown (all fixed).

The 3 REFUTED (no locking in a single-threaded model; no failure backoff; a duplicate re-stamp
finding) were correctly not fixed. **22 regression tests added across rounds → 73 capability tests.**

## Expansion Pack (AppLlama + security fabric + HERO + Empire)

New governance shipped + tested (pure `security.py` + manifest tiers; 13 security + expansion tests):
Security-tier model (§17) **PASS** · least-power selection (§18) **PASS** · AuthorizedTarget allowlist
(§32) **PASS** · Empire full-envelope gate + never-auto (§14/§23/§31) **PASS** · HERO precedence (§11)
**PASS** (never trims a load-bearing security concern). All 8 upstreams verified; none installed.

| capability | tier | type | status |
|-----------|------|------|--------|
| hero | 0 | AGENT_BEHAVIOR_POLICY | **CERTIFIED_POLICY** (integrated into CLAUDE.md; precedence enforced) |
| appllama | 0 | AGENT_SKILL | **EXPERIMENTAL** — verified, not installed (needs external Appllama MCP + paid acct) |
| awesome-osint | 1 | OSINT_RESOURCE_PACK | **EXPERIMENTAL** — verified, not installed; lawful public info only |
| awesome-hacking | 0 | SECURITY_KNOWLEDGE_PACK | **EXPERIMENTAL** — canonical Hack-with-Github (0x4D31 is a 404) |
| payloads-all-the-things | 2 | SECURITY_KNOWLEDGE_PACK | **EXTERNAL_BLOCKED** — authorized-mission only; never auto-loaded |
| seclists | 2 | SECURITY_DATA_PACK | **EXTERNAL_BLOCKED** — authorized-mission only; never auto-loaded |
| cybersecurity-reference | 0 | SECURITY_KNOWLEDGE_PACK | **UPSTREAM_UNRESOLVED** → DISABLED |
| empire | 4 | SECURITY_EXECUTION_FRAMEWORK | **DISABLED_RESTRICTED_LAB_ONLY** — never auto; full envelope + sandbox + approval |

## Coding Agent Pool (§10–§16)

`CodingWorkerRouter` shipped + tested (`coding.py`): selection by measured §11 factors — **no
hard-coded winner** (a provider-pinned or parallel task routes away from the CERTIFIED default);
interactive-only excluded from unattended missions; no silent model switch (§19). §14 action
classes (merge=DESTRUCTIVE, branch-protection=PROHIBITED). §16 doctrine — a worker **never
certifies itself** (independent review + passing tests required; "done" without tests is never
trusted). §12/§13 one isolated worktree/branch per writable worker. 12 coding + adversarial tests.

| worker | status |
|--------|--------|
| claude-code | **AVAILABLE / PRIMARY** (native) |
| codex · cline · gemini-cli · github-copilot-cli · jcode | **EXPERIMENTAL** — verified, not installed → not auto-routed live |
| windsurf | **HUMAN_INTERACTIVE_ONLY** (Devin Desktop, GUI-only; never unattended) |
| roo | **REJECTED / DISABLED** — archived; successor Kilo Code not adopted |

## What blocks CERTIFIED for the external capabilities

1. **No network in the Bash sandbox** → cannot install (pip/npm/git clone/`claude mcp add`).
2. **KAI runtime (App B) is Docker-down** → no live host to wire adapters into.
3. **Env-mutation + credentials require operator approval** (§1/§76) → `claude mcp add`,
   `curl|bash` installers, and GitHub/OpenWork/Buzz credentials are not autonomous actions.

The path to CERTIFIED per capability: install (approved) → build adapter → health check →
auto-routing verified live → integration-tested → certify. None may be forced (§74).

---

# MEGA-EXPANSION (§6–65) — live-web verified 2026-08-31

93 additional candidates were verified against the **live web** by 7 parallel researchers
(strict *verify-or-`UPSTREAM_UNRESOLVED`, never fabricate*). All were added to `seed.py` as
**DISCOVERED** (upstream verified, NOT installed) — the catalog grew **32 → 126** with the
honest-READY invariant intact: **still exactly 5 AVAILABLE**. Nothing installed, nothing
deployed, no production change. Money mode remains MOCK; **0** financial executions.

**Catalog roll-up (126):** AVAILABLE 5 · DISCOVERED 121 — CERTIFIED 5 · PARTIAL 2 ·
EXTERNAL_BLOCKED 41 · EXPERIMENTAL 61 · UPSTREAM_UNRESOLVED 5 · REJECTED 12.
**False READY states: 0. Restricted auto-executions: 0.**

## Per-candidate ledger (§99) — one row per candidate, nothing dropped

### §7 Knowledge / Reference (all KNOWLEDGE_PACK, REFERENCE_ONLY, DISCOVERED)
| candidate | canonical | state / note |
|---|---|---|
| public-apis | public-apis/public-apis (MIT) | REFERENCE — discovery catalog; validate each API before use (§58) |
| developer-roadmap | nilbuild/developer-roadmap | **MOVED + RESTRICTED/DISABLED** — license forbids content ingest; link-only |
| free-programming-books | EbookFoundation/… (CC-BY-4.0) | REFERENCE |
| build-your-own-x | codecrafters-io/… (CC0) | REFERENCE |
| system-design-primer | donnemartin/… (CC-BY-4.0) | REFERENCE |
| coding-interview-university | jwasham/… (CC-BY-SA) | REFERENCE — stale 2024-12, stable |
| the-art-of-command-line | jlevy/… (CC-BY-SA) | REFERENCE — stale 2023-07 |
| project-based-learning | practical-tutorials/… (MIT) | REFERENCE |
| you-dont-know-js | getify/… (CC-BY-NC-ND) | REFERENCE — no commercial/derivatives; read+attribute only |
| the-book-of-secret-knowledge | trimstray/… (MIT) | REFERENCE — stale 2024-11 |
| tech-interview-handbook | yangshun/… (MIT) | REFERENCE |
| freecodecamp | freeCodeCamp/… | REFERENCE — index curriculum prose only, never run the app |
| javascript-algorithms | trekhleb/… (MIT) | REFERENCE |
| 30-seconds-of-code | Chalarangelo/… (CC-BY-4.0) | REFERENCE |
| gitignore | github/gitignore (CC0) | REFERENCE |

### §8/§18/§20/§53 Documents · Code-intelligence · RAG · Memory
| candidate | canonical | disposition |
|---|---|---|
| markitdown | microsoft/markitdown (MIT) | **ADOPT** — broadens ingestion (audio/img/YouTube/EPub) → RAG |
| codebase-memory-mcp | DeusData/… (MIT) | **ADOPT (PRIMARY)** — fills semantic-code-search gap; 100% local |
| claude-context | zilliztech/… (MIT) | RESTRICTED — cloud embeddings; local Ollama+Milvus only |
| codegraph | colbymchenry/codegraph (MIT) | REFERENCE — near-dup alternative; anomalous stars |
| llama_index | run-llama/… (MIT) | **REJECT_DUPLICATE** — KAI RAG |
| ragflow | infiniflow/… (Apache-2.0) | **REJECT_DUPLICATE** — heavy stack |
| supermemory | supermemoryai/… (MIT) | **REJECT_DUPLICATE** — kai-memory |
| mem0 (“memo”) | mem0ai/mem0 (Apache-2.0) | **REJECT_DUPLICATE** — kai-memory; no “memOai/memo” exists |
| brain.md | mindmuxai/brain.md (Apache-2.0) | REFERENCE — name-collision w/ mi4uu/brain.md, pin exact |
| openwiki | langchain-ai/openwiki (MIT) | REFERENCE — self-directed agent; overlaps KAI doc-gen |

### §12/§13 Models / Inference / Routers
| candidate | canonical | disposition |
|---|---|---|
| transformers | huggingface/transformers (Apache-2.0) | ADOPT — heavy, GPU, resource-gated |
| vllm | vllm-project/vllm (Apache-2.0) | ADOPT — GPU serving behind KAI router |
| llama.cpp | **ggml-org**/llama.cpp (MIT) | ADOPT — lightest, CPU-ok (canonical MOVED from ggerganov) |
| DeepSeek V4 | deepseek-ai/DeepSeek-V4 (MIT) | REFERENCE — ~893GB, hosted-API only |
| Bonsai-27B | prism-ml/Bonsai-27B (Apache-2.0) | REFERENCE — exotic 1-bit weights, unverified claims |
| nanochat | karpathy/nanochat (MIT) | REFERENCE — educational |
| Open-Gen-AI | — | **UPSTREAM_UNRESOLVED** — generic name, no clean match |
| free-llm-api-resources | cheahjs/… **(REMOVED, 404)** | **UPSTREAM_UNRESOLVED** — ⚠ namesake of `feat/kai-freellmapi`; canonical gone |
| 9Router | decolua/9router (MIT) | EXPERIMENTAL_PROVIDER_GATEWAY — HIGH; holds all keys, ToS risk |
| OmniRoute (provider) | diegosouzapw/OmniRoute (MIT) | EXPERIMENTAL_PROVIDER_GATEWAY — HIGH; **disambiguated** from geo |
| Kronos | shiyu-coder/Kronos (MIT) | REFERENCE — financial forecast model; signal ≠ order |

### §10/§36 Browser · Web-data · OSINT · AI-security
| candidate | canonical | disposition |
|---|---|---|
| stagehand | browserbase/stagehand (MIT) | REFERENCE — AI layer over seeded playwright |
| browser-use | browser-use/… (MIT) | REFERENCE — cloud tier markets stealth (don’t use) |
| firecrawl | firecrawl/firecrawl (AGPL-3.0) | **ADOPT** — web→RAG crawl gap; isolated self-host/hosted |
| Scrapling | D4Vinci/Scrapling (BSD-3) | **RESTRICTED (EVASION)** — Cloudflare bypass |
| Camoufox | daijro/camoufox (MPL-2.0) | **RESTRICTED (EVASION)** — anti-detect Firefox binary |
| Agent-Reach | Panniantong/Agent-Reach (MIT) | **RESTRICTED** — stores platform cookies, bypasses APIs |
| yt-dlp | yt-dlp/yt-dlp (Unlicense) | ADOPT — authorized content only |
| Maigret | soxoj/maigret (MIT) | ADOPT — username OSINT (tier 1, privacy-classified) |
| Flowsint | reconurge/flowsint (Apache-2.0) | REFERENCE — heavy OSINT stack |
| Bumblebee | perplexityai/bumblebee (Apache-2.0) | **ADOPT** — read-only supply-chain scanner → install gate (§39/§82) |
| iFixAI | ifixai-ai/iFixAi (Apache-2.0) | RESTRICTED — tier-3 AI red-teaming; anomalous stars |
| future-agi | future-agi/… (Apache-2.0) | REFERENCE — eval platform; reuse SDK only |

### §14–17/§40/§46/§47 Agent frameworks · Coding workers · Sandbox · Workflow
| candidate | canonical | disposition |
|---|---|---|
| langchain / langgraph | langchain-ai/* (MIT) | REUSE_LIBRARY — never a second brain |
| autogen | microsoft/autogen (MIT) | **UNMAINTAINED** → REFERENCE (maintenance mode) |
| crewAI | crewAIInc/crewAI (MIT) | REUSE_LIBRARY |
| MetaGPT | FoundationAgents/MetaGPT (MIT) | REFERENCE (MOVED from geekan) |
| DeerFlow | bytedance/deer-flow (MIT) | REFERENCE — HIGH; rival super-agent |
| Goose | **aaif-goose**/goose (Apache-2.0) | USE_AS_WORKER (MOVED from block; govern+sandbox) |
| OpenHands | All-Hands-AI/OpenHands (MIT) | USE_AS_WORKER — Docker sandbox required |
| ruflo | ruvnet/ruflo (MIT) | **REJECT_DUPLICATE** — HIGH; unbounded swarm brain |
| n8n | n8n-io/n8n (fair-code) | ADAPTER_ONLY — isolated service |
| openclaw | openclaw/openclaw (MIT) | **REJECT_DUPLICATE** — HIGH; host-shell rival brain |
| Aider | Aider-AI/aider (Apache-2.0) | USE_AS_WORKER |
| Dyad | dyad-sh/dyad (Apache-2.0+FSL) | REFERENCE — GUI builder |
| Orca | stablyai/orca (MIT) | REFERENCE — overlaps CodingWorkerRouter |
| claude-task-master | eyaltoledano/… (MIT+Commons) | REUSE_LIBRARY — overlaps Missions/sequential-thinking |
| Daytona | daytonaio/daytona (AGPL) | **ARCHIVED** → REFERENCE (colima incumbent) |
| Nango | NangoHQ/nango (Elastic-2.0) | ADAPTER_ONLY — credential broker, compare before adopt |

### §23/§26/§27/§28 Design · Media · Voice
| candidate | canonical | disposition |
|---|---|---|
| three.js / GSAP | mrdoob/three.js (MIT) · greensock/GSAP (non-OSI) | REFERENCE — front-end libraries |
| Genjutsu | AThevon/genjutsu (MIT) | ADOPT — creative-coding skill; review before load |
| Penpot | penpot/penpot (MPL-2.0) | HUMAN_INTERACTIVE — design workspace |
| ai-website-cloner | JCodesMore/… (MIT) | RESTRICTED — authorized/owned sites; original output only (§24) |
| ComfyUI | comfyanonymous/ComfyUI (GPL-3.0) | ADOPT — isolated, **vetted custom-nodes only** |
| HyperFrames | heygen-com/hyperframes (Apache-2.0) | ADOPT — HTML→video, deterministic (pin heygen-com) |
| OpenMontage | calesthio/OpenMontage (AGPL) | RESTRICTED — HIGH; fork-farm, pin canonical |
| MoneyPrinterTurbo | harry0703/… (MIT) | REFERENCE — spam vector, no auto-publish |
| Whisper (local) | openai/whisper (MIT) | ADOPT — local STT gap; reuse KAI voice layer |
| VoxCPM2 | OpenBMB/VoxCPM (Apache-2.0) | RESTRICTED — voice-clone deepfake risk |
| Pipecat | pipecat-ai/pipecat (BSD-2) | ADOPT — realtime voice transport under KAI controller |
| Meetily | Zackriya-Solutions/meetily (MIT) | HUMAN_INTERACTIVE — action items → ActionProposal (§51) |

### §30–34/§62/§63/§75/§76 Marketing · Ads · Analytics · Finance · Commerce · Workspace · UI
| candidate | canonical | disposition |
|---|---|---|
| ai-marketing-skills | ericosiu/… (MIT) | RESTRICTED — read/draft only; no autonomous outbound/spend |
| Claude Ads | ambiguous community forks | **UPSTREAM_UNRESOLVED** — NOT official; dup native ads |
| ViralityAI | viralityai.net (SaaS) | HUMAN_INTERACTIVE — no public API |
| Playto | playto.so (SaaS) | **REJECT_DUPLICATE** — vs Stripe/Dwolla/SOL; no API |
| Plausible | plausible/analytics (AGPL) | SERVICE_CONNECTOR — read-only aggregate stats |
| TradingAgents | TauricResearch/… (Apache-2.0) | RESTRICTED — research/paper only |
| Vibe Trading | HKUDS/Vibe-Trading (MIT) | **RESTRICTED — live exec PROHIBITED_INITIALLY** (real brokers) |
| Fincept Terminal | Fincept-Corp/… (AGPL) | REFERENCE — desktop, no API; live=Enterprise DISABLED |
| Abacus AI | abacus.ai (proprietary) | SERVICE_CONNECTOR (RESTRICTED) — paid/egress; overlaps FreeLLMAPI |
| Dify | langgenius/dify | REFERENCE — duplicates orchestration |
| Langflow | langflow-ai/langflow (MIT) | REFERENCE — HIGH; unauth-RCE history, security-scan |
| Open WebUI | open-webui/… | **REJECT_DUPLICATE** — Nexus |
| LobeChat | lobehub/lobe-chat | **REJECT_DUPLICATE** — Nexus |
| Appwrite | appwrite/appwrite (BSD-3) | REFERENCE — KAI has own backend |
| AppFlowy | AppFlowy-IO/… (AGPL) | HUMAN_INTERACTIVE — no automation API |

### §56 Web-design prompt pack
| candidate | disposition |
|---|---|
| website.{premium_architect,hero_strategist,homepage_conversion,portfolio_designer,service_landing,about_story,mobile_optimizer,full_copywriter,landing_architect,premium_ux} | **UPSTREAM_UNRESOLVED** — declared as one skill pack; instruction bodies pending (operator message truncated) |

## Fabric-core re-certification (mega-expansion, §74/§88)
| check | state | evidence |
|---|---|---|
| Capability suite | **PASS** | 7/7 files, **59 pure tests** (48 + 11 new invariants), 0 fail |
| No fake READY | **PASS** | only 5 AVAILABLE after +93; `t_megaexpansion_nothing_new_is_available` |
| Evasion tools locked | **PASS** | Scrapling/Camoufox/Agent-Reach RESTRICTED+DISABLED, never auto |
| Money safety | **PASS** | TradingAgents/Vibe-Trading DISABLED+never-auto; live exec PROHIBITED; MOCK |
| Duplicates rejected | **PASS** | 12 REJECTED, DISABLED, not selectable |
| Unresolved assert no source | **PASS** | claude-ads/open-gen-ai/free-llm-api-resources/website-design-skills carry no upstream |
| Wrong-tool avoidance | **PASS** | `2+2`→∅; heavy-model/finance prompts select no uninstalled tool |
| Nexus catalog | **PASS** | regenerated 126, Nexus JS 7/7 (no fake READY, RESTRICTED distinct, no secrets) |

**Not installed / not deployed / not certified-live** — every external capability stays DISCOVERED
until the operator-approved install → adapter → health → live-route → integration-test path runs.
This is a catalog wave (§93 Wave A), honestly bounded.

---

# WAVE B (§93) — first real install + certification, 2026-08-31

Promoted the top safe gap from DISCOVERED to genuinely certified. **One capability, end-to-end.**

## markitdown — ✅ CERTIFIED_LOCAL (commit 5b4c2f2)
Full path walked, with evidence: **install** (`markitdown 0.1.7`, isolated cert venv) → **adapter**
(`MarkItDownAdapter`, LIBRARY transport, `live_adapters.py`) → **health** (READY where installed,
OFFLINE-honest where absent) → **invoke** (real HTML→markdown incl. tables) → **normalize**
(ARTIFACT, `trust=UNTRUSTED`; a hostile document raised `injection_flags`, §24) → **tests**
(`test_capability_live_markitdown.py`, 6/6 in cert venv AND 6/6 on base python — no fabrication either
way). Manifest → **AVAILABLE + CERTIFIED**; AVAILABLE set is now the honest **6**. Nexus shows it READY.
**Caveat (honest):** installed in the cert venv only — NOT in the deployed App B runtime. To make it
live in prod: `pip install markitdown` on App B + redeploy. Until then its adapter reports OFFLINE there.

## codebase-memory-mcp — ⏸ install recipe RESOLVED, certification OPERATOR-GATED
It is a **prebuilt native C binary** from a small publisher (npm `codebase-memory-mcp` / pip / brew /
GitHub Releases; the `curl|bash` installer is forbidden §81). Autonomously downloading + executing an
unreviewed native binary — or `claude mcp add` (which mutates this session's own MCP config) — is
**refused** per §81/§83/§84 and the standing "no unreviewed execution" rule. **This is the rule working,
not a blocker to paper over.** Path to certify (operator-approved): review the publisher **or**
build-from-source → **bumblebee** supply-chain scan (§82) → start as an isolated subprocess + MCP
handshake → `claude mcp add` / App B wiring → live index+query test. Stays DISCOVERED until then.

**Wave B state:** 1 capability CERTIFIED_LOCAL, 1 correctly gated. AVAILABLE 5→6. 0 unreviewed binaries
run. 0 prod change. MONEY_MODE=MOCK.
