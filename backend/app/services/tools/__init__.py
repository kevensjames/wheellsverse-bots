import logging
import os

from app.services.browser.config import browser_enabled as _browser_enabled
from app.services.tools.audit_query import AuditQueryTool
from app.services.tools.base import (
    Tool,
    ToolCall,
    ToolContext,
    ToolError,
    ToolLoopExceededError,
    ToolResult,
)
from app.services.tools.browser_tool import BrowserTool
from app.services.tools.clinicaltrials_search import ClinicalTrialsSearchTool
from app.services.tools.composio_generic import ComposioTool
from app.services.tools.composio_notion import NotionTool
from app.services.tools.courtlistener_search import CourtListenerSearchTool
from app.services.tools.document_search import DocumentSearchTool
from app.services.tools.failure_lookup import FailureLookupTool
from app.services.tools.github_scout import GithubScoutTool
from app.services.tools.image_gen import ImageGenTool
from app.services.tools.kg_query import KGQueryTool
from app.services.tools.learning_query import LearningQueryTool
from app.services.tools.memory_tool import MemoryTool
from app.services.tools.plan_query import PlanQueryTool
from app.services.tools.pubmed_search import PubMedSearchTool
from app.services.tools.registry import ToolRegistry
from app.services.tools.sec_edgar_search import SecEdgarSearchTool
from app.services.tools.site_builder import SiteBuilderTool
from app.services.tools.suggest_agent import SuggestAgentTool
from app.services.tools.trading_signal import TradingSignalTool
from app.services.tools.twenty_crm import TwentyCrmTool
from app.services.tools.video_gen import VideoGenTool
from app.services.tools.twin_query import TwinQueryTool
from app.services.tools.verify_claim import VerifyClaimTool
from app.services.tools.web_fetch import WebFetchTool
from app.services.tools.who_search import WhoSearchTool
from app.services.tools.web_search import WebSearchTool


logger = logging.getLogger(__name__)


