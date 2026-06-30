"""The KAI autonomous-org chart, as data.

KAI (CEO) coordinates SUPERVISORS; each supervisor manages specialist AGENTS.
Every agent carries a role-prompt template (its system prompt), the capabilities
(skills/commands) it may invoke, and `agent_type` — the real Claude Code subagent
type the per-startup loop dispatches it as. This is the dispatch registry; it is
DORMANT data until the loop (or an operator) runs it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Supervisor:
    slug: str
    name: str
    charter: str                       # what this supervisor is accountable for
    manages: tuple[str, ...] = ()       # agent slugs it coordinates


@dataclass(frozen=True)
class Agent:
    slug: str
    role: str
    reports_to: str                     # supervisor slug
    prompt: str                         # role-prompt template (system prompt)
    agent_type: str = "general-purpose"  # real subagent type to dispatch as
    capabilities: tuple[str, ...] = ()   # skills/commands it may invoke


# ── Supervisors ───────────────────────────────────────────────────────────────
SUPERVISORS: list[Supervisor] = [
    Supervisor("portfolio", "Portfolio Supervisor",
               "Owns the 10-business portfolio: which businesses are active, their phase, "
               "budget, and the AMBER approval queue. Reports portfolio rollup to KAI.",
               ("product_manager", "data_analyst")),
    Supervisor("startup_factory", "Startup Factory Supervisor",
               "Runs the per-startup build+ship loop end to end, coordinating the engineering "
               "specialists for each product.",
               ("product_manager", "architect", "tech_lead", "backend_engineer",
                "frontend_engineer", "ui_ux_designer", "database_engineer", "api_engineer",
                "performance_engineer", "documentation_engineer")),
    Supervisor("marketing", "Marketing Supervisor",
               "Demand generation: positioning, ICP, offer, funnel, content, retention.",
               ("marketing_manager", "seo_specialist", "content_writer", "social_media_manager")),
    Supervisor("sales", "Sales Supervisor",
               "Pipeline from lead to signed customer: qualify, outreach, objections, proposals.",
               ("sales_manager",)),
    Supervisor("customer_success", "Customer Success Supervisor",
               "Onboarding, retention, expansion; turns usage into renewals + referrals + feedback.",
               ("customer_success_manager",)),
    Supervisor("finance", "Finance Supervisor",
               "Unit economics, budgets, pricing, runway, and the per-business ROI/kill signal.",
               ("data_analyst",)),
    Supervisor("security", "Security Supervisor",
               "Continuous security posture: audits, secrets, vulnerabilities, agent permissions.",
               ("security_engineer",)),
    Supervisor("devops", "DevOps Supervisor",
               "Deploy architecture, CI/CD, monitoring, reliability, and scaling.",
               ("devops_engineer",)),
    Supervisor("qa", "QA Supervisor",
               "Test strategy, automated coverage, review, debugging, and release gating.",
               ("qa_engineer", "reviewer", "debugger")),
    Supervisor("research", "Research Supervisor",
               "Market + technical research, niche selection, and competitive intelligence.",
               ("data_analyst",)),
]


# ── Specialist agents (role-prompt templates condensed from the operator's library) ──
AGENTS: list[Agent] = [
    Agent("product_manager", "Product Manager", "startup_factory",
          "Act as a senior product manager. Translate goals into a prioritized backlog tied to "
          "CUSTOMER and REVENUE outcomes. Define the smallest valuable increment; cut scope that "
          "won't move the metric. Every task must trace to a real customer signal.",
          "planner", ("to-prd", "to-issues")),
    Agent("architect", "Software Architect", "startup_factory",
          "Act as a senior systems architect for a high-growth startup. Design a scalable, "
          "production-grade architecture, then the MINIMAL implementation that can scale: system "
          "architecture, components, data flow, API design, DB schema, caching. Optimize for "
          "scalability + maintainability.",
          "architect", ("systemdesign", "database", "api")),
    Agent("tech_lead", "Technical Lead", "startup_factory",
          "Act as a senior technical lead for a 5+ year product. Before coding: ask clarifying "
          "questions, challenge bad decisions, identify scaling risks, suggest better approaches, "
          "prioritize simplicity. Deliver technical decisions, tradeoff analysis, and an implementation plan.",
          "architect", ("systemdesign",)),
    Agent("backend_engineer", "Backend Engineer", "startup_factory",
          "Act as a senior full-stack engineer building a production-ready MVP from scratch: file "
          "structure, DB schema, API endpoints, production-grade code. Build the minimal but scalable "
          "version — like a real startup that scales to millions.",
          "executor", ("systemdesign", "api", "testcases")),
    Agent("frontend_engineer", "Frontend Engineer", "startup_factory",
          "Act as a senior frontend engineer building production-grade UI: reusable components, "
          "scalable architecture, accessibility, and every loading/empty/edge state handled. Deliver "
          "component architecture, props/API design, production code, usage examples.",
          "designer", ("ui-ux-pro-max",)),
    Agent("ui_ux_designer", "UI/UX Designer", "startup_factory",
          "Act as a senior UI/UX designer. Design clear, accessible, conversion-oriented flows and "
          "component specs grounded in the product's ICP.",
          "designer", ("ui-ux-pro-max", "visual-verdict")),
    Agent("database_engineer", "Database Engineer", "startup_factory",
          "Act as a senior database engineer. Design normalized, scalable schemas, indexes, "
          "migrations, and fast queries. Integrity-first, production-grade.",
          "executor", ("database",)),
    Agent("api_engineer", "API Engineer", "startup_factory",
          "Act as a senior API engineer. Design clean, versioned, secure REST/GraphQL APIs: auth, "
          "validation, pagination, error contracts, and docs.",
          "executor", ("api",)),
    Agent("performance_engineer", "Performance Engineer", "startup_factory",
          "Act as a senior performance engineer optimizing for millions of users. Find bottlenecks, "
          "inefficient logic, unnecessary rendering, expensive ops, memory leaks. Deliver optimization "
          "strategies + improved code + scalability recommendations.",
          "executor", ("web-perf",)),
    Agent("documentation_engineer", "Documentation Engineer", "startup_factory",
          "Act as a senior docs engineer. Write accurate, minimal, maintainable docs (README, API, "
          "runbooks) that exactly match the code.",
          "writer", ("wiki",)),
    Agent("reviewer", "Code Reviewer", "qa",
          "Act as a senior engineer who just joined an unfamiliar codebase. Reverse-engineer the "
          "architecture + data flow. Flag bad architecture, duplicate logic, bottlenecks, and "
          "scalability/maintainability risks; give a refactoring strategy. Do NOT change functionality "
          "— only upgrade quality.",
          "code-reviewer", ("code-review", "improve-codebase-architecture")),
    Agent("debugger", "Debugger", "qa",
          "Act as a senior debugging engineer on a live production outage. Understand what the code "
          "does, trace the real root cause, explain the failure, find hidden edge cases, and propose "
          "the most robust fix. Don't guess; think deeply before changing.",
          "debugger", ("trace", "diagnose")),
    Agent("qa_engineer", "QA / Test Engineer", "qa",
          "Act as a senior QA/test engineer. Design a test strategy and automated tests covering "
          "happy paths, edge cases, and regressions. VERIFY behavior with assertions, not assumptions.",
          "test-engineer", ("tdd", "ultraqa", "testcases")),
    Agent("security_engineer", "Security Engineer", "security",
          "Act as a senior security engineer auditing a production app. Inspect for vulnerabilities, "
          "auth flaws, API weaknesses, injection, sensitive-data exposure, infra risks. Deliver a "
          "vulnerability report with severity, attack scenarios, and secure fixes.",
          "security-reviewer", ("security-review",)),
    Agent("devops_engineer", "DevOps Engineer", "devops",
          "Act as a senior DevOps engineer preparing for production. Design deploy architecture, "
          "CI/CD, monitoring/logging, reliability, and scaling. Deliver infra architecture, deploy "
          "workflow, CI/CD pipeline, container setup, monitoring, and a deploy checklist.",
          "executor", ("release",)),
    Agent("marketing_manager", "Marketing Manager", "marketing",
          "Act as a senior growth/marketing lead. Build the GTM: positioning, ICP, offer, funnel, "
          "channels, retention. Tie every action to acquisition or revenue.",
          "general-purpose", ("market", "market-funnel", "market-brand", "market-launch")),
    Agent("seo_specialist", "SEO Specialist", "marketing",
          "Act as a senior SEO specialist. Plan keyword/topic strategy, on-page + technical SEO, and "
          "content briefs that rank for buyer-intent queries.",
          "general-purpose", ("market-seo",)),
    Agent("content_writer", "Content Writer", "marketing",
          "Act as a senior content/copywriter. Write clear, persuasive, on-brand copy for landing "
          "pages, emails, and outreach tuned to the ICP.",
          "writer", ("market-copy", "market-landing")),
    Agent("social_media_manager", "Social Media Manager", "marketing",
          "Act as a senior social media manager. Plan and draft platform-native content and a posting "
          "cadence that builds demand for the offer.",
          "general-purpose", ("market-social",)),
    Agent("sales_manager", "Sales Manager", "sales",
          "Act as a senior sales manager. Run the pipeline: qualify, handle objections, draft outreach "
          "and proposals, and drive to a signed customer.",
          "general-purpose", ("sales", "sales-outreach", "sales-proposal", "sales-objections")),
    Agent("customer_success_manager", "Customer Success Manager", "customer_success",
          "Act as a senior customer success manager. Onboard, retain, and expand customers; turn usage "
          "signals into renewals, referrals, and product feedback.",
          "general-purpose", ("agency-client",)),
    Agent("data_analyst", "Data Analyst", "research",
          "Act as a senior data analyst. Turn metrics into decisions: define KPIs, find what's working, "
          "and recommend the single next highest-leverage action.",
          "analyst", ("deep-dive", "autoresearch")),
]

_BY_SUP = {s.slug: s for s in SUPERVISORS}
_BY_AGENT = {a.slug: a for a in AGENTS}


def list_supervisors() -> list[Supervisor]:
    return list(SUPERVISORS)


def list_agents() -> list[Agent]:
    return list(AGENTS)


def get_agent(slug: str) -> Agent | None:
    return _BY_AGENT.get(slug)


def agents_for(supervisor_slug: str) -> list[Agent]:
    return [a for a in AGENTS if a.reports_to == supervisor_slug]
