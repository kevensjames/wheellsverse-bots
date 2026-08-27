# KAI Capability Fabric — Upstream Verification Record (§1)

Read-only verification sweep, **2026-08-26**. Every candidate was inspected via its
canonical repository (README / LICENSE / manifests / release tags) using WebFetch — **nothing
was cloned, installed, or executed.** The screenshots that seeded this program were treated as
discovery inputs, not trusted install instructions.

> **Environment reality:** the Bash sandbox has **no outbound network**, and the KAI runtime
> (App B) is Docker-down. Therefore **no capability was installed** and none is live in the
> KAI runtime. Installation, `claude mcp add`, and any `curl|bash` installer are
> **EXTERNAL_BLOCKED** here and are, by directive (§1, §69, §76), gated behind explicit
> operator approval regardless. WebFetch (a separate transport) *does* have network, which is
> what made read-only verification possible.

## Verified capabilities

| id | canonical upstream | owner | license | type | risk | install | key finding |
|----|--------------------|-------|---------|------|------|---------|-------------|
| focus-output (i-have-adhd) | github.com/ayghri/i-have-adhd | ayghri | MIT | AGENT_SKILL | LOW | claude plugin / local hook | **Not** a medical tool — an action-first **output-shaping** ruleset. No network, no telemetry (all 3 hook impls inspected). §2 → `FOCUS_OUTPUT_MODE`. |
| book-to-skill | github.com/virgiliojr94/book-to-skill | virgiliojr94 | MIT | AGENT_SKILL | MEDIUM | `npx skills add` / git clone | Local extraction; does **not** fetch copyrighted content by default. Distilling an untrusted doc is a **prompt-injection surface** → human-review generated skills. |
| reverse-skill | github.com/zhaoxuya520/reverse-skill | zhaoxuya520 | MIT + GPLv3 + AGPL-3.0 | SECURITY_ROUTER | **RESTRICTED** | git clone + tool-index scripts | Ships **offensive** tooling (pentest / attack-chain / EDR-bypass / pwn). "Vet-only, do not wire as-is." Scope-gate is the only built-in control. |
| ai-fundamentals | github.com/microsoft/AI-For-Beginners | microsoft | MIT | KNOWLEDGE_PACK | LOW | reference-only | A 24-lesson curriculum. **Not a runtime** — reference selected authorized material only. |
| tencentdb-memory | github.com/TencentCloud/TencentDB-Agent-Memory | TencentCloud | MIT | MEMORY_PROVIDER | MEDIUM | git clone + self-host (SQLite/Docker) | Layered memory + compression; local SQLite default. **Repo documents NO user/team isolation** — KAI must supply per-tenant namespacing. **Must not co-own canonical memory** (§31). |
| openwork | github.com/different-ai/openwork | different-ai | MIT + EE (source-available) | WORKSPACE_ADAPTER | MEDIUM | reuse as external MCP | Exposes a clean **MCP surface** (`search_capabilities` / `execute_capability`) → reuse-as-MCP, do not embed runtime. Routes via vendor Den control plane + per-user OAuth. |
| buzz | github.com/block/buzz | block | Apache-2.0 | COLLABORATION_TOOL | MEDIUM | git clone + build / Docker / hosted | **Canonical RESOLVED** (directive feared it unresolved). Nostr-based; "agents are members." Heavy external platform — kept DISABLED; ALTERNATIVE to OpenWork. |
| airllm | github.com/lyogavin/airllm | lyogavin | Apache-2.0 | MODEL_RUNTIME | MEDIUM | pip | Layer-by-layer local inference (70B on 4GB VRAM). **Benchmark before production — not assumed faster than Ollama.** Downloads weights from HF. |
| ollama | (incumbent local provider) | — | — | MODEL_RUNTIME | LOW | — | Incumbent; ALTERNATIVE to AirLLM and its default fallback (§30). |
| jcode | github.com/1jehuang/jcode | 1jehuang | MIT | CODE_TOOL | **HIGH** | **curl\|bash** (jcode.sh) / brew / cargo | A Claude Code *competitor* CLI; multi-provider, needs credentials. HIGH because it ships a `curl\|bash` installer — inspect before any install. Never final authority. |
| geolibre | github.com/opengeos/GeoLibre | opengeos | MIT | GEOSPATIAL_TOOL | MEDIUM | desktop/web/pip (Tauri) | **The `taka015/geolibre` hint was a FORK** — canonical is opengeos/GeoLibre (6.7k★). Local-first WASM GIS; preserve location provenance. |

## MCP superstack — INSPECTED via `claude mcp list` (§2, 2026-08-26, not assumed)

| id | configured | connected | exercised |
|----|-----------|-----------|-----------|
| context7 | ✓ `npx @upstash/context7-mcp` | ✓ | ✓ **returned current FastAPI lifespan docs** (source fastapi.tiangolo.com, incl. the 0.93.0 release note) — READ_ONLY/ON_DEMAND/LOW |
| playwright | ✓ `npx @playwright/mcp@latest` | ✓ | ✓ (Avatar Lab, this session) |
| sequential-thinking | ✓ `@modelcontextprotocol/server-sequential-thinking@2026.7.4` (npx, PINNED) | ✓ **Connected** | — exercise + CERTIFIED_INTERNAL pending one restart (tools load at session start) |
| filesystem | ✓ `@modelcontextprotocol/server-filesystem@2026.7.10` (npx, PINNED, **root-scoped** to the KAI worktree) | ✓ **Connected** | — traversal tests + CERTIFIED_SCOPED pending one restart |
| github (remote plugin) | ✓ `api.githubcopilot.com/mcp` (HTTP, plugin-managed) | ✘ **Failed to connect** | **replace** with the official local stdio `github/github-mcp-server` (operator: install release binary + OAuth) |

