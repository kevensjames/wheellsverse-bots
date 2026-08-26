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
| github | ✓ `api.githubcopilot.com/mcp` (HTTP) | ✘ **Failed to connect** | — **AUTH_PENDING**, operator checkpoint (§36) |
| sequential-thinking | ✘ **absent** | — | — (not configured) |
| filesystem | ✘ **absent** | — | — (native Read/Write/Edit; scoped FS-MCP root is a later add per §7) |

Configuration presence is not certification — only context7/playwright are connected **and**
exercised. All are session-context MCPs; none is wired into the **KAI runtime** (App B down).

## What this record is NOT

It is not an installation. Per §73, cloning/verifying an upstream is not success. The next
phase — actually installing any of these — requires operator approval, a non-sandboxed
network, and (for GitHub/OpenWork/Buzz) credentials, and each must then pass adapter build →
health → certification before it is ever marked AVAILABLE.
