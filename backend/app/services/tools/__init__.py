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
from app.services.tools.web_search import WebSearchTool


def build_default_registry(
    *,
    include_perplexity: bool = True,
    include_composio: bool = True,
) -> ToolRegistry:
    """Wire the default tool set.

    - include_perplexity=False  → skip web_search (no PERPLEXITY_API_KEY)
    - include_composio=False    → skip Notion + generic Composio tools
                                  (no COMPOSIO_API_KEY, or tests that mock
                                  the SaaS surface)
    """
    reg = ToolRegistry()
    if include_perplexity:
        reg.register(WebSearchTool())
    reg.register(MemoryTool())
    reg.register(TradingSignalTool())
    if include_composio:
        # Notion is the priority surface (Pattern A — dedicated tool).
        # ComposioTool is the catch-all for the other 200+ Composio apps
        # (Pattern B — discover + execute via toolkit+slug). Together they
        # implement the Stage 6 Hybrid (Pattern C) design.
        reg.register(NotionTool())
        reg.register(ComposioTool())
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
    "WebSearchTool",
    "build_default_registry",
]
