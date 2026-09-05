"""Canonical WHEELLSVERSE registry data + snapshot builder.

Every node is verified structural truth from the Phase-0 forensic inventory
(docs/WHEELLSVERSE_SYSTEM_INVENTORY.md). Statuses are honest; no metric is
invented here. The Command Center renders this; test_registry.py guards it so a
company/surface can never silently disappear from the front door again.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Honest vocabularies (directive §24) ──────────────────────────────────────
class Status:
    """Operational reality of the system's CODE, not a live health probe."""
    HEALTHY   = "HEALTHY"     # exercised + passing (tests/verified behavior)
    DEGRADED  = "DEGRADED"    # works but with a known gap / partial wiring
    DORMANT   = "DORMANT"     # complete code, not currently exercised/running
    LOCAL     = "LOCAL"       # runs on a dev machine only, not deployed
    PRE_DEPLOY = "PRE_DEPLOY" # built, no environment provisioned yet
    EXTERNAL  = "EXTERNAL"    # a third-party service we link to, not our runtime
    HISTORICAL = "HISTORICAL" # superseded / retained for reference
    UNKNOWN   = "UNKNOWN"     # existence known, run-state not verified — NEVER shown green


class DeployState:
    LIVE_PROD       = "LIVE_PROD"        # serving on a production URL right now
    LOCAL_ONLY      = "LOCAL_ONLY"       # never deployed
    CATALOG_ONLY    = "CATALOG_ONLY"     # listed/governed but no executing adapter
    PRE_DEPLOY      = "PRE_DEPLOY"       # no environment yet
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE" # third-party host
    CI_PIPELINE     = "CI_PIPELINE"      # a build/gate, not a served surface
    RETIRED         = "RETIRED"


class DataClass:
    REAL        = "REAL"         # from a live source
    DERIVED     = "DERIVED"      # computed from real structural facts
    UNAVAILABLE = "UNAVAILABLE"  # no live source — must NOT be rendered as a number


# Tiers form the NASA holding hierarchy: WHEELLSVERSE on top, KAI in the middle
# governing, companies + platform + governance integrated below.
TIER_HOLDING    = "HOLDING"
TIER_BRAIN      = "BRAIN"
TIER_COMPANY    = "COMPANY"
TIER_PLATFORM   = "PLATFORM"
TIER_GOVERNANCE = "GOVERNANCE"


@dataclass
class Node:
    id: str
    name: str
    tier: str
    status: str
    deploy: str
    summary: str
    route: Optional[str] = None       # admin surface on App A (the recovery link)
    url: Optional[str] = None         # external production URL, if any
    repo: str = "wheellsverse-bots"
    evidence: str = ""                # file:line pointer, keeps the row auditable
    lost_from_current: bool = False   # was dropped from the current /admin front door
    probe: Optional[str] = None       # live endpoint the UI may call for REAL status
    metrics_class: str = DataClass.UNAVAILABLE  # honesty flag for any figure shown

    def to_dict(self) -> dict:
        return asdict(self)


def _n(*a, **k) -> Node:
    return Node(*a, **k)


