import logging
from typing import Any, Optional
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

    def _build_chat_kwargs(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        options = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        format_param = "json" if json_mode else ""
        chat_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "options": options,
            "format": format_param,
        }
        if tools:
            chat_kwargs["tools"] = tools
        return chat_kwargs

    def _parse_response(self, response: Any) -> LLMResponse:
        prompt_eval_count = response.get("prompt_eval_count") if hasattr(response, "get") else getattr(response, "prompt_eval_count", None)
        eval_count = response.get("eval_count") if hasattr(response, "get") else getattr(response, "eval_count", None)
        total_tokens = None
        if prompt_eval_count is not None and eval_count is not None:
            total_tokens = prompt_eval_count + eval_count

        raw_msg = response.get("message", {}) if hasattr(response, "get") else getattr(response, "message", {})

        # Parse tool calls if present in message
        parsed_tool_calls: Optional[list[ToolCall]] = None
        raw_tool_calls = raw_msg.get("tool_calls") if hasattr(raw_msg, "get") else getattr(raw_msg, "tool_calls", None)
        if raw_tool_calls:
            parsed_tool_calls = []
            for tc in raw_tool_calls:
                function_data = tc.get("function", {}) if hasattr(tc, "get") else getattr(tc, "function", {})
                parsed_tool_calls.append(
                    ToolCall(
                        id=tc.get("id", "") if hasattr(tc, "get") else getattr(tc, "id", ""),
                        name=function_data.get("name", "") if hasattr(function_data, "get") else getattr(function_data, "name", ""),
                        arguments=function_data.get("arguments", {}) if hasattr(function_data, "get") else getattr(function_data, "arguments", {}),
                    )
                )

        raw_message_dict: Optional[dict[str, Any]] = None
        if raw_msg is not None:
            if isinstance(raw_msg, dict):
                raw_message_dict = raw_msg
            elif hasattr(raw_msg, "model_dump"):
                raw_message_dict = raw_msg.model_dump()
            elif hasattr(raw_msg, "dict"):
                raw_message_dict = raw_msg.dict()
            elif hasattr(raw_msg, "__dict__"):
                raw_message_dict = raw_msg.__dict__

        content = raw_msg.get("content", "") if hasattr(raw_msg, "get") else getattr(raw_msg, "content", "")
        model_name = response.get("model", self.model) if hasattr(response, "get") else getattr(response, "model", self.model)

        return LLMResponse(
            content=content,
            model=model_name,
            prompt_tokens=prompt_eval_count,
            completion_tokens=eval_count,
            total_tokens=total_tokens,
            tool_calls=parsed_tool_calls,
            raw_message=raw_message_dict,
        )

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
        return self.generate_chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            tools=tools,
        )

    def generate_chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float = settings.llm_temperature,
        max_tokens: int = settings.llm_max_tokens,
        json_mode: bool = False,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        try:
            chat_kwargs = self._build_chat_kwargs(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                tools=tools,
            )
            response = self.client.chat(**chat_kwargs)
            return self._parse_response(response)
        except Exception as e:
            logger.error(f"Error calling Ollama API: {e}")
            raise RuntimeError(f"Failed to generate response from Ollama: {e}")

    def get_model_name(self) -> str:
        return self.model