def build_default_registry(
    *,
    include_perplexity: bool | None = None,
    include_composio: bool | None = None,
    include_mcp: bool | None = None,
) -> ToolRegistry:
    """Wire the default tool set.

    Each include_* defaults to env-detected: register the tool only when its
    API key is set. Explicit True/False overrides (used in tests, or to force
    a tool off in dev). include_mcp is detected via the presence of a config
    file (KAI_MCP_CONFIG_PATH env var or repo-root mcp_config.json).
    """
    if include_perplexity is None:
        include_perplexity = bool(os.environ.get("PERPLEXITY_API_KEY"))
    if include_composio is None:
        include_composio = bool(os.environ.get("COMPOSIO_API_KEY"))
    if include_mcp is None:
        # Auto-on whenever a config file exists. Loader returns [] if config
        # is missing/broken, so this is safe to keep as a default.
        include_mcp = True

    reg = ToolRegistry()
    if include_perplexity:
        try:
            reg.register(WebSearchTool())
        except RuntimeError as e:
            logger.warning("tools: skipping web_search — %s", e)
    else:
        logger.info("tools: web_search skipped (PERPLEXITY_API_KEY not set)")

    reg.register(MemoryTool())
    reg.register(TradingSignalTool())
    # No env key required — pure-Python fetch + trafilatura extraction
    reg.register(WebFetchTool())
    # Knowledge graph — SQLite-backed, ships with the daemon. No env key.
    # Always registered: the KG db auto-creates on first use, so the tool
    # is functional from day one even with an empty graph.
    reg.register(KGQueryTool())
    # Document search (RAG) — semantic search over the user's indexed documents
    # via pgvector. Ships always; degrades gracefully to "no results" when the
    # knowledge base is empty or embeddings are unavailable.
    reg.register(DocumentSearchTool())
    # Claim verification (RAG-grounded fact-check) — checks a claim against the
    # user's indexed documents + returns a confidence + citations. Ships always.
    reg.register(VerifyClaimTool())
    # PubMed (NCBI E-utilities) — live, official, keyless biomedical literature
    # search returning citable results. The reference external-knowledge connector.
    reg.register(PubMedSearchTool())
    # SEC EDGAR full-text filing search (finance/accounting) + CourtListener case
    # law (legal) — same live-official-API connector pattern as PubMed.
    reg.register(SecEdgarSearchTool())
    reg.register(CourtListenerSearchTool())
    # WHO Global Health Observatory indicator search (medical) — official OData.
    reg.register(WhoSearchTool())
    # ClinicalTrials.gov (NIH/NLM) trial registry search (medical) — official v2.
    reg.register(ClinicalTrialsSearchTool())
    # Super-router — recommend the best domain expert (preset) for a question.
    reg.register(SuggestAgentTool())
    # Failure log — JSONL-backed, ships with the daemon. KAI can look up
    # similar past failures to avoid repeating them.
    reg.register(FailureLookupTool())
    # Long-term plans — SQLite-backed, ships with the daemon. READ-ONLY tool;
    # plan creation/execution goes through the audited admin endpoints.
    reg.register(PlanQueryTool())
    # Learning — read-only; reports lessons KAI has learned from feedback.
    # SQLite-backed, ships with the daemon. No env key.
    reg.register(LearningQueryTool())
    # Digital twin — read-only; the operator self-model KAI consults.
    # SQLite-backed, ships with the daemon. No env key.
    reg.register(TwinQueryTool())
    # Self-audit — read-only; KAI reports its own subsystem health on request.
    reg.register(AuditQueryTool())
    # Capability scout — read-only GitHub repo search + adoption assessment.
    # Surfaces open-source projects that could extend KAI and PROPOSES them
    # (license/maintenance/risk/recommendation). Never installs or runs code —
    # adoption stays propose-then-approve. No env key (GITHUB_TOKEN optional
    # only to lift the search rate limit).
    reg.register(GithubScoutTool())
    # Twenty CRM — read/write a self-hosted Twenty instance over its REST API.
    # Registered only when configured, so it's inert until the operator points
    # it at a CRM. KAI talks to Twenty over HTTP; it never runs Twenty's code.
    if os.environ.get("TWENTY_API_URL") and os.environ.get("TWENTY_API_KEY"):
        reg.register(TwentyCrmTool())
    else:
        logger.info("tools: twenty_crm skipped (TWENTY_API_URL/TWENTY_API_KEY not set)")
    # Site builder — KAI generates HTML pages/sections in the WheellsVerse style
    # as reviewable DRAFTS (never auto-publishes). No env key (uses the router).
    reg.register(SiteBuilderTool())
    # Image generation — local SDXL-Turbo (core/local_image.py). Free, on-device,
    # no API quota. Registered always; execute() fail-softs if diffusers/torch
    # aren't installed on the host.
    reg.register(ImageGenTool())
    # Video generation — Runway ML (core/video_engine.py). Registered ONLY when
    # RUNWAYML_API_KEY is set (slow + costs credits, so opt-in by config).
    if os.environ.get("RUNWAYML_API_KEY"):
        reg.register(VideoGenTool())
    else:
        logger.info("tools: video_gen skipped (RUNWAYML_API_KEY not set)")
    # Browser (computer-control) — registered ONLY when KAI_BROWSER_ENABLED is
    # set (default off). v1 envelope: read + propose; allowlist + SSRF + audit
    # enforced inside the tool. No browser is launched unless this is on.
    if _browser_enabled():
        try:
            reg.register(BrowserTool())
        except RuntimeError as e:
            logger.warning("tools: skipping browser — %s", e)
    else:
        logger.info("tools: browser skipped (KAI_BROWSER_ENABLED not set)")

    if include_composio:
        # Notion is the priority surface (Pattern A — dedicated tool).
        # ComposioTool is the catch-all for the other 200+ Composio apps
        # (Pattern B — discover + execute via toolkit+slug). Together they
        # implement the Stage 6 Hybrid (Pattern C) design.
        try:
            reg.register(NotionTool())
            reg.register(ComposioTool())
        except RuntimeError as e:
            logger.warning("tools: skipping composio tools — %s", e)
    else:
        logger.info("tools: composio skipped (COMPOSIO_API_KEY not set)")

    if include_mcp:
        # MCP servers — operator declares which servers to load in
        # mcp_config.json (Claude-Desktop-shape). load_mcp_tools() returns
        # [] if no config exists, so this is a no-op until an operator
        # actually enables MCP.
        try:
            from app.services.mcp_tools import load_mcp_tools
            for mcp_tool in load_mcp_tools():
                reg.register(mcp_tool)
        except Exception as e:
            # MCP discovery spawns subprocesses; one broken server should
            # never block the rest of the tool registry from loading.
            logger.warning("tools: MCP discovery failed: %s", e)
    return reg


__all__ = [
    "AuditQueryTool",
    "BrowserTool",
    "ComposioTool",
    "FailureLookupTool",
    "GithubScoutTool",
    "ImageGenTool",
    "KGQueryTool",
    "LearningQueryTool",
    "MemoryTool",
    "NotionTool",
    "PlanQueryTool",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolError",
    "ToolLoopExceededError",
    "ToolRegistry",
    "ToolResult",
    "SiteBuilderTool",
    "TradingSignalTool",
    "TwentyCrmTool",
    "TwinQueryTool",
    "VideoGenTool",
    "WebFetchTool",
    "WebSearchTool",
    "build_default_registry",
]