# ── The canonical catalog ─────────────────────────────────────────────────────
# Ordered top-down: holding → brain → companies → platform → governance.
_CATALOG: list[Node] = [
    # ── WHEELLSVERSE holding ─────────────────────────────────────────────────
    _n("wheellsverse", "WHEELLSVERSE", TIER_HOLDING, Status.HEALTHY, DeployState.LIVE_PROD,
       "The holding company. Command Center front door.",
       route="/admin", url="https://app.wheellsverse.com/admin",
       evidence="core/api.py:1930", probe="/api/health", metrics_class=DataClass.DERIVED),

    # ── KAI — the brain in the middle, governs everything ────────────────────
    _n("kai", "KAI", TIER_BRAIN, Status.DEGRADED, DeployState.LOCAL_ONLY,
       "The governed intelligence layer. App B brain daemon is local-only; App A "
       "reaches it through the same-origin bridge.",
       route="/admin/mission-nexus", repo="wheellsverse-bots backend/app",
       evidence="backend/app/main.py:166"),
    _n("kai-capability-fabric", "KAI Capability Fabric", TIER_BRAIN, Status.DORMANT,
       DeployState.CATALOG_ONLY, "32-capability governed kernel — registry/brain/graph/risk/"
       "security-tier/coding-worker. LIVE catalog surface; server adapters not wired.",
       route="/admin/capabilities", evidence="backend/app/services/capability/seed.py",
       probe="/admin/capabilities.json", metrics_class=DataClass.REAL),
    _n("kai-command-nexus", "KAI Command Nexus", TIER_BRAIN, Status.DORMANT, DeployState.LIVE_PROD,
       "Immersive full-screen presence — same governed provider, session and streaming as the orb "
       "(/admin/nexus is a 307 alias to /admin/mission-nexus).",
       route="/admin/mission-nexus", evidence="core/api.py:2147"),
    _n("kai-mission-nexus", "KAI Adaptive Mission Nexus", TIER_BRAIN, Status.DORMANT, DeployState.LIVE_PROD,
       "Mission-control operating environment (adaptive shell, procedures, approvals, telemetry).",
       route="/admin/mission-nexus", evidence="core/api.py:2158"),
    _n("kai-voice", "KAI Voice", TIER_BRAIN, Status.LOCAL, DeployState.LOCAL_ONLY,
       "NarAI v2 voice client + WS.", route="/admin/mission-nexus", lost_from_current=True,
       evidence="core/api.py:15281"),
    _n("ai-workforce", "AI Workforce (146-bot fleet)", TIER_BRAIN, Status.DORMANT, DeployState.LOCAL_ONLY,
       "146 bot.py across 22 categories + the 13-agent Shopify workforce. Configured != running.",
       route="/admin/hub", evidence="bots/ (146 bot.py); core/bot_registry.py"),
    _n("wmos-portfolio-hq", "Portfolio HQ (W-MOS)", TIER_BRAIN, Status.DORMANT, DeployState.LIVE_PROD,
       "Master supervisor / portfolio orchestrator (traffic-light dispatch, ROI killswitch).",
       route="/admin/portfolio", lost_from_current=True, evidence="core/portfolio/orchestrator.py"),

    # ── Companies / startups ─────────────────────────────────────────────────
    _n("sol", "SOL / SOLCIRCLE", TIER_COMPANY, Status.HEALTHY, DeployState.EXTERNAL_SERVICE,
       "ROSCA savings-circle fintech. Real backend is the separate wheellsverse-sol repo, "
       "LIVE on Railway. Money mode = MOCK (APP_ENV=staging). Append-only balanced ledger.",
       route="/sol/admin", url="https://sol-api-production.up.railway.app",
       repo="wheellsverse-sol", lost_from_current=True, evidence="wheellsverse-sol backend/app/main.py"),
    _n("narai", "NarAI", TIER_COMPANY, Status.DEGRADED, DeployState.LIVE_PROD,
       "Multi-domain AI brain. Market/prediction engine LIVE in prod (v2 routers). "
       "The most substantial standalone (152-file package + legacy modules).",
       route="/admin/mission-nexus", lost_from_current=True, evidence="core/api.py:15261; narai/api/main.py"),
    _n("nexora", "Nexora", TIER_COMPANY, Status.DEGRADED, DeployState.LIVE_PROD,
       "Creator-monetization platform (recruit/growth/pages backend).",
       route="/nexora/dashboard", lost_from_current=True, evidence="core/nexora_db.py; core/api.py:10765"),
    _n("suprema", "Suprema", TIER_COMPANY, Status.DORMANT, DeployState.LIVE_PROD,
       "Self-healing / workspace autorepair + monitoring.",
       route="/admin/legacy", lost_from_current=True, evidence="suprema/autorepair/engine.py; core/api.py:3129"),
    _n("nurtelle", "Nurtelle", TIER_COMPANY, Status.PRE_DEPLOY, DeployState.PRE_DEPLOY,
       "Safety-first pregnancy/postpartum companion. Separate chenara repo (Next.js 16). "
       "Mature RLS data layer; no environment provisioned yet.",
       repo="chenara", evidence="chenara README.md; packages/db/migrations 0001-0013"),
    _n("toodle", "Toodle (AI Marketing OS)", TIER_COMPANY, Status.DEGRADED, DeployState.LIVE_PROD,
       "AI marketing OS. 503s without KIT integration key.",
       route="/admin/toodle", lost_from_current=True, evidence="narai/api/routes/toodle.py:63"),
    _n("siteboost", "SiteBoost AI", TIER_COMPANY, Status.DORMANT, DeployState.LIVE_PROD,
       "Local-business outbound engine.", route="/admin/siteboost",
       lost_from_current=True, evidence="core/api.py:1992"),
    _n("shopify-merchants", "Shopify Merchants", TIER_COMPANY, Status.DORMANT, DeployState.LIVE_PROD,
       "Multi-tenant Shopify merchant automation.", route="/admin/shopify",
       evidence="core/api.py:15505; narai/api/routes/shopify_admin.py"),
    _n("second-brain-inbox", "Second Brain Inbox", TIER_COMPANY, Status.HEALTHY, DeployState.LIVE_PROD,
       "AI inbox / capture service.", route="/admin/second-brain-inbox",
       lost_from_current=True, evidence="core/api.py:15550"),
    _n("leadgen", "Lead-Gen Campaigns", TIER_COMPANY, Status.DORMANT, DeployState.LIVE_PROD,
       "Portfolio lead-generation campaigns.", route="/admin/leadgen",
       lost_from_current=True, evidence="core/api.py:2094"),
    _n("scoreboard", "Portfolio Scoreboard", TIER_COMPANY, Status.HEALTHY, DeployState.LIVE_PROD,
       "Cross-portfolio scoreboard (Stripe-backed snapshot).", route="/admin/scoreboard",
       lost_from_current=True, evidence="core/api.py:2066; core/scoreboard.py"),
    _n("amazon-kdp", "Amazon KDP", TIER_COMPANY, Status.DORMANT, DeployState.LIVE_PROD,
       "KDP publishing registry + daily publisher.", route="/admin/legacy",
       lost_from_current=True, evidence="core/kdp_registry.py; core/api.py:8892"),
    _n("printify", "Printify", TIER_COMPANY, Status.DORMANT, DeployState.LIVE_PROD,
       "Print-on-demand integration.", route="/admin/legacy",
       lost_from_current=True, evidence="core/printify_client.py"),

    # ── Platform / infrastructure ────────────────────────────────────────────
    _n("app-a", "App A — Production API (core.api)", TIER_PLATFORM, Status.HEALTHY, DeployState.LIVE_PROD,
       "The deployed FastAPI monolith. Railway grateful-flexibility/wheellsverse-v2.",
       url="https://app.wheellsverse.com", evidence="railway.json:6; core/api.py:779",
       probe="/api/health", metrics_class=DataClass.DERIVED),
    _n("app-b", "App B — KAI Brain daemon", TIER_PLATFORM, Status.LOCAL, DeployState.LOCAL_ONLY,
       "Governed KAI runtime (Postgres+Alembic+Celery). Docker down; never deployed.",
       repo="wheellsverse-bots backend/app", evidence="backend/app/main.py:166"),
    _n("apex-proxy", "Apex proxy (Cloudflare Pages)", TIER_PLATFORM, Status.HEALTHY, DeployState.LIVE_PROD,
       "wheellsverse.com apex; _middleware.js proxies /admin + /api/* to App A.",
       url="https://wheellsverse.com", evidence="frontend/functions/_middleware.js:14"),
    _n("ci-docker-push", "GHCR image build/push CI", TIER_PLATFORM, Status.HEALTHY, DeployState.CI_PIPELINE,
       "Builds + pushes the App A image on push to main.",
       evidence=".github/workflows/docker-push.yml:3"),
    _n("ci-phase0-gate", "Phase-0 Deploy Gate CI", TIER_PLATFORM, Status.HEALTHY, DeployState.CI_PIPELINE,
       "Secret scan (gitleaks) + security tests + dep audit on PRs.",
       evidence=".github/workflows/phase0-gate.yml:20"),
    _n("hub", "Command Center Hub (12-card)", TIER_PLATFORM, Status.HEALTHY, DeployState.LIVE_PROD,
       "The company holding hub — 12 internal + 8 external cards.", route="/admin/hub",
       lost_from_current=True, evidence="frontend/admin/index.html:63"),
    _n("legacy-dashboard", "Legacy 76-nav Master Dashboard", TIER_PLATFORM, Status.HISTORICAL, DeployState.LIVE_PROD,
       "The original company-rich operator dashboard (~60 extra surfaces).",
       route="/admin/legacy", lost_from_current=True, evidence="core/api.py:1978; dashboard/index.html"),
    _n("ceo-dashboard", "CEO Command Center (ceo.html)", TIER_PLATFORM, Status.HEALTHY, DeployState.LIVE_PROD,
       "The W-MOS-focused 3D telemetry view — the current /admin default.",
       route="/admin/ceo", evidence="core/api.py:1930; dashboard/ceo.html"),
    _n("wvkey", "wvkey Vault", TIER_PLATFORM, Status.DORMANT, DeployState.LIVE_PROD,
       "Encrypted operator secrets vault UI — page served in prod, vault not actively exercised.",
       route="/admin/wvkey", lost_from_current=True, evidence="frontend/admin/wvkey.html"),
    _n("avatar-lab", "KAI Avatar Lab", TIER_PLATFORM, Status.DORMANT, DeployState.LIVE_PROD,
       "Developer tool for the KAI avatar / viseme / speech stack.", route="/admin/avatar-lab",
       evidence="core/api.py:1964"),
    _n("theme-picker", "Theme Picker", TIER_PLATFORM, Status.DORMANT, DeployState.LIVE_PROD,
       "Shopify storefront theme picker.", route="/admin/theme-picker",
       evidence="core/api.py:1984"),

    # ── Governance / security ────────────────────────────────────────────────
    _n("auth-rbac", "Operator identity / RBAC", TIER_GOVERNANCE, Status.DORMANT, DeployState.LIVE_PROD,
       "Unified Principal + scopes; App A API_KEY gate is LIVE, session RBAC flag-gated off.",
       evidence="core/operator_session.py:44; core/api.py:1129"),
    _n("kai-bridge", "KAI same-origin bridge", TIER_GOVERNANCE, Status.DORMANT, DeployState.LOCAL_ONLY,
       "App A → App B reverse proxy with 5 gates, fail-closed, secret-free audit.",
       evidence="core/kai_bridge.py:156"),
    _n("governance-audit", "Governance — scope gate + tamper-evident audit", TIER_GOVERNANCE,
       Status.DEGRADED, DeployState.LOCAL_ONLY, "@audited scope gate + hash-chained audit log.",
       evidence="backend/app/services/governance/audit_log.py:44"),
    _n("kai-self-audit", "KAI self-audit engine", TIER_GOVERNANCE, Status.HEALTHY, DeployState.LOCAL_ONLY,
       "Security Command Center source — subsystem auditor (booleans only, no secrets).",
       evidence="backend/app/services/audit/auditor.py:28"),
    _n("reasoning-sanitizer", "Reasoning sanitizer (§24 boundary)", TIER_GOVERNANCE, Status.HEALTHY,
       DeployState.LOCAL_ONLY, "Strips chain-of-thought from streamed output.",
       evidence="backend/app/services/reasoning_sanitizer.py:38"),
    _n("spend-caps", "Spend tracking + soft caps", TIER_GOVERNANCE, Status.DORMANT, DeployState.LOCAL_ONLY,
       "Per-principal spend rollups + cap checks.",
       evidence="backend/app/services/router/spend_tracker.py:18"),
    _n("sentry", "Error monitoring (Sentry)", TIER_GOVERNANCE, Status.DORMANT, DeployState.LIVE_PROD,
       "Init present; active only when SENTRY_DSN is set.", evidence="core/sentry_init.py:32"),
]

