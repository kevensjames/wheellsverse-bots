"""KAI Capability Fabric — seeded capability catalog (§14/§53/§74).

The catalog the Nexus panel, ledger, and docs reflect. Every entry carries VERIFIED
provenance from the read-only §1 upstream sweep (2026-08-26). Statuses are HONEST:

  - Nothing external is installed in this environment (sandboxed network) and the KAI
    runtime (App B) is Docker-down, so every external capability is DISCOVERED (upstream
    verified, NOT installed) with certification EXTERNAL_BLOCKED / EXPERIMENTAL / etc.
    An external capability is therefore NOT selectable — the Brain will not plan it until
    it is genuinely installed + healthy. That is the §73/§74 "never force PASS" rule in data.
  - Native KAI capabilities that already exist (KAI's own memory, the Claude Code engine)
    are AVAILABLE / CERTIFIED.

Verification date is passed as a constant (no clock in pure modules).
"""
from __future__ import annotations

from .manifest import (
    CapabilityManifest as CM, CapabilityType as CT, RiskClass as RK, ActionClass as AC,
    ActivationMode as AM, Availability as AV, Certification as CE, ResourceProfile, Provenance,
    WorkerProfile,
)
from .registry import CapabilityRegistry
from .graph import CapabilityGraph, Relation

VERIFIED_AT = "2026-08-26"


def _prov(upstream, owner, lic, ref, install, verified=True):
    return Provenance(upstream=upstream, owner=owner, license=lic, ref=ref,
                      install_method=install, verified=verified, verified_at=VERIFIED_AT)


VERIFIED_AT_2 = "2026-08-31"   # §6-65 mega-expansion live-web verification sweep (7 parallel researchers)


def _prov2(upstream, owner, lic, ref, install, verified=True):
    return Provenance(upstream=upstream, owner=owner, license=lic, ref=ref,
                      install_method=install, verified=verified, verified_at=VERIFIED_AT_2)