Configuration presence is not certification — only context7/playwright are connected **and**
exercised. All are session-context MCPs; none is wired into the **KAI runtime** (App B down).

## Expansion Pack — verified (read-only sweep, 2026-08-26)

| id | canonical upstream | owner | license | type | tier | risk | key finding |
|----|--------------------|-------|---------|------|------|------|-------------|
| appllama | github.com/Appllama/appllama-skills | Appllama | MIT | AGENT_SKILL | 0 | LOW | Mobile-design agent skill (no offensive execution). Full research features need the **external** Appllama MCP + a **paid Pro account** — vendor egress/auth caveat. |
| hero | github.com/wanshuiyin/HERO-Anti-OverDefense | wanshuiyin | MIT | AGENT_BEHAVIOR_POLICY | 0 | LOW | Pure **policy text** (RULES.md), no runtime. Integrated into CLAUDE.md; can never suppress a load-bearing security concern. |
| awesome-osint | github.com/jivoi/awesome-osint | jivoi | CC-BY-SA-4.0 | OSINT_RESOURCE_PACK | 1 | MEDIUM | Curated OSINT link list; lawful public info only. |
| awesome-hacking | github.com/Hack-with-Github/Awesome-Hacking | Hack-with-Github | CC0-1.0 | SECURITY_KNOWLEDGE_PACK | 0 | LOW | **Canonical RESOLVED** — the `0x4D31/awesome-hacking` candidate is a **404**. Meta-list of links, no code. |
| cybersecurity-reference | **UNRESOLVED** | — | — | SECURITY_KNOWLEDGE_PACK | 0 | LOW | "The Ultimate Cybersecurity Reference Guide" is a generic phrase, not a unique repo → **UPSTREAM_UNRESOLVED / DISABLED**. |
| payloads-all-the-things | github.com/swisskyrepo/PayloadsAllTheThings | swisskyrepo | MIT | SECURITY_KNOWLEDGE_PACK | 2 | HIGH | Offensive payload/methodology **reference DATA**, not an attack engine. Authorized-mission only; never auto-loaded. |
| seclists | github.com/danielmiessler/SecLists | danielmiessler | MIT | SECURITY_DATA_PACK | 2 | HIGH | Wordlists/leaked-password corpora/web-shell samples (AV-false-positive prone). **DATA** only; authorized-mission only. |
| empire | github.com/BC-SECURITY/Empire | BC-SECURITY | BSD-3-Clause | SECURITY_EXECUTION_FRAMEWORK | 4 | RESTRICTED | **Executes** real post-exploitation C2 / adversary emulation (v6.7.1). DISABLED_RESTRICTED_LAB_ONLY; never auto-activated; full envelope + sandbox + approval required. |

## Coding Agent Pool — verified (read-only sweep, 2026-08-26)

| id | canonical upstream | license | class | headless | key finding |
|----|--------------------|---------|-------|----------|-------------|
| claude-code | (native) | — | CODING_WORKER | yes | PRIMARY engineering/certification worker; may delegate bounded subtasks. |
| codex | github.com/openai/codex | Apache-2.0 | CODING_WORKER | yes (`codex exec`) | v0.150.0; npm/brew preferred — **curl\|bash installer FLAGGED**. OpenAI auth. Cloud "Codex Web" variant. |
| cline | github.com/cline/cline | Apache-2.0 | CODING_WORKER | yes (CLI `--json` + `@cline/sdk`) | Multi-provider BYO key; npm, no curl\|bash; parallel-capable. |
| gemini-cli | github.com/google-gemini/gemini-cli | Apache-2.0 | CODING_CLI | yes (`-p --output-format json`) | v0.57.0; npm/brew; Google-only; **use stable, not nightly** (§6). |
| github-copilot-cli | github.com/github/copilot-cli | **Proprietary** | CODING_WORKER | yes (`-p`) | npm `@github/copilot` v1.0.80. The old `gh copilot` extension is **ARCHIVED/DEPRECATED**. Needs GitHub OAuth + Copilot license. |
| windsurf | devin.ai/desktop (Cognition) | Proprietary | CODING_IDE_ADAPTER | **NO (GUI-only)** | Rebranded Windsurf → **Devin Desktop**. **HUMAN_INTERACTIVE_ONLY** — cannot satisfy an unattended mission. |
| roo | github.com/RooCodeInc/Roo-Code | Apache-2.0 | — | n/a | **ARCHIVED** read-only since 2026-05-15 → DISABLED. Successor **Kilo Code** (Kilo-Org/kilocode, MIT) is a separate product, not adopted. |
| jcode | github.com/1jehuang/jcode | MIT | CODING_WORKER | yes | v0.81.1; HIGH — **curl\|bash installer**; bounded lightweight worker only. |

## What this record is NOT

It is not an installation. Per §73, cloning/verifying an upstream is not success. The next
phase — actually installing any of these — requires operator approval, a non-sandboxed
network, and (for GitHub/OpenWork/Buzz) credentials, and each must then pass adapter build →
health → certification before it is ever marked AVAILABLE.
