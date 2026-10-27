from unittest.mock import MagicMock, patch
import pytest

from app.schemas.tool import ToolCall
from app.services.ollama_llm_service import OllamaLLMService


@pytest.fixture
def ollama_service():
    with patch("app.services.ollama_llm_service.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        service = OllamaLLMService(host="http://mock-host:11434", model="test-model")
        service.client = mock_client
        yield service, mock_client


def test_generate_chat_basic(ollama_service):
    service, mock_client = ollama_service
    mock_client.chat.return_value = {
        "model": "test-model",
        "message": {"role": "assistant", "content": "Hello researcher!"},
        "prompt_eval_count": 12,
        "eval_count": 8,
    }

    messages = [
        {"role": "system", "content": "You are a research assistant."},
        {"role": "user", "content": "Hello!"},
    ]
    response = service.generate_chat(messages=messages, temperature=0.2, max_tokens=100)

    assert response.content == "Hello researcher!"
    assert response.model == "test-model"
    assert response.prompt_tokens == 12
    assert response.completion_tokens == 8
    assert response.total_tokens == 20
    assert response.tool_calls is None
    assert response.raw_message == {"role": "assistant", "content": "Hello researcher!"}

    mock_client.chat.assert_called_once_with(
        model="test-model",
        messages=messages,
        options={"temperature": 0.2, "num_predict": 100},
        format="",
    )


def test_generate_chat_with_single_tool_call(ollama_service):
    service, mock_client = ollama_service
    mock_client.chat.return_value = {
        "model": "test-model",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_123",
                    "function": {
                        "name": "search_chunks",
                        "arguments": {"query": "transformer attention", "limit": 5},
                    },
                }
            ],
        },
        "prompt_eval_count": 25,
        "eval_count": 15,
    }

    messages = [{"role": "user", "content": "Search for attention"}]
    tools = [{"type": "function", "function": {"name": "search_chunks"}}]
    response = service.generate_chat(messages=messages, tools=tools)

    assert response.tool_calls is not None
    assert len(response.tool_calls) == 1
    tc = response.tool_calls[0]
    assert tc.id == "call_123"
    assert tc.name == "search_chunks"
    assert tc.arguments == {"query": "transformer attention", "limit": 5}
    assert response.content == ""


def test_generate_chat_with_multiple_tool_calls(ollama_service):
    service, mock_client = ollama_service
    mock_client.chat.return_value = {
        "model": "test-model",
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "get_chunk",
                        "arguments": {"chunk_id": 10},
                    },
                },
                {
                    "id": "call_2",
                    "function": {
                        "name": "get_paper_extraction",
                        "arguments": {"document_id": 2},
                    },
                },
            ],
        },
        "prompt_eval_count": 40,
        "eval_count": 25,
    }

    messages = [{"role": "user", "content": "Get chunk 10 and extraction 2"}]
    response = service.generate_chat(messages=messages)

    assert response.tool_calls is not None
    assert len(response.tool_calls) == 2
    assert response.tool_calls[0].name == "get_chunk"
    assert response.tool_calls[0].arguments == {"chunk_id": 10}
    assert response.tool_calls[1].name == "get_paper_extraction"
    assert response.tool_calls[1].arguments == {"document_id": 2}


def test_generate_backward_compatibility(ollama_service):
    service, mock_client = ollama_service
    mock_client.chat.return_value = {
        "model": "test-model",
        "message": {"role": "assistant", "content": "Generated response"},
        "prompt_eval_count": 20,
        "eval_count": 10,
    }

    response = service.generate(
        system_prompt="System instructions",
        user_prompt="User query",
        temperature=0.5,
        max_tokens=500,
        json_mode=True,
    )

    assert response.content == "Generated response"
    mock_client.chat.assert_called_once_with(
        model="test-model",
        messages=[
            {"role": "system", "content": "System instructions"},
            {"role": "user", "content": "User query"},
        ],
        options={"temperature": 0.5, "num_predict": 500},
        format="json",
    )


def test_generate_chat_error_handling(ollama_service):
    service, mock_client = ollama_service
    mock_client.chat.side_effect = ConnectionError("Ollama daemon unreachable")

    with pytest.raises(RuntimeError, match="Failed to generate response from Ollama"):
        service.generate_chat(messages=[{"role": "user", "content": "test"}])