# Canonical id set — the snapshot test asserts none of these ever vanish.
CANONICAL_IDS = frozenset(n.id for n in _CATALOG)


def systems() -> list[Node]:
    """All canonical nodes (stable order)."""
    return list(_CATALOG)


def companies() -> list[Node]:
    """Just the company/startup tier — the 'all my startups' view."""
    return [n for n in _CATALOG if n.tier == TIER_COMPANY]


def _counts(nodes: list[Node]) -> dict:
    by_status: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for n in nodes:
        by_status[n.status] = by_status.get(n.status, 0) + 1
        by_tier[n.tier] = by_tier.get(n.tier, 0) + 1
    return {
        "total": len(nodes),
        "lost_from_current": sum(1 for n in nodes if n.lost_from_current),
        # deploy classification (a node is CONFIGURED for prod) — NOT a liveness claim
        "live_prod": sum(1 for n in nodes if n.deploy == DeployState.LIVE_PROD),
        # honest "actually serving": prod-deployed AND its own status is healthy/degraded.
        # A DORMANT/HISTORICAL/LOCAL node is never counted as serving (configured != running).
        "serving_now": sum(1 for n in nodes if n.deploy == DeployState.LIVE_PROD
                           and n.status in (Status.HEALTHY, Status.DEGRADED)),
        "by_status": by_status,
        "by_tier": by_tier,
    }


def registry_snapshot(include_evidence: bool = True) -> dict:
    """The JSON the Command Center renders. Structural truth only.

    include_evidence=False strips the per-node `evidence` (source file:line)
    pointers — used by the HTTP endpoint so an anonymous caller doesn't receive
    the internal source layout. The fields carry no secret either way; this just
    avoids handing out source-tree granularity the operator UI doesn't need.
    """
    nodes = systems()
    out = []
    for n in nodes:
        d = n.to_dict()
        if not include_evidence:
            d.pop("evidence", None)
        out.append(d)
    return {
        "version": "1",
        "generated": "2026-08-27",
        "source": "WheellsVerseRegistry (docs/WHEELLSVERSE_SYSTEM_INVENTORY.md)",
        "honesty": "structural truth; no live metric is fabricated — UNAVAILABLE means no probe",
        "counts": _counts(nodes),
        "tiers": [TIER_HOLDING, TIER_BRAIN, TIER_COMPANY, TIER_PLATFORM, TIER_GOVERNANCE],
        "systems": out,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(registry_snapshot(), indent=2))
