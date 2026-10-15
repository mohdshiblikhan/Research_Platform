import json
from unittest.mock import MagicMock, patch

import pytest

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.extraction import DocumentExtraction
from app.models.project import Project
from app.services.llm_service import LLMResponse


@pytest.fixture
def mock_llm_service():
    with patch("app.services.extraction_service.get_llm_service") as mock_factory:
        mock_service = MagicMock()
        mock_service.get_model_name.return_value = "mocked-llm"

        mock_response = LLMResponse(
            content=json.dumps({
                "research_problem": "Test problem",
                "methodology": "Test method",
                "models_used": "Test models",
                "datasets": "Test datasets",
                "evaluation_metrics": "Test metrics",
                "results": "Test results",
                "limitations": "Test limitations",
                "baselines": "Test baselines"
            }),
            model="mocked-llm"
        )
        mock_service.generate.return_value = mock_response
        mock_factory.return_value = mock_service
        yield mock_service


@pytest.fixture
def populated_db(db_session):
    project = Project(title="Extraction Test Project", description="Test")
    db_session.add(project)
    db_session.flush()

    doc = Document(
        project_id=project.id,
        filename="test_extract.pdf",
        mime_type="application/pdf",
        file_size=1000,
        file_path="mock/path.pdf",
        page_count=2,
        status=DocumentStatus.PROCESSED.value
    )
    db_session.add(doc)
    db_session.flush()

    # Create enough chunks to test edge and semantic selection
    for i in range(10):
        chunk = Chunk(
            document_id=doc.id,
            chunk_index=i,
            content=f"Chunk {i} content about research methodology and datasets.",
            page_start=1,
            page_end=1,
            char_offset_start=i*100,
            char_offset_end=(i+1)*100,
            chunk_size=100
        )
        db_session.add(chunk)
    db_session.commit()

    return project.id, doc.id


def test_extract_document(client, mock_llm_service, populated_db):
    project_id, doc_id = populated_db

    response = client.post(f"/api/projects/{project_id}/documents/{doc_id}/extract")
    assert response.status_code == 200
    data = response.json()
    assert data["research_problem"] == "Test problem"
    assert data["methodology"] == "Test method"
    assert data["document_id"] == doc_id

    # Verify the LLM was called with JSON mode
    mock_llm_service.generate.assert_called_once()
    _, kwargs = mock_llm_service.generate.call_args
    assert kwargs.get("json_mode") is True


def test_get_extracted_data(client, populated_db, db_session):
    project_id, doc_id = populated_db

    # Insert an extraction manually
    ext = DocumentExtraction(
        document_id=doc_id,
        research_problem="Pre-inserted problem",
        raw_llm_output={"research_problem": "Pre-inserted problem"}
    )
    db_session.add(ext)
    db_session.commit()

    response = client.get(f"/api/projects/{project_id}/documents/{doc_id}/extract")
    assert response.status_code == 200
    data = response.json()
    assert data["research_problem"] == "Pre-inserted problem"
    assert data["raw_llm_output"] == {"research_problem": "Pre-inserted problem"}


def test_extract_invalid_json(client, mock_llm_service, populated_db):
    project_id, doc_id = populated_db

    # Mock invalid JSON response
    mock_llm_service.generate.return_value.content = "This is not JSON at all."

    response = client.post(f"/api/projects/{project_id}/documents/{doc_id}/extract")
    assert response.status_code == 400
    assert "Failed to parse structured output" in response.json()["detail"]
