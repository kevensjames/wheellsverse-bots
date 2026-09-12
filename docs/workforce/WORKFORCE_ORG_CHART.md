# Workforce Org Chart — divisions & workplaces

Durable division + workplace inventory. Referenced by
`KAI_GOVERNED_WORKFORCE_MASTER_PLAN.md`. **KAI sits at the top of the org chart**;
divisions/specialists work for KAI. Any upstream "Agents Orchestrator" / "Chief of
Staff" role is **downgraded to advisory planning** — KAI is the actual orchestrator.

## Divisions

**Upstream divisions** (populated from the pinned `divisions.json` at import — do
not hard-code; verify against source): academic · design · engineering · finance ·
game development · GIS · healthcare · marketing · paid media · product · project
management · research · sales · security · spatial computing · specialized ·
support · testing · (strategy if present in the pinned source).

**KAI operational divisions** (native): Executive Advisory · Governance & Approvals
· Evidence & Reality · Tenant Security · Platform & Architecture · Data & Memory ·
Models & Evaluation · Browser & Device Safety · Nurtelle Healthcare Safety · SOL
Governance · NarAI Commerce · Legal & Privacy · Release & Incident Operations.

## Workplaces (WorkplaceProfile — an isolation + policy profile, not a UI label)

Mission Control · Architecture Forge · Code Foundry · Design Atelier · Evidence Lab
· Security Vault · Tenant Boundary Lab · Sandbox Harbor · Operations Observatory ·
Event Observatory · Hook Foundry · Data Observatory · Model Laboratory · Retrieval
Laboratory · Memory Archive · Knowledge Archive · Growth Studio · Community Studio ·
Sales Room · Support Desk · Finance Office · Privacy Office · Legal Review Room ·
Healthcare Safety Room · SOL Governance Room · Market Observatory · NarAI Commerce
Lab · Voice Studio · Visual Studio · Browser Quarantine · Device Quarantine Lab ·
Release Hangar · Incident Room.

(Also referenced by characters: Evidence Archive, Data Architecture Chamber,
Credential Vault, Adversarial Safety Lab, Customer Council, FinOps Desk — these are
specializations/rooms within the above profiles and get their own WorkplaceProfile.)

## Per-mission WorkplaceProfile fields

tenant + project · mission ID · scoped worktree/scratch dir · permitted read &
write roots · immutable source inputs · output directory · model profile · tools ·
secrets **by broker reference only** · network allowlist · browser/device state ·
external-effect state · time/token/cost budgets · maximum concurrency · evidence
destination · cleanup + revocation behavior.

## Default state (every workplace, until KAI grants otherwise)

network **denied** · browser **denied** · device **denied** · external writes
**denied** · publishing **denied** · messaging **denied** · financial execution
**denied** · production credentials **denied**.

## Team composition (KAI-selected, normally 3–7 roles)

one planner/domain lead · one or more workers · one security/reality reviewer where
risk requires · one **independent** completion verifier (never the worker).
Rules: planners can't silently execute · workers can't self-approve or self-complete
· reviewers can't verify their own output · consequential actions need a fresh,
bound, single-use approval · delegation tokens are mission/tenant/capability-scoped,
expiring, non-forwardable · no recursive recruiting · hard fan-out + depth limits ·
typed-artifact/event handoffs with provenance · failures return to KAI for replanning.
