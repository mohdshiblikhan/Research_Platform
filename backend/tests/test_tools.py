import json
from unittest.mock import MagicMock, patch
import pytest

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.extraction import DocumentExtraction
from app.models.project import Project
from app.models.research_plan import ResearchPlan
from app.schemas.tool import ToolCall, ToolSafetyTier
from app.services.llm_service import LLMResponse
from app.services.tool_execution_service import ToolExecutionService
from app.services.tools.base import BaseTool, ToolContext
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
from app.services.tools.registry import ToolRegistry, get_default_tool_registry


@pytest.fixture
def tools_setup(db_session):
    """Sets up two projects: Project 1 with 2 processed docs, chunks, extractions, plan,
    and Project 2 with 1 doc and chunk for cross-project isolation tests."""
    # Project 1
    p1 = Project(title="Project 1: Tool Calling", description="Testing tools")
    db_session.add(p1)
    db_session.flush()

    d1 = Document(
        project_id=p1.id,
        filename="paper_one.pdf",
        file_path="mock/paper_one.pdf",
        file_size=1024,
        mime_type="application/pdf",
        page_count=5,
        status=DocumentStatus.PROCESSED.value,
    )
    d2 = Document(
        project_id=p1.id,
        filename="paper_two.pdf",
        file_path="mock/paper_two.pdf",
        file_size=2048,
        mime_type="application/pdf",
        page_count=8,
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add_all([d1, d2])
    db_session.flush()

    c1 = Chunk(
        document_id=d1.id,
        chunk_index=0,
        content="Retrieval-augmented generation reduces hallucinations in large language models.",
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=82,
        chunk_size=82,
        embedding=[0.05] * 384,
    )
    c2 = Chunk(
        document_id=d2.id,
        chunk_index=0,
        content="Cross-encoder reranking significantly boosts top-k retrieval precision.",
        page_start=1,
        page_end=2,
        char_offset_start=0,
        char_offset_end=73,
        chunk_size=73,
        embedding=[0.05] * 384,
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    ext1 = DocumentExtraction(
        document_id=d1.id,
        research_problem="Mitigating hallucinations in RAG",
        methodology="Dense retrieval augmentation",
        models_used="all-MiniLM-L6-v2",
        datasets="SQuAD",
        evaluation_metrics="Recall@10",
        results="Recall increased by 15%",
        limitations="Evaluated only on open-domain datasets",
        baselines="BM25",
    )
    ext2 = DocumentExtraction(
        document_id=d2.id,
        research_problem="Ranking latency and quality trade-offs",
        methodology="Cross-encoder reranking pipeline",
        models_used="ms-marco-MiniLM-L-6-v2",
        datasets="MS MARCO",
        evaluation_metrics="MRR@10, Latency",
        results="MRR improved by 22%",
        limitations="Higher inference latency",
        baselines="Bi-encoder",
    )
    db_session.add_all([ext1, ext2])
    db_session.flush()

    plan = ResearchPlan(
        project_id=p1.id,
        research_question="How to reduce hallucination with reranking?",
        document_ids_used=[d1.id, d2.id],
        plan_output={
            "literature_summary": "Both papers study retrieval optimization.",
            "gaps": [{"id": "G1", "description": "No domain specific evaluation"}],
            "hypotheses": [{"id": "H1", "statement": "Reranking improves domain QA"}],
            "experiments": [{"id": "E1", "title": "MedQA Reranker Benchmark"}],
            "recommended_sequence": ["E1"],
        },
        llm_model="mocked-llm",
        planning_time_ms=120.0,
        documents_analyzed=2,
    )
    db_session.add(plan)
    db_session.flush()

    # Project 2 (Isolated)
    p2 = Project(title="Project 2: Isolated", description="Isolated project")
    db_session.add(p2)
    db_session.flush()

    d3 = Document(
        project_id=p2.id,
        filename="isolated_paper.pdf",
        file_path="mock/isolated.pdf",
        file_size=512,
        mime_type="application/pdf",
        page_count=2,
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add(d3)
    db_session.flush()

    c3 = Chunk(
        document_id=d3.id,
        chunk_index=0,
        content="Secret proprietary research not accessible to Project 1.",
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=58,
        chunk_size=58,
        embedding=[0.01] * 384,
    )
    db_session.add(c3)
    db_session.flush()

    return {
        "p1": p1,
        "d1": d1,
        "d2": d2,
        "c1": c1,
        "c2": c2,
        "ext1": ext1,
        "ext2": ext2,
        "plan": plan,
        "p2": p2,
        "d3": d3,
        "c3": c3,
    }


# ==============================================================================
# 1. Registry & Schema Tests
# ==============================================================================

def test_tool_registry_initialization():
    """Verify registry initializes with all 8 platform tools and allows lookup."""
    registry = get_default_tool_registry()
    tools = registry.get_all_tools()
    assert len(tools) == 8

    tool_names = [t.name for t in tools]
    expected_names = [
        "search_chunks",
        "get_chunk",
        "list_documents",
        "get_document_metadata",
        "get_paper_extraction",
        "compare_papers",
        "get_research_plan",
        "list_research_plans",
    ]
    for name in expected_names:
        assert name in tool_names
        tool = registry.get_tool(name)
        assert tool is not None
        assert tool.name == name

    assert registry.get_tool("nonexistent") is None


def test_tool_registry_duplicate_registration():
    """Verify duplicate tool name registration raises ValueError."""
    registry = ToolRegistry()
    registry.register(SearchChunksTool())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(SearchChunksTool())


def test_tool_to_openai_schema():
    """Verify tool generates valid OpenAI/Ollama function-calling schema."""
    tool = SearchChunksTool()
    schema = tool.to_openai_tool()

    assert schema["type"] == "function"
    assert "function" in schema
    func = schema["function"]
    assert func["name"] == "search_chunks"
    assert "query" in func["parameters"]["properties"]
    assert "mode" in func["parameters"]["properties"]
    assert "limit" in func["parameters"]["properties"]
    assert "required" in func["parameters"]
    assert "query" in func["parameters"]["required"]


# ==============================================================================
# 2. Tool Execution Tests
# ==============================================================================

def test_search_chunks_tool_execution(db_session, tools_setup):
    """Verify search_chunks tool retrieves matching chunks with provenance."""
    p1 = tools_setup["p1"]
    tool = SearchChunksTool()
    context = ToolContext(db=db_session, project_id=p1.id)

    res = tool.run(context, query="retrieval-augmented generation", mode="keyword", limit=5)
    assert res.success is True
    assert "Found" in res.result_summary
    assert "Chunk" in res.result_summary
    assert res.data is not None
    assert len(res.data["results"]) >= 1


def test_get_chunk_tool_success(db_session, tools_setup):
    """Verify get_chunk tool returns verbatim text and provenance."""
    p1 = tools_setup["p1"]
    c1 = tools_setup["c1"]
    tool = GetChunkTool()
    context = ToolContext(db=db_session, project_id=p1.id)

    res = tool.run(context, chunk_id=c1.id)
    assert res.success is True
    assert "Retrieval-augmented generation" in res.result_summary
    assert res.data["id"] == c1.id
    assert res.data["page_start"] == 1


def test_get_chunk_cross_project_isolation(db_session, tools_setup):
    """Verify attempting to access a chunk from Project 2 within Project 1 context fails."""
    p1 = tools_setup["p1"]
    c3 = tools_setup["c3"]  # Belongs to Project 2
    tool = GetChunkTool()
    context = ToolContext(db=db_session, project_id=p1.id)

    res = tool.run(context, chunk_id=c3.id)
    assert res.success is False
    assert "not found in this project" in res.result_summary
    assert res.error is not None


def test_list_documents_tool(db_session, tools_setup):
    """Verify list_documents tool lists all documents with counts and statuses."""
    p1 = tools_setup["p1"]
    tool = ListDocumentsTool()
    context = ToolContext(db=db_session, project_id=p1.id)

    res = tool.run(context)
    assert res.success is True
    assert "Project contains 2 document(s)" in res.result_summary
    assert len(res.data["documents"]) == 2

    # Test status filter
    res_filtered = tool.run(context, status="processed")
    assert len(res_filtered.data["documents"]) == 2
    res_empty = tool.run(context, status="failed")
    assert len(res_empty.data["documents"]) == 0


def test_get_document_metadata_tool(db_session, tools_setup):
    """Verify get_document_metadata tool retrieves document metadata and extraction presence."""
    p1 = tools_setup["p1"]
    d1 = tools_setup["d1"]
    d3 = tools_setup["d3"]  # Project 2
    tool = GetDocumentMetadataTool()
    context = ToolContext(db=db_session, project_id=p1.id)

    res = tool.run(context, document_id=d1.id)
    assert res.success is True
    assert "Structured Extraction Available: Yes" in res.result_summary
    assert res.data["has_extraction"] is True
    assert res.data["chunks_count"] == 1

    # Cross project document access
    res_cross = tool.run(context, document_id=d3.id)
    assert res_cross.success is False
    assert res_cross.error == "Document not found."


def test_get_paper_extraction_tool(db_session, tools_setup):
    """Verify get_paper_extraction tool returns structured metadata fields."""
    p1 = tools_setup["p1"]
    d1 = tools_setup["d1"]
    tool = GetPaperExtractionTool()
    context = ToolContext(db=db_session, project_id=p1.id)

    res = tool.run(context, document_id=d1.id)
    assert res.success is True
    assert "Mitigating hallucinations in RAG" in res.result_summary
    assert res.data["research_problem"] == "Mitigating hallucinations in RAG"
    assert res.data["methodology"] == "Dense retrieval augmentation"


def test_compare_papers_tool(db_session, tools_setup):
    """Verify compare_papers tool returns comparison matrix and synthesis."""
    p1 = tools_setup["p1"]
    d1 = tools_setup["d1"]
    d2 = tools_setup["d2"]
    tool = ComparePapersTool()
    context = ToolContext(db=db_session, project_id=p1.id)

    with patch("app.services.comparison_service.get_llm_service") as mock_comp_factory:
        mock_service = MagicMock()
        mock_service.get_model_name.return_value = "mocked-llm"
        mock_service.generate.return_value = LLMResponse(
            content=json.dumps({
                "key_differences": "Paper 1 uses dense retrieval, Paper 2 uses reranking.",
                "common_themes": "Both address retrieval quality.",
                "conflicting_findings": None,
                "research_gaps": "Neither evaluates specialized domain QA.",
                "summary": "Both explore retrieval optimizations."
            }),
            model="mocked-llm",
        )
        mock_comp_factory.return_value = mock_service

        res = tool.run(context, document_ids=[d1.id, d2.id], include_synthesis=True)
        assert res.success is True
        assert "Comparison of 2 documents" in res.result_summary
        assert "Key Differences" in res.result_summary


def test_research_plan_tools(db_session, tools_setup):
    """Verify list_research_plans and get_research_plan tools."""
    p1 = tools_setup["p1"]
    plan = tools_setup["plan"]
    list_tool = ListResearchPlansTool()
    get_tool = GetResearchPlanTool()
    context = ToolContext(db=db_session, project_id=p1.id)

    # List plans
    list_res = list_tool.run(context)
    assert list_res.success is True
    assert "Project contains 1 research plan(s)" in list_res.result_summary
    assert len(list_res.data["plans"]) == 1

    # Get plan
    get_res = get_tool.run(context, plan_id=plan.id)
    assert get_res.success is True
    assert f"Research Plan ID {plan.id}" in get_res.result_summary
    assert "MedQA Reranker Benchmark" in get_res.result_summary


# ==============================================================================
# 3. ToolExecutionService Sandboxing & Validation Tests
# ==============================================================================

def test_tool_execution_service_validation_error(db_session, tools_setup):
    """Verify Pydantic validation errors are safely trapped and returned."""
    p1 = tools_setup["p1"]
    service = ToolExecutionService()

    # Query length too short (< 3)
    res = service.execute(
        db=db_session,
        project_id=p1.id,
        tool_name="search_chunks",
        arguments={"query": "ab"},
    )
    assert res.success is False
    assert "Invalid arguments" in res.result_summary
    assert res.error is not None
    assert res.execution_time_ms >= 0


def test_tool_execution_service_unknown_tool(db_session, tools_setup):
    """Verify executing an unregistered tool returns clean error response."""
    p1 = tools_setup["p1"]
    service = ToolExecutionService()

    res = service.execute(
        db=db_session,
        project_id=p1.id,
        tool_name="drop_database",
        arguments={},
    )
    assert res.success is False
    assert "does not exist in registry" in res.result_summary
    assert "Tool 'drop_database' not found." in res.error


# ==============================================================================
# 4. REST API Endpoint Tests
# ==============================================================================

def test_api_list_tools(client, db_session, tools_setup):
    """Verify GET /api/projects/{project_id}/tools returns all registered tools."""
    p1 = tools_setup["p1"]
    response = client.get(f"/api/projects/{p1.id}/tools")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 8
    names = [t["name"] for t in data]
    assert "search_chunks" in names
    assert "compare_papers" in names

    # 404 for invalid project
    res_404 = client.get("/api/projects/999999/tools")
    assert res_404.status_code == 404


def test_api_execute_tool_endpoint(client, db_session, tools_setup):
    """Verify POST /api/projects/{project_id}/tools/execute executes tool."""
    p1 = tools_setup["p1"]
    payload = {
        "tool_name": "list_documents",
        "arguments": {},
    }
    response = client.post(f"/api/projects/{p1.id}/tools/execute", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["tool_name"] == "list_documents"
    assert "Project contains 2 document(s)" in data["result_summary"]
    assert data["execution_time_ms"] >= 0

    # 404 for invalid project
    res_404 = client.post("/api/projects/999999/tools/execute", json=payload)
    assert res_404.status_code == 404


# ==============================================================================
# 5. LLM Tool Calling Integration Test
# ==============================================================================

def test_mock_llm_tool_calling_flow(db_session, tools_setup):
    """Verify end-to-end agent tool execution pattern with parsed ToolCall."""
    p1 = tools_setup["p1"]
    service = ToolExecutionService()

    # Simulate LLM returning a tool call
    mock_llm_response = LLMResponse(
        content="",
        model="mocked-llm",
        tool_calls=[
            ToolCall(
                id="call_123",
                name="search_chunks",
                arguments={"query": "hallucinations in large language models", "mode": "keyword", "limit": 3},
            )
        ],
    )

    # Agent loop inspects tool call and dispatches
    assert mock_llm_response.tool_calls is not None
    tc = mock_llm_response.tool_calls[0]
    exec_res = service.execute(
        db=db_session,
        project_id=p1.id,
        tool_name=tc.name,
        arguments=tc.arguments,
    )

    assert exec_res.success is True
    assert "Found" in exec_res.result_summary
    assert exec_res.data is not None
