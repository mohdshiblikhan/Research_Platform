import json
import time
from unittest.mock import MagicMock, patch
import pytest

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.project import Project
from app.schemas.agent import AgentResearchRequest
from app.schemas.tool import ToolCall
from app.services.agent_service import AgentService, _trim_messages_if_needed
from app.services.llm_service import LLMResponse


@pytest.fixture
def agent_setup(db_session):
    """Sets up a test project with documents and chunks for agent execution tests."""
    p1 = Project(title="RAG Hallucinations Research", description="Agent evaluation project")
    p2 = Project(title="Another Project", description="Isolation test project")
    db_session.add_all([p1, p2])
    db_session.flush()

    d1 = Document(
        project_id=p1.id,
        filename="rag_survey.pdf",
        file_path="mock/rag_survey.pdf",
        file_size=1024,
        mime_type="application/pdf",
        page_count=6,
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add(d1)
    db_session.flush()

    c1 = Chunk(
        document_id=d1.id,
        chunk_index=0,
        content="Retrieval-augmented generation grounds LLM responses with retrieved factual evidence.",
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=88,
        chunk_size=88,
        embedding=[0.1] * 384,
    )
    db_session.add(c1)
    db_session.flush()

    return {"p1": p1, "p2": p2, "d1": d1, "c1": c1}


def test_agent_converges_naturally(db_session, agent_setup):
    p1 = agent_setup["p1"]
    mock_llm = MagicMock()

    # Turn 1: LLM calls search_chunks
    # Turn 2: LLM produces JSON final answer
    resp_turn_1 = LLMResponse(
        content="",
        model="llama3.1:8b",
        total_tokens=45,
        tool_calls=[
            ToolCall(
                id="call_1",
                name="search_chunks",
                arguments={"query": "retrieval augmented generation", "limit": 2},
            )
        ],
    )
    final_json = json.dumps({
        "answer": "RAG reduces hallucinations by grounding responses in retrieved passages.",
        "citations": [
            {
                "chunk_id": agent_setup["c1"].id,
                "document_id": agent_setup["d1"].id,
                "filename": "rag_survey.pdf",
                "page_number": 1,
                "claim": "RAG grounds LLM responses with factual evidence",
            }
        ],
    })
    resp_turn_2 = LLMResponse(
        content=final_json,
        model="llama3.1:8b",
        total_tokens=60,
        tool_calls=None,
    )

    mock_llm.generate_chat.side_effect = [resp_turn_1, resp_turn_2]
    mock_llm.get_model_name.return_value = "llama3.1:8b"

    service = AgentService(db=db_session, llm_service=mock_llm)
    request = AgentResearchRequest(
        research_question="How does RAG mitigate hallucinations?",
        max_iterations=5,
    )

    result = service.run_research_session(project_id=p1.id, request=request)

    assert result.status == "completed"
    assert result.stop_reason == "Agent converged on final answer"
    assert "RAG reduces hallucinations" in result.final_answer
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == agent_setup["c1"].id
    assert len(result.trajectory) == 2
    assert result.trajectory[0].action_type == "tool_call"
    assert result.trajectory[1].action_type == "final_answer"
    assert result.total_tool_calls == 1
    assert result.total_tokens_used == 105


def test_agent_max_iterations_forced_synthesis(db_session, agent_setup):
    p1 = agent_setup["p1"]
    mock_llm = MagicMock()

    # LLM keeps calling list_documents repeatedly without converging
    tool_resp = LLMResponse(
        content="",
        model="llama3.1:8b",
        total_tokens=30,
        tool_calls=[
            ToolCall(
                id="call_doc",
                name="list_documents",
                arguments={},
            )
        ],
    )
    # Forced synthesis returns final synthesized answer
    synth_json = json.dumps({
        "answer": "Synthesized conclusion based on project documents.",
        "citations": [],
    })
    synth_resp = LLMResponse(
        content=synth_json,
        model="llama3.1:8b",
        total_tokens=40,
        tool_calls=None,
    )

    mock_llm.generate_chat.side_effect = [tool_resp, tool_resp, synth_resp]
    mock_llm.get_model_name.return_value = "llama3.1:8b"

    service = AgentService(db=db_session, llm_service=mock_llm)
    request = AgentResearchRequest(
        research_question="What documents exist?",
        max_iterations=2,
    )

    result = service.run_research_session(project_id=p1.id, request=request)

    assert result.status == "max_iterations"
    assert "maximum 2 iterations" in result.stop_reason
    assert "Synthesized conclusion" in result.final_answer
    # Trajectory has 2 tool iterations + 1 forced_synthesis step
    assert len(result.trajectory) == 3
    assert result.trajectory[2].action_type == "forced_synthesis"


def test_agent_max_tool_calls_reached(db_session, agent_setup):
    p1 = agent_setup["p1"]
    mock_llm = MagicMock()

    # Turn 1 requests 2 tool calls
    resp_turn_1 = LLMResponse(
        content="",
        model="llama3.1:8b",
        total_tokens=35,
        tool_calls=[
            ToolCall(id="c1", name="list_documents", arguments={}),
            ToolCall(id="c2", name="search_chunks", arguments={"query": "test"}),
        ],
    )
    synth_json = json.dumps({"answer": "Forced synthesis after tool limit.", "citations": []})
    resp_synth = LLMResponse(content=synth_json, model="llama3.1:8b", total_tokens=25)

    mock_llm.generate_chat.side_effect = [resp_turn_1, resp_synth]
    mock_llm.get_model_name.return_value = "llama3.1:8b"

    service = AgentService(db=db_session, llm_service=mock_llm)
    request = AgentResearchRequest(
        research_question="Test tool budget",
        max_tool_calls=2,
    )

    result = service.run_research_session(project_id=p1.id, request=request)

    assert result.status == "max_tool_calls"
    assert "limit of 2 tool calls" in result.stop_reason
    assert result.total_tool_calls == 2


def test_agent_timeout(db_session, agent_setup):
    p1 = agent_setup["p1"]
    mock_llm = MagicMock()

    mock_llm.generate_chat.return_value = LLMResponse(
        content=json.dumps({"answer": "Timed out synthesis", "citations": []}),
        model="llama3.1:8b",
    )
    mock_llm.get_model_name.return_value = "llama3.1:8b"

    service = AgentService(db=db_session, llm_service=mock_llm)
    # Patch time.perf_counter so elapsed immediately exceeds max_time_seconds
    with patch("time.perf_counter", side_effect=[0.0, 15.0, 15.1, 15.2, 15.3, 15.4]):
        request = AgentResearchRequest(
            research_question="Test timeout",
            max_time_seconds=10,
        )
        result = service.run_research_session(project_id=p1.id, request=request)

    assert result.status == "timeout"
    assert "exceeded 10s" in result.stop_reason


def test_agent_consecutive_errors(db_session, agent_setup):
    p1 = agent_setup["p1"]
    mock_llm = MagicMock()

    # LLM requests nonexistent tool 3 times consecutively
    fail_resp = LLMResponse(
        content="",
        model="llama3.1:8b",
        total_tokens=10,
        tool_calls=[ToolCall(id="err", name="nonexistent_tool", arguments={})],
    )
    synth_resp = LLMResponse(
        content=json.dumps({"answer": "Error synthesis", "citations": []}),
        model="llama3.1:8b",
    )

    mock_llm.generate_chat.side_effect = [fail_resp, fail_resp, fail_resp, synth_resp]
    mock_llm.get_model_name.return_value = "llama3.1:8b"

    service = AgentService(db=db_session, llm_service=mock_llm)
    request = AgentResearchRequest(
        research_question="Test error handling",
        max_iterations=10,
    )

    result = service.run_research_session(project_id=p1.id, request=request)

    assert result.status == "failed"
    assert "consecutive tool/call errors" in result.stop_reason


def test_agent_duplicate_tool_call_skipped(db_session, agent_setup):
    p1 = agent_setup["p1"]
    mock_llm = MagicMock()

    # Turn 1: search_chunks query="test"
    turn_1 = LLMResponse(
        content="",
        model="llama3.1:8b",
        tool_calls=[ToolCall(id="c1", name="search_chunks", arguments={"query": "test"})],
    )
    # Turn 2: identical search_chunks query="test"
    turn_2 = LLMResponse(
        content="",
        model="llama3.1:8b",
        tool_calls=[ToolCall(id="c2", name="search_chunks", arguments={"query": "test"})],
    )
    turn_3 = LLMResponse(
        content=json.dumps({"answer": "Final response after duplicate", "citations": []}),
        model="llama3.1:8b",
    )

    mock_llm.generate_chat.side_effect = [turn_1, turn_2, turn_3]
    mock_llm.get_model_name.return_value = "llama3.1:8b"

    service = AgentService(db=db_session, llm_service=mock_llm)
    request = AgentResearchRequest(research_question="Duplicate test", max_iterations=5)

    result = service.run_research_session(project_id=p1.id, request=request)

    assert result.status == "completed"
    # Check that in trajectory step 2, duplicate was skipped
    step_2 = result.trajectory[1]
    assert len(step_2.tool_calls) == 1
    assert "Duplicate tool call" in step_2.tool_calls[0].result_summary
    assert result.total_tool_calls == 1  # only 1 executed call counted


def test_agent_trajectory_observable_structure(db_session, agent_setup):
    p1 = agent_setup["p1"]
    mock_llm = MagicMock()

    turn_1 = LLMResponse(
        content="",
        model="llama3.1:8b",
        total_tokens=20,
        tool_calls=[ToolCall(id="c1", name="list_documents", arguments={})],
    )
    turn_2 = LLMResponse(
        content=json.dumps({"answer": "We have 1 document.", "citations": []}),
        model="llama3.1:8b",
        total_tokens=25,
    )

    mock_llm.generate_chat.side_effect = [turn_1, turn_2]
    mock_llm.get_model_name.return_value = "llama3.1:8b"

    service = AgentService(db=db_session, llm_service=mock_llm)
    request = AgentResearchRequest(research_question="Structure test")
    result = service.run_research_session(project_id=p1.id, request=request)

    for step in result.trajectory:
        assert step.iteration > 0
        assert step.action_type in ["tool_call", "final_answer", "forced_synthesis"]
        assert step.iteration_time_ms >= 0.0


def test_agent_session_persistence_lifecycle(db_session, agent_setup):
    p1 = agent_setup["p1"]
    mock_llm = MagicMock()

    mock_llm.generate_chat.return_value = LLMResponse(
        content=json.dumps({"answer": "Immediate answer", "citations": []}),
        model="llama3.1:8b",
    )
    mock_llm.get_model_name.return_value = "llama3.1:8b"

    service = AgentService(db=db_session, llm_service=mock_llm)
    result = service.run_research_session(
        project_id=p1.id,
        request=AgentResearchRequest(research_question="Lifecycle test"),
    )

    from app.repositories.agent_session_repository import AgentSessionRepository
    repo = AgentSessionRepository(db_session)
    stored = repo.get_by_id(result.session_id)

    assert stored is not None
    assert stored.status == "completed"
    assert stored.final_answer == "Immediate answer"
    assert stored.completed_at is not None
    assert stored.total_time_ms > 0


def test_agent_checkpointing(db_session, agent_setup):
    p1 = agent_setup["p1"]
    mock_llm = MagicMock()

    tool_call = LLMResponse(
        content="",
        model="llama3.1:8b",
        tool_calls=[ToolCall(id="c", name="list_documents", arguments={})],
    )
    final_resp = LLMResponse(
        content=json.dumps({"answer": "Done after 3", "citations": []}),
        model="llama3.1:8b",
    )
    mock_llm.generate_chat.side_effect = [tool_call, tool_call, tool_call, final_resp]
    mock_llm.get_model_name.return_value = "llama3.1:8b"

    mock_repo = MagicMock()
    mock_session = MagicMock(id=42, created_at=None, completed_at=None)
    mock_repo.create.return_value = mock_session
    mock_repo.finalize_session.return_value = mock_session

    service = AgentService(db=db_session, llm_service=mock_llm, session_repo=mock_repo)
    service.run_research_session(
        project_id=p1.id,
        request=AgentResearchRequest(research_question="Checkpoint test", max_iterations=4),
    )

    # With checkpoint_interval=3, checkpoint_trajectory must have been called on iteration 3
    assert mock_repo.checkpoint_trajectory.call_count >= 1


def test_agent_endpoint_success(client, agent_setup):
    p1 = agent_setup["p1"]

    mock_resp = LLMResponse(
        content=json.dumps({"answer": "API answer", "citations": []}),
        model="llama3.1:8b",
        total_tokens=30,
    )
    with patch("app.services.agent_service.get_llm_service") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.generate_chat.return_value = mock_resp
        mock_llm.get_model_name.return_value = "llama3.1:8b"
        mock_get_llm.return_value = mock_llm

        res = client.post(
            f"/api/projects/{p1.id}/agent/research",
            json={"research_question": "Endpoint test question"},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["final_answer"] == "API answer"
        assert data["project_id"] == p1.id


def test_agent_endpoint_not_found(client):
    res = client.post(
        "/api/projects/99999/agent/research",
        json={"research_question": "Nonexistent project"},
    )
    assert res.status_code == 404


def test_agent_list_sessions_endpoint(client, agent_setup, db_session):
    p1 = agent_setup["p1"]
    from app.repositories.agent_session_repository import AgentSessionRepository
    repo = AgentSessionRepository(db_session)
    s = repo.create(project_id=p1.id, research_question="Q1", model_used="test")
    repo.finalize_session(
        session_id=s.id,
        status="completed",
        final_answer="A1",
        citations=[],
        trajectory=[],
        total_iterations=1,
        total_tool_calls=1,
        total_tokens_used=10,
        total_time_ms=50.0,
        stop_reason="test",
    )

    res = client.get(f"/api/projects/{p1.id}/agent/sessions")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["session_id"] == s.id
    assert data[0]["research_question"] == "Q1"


def test_agent_get_session_endpoint(client, agent_setup, db_session):
    p1 = agent_setup["p1"]
    from app.repositories.agent_session_repository import AgentSessionRepository
    repo = AgentSessionRepository(db_session)
    s = repo.create(project_id=p1.id, research_question="Inspectable Session", model_used="test")
    repo.finalize_session(
        session_id=s.id,
        status="completed",
        final_answer="Detailed answer",
        citations=[{"chunk_id": 1, "claim": "C"}],
        trajectory=[{"iteration": 1, "action_type": "final_answer", "tool_calls": [], "iteration_time_ms": 10.0}],
        total_iterations=1,
        total_tool_calls=0,
        total_tokens_used=20,
        total_time_ms=100.0,
        stop_reason="test",
    )

    res = client.get(f"/api/projects/{p1.id}/agent/sessions/{s.id}")
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == s.id
    assert data["final_answer"] == "Detailed answer"
    assert len(data["trajectory"]) == 1


def test_agent_get_session_cross_project_isolation(client, agent_setup, db_session):
    p1 = agent_setup["p1"]
    p2 = agent_setup["p2"]
    from app.repositories.agent_session_repository import AgentSessionRepository
    repo = AgentSessionRepository(db_session)
    s = repo.create(project_id=p1.id, research_question="Project 1 only", model_used="test")

    # Attempting to access p1's session via p2's URL must return 404
    res = client.get(f"/api/projects/{p2.id}/agent/sessions/{s.id}")
    assert res.status_code == 404


def test_agent_context_budget_trimming():
    long_content = "X" * 1000
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "research question"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "search"}]},
        {"role": "tool", "content": long_content, "tool_name": "search"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "get_chunk"}]},
        {"role": "tool", "content": "short content", "tool_name": "get_chunk"},
    ]

    # Set very small budget to force trimming
    _trim_messages_if_needed(messages, max_tokens=100)

    # Observation at index 3 must be trimmed
    assert len(messages[3]["content"]) < len(long_content)
    assert "[earlier observation trimmed" in messages[3]["content"]
    # System and user must remain untouched
    assert messages[0]["content"] == "system prompt"
    assert messages[1]["content"] == "research question"