def seed_manifests() -> list[CM]:
    return [
        # ── native KAI capabilities (genuinely available) ──────────────────────
        CM(id="kai-memory", name="KAI Memory", type=CT.NATIVE_KAI_TOOL, version="native",
           availability=AV.AVAILABLE, certification=CE.CERTIFIED, activation=AM.ALWAYS_AVAILABLE,
           risk_class=RK.LOW, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["long_term_memory", "recall", "persist"],
           triggers=["remember", "memory", "recall", "what we learned"],
           notes="Canonical source of truth for long-term memory (§31). One writer only."),
        CM(id="claude-code", name="Claude Code", type=CT.CODING_WORKER, version="native",
           availability=AV.AVAILABLE, certification=CE.CERTIFIED, activation=AM.ALWAYS_AVAILABLE,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["implement", "refactor", "engineer"],
           triggers=["implement", "refactor", "fix the bug", "write code"],
           worker_profile=WorkerProfile(coding_modes=["implement", "review", "debug", "test"],
                                        headless_support=True, workspace_support=True, git_support=True,
                                        tool_support=True, context_window=200000, model_provider="anthropic"),
           notes="PRIMARY engineering/certification worker (§2/§10/§40). May delegate bounded subtasks; "
                 "no worker merges/deploys independently."),

        # ── MCP superstack (§12/§42) — transports, not wired into the KAI runtime here ──
        CM(id="context7", name="Context7 MCP", type=CT.MCP, availability=AV.AVAILABLE,
           certification=CE.CERTIFIED, activation=AM.ON_DEMAND, risk_class=RK.LOW,
           default_action_class=AC.READ_ONLY, version="@upstash/context7-mcp (npx, UNPINNED)",
           capabilities=["library_docs", "api_reference"],
           triggers=["documentation", "docs", "library", "framework", "api reference"],
           provenance=_prov("https://github.com/upstash/context7", "upstash", "MIT", "",
                            "claude mcp (npx @upstash/context7-mcp)"),
           notes="§3 CERTIFIED at the Claude Code layer: connected + exercised (returned current "
                 "FastAPI lifespan docs w/ source fastapi.tiangolo.com), auto-routing proven. "
                 "CAVEATS: config uses UNPINNED npx (pin a version for the final config, §3/§9); "
                 "KAI-runtime (App B) wiring EXTERNAL_BLOCKED — Claude-Code layer only (§13)."),
        CM(id="playwright", name="Playwright MCP", type=CT.BROWSER_TOOL, availability=AV.AVAILABLE,
           certification=CE.CERTIFIED, activation=AM.ON_DEMAND, risk_class=RK.LOW,
           default_action_class=AC.READ_ONLY, version="@playwright/mcp (npx, UNPINNED)",
           capabilities=["browser_qa", "screenshot", "dom"],
           triggers=["browser", "mobile", "screenshot", "verify the page", "render"],
           provenance=_prov("https://github.com/microsoft/playwright-mcp", "microsoft", "Apache-2.0", "",
                            "claude mcp (npx @playwright/mcp)"),
           notes="§4 CERTIFIED_LOCAL_STAGING at the Claude Code layer: connected + exercised at "
                 "3440x1440 / 1920x1080 / 390x844 (no horizontal overflow; console inspection worked). "
                 "POLICY: local/staging only — inspection is READ_ONLY; local interaction REVERSIBLE_WRITE; "
                 "production mutation / deploy / merge is HIGH_IMPACT + approval-gated (§5/§16). "
                 "CAVEATS: unpinned npx (§3/§9); KAI-runtime EXTERNAL_BLOCKED (§13)."),
        CM(id="sequential-thinking", name="Sequential Thinking MCP", type=CT.MCP,
           availability=AV.DISCOVERED, certification=CE.PARTIAL, activation=AM.ON_DEMAND,
           version="@modelcontextprotocol/server-sequential-thinking@2026.7.4",
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, capabilities=["structured_planning"],
           triggers=["step by step", "think through", "plan the approach"],
           provenance=_prov("https://github.com/modelcontextprotocol/servers", "modelcontextprotocol",
                            "MIT", "server-sequential-thinking@2026.7.4", "claude mcp add (npx, PINNED)"),
           notes="§3: CONFIGURED + CONNECTED (pinned 2026.7.4, user config). INTERNAL_ONLY — raw reasoning "
                 "must NEVER reach Nexus/messages/memory/audit/TTS/subtitles (§4/§24). Exercise + "
                 "CERTIFIED_INTERNAL pending one Claude Code restart to load its tools."),
        CM(id="filesystem", name="Filesystem MCP", type=CT.MCP, availability=AV.DISCOVERED,
           certification=CE.PARTIAL, activation=AM.ON_DEMAND, risk_class=RK.MEDIUM,
           version="@modelcontextprotocol/server-filesystem@2026.7.10",
           default_action_class=AC.READ_ONLY, capabilities=["read_files", "search"],
           triggers=["repository", "codebase", "read the file", "project files"],
           permissions=["fs.workspace"],
           provenance=_prov("https://github.com/modelcontextprotocol/servers", "modelcontextprotocol",
                            "MIT", "server-filesystem@2026.7.10", "claude mcp add (npx, PINNED, root-scoped)"),
           notes="§5/§6: CONFIGURED + CONNECTED (pinned 2026.7.10), ROOT-SCOPED to the KAI worktree only. "
                 "NOT natively read-only — Phase-1 read-only = root containment + auto-allow READ ops only; "
                 "write=REVERSIBLE_WRITE (gated), delete=DESTRUCTIVE (denied). Traversal/symlink-escape + "
                 "CERTIFIED_SCOPED pending one restart to load its tools."),
        CM(id="github", name="GitHub MCP", type=CT.MCP, availability=AV.DISCOVERED,
           certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND, risk_class=RK.MEDIUM,
           default_action_class=AC.READ_ONLY, capabilities=["repo_read", "pr", "issues"],
           triggers=["github", "pull request", "commit", "open a pr"], permissions=["github.read"],
           notes="Needs a scoped credential via the broker (§50); PR/merge = HIGH_IMPACT, approval-gated."),

        # ── verified external repositories (upstream-verified, NOT installed) ──────
        CM(id="focus-output", name="Focus Output Mode (i-have-adhd)", type=CT.AGENT_SKILL,
           version="0.2.0", availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL,
           activation=AM.DISABLED, risk_class=RK.LOW, default_action_class=AC.READ_ONLY,
           capabilities=["concise_output", "action_first"], triggers=[],
           provenance=_prov("https://github.com/ayghri/i-have-adhd", "ayghri", "MIT",
                            "b42a45a", "claude plugin / local hook"),
           notes="§2: an OUTPUT_MODE, not a medical tool. No network/telemetry. Auto-select for "
                 "code remediation / deploy / incident tasks; never force terse for research/legal/safety."),
        CM(id="book-to-skill", name="Book-to-Skill", type=CT.AGENT_SKILL, availability=AV.DISCOVERED,
           certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY, risk_class=RK.MEDIUM,
           default_action_class=AC.REVERSIBLE_WRITE, capabilities=["skill_compile", "document_distill"],
           triggers=["pdf", "book", "learn this document", "turn into a skill"],
           provenance=_prov("https://github.com/virgiliojr94/book-to-skill", "virgiliojr94", "MIT",
                            "8a2cae6", "npx skills add / git clone"),
           notes="§3/§34: authorized/open-license material ONLY. Distilling an untrusted doc is a "
                 "prompt-injection surface — human-review generated skills before load."),
        CM(id="reverse-skill", name="Reverse-Skill (Security Router)", type=CT.SECURITY_ROUTER,
           version="1.0.1", availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED,
           activation=AM.DISABLED, risk_class=RK.RESTRICTED, default_action_class=AC.READ_ONLY,
           capabilities=["reverse_analysis", "malware_analysis", "code_audit"],
           triggers=["reverse engineer", "analyze this binary", "malware", "security audit"],
           permissions=["security.authorized"],
           provenance=_prov("https://github.com/zhaoxuya520/reverse-skill", "zhaoxuya520",
                            "MIT/GPLv3/AGPL-3.0", "914f74a", "git clone + tool-index scripts"),
           notes="§4/§35: RESTRICTED. Ships OFFENSIVE tooling — 'vet-only, do not wire as-is'. "
                 "Owned/authorized targets only; accessibility != authorization. SECURITY_GATED."),
        CM(id="ai-fundamentals", name="AI Fundamentals (AI-For-Beginners)", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY,
           capabilities=["ai_concepts", "neural_networks", "responsible_ai"],
           triggers=["ai fundamentals", "explain neural network", "ai concept", "responsible ai"],
           provenance=_prov("https://github.com/microsoft/AI-For-Beginners", "microsoft", "MIT",
                            "", "reference-only (no runtime)"),
           notes="§5: KNOWLEDGE_PACK, not a runtime. Reference selected authorized material."),
        CM(id="tencentdb-memory", name="TencentDB Agent Memory", type=CT.MEMORY_PROVIDER,
           version="2.0.0", availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL,
           activation=AM.MANUAL_ONLY, risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["layered_memory", "context_compression"], triggers=[],
           conflicts=["kai-memory"],
           provenance=_prov("https://github.com/TencentCloud/TencentDB-Agent-Memory", "TencentCloud",
                            "MIT", "v2.0.0", "git clone + self-host (SQLite/Docker)"),
           notes="§6/§31/§37: EXPERIMENTAL only. Repo documents NO user/team isolation — KAI must "
                 "supply per-tenant namespacing. Must NOT co-own canonical memory (conflicts kai-memory)."),
        CM(id="openwork", name="OpenWork", type=CT.WORKSPACE_ADAPTER, version="0.18.36",
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["shared_workspace", "skill_sharing"],
           triggers=["shared workspace", "share this workflow"],
           provenance=_prov("https://github.com/different-ai/openwork", "different-ai",
                            "MIT + EE (source-available)", "v0.18.36", "reuse as external MCP"),
           notes="§7: REUSE-AS-MCP (search_capabilities/execute_capability); do NOT embed runtime. "
                 "Routes via vendor Den control plane + per-user OAuth — never bypasses KAI governance."),
        CM(id="buzz", name="Buzz (block/buzz)", type=CT.COLLABORATION_TOOL, version="0.5.20",
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["agent_rooms", "signed_activity"], triggers=[], conflicts=[],
           provenance=_prov("https://github.com/block/buzz", "block", "Apache-2.0",
                            "desktop-v0.5.20", "git clone + build / Docker / hosted"),
           notes="§8: canonical RESOLVED to block/buzz (Nostr, signed events). Kept DISABLED — heavy "
                 "external platform; ALTERNATIVE to OpenWork, evaluate before enabling."),
        CM(id="airllm", name="AirLLM", type=CT.MODEL_RUNTIME, availability=AV.DISCOVERED,
           certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND, risk_class=RK.MEDIUM,
           default_action_class=AC.READ_ONLY, capabilities=["local_inference", "low_vram"],
           triggers=["run locally", "local model", "low vram", "offline model"],
           resource_profile=ResourceProfile(vram_mb=4000, gpu=True, heavy=True, network=True, est_latency_ms=6000),
           provenance=_prov("https://github.com/lyogavin/airllm", "lyogavin", "Apache-2.0", "", "pip"),
           notes="§9: layer-by-layer local inference (70B on 4GB). Benchmark before production — "
                 "NOT assumed faster than Ollama. Inference infra, not a brain."),
        CM(id="ollama", name="Ollama", type=CT.MODEL_RUNTIME, availability=AV.DISCOVERED,
           certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND, risk_class=RK.LOW,
           default_action_class=AC.READ_ONLY, capabilities=["local_inference"],
           triggers=["run locally", "local model", "offline model"],
           resource_profile=ResourceProfile(vram_mb=6000, gpu=True, est_latency_ms=1500),
           notes="Incumbent local provider (§30/§47). ALTERNATIVE to AirLLM; the default fallback."),
        CM(id="jcode", name="jcode (Lightweight Coding Worker)", type=CT.CODING_WORKER, version="0.81.1",
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND,
           risk_class=RK.HIGH, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["lightweight_coding", "parallel_scan"],
           triggers=["lightweight coding worker", "parallel repository scan"],
           worker_profile=WorkerProfile(coding_modes=["implement", "inspect"], headless_support=True,
                                        parallel_support=True, git_support=True, context_window=32000,
                                        model_provider=""),
           provenance=_prov("https://github.com/1jehuang/jcode", "1jehuang", "MIT", "v0.81.1",
                            "curl|bash (jcode.sh) / brew / cargo"),
           notes="§9/§10/§40: bounded lightweight worker, NOT a replacement for Claude Code; never final "
                 "authority. HIGH risk — ships a curl|bash installer; inspect before any install."),
        CM(id="geolibre", name="GeoLibre", type=CT.GEOSPATIAL_TOOL, version="2.7.0",
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY,
           capabilities=["gis", "map_layers", "spatial_query"],
           triggers=["map", "coordinates", "by region", "geospatial", "gis"],
           provenance=_prov("https://github.com/opengeos/GeoLibre", "opengeos", "MIT", "v2.7.0",
                            "desktop/web/pip (Tauri)"),
           notes="§11: canonical is opengeos/GeoLibre (the taka015 hint was a FORK). Preserve location "
                 "provenance; never fabricate coordinates. Integrate with World Mode."),

        # ── EXPANSION PACK — verified upstreams, NOT installed (§Expansion) ────────
        CM(id="appllama", name="AppLlama (Mobile Design Skills)", type=CT.AGENT_SKILL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["mobile_design_research", "onboarding_research", "paywall_research", "react_native_design"],
           triggers=["build mobile app", "mobile onboarding", "design mobile screen", "subscription flow",
                     "react native ui", "expo screen", "mobile ux"],
           provenance=_prov("https://github.com/Appllama/appllama-skills", "Appllama", "MIT", "4b54282",
                            "npx skills add appllama/appllama-skills"),
           notes="§2: mobile-app DESIGN agent skill (no offensive execution). Full research features need "
                 "the EXTERNAL Appllama MCP (mcp.appllama.io) + a paid Pro account — vendor egress/auth "
                 "caveat, not a security risk. §36: use for pattern research, never pixel-clone copyrighted apps."),
        CM(id="hero", name="HERO (Proportional Engineering Policy)", type=CT.AGENT_BEHAVIOR_POLICY,
           availability=AV.AVAILABLE, certification=CE.CERTIFIED, activation=AM.ALWAYS_AVAILABLE,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0, triggers=[],
           provenance=_prov("https://github.com/wanshuiyin/HERO-Anti-OverDefense", "wanshuiyin", "MIT",
                            "bfe4026", "paste-in policy text (no runtime)"),
           notes="§11/§12: a BEHAVIOR POLICY, not a tool — integrated into CLAUDE.md. Trims speculative "
                 "over-engineering but can NEVER suppress a load-bearing security/auth/financial/privacy/"
                 "production/verified-finding concern (enforced by security.hero_allows_reduction). "
                 "Precedence: system safety > security > regulatory > user > project > HERO."),
        CM(id="awesome-osint", name="Awesome OSINT", type=CT.OSINT_RESOURCE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=1,
           capabilities=["osint_resources", "public_research"],
           triggers=["osint", "open-source intel", "public research", "company research"],
           provenance=_prov("https://github.com/jivoi/awesome-osint", "jivoi", "CC-BY-SA-4.0", "374d93d",
                            "reference list (no runtime)"),
           notes="§8: curated OSINT resource list (tier 1). LAWFUL PUBLIC info only — never authorizes "
                 "credential theft, intrusion, private-data access, or doxxing. §35: OSINT results with "
                 "personal data must route through privacy classification before any memory write."),
        CM(id="awesome-hacking", name="Awesome-Hacking (Reference)", type=CT.SECURITY_KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["security_reference"],
           triggers=["security resources", "hacking reference", "security reading list"],
           provenance=_prov("https://github.com/Hack-with-Github/Awesome-Hacking", "Hack-with-Github", "CC0-1.0",
                            "", "reference meta-list (no runtime)"),
           notes="§9: canonical RESOLVED to Hack-with-Github/Awesome-Hacking (the 0x4D31 candidate is a 404). "
                 "A meta-list of links — no code, tier 0."),
        CM(id="payloads-all-the-things", name="PayloadsAllTheThings", type=CT.SECURITY_KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, security_tier=2,
           authorized_context_required=True, automatic_activation_allowed=False,
           permissions=["security.authorized"], capabilities=["web_security_payloads", "methodology"],
           triggers=["payload reference", "authorized web-security review"],
           provenance=_prov("https://github.com/swisskyrepo/PayloadsAllTheThings", "swisskyrepo", "MIT", "3bff425",
                            "git clone (markdown/payload reference)"),
           notes="§6: offensive payload/methodology REFERENCE (tier 2) — DATA, not an attack engine. "
                 "Never auto-loaded for ordinary work; requires an authorized security mission. Retrieve "
                 "only the needed subset; do not execute payloads because they exist. RISK HIGH."),
        CM(id="seclists", name="SecLists", type=CT.SECURITY_DATA_PACK,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, security_tier=2,
           authorized_context_required=True, automatic_activation_allowed=False,
           permissions=["security.authorized"], capabilities=["wordlists", "fuzzing_data"],
           triggers=["wordlist", "fuzzing data", "authorized discovery list"],
           provenance=_prov("https://github.com/danielmiessler/SecLists", "danielmiessler", "MIT", "2026.1",
                            "git clone (static data)"),
           notes="§7: security DATA pack (tier 2) — wordlists, leaked-password corpora, web-shell samples "
                 "(AV false-positive prone). Never auto-loaded; authorized mission only. Retrieve the "
                 "minimal subset; never surface sensitive list content unnecessarily. RISK HIGH."),
        CM(id="cybersecurity-reference", name="Cybersecurity Reference Guide", type=CT.SECURITY_KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.UPSTREAM_UNRESOLVED, activation=AM.DISABLED,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           automatic_activation_allowed=False, triggers=[],
           notes="§10: 'The Ultimate Cybersecurity Reference Guide' is a generic phrase, not a unique repo — "
                 "UPSTREAM_UNRESOLVED → DISABLED. Do not guess a canonical repo."),
        CM(id="empire", name="PowerShell Empire (Adversary Emulation)", type=CT.SECURITY_EXECUTION_FRAMEWORK,
           version="v6.7.1", availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.RESTRICTED, default_action_class=AC.HIGH_IMPACT, security_tier=4,
           authorized_context_required=True, target_allowlist_required=True, operator_approval_required=True,
           sandbox_required=True, automatic_activation_allowed=False, permissions=["security.redteam"],
           capabilities=["adversary_emulation", "c2", "post_exploitation"], triggers=[],
           provenance=_prov("https://github.com/BC-SECURITY/Empire", "BC-SECURITY", "BSD-3-Clause", "v6.7.1",
                            "git clone --recursive + ps-empire install (lab only)"),
           notes="§13-16: EXECUTING post-exploitation C2 (tier 4) — DISABLED_RESTRICTED_LAB_ONLY. NEVER "
                 "auto-activated (§23/§31); requires the FULL envelope — authorized security mission, "
                 "AuthorizedTarget on the allowlist, explicit high-impact approval, initialized sandbox, "
                 "network policy, audit. No internet-wide/production targeting, ever (§15). RISK RESTRICTED."),

        # ── CODING AGENT POOL — verified upstreams, NOT installed (§Coding) ────────
        CM(id="codex", name="OpenAI Codex", type=CT.CODING_WORKER, version="v0.150.0",
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["implement", "review", "test"], triggers=["implement", "generate tests"],
           worker_profile=WorkerProfile(coding_modes=["implement", "review", "test"], headless_support=True,
                                        git_support=True, tool_support=True, cloud_execution=True,
                                        context_window=192000, model_provider="openai"),
           provenance=_prov("https://github.com/openai/codex", "openai", "Apache-2.0", "v0.150.0",
                            "npm @openai/codex (PREFERRED) / brew — curl|bash installer FLAGGED, avoid"),
           notes="§3: CLI+IDE+cloud coding worker (`codex exec` headless). VERIFY_INSTALLATION via npm/brew, "
                 "NOT the curl|bash path (§9). Auth = ChatGPT sign-in or OpenAI key (operator, never in chat). "
                 "Cannot merge/deploy merely because it can modify code."),
        CM(id="cline", name="Cline", type=CT.CODING_WORKER, version="cli-3.0.60",
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["implement", "review"], triggers=["headless coding", "parallel coding task"],
           worker_profile=WorkerProfile(coding_modes=["implement", "review"], headless_support=True,
                                        parallel_support=True, git_support=True, tool_support=True,
                                        context_window=200000, model_provider=""),
           provenance=_prov("https://github.com/cline/cline", "Cline Bot Inc.", "Apache-2.0", "cli-v3.0.60",
                            "npm i -g cline / @cline/sdk (no curl|bash)"),
           notes="§4: headless CLI (`cline --json --auto-approve`) + SDK (@cline/sdk) — prefer SDK/CLI over "
                 "UI automation. Multi-provider BYO key (local Ollama needs none). Bounded workspace; no "
                 "unlimited shell/fs."),
        CM(id="gemini-cli", name="Gemini CLI", type=CT.CODING_CLI, version="v0.57.0",
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["implement"], triggers=["gemini coding"],
           worker_profile=WorkerProfile(coding_modes=["implement"], headless_support=True, git_support=True,
                                        context_window=1000000, model_provider="google"),
           provenance=_prov("https://github.com/google-gemini/gemini-cli", "google-gemini", "Apache-2.0",
                            "v0.57.0", "npm @google/gemini-cli / brew (stable only, NOT nightly §6)"),
           notes="§6: headless `gemini -p --output-format json`. Google-only; headless auth = GEMINI_API_KEY / "
                 "Vertex (OAuth is interactive). Use the STABLE channel in certified config, never nightly."),
        CM(id="github-copilot-cli", name="GitHub Copilot CLI", type=CT.CODING_WORKER, version="v1.0.80",
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["implement", "github_context"], triggers=["github coding task"],
           worker_profile=WorkerProfile(coding_modes=["implement", "review"], headless_support=True,
                                        git_support=True, context_window=128000, model_provider="github"),
           provenance=_prov("https://github.com/github/copilot-cli", "github", "Proprietary", "v1.0.80",
                            "npm @github/copilot / brew / winget"),
           notes="§5: GitHub-native (`copilot -p`). Canonical is github/copilot-cli — the old `gh copilot` "
                 "extension is ARCHIVED/DEPRECATED. Proprietary. VERIFY_AUTH: GitHub OAuth + Copilot license "
                 "(operator, never in chat). Initial mode REVERSIBLE_WRITE; PR merge governed separately."),
        CM(id="windsurf", name="Windsurf / Devin Desktop", type=CT.CODING_IDE_ADAPTER,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False,
           capabilities=["interactive_coding"], triggers=[],
           worker_profile=WorkerProfile(coding_modes=["implement"], headless_support=False,
                                        interactive_only=True, local_execution=True, model_provider=""),
           provenance=_prov("https://devin.ai/desktop", "Cognition", "Proprietary", "Devin-Desktop",
                            "signed desktop installer (GUI)"),
           notes="§7: HUMAN_INTERACTIVE_ONLY — GUI IDE (rebranded Windsurf→Devin Desktop; Cognition acquired "
                 "Codeium). No official headless/API interface → cannot satisfy an unattended mission. KAI may "
                 "prepare tasks/context for a human handoff; never claims autonomous execution."),
        CM(id="roo", name="Roo Code (archived)", type=CT.CODING_CLI,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False,
           capabilities=[], triggers=[],
           provenance=_prov("https://github.com/RooCodeInc/Roo-Code", "RooCodeInc", "Apache-2.0", "ARCHIVED",
                            "n/a — archived read-only 2026-05-15"),
           notes="§8: ARCHIVED (read-only since 2026-05-15) → DISABLED, do not certify. Successor is Kilo Code "
                 "(Kilo-Org/kilocode, MIT, @kilocode/cli) — a SEPARATE product, not adopted here; evaluate "
                 "independently before any use."),

        # ══════════════════════════════════════════════════════════════════════════
        # MEGA-EXPANSION (§6-65) — live-web verified 2026-08-31 by 7 parallel
        # researchers. Every entry is DISCOVERED (upstream verified, NOT installed);
        # nothing is AVAILABLE (the honest-READY invariant stays frozen at 5). States
        # are honest: REJECTED=duplicate/archived, UPSTREAM_UNRESOLVED=couldn't verify.
        # ══════════════════════════════════════════════════════════════════════════

        # ── §7 KNOWLEDGE / REFERENCE / LEARNING packs (reference-only, no runtime) ──
        CM(id="public-apis", name="Public APIs (catalog)", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["api_discovery", "public_api_catalog"],
           triggers=["public api", "free api", "is there an api for"],
           provenance=_prov2("https://github.com/public-apis/public-apis", "public-apis", "MIT", "", "reference list (no runtime)"),
           notes="§58: discovery catalog only. A listing is NOT a trusted provider — KAI independently "
                 "validates HTTPS/auth/terms/rate-limit/privacy before any production use of a named API."),
        CM(id="developer-roadmap", name="Developer Roadmaps (roadmap.sh)", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.DISABLED,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, security_tier=0,
           automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/nilbuild/developer-roadmap", "nilbuild (roadmap.sh)",
                             "Custom restrictive (no commercial/redistribution)", "", "LINK ONLY — do not ingest content"),
           notes="§7: MOVED kamranahmedse->nilbuild. LICENSE forbids content redistribution + commercial use -> "
                 "DISABLED for ingestion; may LINK to roadmap.sh only, never index the content. HIGH legal risk."),
        CM(id="free-programming-books", name="Free Programming Books", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["learning_resources"], triggers=["free book", "learn programming resource"],
           provenance=_prov2("https://github.com/EbookFoundation/free-programming-books", "EbookFoundation", "CC-BY-4.0", "", "reference list"),
           notes="§7: CC-BY-4.0 (attribution). Pure link/list content, no runtime."),
        CM(id="build-your-own-x", name="Build-Your-Own-X", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["from_scratch_tutorials"], triggers=["build your own", "from scratch tutorial"],
           provenance=_prov2("https://github.com/codecrafters-io/build-your-own-x", "CodeCrafters", "CC0-1.0", "", "reference list"),
           notes="§7: CC0 public domain. Curated 'build X from scratch' tutorial index."),
        CM(id="system-design-primer", name="System Design Primer", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["system_design", "architecture_reference"],
           triggers=["system design", "scalability", "design a large-scale system"],
           provenance=_prov2("https://github.com/donnemartin/system-design-primer", "Donne Martin", "CC-BY-4.0", "", "reference"),
           notes="§7: CC-BY-4.0. System-design study reference; retrieve slices, never dump."),
        CM(id="coding-interview-university", name="Coding Interview University", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["cs_study_plan"], triggers=["interview prep", "cs study plan"],
           provenance=_prov2("https://github.com/jwasham/coding-interview-university", "John Washam", "CC-BY-SA-4.0", "", "reference"),
           notes="§7: CC-BY-SA share-alike on derivatives. Stale (2024-12) but content-stable."),
        CM(id="the-art-of-command-line", name="The Art of Command Line", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["command_line_reference"], triggers=["command line", "shell tips", "cli reference"],
           provenance=_prov2("https://github.com/jlevy/the-art-of-command-line", "Joshua Levy", "CC-BY-SA-4.0", "", "reference"),
           notes="§7: CC-BY-SA. Stale (2023-07) but stable single-page CLI reference."),
        CM(id="project-based-learning", name="Project-Based Learning", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["project_tutorials"], triggers=["project tutorial", "learn by building"],
           provenance=_prov2("https://github.com/practical-tutorials/project-based-learning", "practical-tutorials", "MIT", "", "reference list"),
           notes="§7: MIT list of project-based tutorials by language."),
        CM(id="you-dont-know-js", name="You Don't Know JS (Yet)", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["javascript_deep_reference"], triggers=["javascript internals", "how does js work"],
           provenance=_prov2("https://github.com/getify/You-Dont-Know-JS", "Kyle Simpson", "CC-BY-NC-ND-4.0", "", "read + attribute only"),
           notes="§7: CC-BY-NC-ND — no commercial, NO derivatives. Read + attribute only; never transform/re-derive. "
                 "Author-frozen (complete, 2026-01), not neglected."),
        CM(id="book-of-secret-knowledge", name="The Book of Secret Knowledge", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["sysadmin_devops_reference", "cheatsheets"],
           triggers=["cheatsheet", "one-liner", "sysadmin reference", "devops tools"],
           provenance=_prov2("https://github.com/trimstray/the-book-of-secret-knowledge", "trimstray", "MIT", "", "reference list"),
           notes="§7/§36: MIT list of manuals/cheatsheets/CLI tools (sysadmin/devops/security). Stale (2024-11) but stable. "
                 "Broader than seeded awesome-hacking; a reference list, not an execution tool."),
        CM(id="tech-interview-handbook", name="Tech Interview Handbook", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["interview_prep"], triggers=["resume tips", "behavioral interview"],
           provenance=_prov2("https://github.com/yangshun/tech-interview-handbook", "Yangshun Tay", "MIT", "", "reference"),
           notes="§7: MIT interview-prep reference."),
        CM(id="freecodecamp", name="freeCodeCamp (curriculum)", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["coding_curriculum"], triggers=["learn to code", "coding curriculum"],
           provenance=_prov2("https://github.com/freeCodeCamp/freeCodeCamp", "freeCodeCamp.org", "BSD-3-Clause / CC-BY-SA (curriculum)", "", "index curriculum prose only"),
           notes="§7: index the CURRICULUM prose only; the repo is a large full-stack app — never install/run it as a runtime."),
        CM(id="javascript-algorithms", name="JavaScript Algorithms", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["algorithms_reference"], triggers=["algorithm", "data structure example"],
           provenance=_prov2("https://github.com/trekhleb/javascript-algorithms", "Oleksii Trekhleb", "MIT", "", "reference"),
           notes="§7: MIT algorithms/data-structures with explanations. Index as reference; don't run the test tooling."),
        CM(id="30-seconds-of-code", name="30 Seconds of Code", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["code_snippets"], triggers=["code snippet", "how do i in javascript"],
           provenance=_prov2("https://github.com/Chalarangelo/30-seconds-of-code", "Angelos Chalaris", "CC-BY-4.0", "", "reference"),
           notes="§7: CC-BY-4.0 short snippets/articles reference."),
        CM(id="gitignore-templates", name="gitignore Templates", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["gitignore_templates"], triggers=["gitignore", "ignore file template"],
           provenance=_prov2("https://github.com/github/gitignore", "GitHub", "CC0-1.0", "", "template data"),
           notes="§7: CC0 .gitignore templates. Pure config data."),

        # ── §8/§18/§20/§53 DOCUMENTS · CODE-INTELLIGENCE · RAG · MEMORY ──
        CM(id="markitdown", name="MarkItDown (document convert)", type=CT.CODE_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["document_convert", "pdf_to_markdown", "office_to_markdown", "media_to_markdown"],
           triggers=["convert to markdown", "pdf to structured", "turn this document into", "parse this file"],
           provenance=_prov2("https://github.com/microsoft/markitdown", "Microsoft", "MIT", "", "pip install markitdown"),
           notes="§8: ADOPT — broadens ingestion (audio/image/YouTube/EPub/ZIP) beyond KAI's native extractors; "
                 "feeds the existing RAG pipeline. Never overwrite source files. Sanitize untrusted input."),
        CM(id="codebase-memory-mcp", name="Codebase Memory MCP (code intelligence)", type=CT.MCP,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["semantic_code_search", "code_knowledge_graph", "impact_analysis"],
           triggers=["find in the codebase", "where is this defined", "trace this function", "code impact"],
           provenance=_prov2("https://github.com/DeusData/codebase-memory-mcp", "DeusData", "MIT", "", "MCP (build-from-source to de-risk binary)"),
           notes="§18: PRIMARY fill for KAI's genuine semantic-code-search GAP. 100% local, zero-cred, tree-sitter "
                 "graph (162 langs). Distributed as a prebuilt native binary from a small publisher -> prefer build-from-source."),
        CM(id="claude-context", name="Claude Context (semantic code search)", type=CT.MCP,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=0,
           automatic_activation_allowed=False, permissions=["code.local_only"],
           capabilities=["semantic_code_search"], triggers=[], fallback="codebase-memory-mcp",
           conflicts=["codebase-memory-mcp"],
           provenance=_prov2("https://github.com/zilliztech/claude-context", "zilliztech", "MIT", "", "MCP (local Ollama+Milvus mode only)"),
           notes="§18: RESTRICTED — default config sends code to CLOUD embeddings + cloud vector DB. Adopt ONLY in "
                 "local Ollama+Milvus mode; never let source leave the host. Alternative to codebase-memory-mcp."),
        CM(id="codegraph", name="CodeGraph (code knowledge graph)", type=CT.MCP,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=0,
           automatic_activation_allowed=False, conflicts=["codebase-memory-mcp"], triggers=[],
           capabilities=["code_knowledge_graph"], fallback="codebase-memory-mcp",
           provenance=_prov2("https://github.com/colbymchenry/codegraph", "colbymchenry", "MIT", "", "MCP (local)"),
           notes="§18/§53: near-duplicate ALTERNATIVE to codebase-memory-mcp (local Rust graph). Anomalous ~68.7k "
                 "stars for a young niche tool -> verify publisher authenticity before trust. Not a separate adoption."),
        CM(id="llama-index", name="LlamaIndex", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/run-llama/llama_index", "run-llama", "MIT", "", "REJECT_DUPLICATE (not installed)"),
           notes="§20/§54: REJECT_DUPLICATE — KAI already has chunk+embed+pgvector+citations RAG. LlamaIndex would "
                 "import a competing architecture with a huge dep surface. Reference only."),
        CM(id="ragflow", name="RAGFlow", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/infiniflow/ragflow", "infiniflow", "Apache-2.0", "v0.27.1", "REJECT_DUPLICATE (heavy Docker stack)"),
           notes="§54: REJECT_DUPLICATE — heavy multi-service stack (16GB RAM) + bundled code-exec sandbox for the same "
                 "job KAI's RAG does. Only narrow gap is reranking/deep-parse — not worth the stack. Reference only."),
        CM(id="supermemory", name="Supermemory", type=CT.MEMORY_PROVIDER,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False,
           conflicts=["kai-memory"], triggers=[],
           provenance=_prov2("https://github.com/supermemoryai/supermemory", "supermemoryai", "MIT", "", "REJECT_DUPLICATE"),
           notes="§19/§31: REJECT_DUPLICATE — KAI memory is the single canonical writer. Conflicts kai-memory."),
        CM(id="mem0", name="Mem0 (memo)", type=CT.MEMORY_PROVIDER,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False,
           conflicts=["kai-memory"], triggers=[],
           provenance=_prov2("https://github.com/mem0ai/mem0", "mem0ai", "Apache-2.0", "", "REJECT_DUPLICATE"),
           notes="§19/§31: REJECT_DUPLICATE — the 'memo' input resolves to Mem0 (no 'memOai/memo' exists). "
                 "Universal-memory layer duplicating kai-memory. Conflicts kai-memory."),
        CM(id="brain-md", name="brain.md (project brain)", type=CT.MEMORY_PROVIDER,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False,
           conflicts=["kai-memory"], triggers=[],
           provenance=_prov2("https://github.com/mindmuxai/brain.md", "mindmuxai", "Apache-2.0", "", "PIN exact repo (name collision)"),
           notes="§19: REFERENCE — durable-decisions-as-Markdown. NAME COLLISION with active mi4uu/brain.md (AGPL) — "
                 "PIN mindmuxai to avoid installing the wrong one. Must not co-own canonical memory (conflicts kai-memory)."),
        CM(id="openwiki", name="OpenWiki (repo docs generator)", type=CT.CODE_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/langchain-ai/openwiki", "langchain-ai", "MIT", "", "REFERENCE (runs a self-directed agent)"),
           notes="§18: REFERENCE — auto-maintains a Markdown wiki for a codebase, but runs its OWN self-directed agent "
                 "with broad provider/connector reach + its own creds. Overlaps KAI's agentic doc gen. Keep governed."),

        # ── §12/§13/§59 MODEL & INFERENCE RUNTIMES (heavy · resource-gated · dormant) ──
        CM(id="transformers", name="HuggingFace Transformers", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["local_inference", "training", "multimodal"], triggers=["run a huggingface model", "local transformer"],
           resource_profile=ResourceProfile(ram_mb=16000, vram_mb=16000, gpu=True, heavy=True, network=True, est_latency_ms=4000),
           provenance=_prov2("https://github.com/huggingface/transformers", "Hugging Face", "Apache-2.0", "", "pip"),
           notes="§12: ADOPT (optional heavy local serving). Resource Brain must check host GPU/RAM before activation. "
                 "Inference infra, NOT a brain; benchmark before production, never hard-code as 'best'."),
        CM(id="vllm", name="vLLM (serving engine)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["high_throughput_serving", "openai_compatible"], triggers=["serve a model", "high throughput inference"],
           resource_profile=ResourceProfile(ram_mb=32000, vram_mb=24000, gpu=True, heavy=True, network=True, est_latency_ms=800),
           provenance=_prov2("https://github.com/vllm-project/vllm", "vLLM project", "Apache-2.0", "", "pip / docker"),
           notes="§12: ADOPT (optional GPU serving). GPU effectively required (24GB+). OpenAI-compatible server can sit "
                 "BEHIND KAI's existing provider router. Resource-gated + dormant."),
        CM(id="llama-cpp", name="llama.cpp", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["local_inference", "gguf", "cpu_inference"], triggers=["run gguf", "cpu inference", "local model no gpu"],
           resource_profile=ResourceProfile(ram_mb=12000, gpu=False, heavy=True, est_latency_ms=2000),
           provenance=_prov2("https://github.com/ggml-org/llama.cpp", "ggml-org", "MIT", "", "build / brew"),
           notes="§12: ADOPT (lightest engine, CPU-friendly). Canonical MOVED ggerganov->ggml-org (old path redirects). "
                 "Alternative to seeded ollama/airllm; the CPU-only fallback."),
        CM(id="deepseek-v4", name="DeepSeek V4 (open weights)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=0, automatic_activation_allowed=False, triggers=[],
           resource_profile=ResourceProfile(vram_mb=640000, gpu=True, heavy=True, network=True),
           provenance=_prov2("https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-0813", "DeepSeek AI", "MIT (open weights)", "V4-Pro-0813", "hosted API only"),
           notes="§61: bare weights (~1.6-1.7T MoE, ~893GB), NOT a runtime. Realistic KAI use = hosted API; local self-host "
                 "needs a multi-GPU datacenter. Verify weights hash if ever hosted locally. Never hard-coded as 'best'."),
        CM(id="bonsai-27b", name="Bonsai-27B (1-bit/ternary)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=0, automatic_activation_allowed=False, triggers=[],
           resource_profile=ResourceProfile(ram_mb=9000, gpu=False, heavy=False),
           provenance=_prov2("https://huggingface.co/collections/prism-ml/bonsai-27b", "PrismML", "Apache-2.0", "2026-07-14", "HF weights + ternary runtime"),
           notes="§61: bare weights (exotic 1-bit/ternary), needs a compatible runtime (llama.cpp/BitNet/MLX). Brand-new "
                 "vendor; aggressive 'runs-on-a-phone / ~90-95% retained' claims UNVERIFIED — benchmark before trust."),
        CM(id="nanochat", name="nanochat (Karpathy)", type=CT.CODE_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/karpathy/nanochat", "Andrej Karpathy", "MIT", "a825e63", "git clone (educational)"),
           notes="§12: REFERENCE — minimal full-stack LLM training pipeline (~$100 to train). Educational; training needs "
                 "8xH100. Not a production runtime."),
        CM(id="open-gen-ai", name="Open-Gen-AI (unresolved)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.UPSTREAM_UNRESOLVED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           notes="§60: UPSTREAM_UNRESOLVED — the name is too generic; the closest match (anil-matcha/Open-Generative-AI) "
                 "is a cloud-first media-gen studio, a modality mismatch for the claimed 'local multimodal runtime'. "
                 "No canonical source verified -> DISABLED, no provenance asserted."),
        CM(id="free-llm-api-resources", name="Free LLM API Resources (catalog, upstream removed)", type=CT.KNOWLEDGE_PACK,
           availability=AV.DISCOVERED, certification=CE.UPSTREAM_UNRESOLVED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           notes="§13: MOVED/REMOVED — the canonical cheahjs/free-llm-api-resources now 404s (authenticated), no redirect; "
                 "only unaffiliated low-star re-uploads remain. This is the NAMESAKE of the feat/kai-freellmapi branch + "
                 "commit 3a9da00 FreeLLMAPI gateway -> FLAG to whoever owns that integration. No provenance asserted "
                 "(canonical gone). 'free/unlimited' listings are never auto-trusted (§13)."),
        CM(id="9router", name="9Router (provider gateway)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, security_tier=0, automatic_activation_allowed=False,
           permissions=["provider.keys"], triggers=[],
           provenance=_prov2("https://github.com/decolua/9router", "decolua", "MIT", "", "EXPERIMENTAL_PROVIDER_GATEWAY (privacy review)"),
           notes="§59: EXPERIMENTAL_PROVIDER_GATEWAY, HIGH risk — sits between KAI and providers so it sees ALL prompts + "
                 "holds ALL keys; multi-account round-robin/OAuth-refresh to farm free tiers = ToS risk; fork-farm provenance. "
                 "Do NOT place between KAI and sensitive data until privacy/security reviewed."),
        CM(id="omniroute-gateway", name="OmniRoute (provider gateway)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, security_tier=0, automatic_activation_allowed=False,
           permissions=["provider.keys"], triggers=[],
           provenance=_prov2("https://github.com/diegosouzapw/OmniRoute", "diegosouzapw", "MIT", "", "EXPERIMENTAL_PROVIDER_GATEWAY (privacy review)"),
           notes="§52/§59: EXPERIMENTAL_PROVIDER_GATEWAY, HIGH risk. NAMING COLLISION resolved: this is the AI-provider "
                 "router (id 'omniroute-gateway'), DISTINCT from any geospatial 'OmniRoute' (KAI's geo tool is geolibre). "
                 "Sibling of 9Router (shared marketing, fork-farm); proxies all prompts + holds keys. Privacy review required."),
        CM(id="kronos-finmodel", name="Kronos (financial forecast model)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=0, automatic_activation_allowed=False, triggers=[],
           resource_profile=ResourceProfile(ram_mb=4000, gpu=False),
           provenance=_prov2("https://github.com/shiyu-coder/Kronos", "shiyu-coder (AAAI 2026)", "MIT", "", "HF weights (research)"),
           notes="§34/§61: financial candlestick forecasting foundation model. FINANCIAL_RESEARCH only — a forecast is a "
                 "SIGNAL, never an order (§35). Real trading stays DISABLED until a separate financial-execution cert."),

        # ── §10/§36/§57 BROWSER · WEB-DATA · OSINT · AI-SECURITY ──
        CM(id="stagehand", name="Stagehand (AI browser)", type=CT.BROWSER_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False,
           conflicts=[], fallback="playwright", triggers=[],
           provenance=_prov2("https://github.com/browserbase/stagehand", "Browserbase", "MIT", "", "REFERENCE (AI layer over Playwright)"),
           notes="§10: REFERENCE — self-healing AI layer over the SAME engine KAI already has (playwright). Full features "
                 "tie to Browserbase cloud + LLM keys. Adopt only if autonomous multi-step nav is genuinely needed."),
        CM(id="browser-use", name="browser-use (AI browser agent)", type=CT.BROWSER_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=2, automatic_activation_allowed=False,
           fallback="playwright", triggers=[],
           provenance=_prov2("https://github.com/browser-use/browser-use", "browser-use", "MIT", "", "REFERENCE (LLM autonomy over Playwright)"),
           notes="§10/§11: REFERENCE — LLM autonomy layer over Playwright. CAUTION: the hosted Cloud tier markets "
                 "stealth fingerprinting + CAPTCHA solving + proxy rotation, which KAI must NOT use (§11)."),
        CM(id="firecrawl", name="Firecrawl (web -> RAG)", type=CT.BROWSER_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=1,
           capabilities=["web_crawl", "site_to_markdown", "structured_extract"],
           triggers=["crawl this site", "scrape into markdown", "extract the whole website"],
           provenance=_prov2("https://github.com/firecrawl/firecrawl", "Firecrawl (ex-mendableai)", "AGPL-3.0 core / MIT SDKs", "", "hosted API or isolated self-host"),
           notes="§10/§20: ADOPT — fills the web->RAG CRAWL gap KAI lacks (KAI has only single-page fetch). AGPL-3.0 core "
                 "is an embed/license consideration -> prefer the hosted API or an ISOLATED self-host, not in-process. "
                 "PRODUCES WebDocument -> consumed by the RAG pipeline. robots/terms respected (§57)."),
        CM(id="scrapling", name="Scrapling (adaptive scraper)", type=CT.BROWSER_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.RESTRICTED, default_action_class=AC.READ_ONLY, security_tier=3,
           automatic_activation_allowed=False, permissions=["security.authorized"], triggers=[],
           provenance=_prov2("https://github.com/D4Vinci/Scrapling", "D4Vinci", "BSD-3-Clause", "", "RESTRICTED (evasion)"),
           notes="§11: RESTRICTED (EVASION) — core selling point is anti-bot/CAPTCHA bypass (StealthyFetcher, Cloudflare "
                 "Turnstile). KAI must NOT use stealth to bypass access controls. DISABLED; never auto-activated."),
        CM(id="camoufox", name="Camoufox (anti-detect Firefox)", type=CT.BROWSER_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.RESTRICTED, default_action_class=AC.READ_ONLY, security_tier=3,
           automatic_activation_allowed=False, permissions=["security.authorized"], triggers=[],
           provenance=_prov2("https://github.com/daijro/camoufox", "daijro", "MPL-2.0", "", "RESTRICTED (evasion)"),
           notes="§11: RESTRICTED (EVASION), HIGH — purpose IS fingerprint spoofing/anti-detection; distributes an opaque "
                 "patched Firefox C++ binary. Circumvents access controls -> DISABLED, never auto-activated."),
        CM(id="agent-reach", name="Agent-Reach (platform access CLI)", type=CT.BROWSER_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.RESTRICTED, default_action_class=AC.READ_ONLY, security_tier=1,
           automatic_activation_allowed=False, permissions=["security.authorized"], triggers=[],
           provenance=_prov2("https://github.com/Panniantong/Agent-Reach", "Panniantong", "MIT", "", "RESTRICTED (bypasses official APIs)"),
           notes="§11/§57: RESTRICTED, HIGH — bypasses official platform APIs/fees via browser automation + STORES platform "
                 "login cookies; bundles many third-party CLIs/MCPs (broad supply-chain surface). KAI prefers official APIs; "
                 "never bypass auth/ToS. DISABLED."),
        CM(id="yt-dlp", name="yt-dlp (authorized media)", type=CT.CODE_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=1, automatic_activation_allowed=False,
           capabilities=["media_download"], triggers=[],
           provenance=_prov2("https://github.com/yt-dlp/yt-dlp", "yt-dlp", "Unlicense", "", "pip / binary"),
           notes="§27/§80: ADOPT for AUTHORIZED content retrieval only (operator owns/is-authorized). Not a piracy workflow. "
                 "Manual-only; no auto-publish of retrieved media."),
        CM(id="maigret", name="Maigret (username OSINT)", type=CT.OSINT_RESOURCE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=1,
           automatic_activation_allowed=False, permissions=["security.authorized"], triggers=[],
           provenance=_prov2("https://github.com/soxoj/maigret", "soxoj", "MIT", "", "pip (authorized OSINT)"),
           notes="§36: username OSINT across 3000+ sites (tier 1, passive public info). Profiles individuals -> AUTHORIZED "
                 "use only; results with personal data route through privacy classification before any memory write (§35)."),
        CM(id="flowsint", name="Flowsint (OSINT investigation graph)", type=CT.OSINT_RESOURCE_PACK,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, security_tier=1,
           automatic_activation_allowed=False, permissions=["security.authorized"], triggers=[],
           provenance=_prov2("https://github.com/reconurge/flowsint", "reconurge", "Apache-2.0", "", "REFERENCE (heavy self-host)"),
           notes="§36: REFERENCE — graph-based OSINT platform (Neo4j/Postgres/FastAPI), heavy self-hosted stack. "
                 "Authorized/lawful public info only; privacy-classified."),
        CM(id="bumblebee", name="Bumblebee (AI supply-chain scanner)", type=CT.CODE_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=1,
           capabilities=["supply_chain_scan", "dependency_audit"],
           triggers=["supply chain scan", "check for compromised packages", "dependency exposure"],
           provenance=_prov2("https://github.com/perplexityai/bumblebee", "Perplexity AI", "Apache-2.0", "v0.1.2", "Go binary (read-only)"),
           notes="§39/§82: ADOPT — read-only scanner of on-disk pkg/extension metadata for supply-chain exposure. Go, zero "
                 "non-stdlib deps, never runs install scripts. HIGH-LEVERAGE: candidate for the capability INSTALL GATE "
                 "(scan every new plugin/model/MCP before promotion). Young (v0.1.x)."),
        CM(id="ifixai", name="iFixAI (AI red-teaming)", type=CT.SECURITY_EXECUTION_FRAMEWORK,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.RESTRICTED, default_action_class=AC.HIGH_IMPACT, security_tier=3,
           authorized_context_required=True, operator_approval_required=True, sandbox_required=True,
           automatic_activation_allowed=False, permissions=["security.authorized"], triggers=[],
           provenance=_prov2("https://github.com/ifixai-ai/iFixAi", "ifixai-ai", "Apache-2.0", "", "RESTRICTED (adversarial testing)"),
           notes="§37/§38/§65: RESTRICTED (tier 3) — adversarial auditing/red-teaming of AI agents; runs adversarial prompts "
                 "+ hooks agent runtimes. Anomalous 11.9k-stars/88-commits -> human review before trust. A candidate agent "
                 "must NEVER control its own evaluator (§65). Authorized mission + approval + sandbox only."),
        CM(id="future-agi", name="Future AGI (eval/observability)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/future-agi/future-agi", "Future AGI", "Apache-2.0", "", "REFERENCE (Python SDK is the light piece)"),
           notes="§38/§65: REFERENCE — LLM eval/observability/guardrails platform. Heavy multi-lang stack; the Python "
                 "instrumentation SDK is the lighter adoptable piece. Compare vs KAI's own independent cert harness; "
                 "don't duplicate if KAI is stronger. Reuse individual eval components at most."),

        # ── §14-17/§40/§46/§47 AGENT FRAMEWORKS · CODING WORKERS · SANDBOX · WORKFLOW ──
        CM(id="langchain", name="LangChain (library)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/langchain-ai/langchain", "langchain-ai", "MIT", "", "REUSE_LIBRARY (never a second brain)"),
           notes="§14/§15: REUSE_LIBRARY — a library KAI could CALL, never a competing orchestrator. KAI is already the "
                 "orchestrator. Huge transitive dep surface; embed narrowly if ever needed."),
        CM(id="langgraph", name="LangGraph (library)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/langchain-ai/langgraph", "langchain-ai", "MIT", "", "REUSE_LIBRARY"),
           notes="§14/§15: REUSE_LIBRARY — the one ADAPT-worthy orchestration lib IF KAI's tool-loop/plan machine ever "
                 "needs durable branching. Embed as a library inside KAI's loop, never a rival control loop."),
        CM(id="autogen", name="AutoGen (maintenance mode)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/microsoft/autogen", "microsoft", "MIT", "", "REFERENCE (unmaintained/superseded)"),
           notes="§14/§15: REFERENCE — now in MAINTENANCE MODE (superseded by MS Agent Framework). Recursive multi-agent + "
                 "code exec = don't adopt as a live component."),
        CM(id="crewai", name="CrewAI (library)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/crewAIInc/crewAI", "crewAIInc", "MIT", "v0.102.0", "REUSE_LIBRARY"),
           notes="§14/§15: REUSE_LIBRARY — role-playing crews; embeddable but its autonomous crew loop + code exec must stay "
                 "governed, never a second brain."),
        CM(id="metagpt", name="MetaGPT (AI software company)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/FoundationAgents/MetaGPT", "FoundationAgents", "MIT", "", "REFERENCE (MOVED from geekan)"),
           notes="§14/§15: REFERENCE — heavyweight opinionated multi-agent orchestrator (a rival control loop); recursive "
                 "role spawning + code exec. MOVED geekan->FoundationAgents (old path redirects)."),
        CM(id="deerflow", name="DeerFlow (super-agent)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.DISABLED,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/bytedance/deer-flow", "bytedance", "MIT", "v2.0", "REFERENCE (rival orchestrator)"),
           notes="§15/§48: REFERENCE, HIGH — a full competing 'super-agent' that recursively spawns sub-agents (task tool) + "
                 "runs shell in sandboxes. Adopting it = a rival orchestrator. KAI's own research system already covers this."),
        CM(id="goose", name="Goose (coding worker)", type=CT.CODING_WORKER,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.HIGH, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False,
           capabilities=["implement", "execute", "edit", "test"], triggers=[],
           worker_profile=WorkerProfile(coding_modes=["implement", "test", "debug"], headless_support=True,
                                        git_support=True, tool_support=True, model_provider=""),
           provenance=_prov2("https://github.com/aaif-goose/goose", "aaif-goose (Linux Foundation)", "Apache-2.0", "", "USE_AS_WORKER (govern+sandbox)"),
           notes="§16/§47: USE_AS_WORKER under CodingWorkerRouter — legit coding agent, but runs host SHELL (sandboxing is "
                 "the operator's job) + loads MCP extensions. MOVED block/goose->aaif-goose (Apr 2026). Recipes are "
                 "externally-supplied capability defs, all governed by KAI. No autonomous merge/deploy."),
        CM(id="openhands", name="OpenHands (coding worker)", type=CT.CODING_WORKER,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.HIGH, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False,
           sandbox_required=True, capabilities=["implement", "execute", "test"], triggers=[],
           worker_profile=WorkerProfile(coding_modes=["implement", "test", "debug"], headless_support=True,
                                        git_support=True, tool_support=True, cloud_execution=True, model_provider=""),
           provenance=_prov2("https://github.com/All-Hands-AI/OpenHands", "All-Hands-AI", "MIT", "v1.16.0", "USE_AS_WORKER (Docker sandbox required)"),
           notes="§16/§46: USE_AS_WORKER — powerful coding agent with FULL filesystem access -> Docker sandbox REQUIRED. As "
                 "a 'control center' it can spawn other agents -> bound to worker role. No production merge/deploy rights."),
        CM(id="ruflo", name="ruflo (meta-orchestrator)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/ruvnet/ruflo", "ruvnet", "MIT", "v3.8.0", "REJECT_DUPLICATE (rival brain)"),
           notes="§15/§17: REJECT_DUPLICATE, HIGH — a competing meta-orchestrator that recursively spawns 100+ UNBOUNDED "
                 "swarm agents + self-modifying memory, wrapping the exact coding workers KAI already routes. All parallelism "
                 "must stay bounded by KAI's CodingWorkerRouter/concurrency budget (§17). Do not adopt as a brain."),
        CM(id="n8n", name="n8n (workflow automation)", type=CT.WORKSPACE_ADAPTER,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/n8n-io/n8n", "n8n-io", "Sustainable Use License (fair-code, non-OSI)", "", "ADAPTER_ONLY (isolated service)"),
           notes="§21: ADAPTER_ONLY — isolated workflow service OUTSIDE the agent loop; never bypasses KAI approval policy. "
                 "Source-available license restricts hosting-as-a-service. Large integration surface."),
        CM(id="openclaw", name="openclaw (personal agent)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/openclaw/openclaw", "openclaw", "MIT", "", "REJECT_DUPLICATE (host-shell rival)"),
           notes="§15: REJECT_DUPLICATE, HIGH — an autonomous personal-agent brain that runs host commands BY DEFAULT "
                 "(sandbox opt-in) with a messaging-app attack surface. A rival control loop; do not run."),
        CM(id="aider", name="Aider (pair-programming CLI)", type=CT.CODING_CLI,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False,
           capabilities=["implement", "edit"], triggers=[],
           worker_profile=WorkerProfile(coding_modes=["implement"], headless_support=True, git_support=True, model_provider=""),
           provenance=_prov2("https://github.com/Aider-AI/aider", "Aider-AI", "Apache-2.0", "", "USE_AS_WORKER"),
           notes="§16: USE_AS_WORKER under CodingWorkerRouter — mature single-brain CLI; runs shell/tests + auto-commits in "
                 "the project dir. Keep governed (no autonomous merge/deploy)."),
        CM(id="dyad", name="Dyad (local app builder)", type=CT.CODING_WORKER,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False,
           capabilities=["app_prototype"], triggers=[],
           worker_profile=WorkerProfile(coding_modes=["implement"], headless_support=False, interactive_only=True, model_provider=""),
           provenance=_prov2("https://github.com/dyad-sh/dyad", "dyad-sh", "Apache-2.0 + FSL-1.1 (src/pro)", "", "REFERENCE (GUI)"),
           notes="§55: REFERENCE — Electron GUI app builder, awkward to govern headless; prefer CodingWorkerRouter for real "
                 "repo work. FSL-1.1 on pro modules restricts commercial reuse."),
        CM(id="orca", name="Orca (parallel-agent IDE)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/stablyai/orca", "stablyai", "MIT", "v1.4.192", "REFERENCE (overlaps CodingWorkerRouter)"),
           notes="§17: REFERENCE — runs a fleet of parallel coding-agent CLIs isolated via git worktrees. Overlaps KAI's "
                 "existing CodingWorkerRouter; useful as a reference for the git-worktree parallel-isolation pattern."),
        CM(id="claude-task-master", name="Claude Task Master", type=CT.MCP,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False,
           conflicts=[], triggers=[],
           provenance=_prov2("https://github.com/eyaltoledano/claude-task-master", "eyaltoledano", "MIT + Commons Clause", "", "REUSE_LIBRARY (MCP)"),
           notes="§44: REUSE_LIBRARY — task-planning MCP, no code exec. Overlaps seeded sequential-thinking + KAI Missions/"
                 "procedures/todos + the Holding operator. Commons Clause restricts resale. Adopt only if it beats native."),
        CM(id="daytona", name="Daytona (sandbox, archived)", type=CT.CODE_TOOL,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/daytonaio/daytona", "daytonaio", "AGPL-3.0", "v0.190.0 (final OSS)", "REFERENCE (archived; colima incumbent)"),
           notes="§40: REFERENCE — OSS ARCHIVED (frozen v0.190.0 Jun 2026; core went private) + AGPL network copyleft. KAI "
                 "already has colima isolation -> comparison reference only, NOT a migration target."),
        CM(id="nango", name="Nango (OAuth/API broker)", type=CT.WORKSPACE_ADAPTER,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False,
           permissions=["integration.oauth"], triggers=[],
           provenance=_prov2("https://github.com/NangoHQ/nango", "NangoHQ", "Elastic License 2.0 (non-OSI)", "", "ADAPTER_ONLY (isolated broker)"),
           notes="§22/§74: ADAPTER_ONLY — OAuth+API broker for 900+ APIs; a credential broker (blast radius if compromised). "
                 "Architecture comparison BEFORE adoption; do NOT migrate current credentials automatically. Isolated service."),

        # ── §23/§26/§27/§28 DESIGN · MEDIA · VOICE ──
        CM(id="three-js", name="Three.js (3D library)", type=CT.CODE_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["3d_graphics", "webgl"], triggers=["three.js", "3d scene", "webgl"],
           provenance=_prov2("https://github.com/mrdoob/three.js", "mrdoob", "MIT", "", "REFERENCE (front-end library)"),
           notes="§26: a front-end LIBRARY a coding worker USES in its output, not a KAI runtime. Use only when a task needs "
                 "advanced 3D; do NOT rewrite the existing Nexus avatar/halo architecture."),
        CM(id="gsap", name="GSAP (animation library)", type=CT.CODE_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["animation", "motion"], triggers=["gsap", "animate the", "scroll animation"],
           provenance=_prov2("https://github.com/greensock/GSAP", "GreenSock", "GreenSock no-charge (non-OSI, now free)", "3.15", "REFERENCE (front-end library)"),
           notes="§26: front-end animation LIBRARY (now fully free). Non-OSI custom license — review before redistribution. "
                 "Use when motion genuinely serves the work; not always-on."),
        CM(id="genjutsu", name="Genjutsu (creative-coding skill)", type=CT.AGENT_SKILL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["creative_coding", "animation_design", "design_systems"],
           triggers=["creative coding", "generative animation", "motion design system"],
           provenance=_prov2("https://github.com/AThevon/genjutsu", "AThevon", "MIT", "", "npx skills add (review before load)"),
           notes="§23: ADOPT — markdown creative-coding skill pack (animation/3D/motion across React/Vue/Three.js). Small "
                 "single maintainer (~300 stars) -> human-review skill content before load (untrusted skill surface)."),
        CM(id="penpot", name="Penpot (design workspace)", type=CT.COLLABORATION_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/penpot/penpot", "Penpot (Kaleidos)", "MPL-2.0", "", "HUMAN_INTERACTIVE (prefer API, no blind GUI automation)"),
           notes="§64: HUMAN_INTERACTIVE — open-source design/prototyping workspace (heavy self-host stack). Prefer official "
                 "API/automation paths if available; do NOT automate the GUI blindly."),
        CM(id="ai-website-cloner", name="AI Website Cloner (design analysis)", type=CT.AGENT_SKILL,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/JCodesMore/ai-website-cloner-template", "JCodesMore", "MIT", "", "RESTRICTED (authorized/owned sites only)"),
           notes="§24/§25: RESTRICTED — design ANALYSIS / authorized migration ONLY (owned sites, lost-source reconstruction). "
                 "Must produce ORIGINAL output from generalized patterns; NEVER reproduce proprietary logos/copy/pixel-"
                 "identical pages. Not IP theft, not phishing. DISABLED by default."),
        CM(id="comfyui", name="ComfyUI (generative media)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False,
           capabilities=["image_generation", "video_generation"], triggers=[],
           resource_profile=ResourceProfile(ram_mb=16000, vram_mb=12000, gpu=True, heavy=True, network=True),
           provenance=_prov2("https://github.com/comfyanonymous/ComfyUI", "Comfy-Org", "GPL-3.0", "", "ADOPT (isolated, vetted nodes only)"),
           notes="§27: ADOPT (optional isolated media runtime, GPU). CORE is clean, but third-party CUSTOM NODES execute "
                 "arbitrary Python = HIGH supply-chain vector -> VETTED nodes only. No auto-publishing of generated content."),
        CM(id="hyperframes", name="HyperFrames (HTML -> video)", type=CT.CODE_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["html_to_video", "deterministic_render"], triggers=["render a video from html", "code-driven video"],
           resource_profile=ResourceProfile(ram_mb=4000, gpu=False, network=False),
           provenance=_prov2("https://github.com/heygen-com/hyperframes", "HeyGen", "Apache-2.0", "", "ADOPT (pin heygen-com)"),
           notes="§27/§49: ADOPT — deterministic HTML/CSS/JS->MP4 (headless Chrome + FFmpeg, no GPU/model). PIN heygen-com "
                 "(the hyperframes/hyperframes org is a placeholder). VideoCapabilityRouter specialist for code-driven video. "
                 "No auto-publish."),
        CM(id="openmontage", name="OpenMontage (agent video studio)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/calesthio/OpenMontage", "calesthio", "AGPL-3.0", "", "RESTRICTED (pin calesthio; fork-farm)"),
           notes="§49: RESTRICTED, HIGH — agentic video-production system, ~2-3mo old, AGPL, runs arbitrary Python + Remotion, "
                 "surrounded by a fork/mirror/typosquat cluster + SourceForge mirror. PIN canonical calesthio, keep DORMANT. "
                 "VideoCapabilityRouter alternative to hyperframes; no auto-publish."),
        CM(id="moneyprinter-turbo", name="MoneyPrinterTurbo (short-form video)", type=CT.CODE_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/harry0703/MoneyPrinterTurbo", "harry0703", "MIT", "", "REFERENCE (spam-vector; no auto-publish)"),
           notes="§27/§49/§80: REFERENCE — automated short-form pipeline, but purpose-built for MASS/bulk content = spam/"
                 "low-quality auto-publish misuse. Generated content stays reviewable; NEVER auto-post externally."),
        CM(id="whisper-local", name="Whisper (local STT)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0,
           capabilities=["speech_to_text", "offline_stt"], triggers=["transcribe offline", "local speech to text"],
           resource_profile=ResourceProfile(ram_mb=4000, vram_mb=5000, gpu=True, heavy=False),
           provenance=_prov2("https://github.com/openai/whisper", "OpenAI", "MIT", "", "ADOPT (fills local-STT gap)"),
           notes="§28: ADOPT — LOCAL/offline STT (KAI currently has only hosted whisper-1). Reference impl is stale (faster-"
                 "whisper forks are more active) but canonical weights. REUSE KAI's existing voice layer; don't duplicate."),
        CM(id="voxcpm", name="VoxCPM2 (TTS + voice clone)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.RESTRICTED, default_action_class=AC.READ_ONLY, security_tier=0,
           automatic_activation_allowed=False, operator_approval_required=True, triggers=[],
           resource_profile=ResourceProfile(vram_mb=8000, gpu=True),
           provenance=_prov2("https://github.com/OpenBMB/VoxCPM", "OpenBMB", "Apache-2.0", "VoxCPM2 (2026-04)", "RESTRICTED (voice-clone misuse)"),
           notes="§28: RESTRICTED — zero-shot voice CLONING = deepfake/impersonation misuse risk -> operator approval, "
                 "authorized voices only. Verify HF weight hashes. DISABLED by default."),
        CM(id="pipecat", name="Pipecat (realtime voice transport)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False,
           capabilities=["realtime_voice", "voice_transport"], triggers=[],
           provenance=_prov2("https://github.com/pipecat-ai/pipecat", "pipecat-ai (Daily)", "BSD-2-Clause", "", "ADOPT (under KAI voice layer)"),
           notes="§28/§29: ADOPT — realtime voice transport/orchestration (STT+LLM+TTS+WebRTC) that sits BENEATH KAI's "
                 "existing embodiment/voice + policy layer. Does NOT replace KAI's identity/policy; KAI stays the Voice "
                 "Session Controller. Scope the 100+ optional integrations carefully."),
        CM(id="meetily", name="Meetily (meeting assistant)", type=CT.COLLABORATION_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/Zackriya-Solutions/meetily", "Zackriya Solutions", "MIT", "v0.4.0", "HUMAN_INTERACTIVE (desktop, privacy)"),
           notes="§51: HUMAN_INTERACTIVE — privacy-first self-hosted meeting note-taker (local Whisper + diarization + LLM). "
                 "Desktop binaries capture live audio (privacy-sensitive, verify signatures). Meeting action items become "
                 "ActionProposal objects — NEVER auto-executed."),

        # ── §30-34/§62/§63/§75/§76 MARKETING · ADS · ANALYTICS · FINANCE · COMMERCE · WORKSPACE · UI ──
        CM(id="ai-marketing-skills", name="AI Marketing Skills", type=CT.AGENT_SKILL,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False,
           capabilities=["growth", "seo", "content", "outbound_draft"], triggers=[],
           provenance=_prov2("https://github.com/ericosiu/ai-marketing-skills", "ericosiu (Single Brain)", "MIT", "", "RESTRICTED (read/draft only)"),
           notes="§30/§77: RESTRICTED — adopt READ/DRAFT skills only (audit/analyze/score/draft). Autonomous outbound SEND "
                 "and any ad SPEND are FINANCIAL/APPROVAL_REQUIRED and disabled initially. Executes local Python + opt-in "
                 "telemetry -> audit + pin before use. Partial overlap with native market/sales skills."),
        CM(id="claude-ads", name="Claude Ads (ambiguous)", type=CT.AGENT_SKILL,
           availability=AV.DISCOVERED, certification=CE.UPSTREAM_UNRESOLVED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           notes="§31: UPSTREAM_UNRESOLVED — NOT an official Anthropic product (Anthropic states there are no ads in Claude). "
                 "Maps to several identically-named community Claude-Code skills (AgriciDaniel/claude-ads et al.) that also "
                 "duplicate KAI's native ads skills. No canonical source -> DISABLED, no provenance asserted. Ad writes/budget "
                 "changes would be FINANCIAL/APPROVAL_REQUIRED regardless (§31)."),
        CM(id="viralityai", name="ViralityAI (SaaS)", type=CT.COLLABORATION_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://viralityai.net/", "ViralityAI", "Proprietary/SaaS", "", "HUMAN_INTERACTIVE (no public API)"),
           notes="§30/§57/§75: HUMAN_INTERACTIVE_ONLY — SaaS viral-content discovery with NO public API. Do NOT scrape the "
                 "dashboard. Any outbound posting would be approval-gated if an API existed."),
        CM(id="playto", name="Playto (payments SaaS)", type=CT.WORKSPACE_ADAPTER,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://www.playto.so/", "Sanhik Roy Industries Pvt Ltd", "Proprietary/SaaS", "", "REJECT_DUPLICATE (no gap, no API)"),
           notes="§32: REJECT_DUPLICATE — creator payments SaaS with NO public API (in development) and no gap vs KAI's "
                 "existing Stripe/Dwolla/SOL infra. 'Collect payments for free' marketing != architecture fact. Financial "
                 "writes remain approval-bound regardless."),
        CM(id="plausible", name="Plausible Analytics", type=CT.WORKSPACE_ADAPTER,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False,
           capabilities=["web_analytics"], permissions=["analytics.read"], triggers=[],
           provenance=_prov2("https://github.com/plausible/analytics", "Plausible Insights OÜ", "AGPLv3 (tracker MIT)", "", "SERVICE_CONNECTOR (read-only)"),
           notes="§33/§62: SERVICE_CONNECTOR — optional privacy-first web analytics via official Stats API (READ). Feed KAI "
                 "Holding/Nexus AGGREGATE metrics only; never expose individual visitor identities. Migration intentional."),
        CM(id="tradingagents", name="TradingAgents (research)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.RESTRICTED, default_action_class=AC.READ_ONLY, security_tier=0,
           automatic_activation_allowed=False, operator_approval_required=True, triggers=[],
           provenance=_prov2("https://github.com/TauricResearch/TradingAgents", "TauricResearch", "Apache-2.0", "v0.4.0", "RESTRICTED (research/paper only)"),
           notes="§34/§35/§79: RESTRICTED — multi-agent trading RESEARCH on a SIMULATED exchange. RECOMMENDATION/SIGNAL/"
                 "BACKTEST/PAPER only; a model saying BUY does NOT authorize a trade. Real brokerage order execution stays "
                 "DISABLED until a separate financial-execution certification exists."),
        CM(id="vibe-trading", name="Vibe Trading (live broker)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.RESTRICTED, default_action_class=AC.FINANCIAL, security_tier=0,
           automatic_activation_allowed=False, operator_approval_required=True, target_allowlist_required=True, triggers=[],
           provenance=_prov2("https://github.com/HKUDS/Vibe-Trading", "HKUDS (HKU)", "MIT", "v0.1.14", "RESTRICTED (live execution PROHIBITED_INITIALLY)"),
           notes="§34/§35/§79: RESTRICTED, HIGH — an AI agent with REAL LIVE brokerage execution across 10+ brokers "
                 "(Alpaca/IBKR/Binance/OKX/eToro/MT5). Live order execution is PROHIBITED_INITIALLY and DISABLED; only "
                 "paper/backtest permitted. Real trading needs the full separate cert (broker/identity/limits/kill-switch)."),
        CM(id="fincept", name="Fincept Terminal", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/Fincept-Corporation/FinceptTerminal", "Fincept Corporation", "AGPL-3.0-or-later / Enterprise", "v4.4.1", "REFERENCE (desktop, no API)"),
           notes="§34: REFERENCE — desktop financial-research terminal, no automation API (the separate read-only Fincept "
                 "Data API could be a SERVICE_CONNECTOR if a data gap appears). OSS = analytics/paper only; live broker "
                 "routing is Enterprise -> DISABLED."),
        CM(id="abacus-ai", name="Abacus.AI (platform)", type=CT.MODEL_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False,
           permissions=["provider.keys"], triggers=[],
           provenance=_prov2("https://abacus.ai/", "Abacus.AI", "Proprietary/SaaS", "", "SERVICE_CONNECTOR (RESTRICTED)"),
           notes="§76: SERVICE_CONNECTOR (RESTRICTED) — paid proprietary platform (100+ model router, agents, AutoML) with "
                 "an official REST/SDK. Paid + credentials + data egress -> budget-capped, privacy-reviewed. Overlaps KAI's "
                 "FreeLLMAPI/provider gateway (not the Nexus UI). Optional."),
        CM(id="dify", name="Dify (agent platform)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXPERIMENTAL, activation=AM.MANUAL_ONLY,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/langgenius/dify", "LangGenius", "Dify OSS License (Apache-2.0 + conditions)", "", "REFERENCE (duplicates orchestration)"),
           notes="§9/§14: REFERENCE — heavy agentic-workflow + RAG platform that duplicates KAI's own orchestration runtime. "
                 "License carries commercial-use conditions. Not a fourth orchestrator."),
        CM(id="langflow", name="Langflow (visual builder)", type=CT.AGENT_RUNTIME,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.DISABLED,
           risk_class=RK.HIGH, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/langflow-ai/langflow", "langflow-ai (DataStax/IBM)", "MIT", "", "REFERENCE (RCE history)"),
           notes="§9/§81: REFERENCE, HIGH — visual low-code LLM builder that executes arbitrary Python components and has a "
                 "reported unauthenticated-RCE history. If ever adopted: security-scan, patch, NEVER expose unauthenticated. "
                 "Duplicates KAI orchestration. DISABLED."),
        CM(id="open-webui", name="Open WebUI (chat UI)", type=CT.COLLABORATION_TOOL,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False,
           conflicts=[], triggers=[],
           provenance=_prov2("https://github.com/open-webui/open-webui", "Open WebUI", "Open WebUI License (branding clause)", "", "REJECT_DUPLICATE (Nexus)"),
           notes="§9: REJECT_DUPLICATE — KAI Nexus already provides the chat UI. Could point at KAI's /v1 endpoint but adds "
                 "a fourth chat interface with no clear gap. Optional/low-priority."),
        CM(id="lobe-chat", name="LobeChat (chat UI)", type=CT.COLLABORATION_TOOL,
           availability=AV.DISCOVERED, certification=CE.REJECTED, activation=AM.DISABLED,
           risk_class=RK.MEDIUM, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/lobehub/lobe-chat", "LobeHub", "LobeHub Community License", "", "REJECT_DUPLICATE (Nexus)"),
           notes="§9: REJECT_DUPLICATE — multi-agent chat UI duplicating KAI Nexus. Do not create a fourth chat interface."),
        CM(id="appwrite", name="Appwrite (BaaS)", type=CT.WORKSPACE_ADAPTER,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/appwrite/appwrite", "Appwrite", "BSD-3-Clause", "v1.9.6", "REFERENCE (KAI has own backend)"),
           notes="§21: REFERENCE — open-source BaaS (auth/db/storage/functions). KAI already runs its own FastAPI/Postgres/"
                 "Redis backend; adopt only if a real BaaS gap appears. Governed if ever used."),
        CM(id="appflowy", name="AppFlowy (knowledge workspace)", type=CT.COLLABORATION_TOOL,
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.MANUAL_ONLY,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, automatic_activation_allowed=False, triggers=[],
           provenance=_prov2("https://github.com/AppFlowy-IO/AppFlowy", "AppFlowy-IO", "AGPLv3", "", "HUMAN_INTERACTIVE (no automation API)"),
           notes="§63: HUMAN_INTERACTIVE_ONLY — open-source Notion alternative with NO documented public automation API. "
                 "A human WORKSPACE, not KAI's canonical memory. Do NOT scrape."),

        # ── §56 WEB-DESIGN PROMPT PACK — operator-supplied skills (bodies pending) ──
        CM(id="website-design-skills", name="Premium Website Design Skills (pack)", type=CT.AGENT_SKILL,
           availability=AV.DISCOVERED, certification=CE.UPSTREAM_UNRESOLVED, activation=AM.MANUAL_ONLY,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, security_tier=0, automatic_activation_allowed=False,
           capabilities=["website.premium_architect", "website.hero_strategist", "website.homepage_conversion",
                         "website.portfolio_designer", "website.service_landing", "website.about_story",
                         "website.mobile_optimizer", "website.full_copywriter", "website.landing_architect",
                         "website.premium_ux"],
           triggers=[],
           notes="§23/§56: the ten operator-provided website prompt packs, declared as first-class skill IDs so the Brain + "
                 "Nexus can see the DESIGN category. Bodies are UPSTREAM_UNRESOLVED — the operator's prompt text was truncated "
                 "in the source message; register the structured instruction bodies before enabling (MANUAL_ONLY until then)."),
    ]


