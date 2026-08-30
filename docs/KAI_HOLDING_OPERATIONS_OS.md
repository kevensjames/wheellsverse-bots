# KAI Holding Operations OS — Phase 1 (foundation) + program plan
## 2026-08-30 · branch feature/kai-holding-operations-os · NOT deployed · reuse-first, staged

The Jarvis vision is a **multi-phase program**, not a one-session install. Per the mission's own
Section 2 ("do not install every candidate; reuse existing KAI; reject duplication"), this pass does the
mandated **evaluate → audit → build the safe foundation**, and stages/gates the heavy parts.

## KAI already provides (REUSE — do not rebuild)
| Need | Existing KAI component |
|---|---|
| Control plane / auth / approval | `core/api.py` + `core/operator_session*` (owner-only kai.ultra, bound approval) |
| Capability governance | `backend/app/services/capability/` fabric (tiers, availability, runtime-truth) |
| Scheduler / workers | Celery (`backend/app/workers/`) |
| Observability / monitoring (Section 11) | **kai-prod-monitor** (LIVE) — 9 signals, Telegram alerts, audit-gap, self-health |
| Audit / evidence | `governance/audit_log.py` + `audit/auditor.py` + `llm_call_log` |
| Memory / planning | `backend/app/services/nai_brain/` (governed brain + operational-truth grounding) |
| Computer-use foundation (Section 7) | `backend/app/services/tars/` (Phase-1, fail-closed, pinned UI-TARS 0.3.0) |
| Dashboard | the real `/admin` Command Center (integrate into it — no second dashboard) |

## Repository evaluation matrix (Section 2)
| Repo | Decision | Reason |
|---|---|---|
| bytedance/UI-TARS-desktop | **USE** | computer-use worker; Phase-1 foundation built, pinned 0.3.0, Apache-2.0 |
| github/github-mcp-server | **USE (github phase)** | official MCP + GitHub App least-privilege for the coding/GitHub worker |
| browser-use / Skyvern | **DEFER** | browser worker phase; prefer deterministic automation; evaluate both then pick one |
| temporalio/temporal | **DEFER** | durable workflow engine — real value for Section 6, but Celery covers scheduling now; heavy infra decision |
| livekit/agents (+js) | **DEFER (voice phase)** | preferred voice runtime if it fits; needs a media/session decision |
| openai/whisper · pipecat | **REFERENCE/DEFER** | local STT / voice alt |
| OpenHands / software-agent-sdk | **DEFER** | only if it adds isolated runtime/run-history beyond existing Claude Code/Codex |
| renovatebot/renovate · getsentry/sentry · grafana | **DEFER** | deps-PRs / error-tracking / dashboards — later phases |
| Infisical · getsops/sops | **DEFER (secrets phase)** | Railway env + `${{...}}` refs cover secrets now; Infisical is the target managed store to evaluate |
| louislam/uptime-kuma | **REFERENCE** | kai-prod-monitor already covers monitoring; reference only for a public status page |
| langchain-ai/langgraph | **REFERENCE** | KAI has its own planner; reference for graph patterns only |
| OpenInterpreter/open-interpreter | **REJECT** | unrestricted local code/computer execution — violates the no-unrestricted-access mandate |
| crewAIInc/crewAI | **REJECT** | multi-agent framework would create a second assistant — KAI must stay authoritative |
| microsoft/AutoGen | **REJECT** | maintenance mode (per mission) |
| appsmith / ToolJet / erpnext / twenty | **REJECT/DEFER** | dashboard/ERP/CRM overlap the `/admin` Command Center + Holding Registry — no disconnected catalog |

## Delivered this phase (safe, buildable now — no installs/credentials/Docker, not wired live)
`backend/app/services/holding/registry.py` (+ test 7/7) — the authoritative operational model of the holding.
- Entities: Wheellsverse Holdings, SOLCIRCLE LLC, SOL, KAI, Nurtelle, NarAI, Nexora, SiteBoost, W-MOS,
  Suprema, Wheellsverse Bots.
- **No fabrication:** every revenue/expense/customer/banking/payment/compliance/ownership field is
  `REQUIRES_OPERATOR_CONFIRMATION` and `report_value()` returns None+disclaim; only repo/deployment/status
  facts verifiable this engagement or in-repo are seeded VERIFIED, with provenance. KAI can never invent a number.

## Execution priority (Section 1) & action policy (Section 9)
Official API > authenticated connector > reviewed MCP > deterministic browser > AI browser > visual desktop
(last resort). Autonomous read-only + reversible-internal only; **every external write needs a bound approval**;
finance/legal/production/secret-export **prohibited**. An agent never approves its own action. (Enforced by the
existing owner-session + capability fabric + the TARS policy module.)

## Phased plan (each phase gated, staging-first, no production until you approve the exact commit)
1. **Holding Registry** ✅ (this phase) → wire into `/admin` (Executive Overview / Company Portfolio read-only views).
2. **Daily routines** on Celery (morning briefing / EOD / weekly) reading ONLY source-backed registry + monitor data.
3. **GitHub worker** (github-mcp-server + GitHub App, least-privilege) → draft PRs / CI, branches only.
4. **Browser worker** (browse-use or Skyvern, containerized isolation) → read-only + approval-gated writes.
5. **Computer-use worker** (UI-TARS, local isolated) → the harmless staging milestone.
6. **Voice** (LiveKit) push-to-talk → authenticated KAI request → policy → workflow (never bypasses approval).
7. **Durable orchestrator** (Temporal) if Celery proves insufficient for approval-pauses/resumable workflows.

## Genuine blockers / operator decisions (needed before the heavy phases)
- **Docker daemon** (currently off) — for isolated browser/computer-use worker containers.
- **TARS + browser model-provider credentials** — which provider + credential.
- **GitHub App** creation (least-privilege) for the GitHub worker.
- **Voice/media + Temporal infra** decisions (consequential architecture, cost).
- **Holding data confirmation** — you confirm the `REQUIRES_OPERATOR_CONFIRMATION` fields (legal names, ownership,
  revenue/customers, banking/payment references) so KAI can report them truthfully.

## Invariants held
No production change · App A/B unchanged · money MOCK · no capability enabled · no unrestricted access · no
secrets · dormant module (not imported by main.py) → zero runtime attack surface. Removal: delete
`backend/app/services/holding/` + this doc.
