from typing import Optional

from app.core.config import settings
from app.services.llm_service import LLMService

_llm_service: Optional[LLMService] = None

def get_llm_service() -> LLMService:
    """Factory to get the singleton LLMService instance."""
    global _llm_service
    if _llm_service is None:
        if settings.llm_provider == "ollama":
            from app.services.ollama_llm_service import OllamaLLMService
            _llm_service = OllamaLLMService()
        else:
            raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
    return _llm_service