def seed_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register_all(seed_manifests())
    return reg


def seed_graph() -> CapabilityGraph:
    g = CapabilityGraph()
    # §31: two memory systems must never co-own canonical memory
    g.add("tencentdb-memory", Relation.CONFLICTS_WITH, "kai-memory")
    # §61 alternatives + §30 fallbacks
    g.add("ollama", Relation.ALTERNATIVE_TO, "airllm")
    g.add("ollama", Relation.FALLBACK_FOR, "airllm")
    g.add("jcode", Relation.ALTERNATIVE_TO, "claude-code")
    g.add("claude-code", Relation.FALLBACK_FOR, "jcode")
    g.add("buzz", Relation.ALTERNATIVE_TO, "openwork")
    # §17 helper relations for a code/security task
    for helper in ("context7", "github", "playwright"):
        g.add("claude-code", Relation.HELPS, helper)
    g.add("reverse-skill", Relation.HELPS, "filesystem")
    g.add("reverse-skill", Relation.HELPS, "github")
    # ── expansion relations (§48) ──
    g.add("appllama", Relation.HELPS, "claude-code")          # mobile design → implementation
    g.add("hero", Relation.HELPS, "claude-code")              # HERO guides coding workers (proportional)
    g.add("payloads-all-the-things", Relation.HELPS, "reverse-skill")   # authorized web-security review
    g.add("seclists", Relation.HELPS, "reverse-skill")
    g.add("awesome-osint", Relation.HELPS, "claude-code")     # public-source research feeds analysis
    # ── coding agent pool (§24) — interchangeable workers collapse to one; claude-code is the fallback (§19) ──
    for w in ("codex", "cline", "gemini-cli", "github-copilot-cli", "jcode"):
        g.add(w, Relation.ALTERNATIVE_TO, "claude-code")
        g.add("claude-code", Relation.FALLBACK_FOR, w)

    # ══ MEGA-EXPANSION relations (§70 data-flow, §61 alternatives, §60 deps) ══
    # §18 code intelligence: one primary (codebase-memory-mcp), the rest collapse to alternatives
    g.add("codebase-memory-mcp", Relation.HELPS, "claude-code")
    for alt in ("claude-context", "codegraph"):
        g.add(alt, Relation.ALTERNATIVE_TO, "codebase-memory-mcp")
        g.add("codebase-memory-mcp", Relation.FALLBACK_FOR, alt)
    # §70 document/web ingestion PRODUCES content the memory/RAG store consumes
    g.add("markitdown", Relation.PRODUCES, "kai-memory")
    g.add("firecrawl", Relation.PRODUCES, "kai-memory")
    g.add("markitdown", Relation.HELPS, "claude-code")
    # §31 rival memories can never co-own canonical memory
    for mem in ("supermemory", "mem0", "brain-md"):
        g.add(mem, Relation.CONFLICTS_WITH, "kai-memory")
    # §12 local model runtimes are alternatives to the incumbent local provider (ollama)
    for r in ("vllm", "llama-cpp", "transformers"):
        g.add(r, Relation.ALTERNATIVE_TO, "ollama")
        g.add("ollama", Relation.FALLBACK_FOR, r)
    # §59 provider gateways are siblings (same ecosystem)
    g.add("9router", Relation.ALTERNATIVE_TO, "omniroute-gateway")
    # §10 AI browser layers sit over the deterministic engine (playwright) which is the fallback
    for b in ("stagehand", "browser-use"):
        g.add(b, Relation.ALTERNATIVE_TO, "playwright")
        g.add("playwright", Relation.FALLBACK_FOR, b)
    # §16 new coding workers collapse to the pool; claude-code is the certified fallback (§19)
    for w in ("goose", "openhands", "aider", "dyad"):
        g.add(w, Relation.ALTERNATIVE_TO, "claude-code")
        g.add("claude-code", Relation.FALLBACK_FOR, w)
    # §28/§29 voice: STT + TTS feed the realtime transport, which sits under KAI's voice controller
    g.add("whisper-local", Relation.HELPS, "pipecat")     # STT_FOR
    g.add("voxcpm", Relation.HELPS, "pipecat")            # TTS_FOR
    # §49 video specialists are alternatives (VideoCapabilityRouter picks one per task)
    g.add("hyperframes", Relation.ALTERNATIVE_TO, "openmontage")
    g.add("openmontage", Relation.ALTERNATIVE_TO, "moneyprinter-turbo")
    # §23/§26 design skills + libraries assist the coding worker
    for d in ("three-js", "gsap", "genjutsu", "website-design-skills", "ai-marketing-skills"):
        g.add(d, Relation.HELPS, "claude-code")
    # §39/§82 supply-chain scanner gates new capability onboarding
    g.add("bumblebee", Relation.HELPS, "claude-code")
    return g
