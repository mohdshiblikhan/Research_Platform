import json
import pytest
from unittest.mock import patch, MagicMock

from app.services.llm_service import LLMResponse
from app.models.project import Project
from app.models.document import Document, DocumentStatus
from app.models.chunk import Chunk


@pytest.fixture
def mock_llm_service():
    with patch("app.services.rag_service.get_llm_service") as mock_factory:
        mock_service = MagicMock()
        mock_service.get_model_name.return_value = "mocked-llm"
        
        # Default mock response
        mock_response = LLMResponse(
            content=json.dumps({
                "evidence_analysis": "Mock analysis of evidence.",
                "answer": "This is a grounded answer [1].",
                "citations": [
                    {"claim": "A claim", "source_indices": [1], "quote": "Quote"}
                ],
                "confidence": "high",
                "has_sufficient_evidence": True
            }),
            model="mocked-llm",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150
        )
        mock_service.generate.return_value = mock_response
        mock_factory.return_value = mock_service
        yield mock_service


@pytest.fixture
def populated_db(db_session):
    """Creates a project, a document, and a few chunks."""
    # Create Project
    project = Project(title="RAG Test Project", description="Test")
    db_session.add(project)
    db_session.flush()
    
    # Create Document
    doc = Document(
        project_id=project.id,
        filename="test_rag.pdf",
        mime_type="application/pdf",
        file_size=1000,
        file_path="mock/path.pdf",
        page_count=2,
        status=DocumentStatus.PROCESSED.value
    )
    db_session.add(doc)
    db_session.flush()
    
    # Create Chunk 1
    chunk1 = Chunk(
        document_id=doc.id,
        chunk_index=0,
        content="The sky is blue because of Rayleigh scattering.",
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=45,
        chunk_size=45
    )
    # Create Chunk 2
    chunk2 = Chunk(
        document_id=doc.id,
        chunk_index=1,
        content="Water is made of hydrogen and oxygen.",
        page_start=2,
        page_end=2,
        char_offset_start=46,
        char_offset_end=83,
        chunk_size=37
    )
    db_session.add_all([chunk1, chunk2])
    db_session.commit()
    
    return project.id, doc.id


def test_ask_basic(client, mock_llm_service, populated_db):
    project_id, _ = populated_db
    
    response = client.post(f"/api/projects/{project_id}/ask", json={
        "question": "Why is the sky blue?",
        "search_mode": "keyword",
        "rerank": False
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["question"] == "Why is the sky blue?"
    assert data["answer"] == "This is a grounded answer [1]."
    assert data["evidence_analysis"] == "Mock analysis of evidence."
    assert len(data["citations"]) == 1
    assert data["citations"][0]["source_index"] == 1
    assert data["citations"][0]["document_filename"] == "test_rag.pdf"
    
    # The first source should be Chunk 1 (Rayleigh scattering)
    assert len(data["sources"]) >= 1
    assert "Rayleigh scattering" in data["sources"][0]["content"]

def test_ask_empty_question(client, populated_db):
    project_id, _ = populated_db
    response = client.post(f"/api/projects/{project_id}/ask", json={
        "question": ""
    })
    assert response.status_code == 422 # FastAPI validation

def test_ask_nonexistent_project(client, mock_llm_service):
    response = client.post("/api/projects/9999/ask", json={
        "question": "Test?"
    })
    assert response.status_code == 404

def test_ask_no_matching_chunks(client, mock_llm_service, populated_db):
    project_id, _ = populated_db
    
    # "zebra" won't match any chunks
    response = client.post(f"/api/projects/{project_id}/ask", json={
        "question": "Tell me about zebras.",
        "search_mode": "keyword"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "could not find relevant evidence" in data["answer"]
    assert len(data["sources"]) == 0
    assert data["citation_verification"]["total"] == 0
    
    # LLM should not have been called
    mock_llm_service.generate.assert_not_called()

def test_ask_hallucinated_citation(client, mock_llm_service, populated_db):
    project_id, _ = populated_db
    
    # Modify mock to return an invalid source_index (999)
    mock_llm_service.generate.return_value.content = json.dumps({
        "evidence_analysis": "Analysis",
        "answer": "Answer.",
        "citations": [
            {"claim": "Claim", "source_indices": [999], "quote": "Quote"}
        ],
        "confidence": "high",
        "has_sufficient_evidence": True
    })
    
    response = client.post(f"/api/projects/{project_id}/ask", json={
        "question": "Why is the sky blue?",
        "search_mode": "keyword"
    })
    
    assert response.status_code == 200
    data = response.json()
    assert data["citation_verification"]["invalid"] == 1
    assert len(data["citations"]) == 0 # It should strip invalid citations
