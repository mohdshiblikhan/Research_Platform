import json
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document, DocumentStatus
from app.models.extraction import DocumentExtraction
from app.models.project import Project
from app.services.llm_service import LLMResponse


@pytest.fixture
def mock_llm_service():
    with patch("app.services.comparison_service.get_llm_service") as mock_factory:
        mock_service = MagicMock()
        mock_service.get_model_name.return_value = "mocked-llm"

        mock_response = LLMResponse(
            content=json.dumps({
                "key_differences": "Paper 1 uses Method 1 while Paper 2 uses Method 2.",
                "common_themes": "Both address AI research.",
                "conflicting_findings": None,
                "research_gaps": "Neither evaluates on real-world datasets.",
                "summary": "Paper 1 and Paper 2 explore alternative models."
            }),
            model="mocked-llm"
        )
        mock_service.generate.return_value = mock_response
        mock_factory.return_value = mock_service
        yield mock_service


@pytest.fixture
def comparison_setup(db_session):
    """Fixture that creates a project with 3 documents: 2 with extractions, 1 without."""
    project = Project(title="Comparison Project", description="Test literature comparison")
    db_session.add(project)
    db_session.flush()

    doc1 = Document(
        project_id=project.id,
        filename="test1.pdf",
        mime_type="application/pdf",
        file_size=1000,
        file_path="mock/test1.pdf",
        page_count=5,
        status=DocumentStatus.PROCESSED.value,
    )
    doc2 = Document(
        project_id=project.id,
        filename="test2.pdf",
        mime_type="application/pdf",
        file_size=1200,
        file_path="mock/test2.pdf",
        page_count=8,
        status=DocumentStatus.PROCESSED.value,
    )
    doc3 = Document(
        project_id=project.id,
        filename="test3.pdf",
        mime_type="application/pdf",
        file_size=900,
        file_path="mock/test3.pdf",
        page_count=3,
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add_all([doc1, doc2, doc3])
    db_session.flush()

    ext1 = DocumentExtraction(
        document_id=doc1.id,
        research_problem="Problem 1",
        methodology="Method 1",
        models_used="Model 1",
        datasets="Dataset 1",
        evaluation_metrics="Metric 1",
        results="Result 1",
        limitations="Limitation 1",
        baselines="Baseline 1",
        raw_llm_output={"research_problem": "Problem 1"},
    )
    ext2 = DocumentExtraction(
        document_id=doc2.id,
        research_problem="Problem 2",
        methodology="Method 2",
        models_used="Model 2",
        datasets="Dataset 2",
        evaluation_metrics="Metric 2",
        results="Result 2",
        limitations="Limitation 2",
        baselines="Baseline 2",
        raw_llm_output={"research_problem": "Problem 2"},
    )
    db_session.add_all([ext1, ext2])
    db_session.commit()

    return project.id, doc1.id, doc2.id, doc3.id


def test_compare_two_documents_success(client, comparison_setup):
    """Test 1: Compare 2 documents with extractions successfully."""
    p_id, d1_id, d2_id, _ = comparison_setup

    response = client.post(
        f"/api/projects/{p_id}/compare",
        json={"document_ids": [d1_id, d2_id]},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["project_id"] == p_id
    assert data["documents_compared"] == 2
    assert data["documents_missing_extraction"] == []
    assert len(data["fields"]) == 8
    assert data["synthesis"] is None
    assert data["llm_model"] is None
    assert data["synthesis_time_ms"] is None


def test_compare_with_one_missing_extraction(client, comparison_setup):
    """Test 2: Compare 3 documents where 1 is missing extraction."""
    p_id, d1_id, d2_id, d3_id = comparison_setup

    response = client.post(
        f"/api/projects/{p_id}/compare",
        json={"document_ids": [d1_id, d2_id, d3_id]},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["documents_compared"] == 2
    assert data["documents_missing_extraction"] == [d3_id]
    assert len(data["fields"]) == 8


def test_compare_fewer_than_two_document_ids(client, comparison_setup):
    """Test 3: Request with only 1 document fails 422."""
    p_id, d1_id, _, _ = comparison_setup

    response = client.post(
        f"/api/projects/{p_id}/compare",
        json={"document_ids": [d1_id]},
    )
    assert response.status_code == 422


def test_compare_more_than_ten_document_ids(client, comparison_setup):
    """Test 4: Request with more than 10 documents fails 422."""
    p_id, _, _, _ = comparison_setup

    response = client.post(
        f"/api/projects/{p_id}/compare",
        json={"document_ids": list(range(1, 12))},
    )
    assert response.status_code == 422


def test_compare_document_not_in_project(client, comparison_setup):
    """Test 5: Document ID not in project returns 404."""
    p_id, d1_id, _, _ = comparison_setup

    response = client.post(
        f"/api/projects/{p_id}/compare",
        json={"document_ids": [d1_id, 999999]},
    )
    assert response.status_code == 404
    assert "not found in project" in response.json()["detail"].lower()


def test_compare_no_documents_have_extractions(client, db_session):
    """Test 6: None of the documents have extractions returns 400."""
    project = Project(title="No Extractions Project", description="None")
    db_session.add(project)
    db_session.flush()

    doc_a = Document(
        project_id=project.id,
        filename="a.pdf",
        mime_type="application/pdf",
        file_size=100,
        file_path="mock/a.pdf",
        page_count=1,
        status=DocumentStatus.PROCESSED.value,
    )
    doc_b = Document(
        project_id=project.id,
        filename="b.pdf",
        mime_type="application/pdf",
        file_size=100,
        file_path="mock/b.pdf",
        page_count=1,
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add_all([doc_a, doc_b])
    db_session.commit()

    response = client.post(
        f"/api/projects/{project.id}/compare",
        json={"document_ids": [doc_a.id, doc_b.id]},
    )
    assert response.status_code == 400
    assert "None of the specified documents have extractions" in response.json()["detail"]


def test_compare_only_one_document_has_extraction(client, comparison_setup):
    """Test 7: Only 1 document has extraction returns 400."""
    p_id, d1_id, _, d3_id = comparison_setup

    response = client.post(
        f"/api/projects/{p_id}/compare",
        json={"document_ids": [d1_id, d3_id]},
    )
    assert response.status_code == 400
    assert "At least 2 documents must have extractions" in response.json()["detail"]


def test_compare_with_synthesis(client, mock_llm_service, comparison_setup):
    """Test 8: include_synthesis=True calls LLM and returns structured synthesis."""
    p_id, d1_id, d2_id, _ = comparison_setup

    response = client.post(
        f"/api/projects/{p_id}/compare",
        json={"document_ids": [d1_id, d2_id], "include_synthesis": True},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["synthesis"] is not None
    assert data["synthesis"]["key_differences"] == "Paper 1 uses Method 1 while Paper 2 uses Method 2."
    assert data["synthesis"]["common_themes"] == "Both address AI research."
    assert data["synthesis"]["conflicting_findings"] is None
    assert data["synthesis"]["research_gaps"] == "Neither evaluates on real-world datasets."
    assert data["synthesis"]["summary"] == "Paper 1 and Paper 2 explore alternative models."
    assert data["llm_model"] == "mocked-llm"
    assert data["synthesis_time_ms"] is not None
    assert data["synthesis_time_ms"] >= 0

    # Verify LLM was called with json_mode=True
    mock_llm_service.generate.assert_called_once()
    _, kwargs = mock_llm_service.generate.call_args
    assert kwargs.get("json_mode") is True


def test_compare_without_synthesis_default(client, comparison_setup):
    """Test 9: include_synthesis=False (default) returns None for synthesis."""
    p_id, d1_id, d2_id, _ = comparison_setup

    response = client.post(
        f"/api/projects/{p_id}/compare",
        json={"document_ids": [d1_id, d2_id]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["synthesis"] is None
    assert data["llm_model"] is None
    assert data["synthesis_time_ms"] is None


def test_compare_field_values_correctness(client, comparison_setup):
    """Test 10: Compare specific field values and check matching data."""
    p_id, d1_id, d2_id, _ = comparison_setup

    response = client.post(
        f"/api/projects/{p_id}/compare",
        json={"document_ids": [d1_id, d2_id]},
    )
    assert response.status_code == 200
    data = response.json()

    # Turn fields into dict keyed by field_name
    fields_by_name = {f["field_name"]: f for f in data["fields"]}

    # Check methodology row
    assert "methodology" in fields_by_name
    methodology_field = fields_by_name["methodology"]
    assert methodology_field["field_label"] == "Methodology"
    assert len(methodology_field["values"]) == 2

    assert methodology_field["values"][0]["document_id"] == d1_id
    assert methodology_field["values"][0]["filename"] == "test1.pdf"
    assert methodology_field["values"][0]["value"] == "Method 1"

    assert methodology_field["values"][1]["document_id"] == d2_id
    assert methodology_field["values"][1]["filename"] == "test2.pdf"
    assert methodology_field["values"][1]["value"] == "Method 2"

    # Check results row
    results_field = fields_by_name["results"]
    assert results_field["field_label"] == "Results"
    assert results_field["values"][0]["value"] == "Result 1"
    assert results_field["values"][1]["value"] == "Result 2"
