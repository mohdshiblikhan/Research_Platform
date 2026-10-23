from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.schemas.tool import ToolResult, ToolSafetyTier


@dataclass
class ToolContext:
    """Execution context injected by the server. Never exposed to the LLM."""
    db: Session
    project_id: int


class BaseTool(ABC):
    """Abstract base class for all platform tools."""
    name: str
    description: str
    args_schema: type[BaseModel]
    safety_tier: ToolSafetyTier = ToolSafetyTier.READ_ONLY

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert tool to OpenAI/Ollama function-calling format."""
        schema = self.args_schema.model_json_schema()
        # Clean up title and metadata for LLM compatibility
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    @abstractmethod
    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the tool against platform services with the injected context."""
        pass
