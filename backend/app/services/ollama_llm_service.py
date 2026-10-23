import logging
from typing import Optional
from ollama import Client

from app.core.config import settings
from app.schemas.tool import ToolCall
from app.services.llm_service import LLMService, LLMResponse

logger = logging.getLogger(__name__)


class OllamaLLMService(LLMService):
    """LLMService implementation using a local Ollama instance."""

    def __init__(self, host: str = settings.llm_base_url, model: str = settings.llm_model):
        self.host = host
        self.model = model
        self.client = Client(host=self.host)
        logger.info(f"Initialized OllamaLLMService with host={self.host}, model={self.model}")

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = settings.llm_temperature,
        max_tokens: int = settings.llm_max_tokens,
        json_mode: bool = False,
        tools: Optional[list[dict]] = None,
    ) -> LLMResponse:
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        
        options = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        
        format_param = "json" if json_mode else ""
        
        try:
            chat_kwargs = {
                "model": self.model,
                "messages": messages,
                "options": options,
                "format": format_param,
            }
            if tools:
                chat_kwargs["tools"] = tools

            response = self.client.chat(**chat_kwargs)
            
            # Extract token counts if available
            prompt_eval_count = response.get("prompt_eval_count")
            eval_count = response.get("eval_count")
            total_tokens = None
            if prompt_eval_count is not None and eval_count is not None:
                total_tokens = prompt_eval_count + eval_count

            # Parse tool calls if present in message
            parsed_tool_calls: Optional[list[ToolCall]] = None
            raw_tool_calls = response.get("message", {}).get("tool_calls")
            if raw_tool_calls:
                parsed_tool_calls = []
                for tc in raw_tool_calls:
                    function_data = tc.get("function", {})
                    parsed_tool_calls.append(
                        ToolCall(
                            id=tc.get("id", ""),
                            name=function_data.get("name", ""),
                            arguments=function_data.get("arguments", {}),
                        )
                    )

            return LLMResponse(
                content=response.get("message", {}).get("content", ""),
                model=response.get("model", self.model),
                prompt_tokens=prompt_eval_count,
                completion_tokens=eval_count,
                total_tokens=total_tokens,
                tool_calls=parsed_tool_calls,
            )
            
        except Exception as e:
            logger.error(f"Error calling Ollama API: {e}")
            raise RuntimeError(f"Failed to generate response from Ollama: {e}")

    def get_model_name(self) -> str:
        return self.model
