import logging
import os

from app.services.tools.base import (
    Tool,
    ToolCall,
    ToolContext,
    ToolError,
    ToolLoopExceededError,
    ToolResult,
)
from app.services.tools.composio_generic import ComposioTool
from app.services.tools.composio_notion import NotionTool
from app.services.tools.memory_tool import MemoryTool
from app.services.tools.registry import ToolRegistry
from app.services.tools.trading_signal import TradingSignalTool
from app.services.tools.web_fetch import WebFetchTool
from app.services.tools.web_search import WebSearchTool


logger = logging.getLogger(__name__)


def build_default_registry(
    *,
    include_perplexity: bool | None = None,
    include_composio: bool | None = None,
) -> ToolRegistry:
    """Wire the default tool set.

    Each include_* defaults to env-detected: register the tool only when its
    API key is set. Explicit True/False overrides (used in tests, or to force
    a tool off in dev).
    """
    if include_perplexity is None:
        include_perplexity = bool(os.environ.get("PERPLEXITY_API_KEY"))
    if include_composio is None:
        include_composio = bool(os.environ.get("COMPOSIO_API_KEY"))

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
    return reg


__all__ = [
    "ComposioTool",
    "MemoryTool",
    "NotionTool",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolError",
    "ToolLoopExceededError",
    "ToolRegistry",
    "ToolResult",
    "TradingSignalTool",
    "WebFetchTool",
    "WebSearchTool",
    "build_default_registry",
]
