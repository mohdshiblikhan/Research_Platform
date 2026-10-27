from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel

from app.schemas.tool import ToolCall


class LLMResponse(BaseModel):
    """Standardized response from any LLM provider."""
    content: str                           # Raw text or JSON content
    model: str                             # Model that generated this
    prompt_tokens: Optional[int] = None    # Input token count
    completion_tokens: Optional[int] = None # Output token count
    total_tokens: Optional[int] = None     # Total token count
    tool_calls: Optional[list[ToolCall]] = None # Tool calls requested by LLM
    raw_message: Optional[dict[str, Any]] = None # Provider-native message dict for chat history


class LLMService(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        json_mode: bool = False,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Generate a completion from the LLM.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User's message with context.
            temperature: Randomness control (0.0 = deterministic).
            max_tokens: Maximum response length.
            json_mode: If True, force JSON-formatted output.
            tools: Optional list of tool definitions in OpenAI/Ollama function format.

        Returns:
            LLMResponse with generated content, metadata, and optional tool_calls.
        """
        pass

    @abstractmethod
    def generate_chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        json_mode: bool = False,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Generate a completion from a multi-turn conversation.

        Args:
            messages: List of message dicts with 'role' and 'content'
                      (and optional 'tool_calls', 'tool_name').
            temperature: Randomness control (0.0 = deterministic).
            max_tokens: Maximum response length.
            json_mode: If True, force JSON-formatted output.
            tools: Optional list of tool definitions in OpenAI/Ollama function format.

        Returns:
            LLMResponse with generated content, metadata, and optional tool_calls.
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model identifier."""
        pass
