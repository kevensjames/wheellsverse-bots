from app.services.tools.base import (
    Tool,
    ToolCall,
    ToolContext,
    ToolError,
    ToolLoopExceededError,
    ToolResult,
)
from app.services.tools.memory_tool import MemoryTool
from app.services.tools.registry import ToolRegistry
from app.services.tools.trading_signal import TradingSignalTool
from app.services.tools.web_search import WebSearchTool


def build_default_registry(*, include_perplexity: bool = True) -> ToolRegistry:
    """Wire the three v1 tools. Set include_perplexity=False to skip web_search
    when no PERPLEXITY_API_KEY is configured."""
    reg = ToolRegistry()
    if include_perplexity:
        reg.register(WebSearchTool())
    reg.register(MemoryTool())
    reg.register(TradingSignalTool())
    return reg


__all__ = [
    "MemoryTool",
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
