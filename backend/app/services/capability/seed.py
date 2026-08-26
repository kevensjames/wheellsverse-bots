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
)
from .registry import CapabilityRegistry
from .graph import CapabilityGraph, Relation

VERIFIED_AT = "2026-08-26"


def _prov(upstream, owner, lic, ref, install, verified=True):
    return Provenance(upstream=upstream, owner=owner, license=lic, ref=ref,
                      install_method=install, verified=verified, verified_at=VERIFIED_AT)


def seed_manifests() -> list[CM]:
    return [
        # ── native KAI capabilities (genuinely available) ──────────────────────
        CM(id="kai-memory", name="KAI Memory", type=CT.NATIVE_KAI_TOOL, version="native",
           availability=AV.AVAILABLE, certification=CE.CERTIFIED, activation=AM.ALWAYS_AVAILABLE,
           risk_class=RK.LOW, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["long_term_memory", "recall", "persist"],
           triggers=["remember", "memory", "recall", "what we learned"],
           notes="Canonical source of truth for long-term memory (§31). One writer only."),
        CM(id="claude-code", name="Claude Code", type=CT.AGENT_RUNTIME, version="native",
           availability=AV.AVAILABLE, certification=CE.CERTIFIED, activation=AM.ALWAYS_AVAILABLE,
           risk_class=RK.MEDIUM, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["implement", "refactor", "engineer"],
           triggers=["implement", "refactor", "fix the bug", "write code"],
           notes="Primary engineering authority (§10/§40). No worker merges/deploys independently."),

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
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND,
           risk_class=RK.LOW, default_action_class=AC.READ_ONLY, capabilities=["structured_planning"],
           triggers=["step by step", "think through", "plan the approach"],
           notes="VERIFY connection before use (§42)."),
        CM(id="filesystem", name="Filesystem MCP", type=CT.MCP, availability=AV.DISCOVERED,
           certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND, risk_class=RK.MEDIUM,
           default_action_class=AC.REVERSIBLE_WRITE, capabilities=["read_files", "write_files"],
           triggers=["repository", "codebase", "read the file", "project files"],
           permissions=["fs.workspace"], notes="Sandbox to a workspace root (§49). VERIFY."),
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
        CM(id="jcode", name="jcode (Coding Worker)", type=CT.CODE_TOOL, version="0.81.1",
           availability=AV.DISCOVERED, certification=CE.EXTERNAL_BLOCKED, activation=AM.ON_DEMAND,
           risk_class=RK.HIGH, default_action_class=AC.REVERSIBLE_WRITE,
           capabilities=["lightweight_coding", "parallel_scan"],
           triggers=["lightweight coding worker", "parallel repository scan"],
           provenance=_prov("https://github.com/1jehuang/jcode", "1jehuang", "MIT", "v0.81.1",
                            "curl|bash (jcode.sh) / brew / cargo"),
           notes="§10/§40: bounded worker, NOT a replacement for Claude Code; never final authority. "
                 "HIGH risk — ships a curl|bash installer; inspect before any install."),
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
    return g
