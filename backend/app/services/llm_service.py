from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Optional


class LLMResponse(BaseModel):
    """Standardized response from any LLM provider."""
    content: str                           # Raw text or JSON content
    model: str                             # Model that generated this
    prompt_tokens: Optional[int] = None    # Input token count
    completion_tokens: Optional[int] = None # Output token count
    total_tokens: Optional[int] = None     # Total token count


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
    ) -> LLMResponse:
        """Generate a completion from the LLM.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User's message with context.
            temperature: Randomness control (0.0 = deterministic).
            max_tokens: Maximum response length.
            json_mode: If True, force JSON-formatted output.

        Returns:
            LLMResponse with generated content and metadata.
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model identifier."""
        pass
