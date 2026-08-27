# WHEELLSVERSE — KAI Capability Matrix

KAI is the intelligence layer of the Command Center. It runs the **Capability Fabric**
(`backend/app/services/capability/`) — a pure-stdlib governance kernel (manifest / registry / graph /
brain / risk / security-tier / coding-worker router / invocation), **32 capabilities**, all tested.

## Honest runtime split (directive §5/§24) — the column that matters
A capability is NOT "READY" just because a dev machine has it. Every capability carries two states:

| runtime lane | meaning |
|---|---|
| **CLAUDE_LOCAL** | usable in *this* Claude-Code/operator session (verified MCP state) |
| **KAI_SERVER** | usable in the hosted KAI runtime (App B) — currently **CATALOG_ONLY** everywhere (no adapters wired) |

So the Command Center shows, e.g., Context7 = CLAUDE_LOCAL **CERTIFIED** / KAI_SERVER **CATALOG_ONLY** —
never a single misleading green badge.

## Capability groups (from the live registry)

| Group | Capabilities | Live status |
|---|---|---|
| **MCP FOUNDATION** | Context7, Playwright, Sequential Thinking, Filesystem, GitHub | Context7/Playwright CERTIFIED (Claude-local); Sequential/Filesystem CONNECTED (pinned); GitHub AUTH_PENDING |
| **CODING WORKFORCE** | Claude Code (PRIMARY), OpenAI Codex, Cline, Gemini CLI, GitHub Copilot CLI, jcode | Claude Code AVAILABLE; the rest EXPERIMENTAL/not-installed; Windsurf HUMAN_INTERACTIVE; Roo REJECTED (archived) |
| **KNOWLEDGE** | AI-For-Beginners, Book-to-Skill, awesome-hacking (ref) | verified upstreams; not installed |
| **MOBILE DESIGN** | AppLlama | verified; needs external MCP + paid acct |
| **SECURITY REFERENCE** | PayloadsAllTheThings, SecLists | RESTRICTED reference/data; authorized-mission only |
| **OSINT** | Awesome OSINT | tier-1 public reference |
| **ACTIVE SECURITY** | reverse-skill | RESTRICTED, DISABLED |
| **ADVERSARY EMULATION** | Empire | tier-4, **DISABLED_RESTRICTED_LAB_ONLY**, never auto-selectable |
| **AGENT BEHAVIOR** | HERO (proportional engineering) | CERTIFIED policy (never suppresses a real security concern) |
| **MEMORY** | KAI Memory (native), TencentDB (experimental, conflicts) | one canonical writer only |
| **INFERENCE** | Ollama, AirLLM | local runtimes; benchmarked-before-use |
| **GEO** | GeoLibre | verified; not installed |

## The governance kernel KAI enforces (never weakened by a redesign)
- **Security tiers 0→4** with least-privilege selection; tier-4 (Empire) needs the full envelope
  (authorized mission + AuthorizedTarget on the allowlist + approval + sandbox) or it is DENIED, and is
  **never reachable by natural-language routing**.
- **Governed invocation:** principal/mission/correlation on every call; a DENY never executes; a
  REQUIRE_APPROVAL returns an inert proposal; a worker never self-certifies (independent review + tests).
- **Prompt-injection boundary:** capability output is untrusted data — it can never grant authority.
- **HERO precedence:** may trim over-engineering, never a real auth/RBAC/secret/financial/privacy/
  production/verified-finding concern.

## AI WORKFORCE (the 146-bot fleet)
`bots/` holds ~146 `bot.py` across categories (agent_workforce, assistant, books, business, campaigns,
core, customer_support, ecommerce, …). The Command Center's AI Workforce view must distinguish
**configured vs installed vs available vs running** and show real heartbeat/queue/success/failure —
never mark the fleet "online" from a scheduler being up (prod reports 142 idle / 0 running / 3 failed).
