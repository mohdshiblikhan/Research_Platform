from typing import Any, Optional
from app.services.tools.base import BaseTool
from app.services.tools.implementations import (
    ComparePapersTool,
    GetChunkTool,
    GetDocumentMetadataTool,
    GetPaperExtractionTool,
    GetResearchPlanTool,
    ListDocumentsTool,
    ListResearchPlansTool,
    SearchChunksTool,
)


class ToolRegistry:
    """Central registry holding available tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance, raising ValueError on duplicate names."""
        if tool.name in self._tools:
            raise ValueError(f"Tool with name '{tool.name}' is already registered.")
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Lookup tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Export all tools to OpenAI/Ollama function calling schema format."""
        return [tool.to_openai_tool() for tool in self._tools.values()]


def get_default_tool_registry() -> ToolRegistry:
    """Factory creating registry pre-populated with all 8 platform tools."""
    registry = ToolRegistry()
    registry.register(SearchChunksTool())
    registry.register(GetChunkTool())
    registry.register(ListDocumentsTool())
    registry.register(GetDocumentMetadataTool())
    registry.register(GetPaperExtractionTool())
    registry.register(ComparePapersTool())
    registry.register(GetResearchPlanTool())
    registry.register(ListResearchPlansTool())
    return registry
