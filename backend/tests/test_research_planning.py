import json
from unittest.mock import MagicMock, patch

import pytest

from app.models.document import Document, DocumentStatus
from app.models.extraction import DocumentExtraction
from app.models.project import Project
from app.models.research_plan import ResearchPlan
from app.services.llm_service import LLMResponse


@pytest.fixture
def mock_llm_service():
    """Mock LLMService that handles both comparison synthesis and research planning calls."""
    with patch("app.services.research_planning_service.get_llm_service") as mock_plan_factory, \
         patch("app.services.comparison_service.get_llm_service") as mock_comp_factory:
        mock_service = MagicMock()
        mock_service.get_model_name.return_value = "mocked-llm"

        def mock_generate(*args, **kwargs):
            system_prompt = kwargs.get("system_prompt", "")
            if "research analyst" in system_prompt or "key_differences" in system_prompt:
                # Comparison synthesis response
                return LLMResponse(
                    content=json.dumps({
                        "key_differences": "Paper 1 uses dense retrieval while Paper 2 uses hybrid BM25.",
                        "common_themes": "Both address retrieval-augmented generation and hallucination mitigation.",
                        "conflicting_findings": None,
                        "research_gaps": "Neither evaluates on domain-specific medical QA benchmarks.",
                        "summary": "Both papers explore retrieval architectures to reduce LLM hallucinations."
                    }),
                    model="mocked-llm",
                )
            else:
                # Research planning response
                return LLMResponse(
                    content=json.dumps({
                        "reasoning": "The analyzed literature establishes that retrieval reduces hallucinations, but domain-specific evaluation is unaddressed. Hence, G1 addresses domain evaluation...",
                        "literature_summary": "Analysis of the project papers reveals strong general QA baselines but a critical gap in specialized domains.",
                        "gaps": [
                            {
                                "id": "G1",
                                "description": "Lack of evaluation on specialized medical domain QA benchmarks.",
                                "evidence": ["Doc 1 tested only SQuAD", "Doc 2 limitations note biomedical vocabulary degradation"],
                                "source_documents": [1, 2]
                            }
                        ],
                        "hypotheses": [
                            {
                                "id": "H1",
                                "statement": "Domain-adapted cross-encoder reranking reduces hallucination rate by at least 15% on MedQA.",
                                "addresses_gaps": ["G1"],
                                "rationale": "Cross-encoders capture deep token interactions, which mitigates specialized terminology confusion."
                            }
                        ],
                        "experiments": [
                            {
                                "id": "E1",
                                "title": "Cross-Encoder Adaptation on MedQA",
                                "hypothesis": "H1",
                                "method": "Fine-tune MiniLM reranker on MedQA and compare against BM25 baseline.",
                                "datasets": "MedQA, PubMedQA",
                                "metrics": ["Recall@10", "Faithfulness", "HallucinationRate"],
                                "priority": "high"
                            }
                        ],
                        "recommended_sequence": ["E1"],
                        "confidence": "high",
                        "limitations": "This plan is strictly bounded by the 2 analyzed papers in this project corpus."
                    }),
                    model="mocked-llm",
                )

        mock_service.generate.side_effect = mock_generate
        mock_plan_factory.return_value = mock_service
        mock_comp_factory.return_value = mock_service
        yield mock_service


@pytest.fixture
def planning_setup(db_session):
    """Creates a project with 3 documents: 2 with extractions, 1 without."""
    project = Project(title="RAG Research Planning", description="Testing Milestone 11")
    db_session.add(project)
    db_session.flush()

    doc1 = Document(
        project_id=project.id,
        filename="rag_paper_1.pdf",
        mime_type="application/pdf",
        file_size=1500,
        file_path="mock/rag_paper_1.pdf",
        page_count=6,
        status=DocumentStatus.PROCESSED.value,
    )
    doc2 = Document(
        project_id=project.id,
        filename="rag_paper_2.pdf",
        mime_type="application/pdf",
        file_size=1800,
        file_path="mock/rag_paper_2.pdf",
        page_count=10,
        status=DocumentStatus.PROCESSED.value,
    )
    doc3 = Document(
        project_id=project.id,
        filename="unextracted_paper.pdf",
        mime_type="application/pdf",
        file_size=800,
        file_path="mock/unextracted_paper.pdf",
        page_count=4,
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add_all([doc1, doc2, doc3])
    db_session.flush()

    ext1 = DocumentExtraction(
        document_id=doc1.id,
        research_problem="Hallucinations in dense RAG pipelines",
        methodology="Iterative dense retrieval with feedback",
        models_used="all-MiniLM-L6-v2 + LLaMA-3",
        datasets="SQuAD v2, HotpotQA",
        evaluation_metrics="Recall@10, ExactMatch",
        results="Recall@10 improved by 12%",
        limitations="Evaluated only on open-domain QA",
        baselines="Standard dense retrieval",
        raw_llm_output={"research_problem": "Hallucinations"},
    )
    ext2 = DocumentExtraction(
        document_id=doc2.id,
        research_problem="Retrieval degradation on multi-hop questions",
        methodology="Hybrid BM25 + Cross-Encoder reranking",
        models_used="BM25 + ms-marco-MiniLM",
        datasets="HotpotQA, FEVER",
        evaluation_metrics="MRR, nDCG@10",
        results="nDCG improved from 0.65 to 0.78",
        limitations="High latency during reranking; untested on medical data",
        baselines="BM25 baseline",
        raw_llm_output={"research_problem": "Multi-hop retrieval"},
    )
    db_session.add_all([ext1, ext2])
    db_session.commit()

    return project.id, doc1.id, doc2.id, doc3.id


def test_create_plan_success(client, mock_llm_service, planning_setup):
    """Test 1: Create a research plan with valid question and extractions."""
    p_id, d1_id, d2_id, _ = planning_setup

    response = client.post(
        f"/api/projects/{p_id}/plan",
        json={
            "research_question": "How can we reduce hallucinations in specialized domain RAG pipelines?"
        },
    )
    assert response.status_code == 200
    data = response.json()

    assert data["project_id"] == p_id
    assert data["research_question"] == "How can we reduce hallucinations in specialized domain RAG pipelines?"
    assert data["documents_analyzed"] == 2
    assert d1_id in data["document_ids_used"]
    assert d2_id in data["document_ids_used"]
    assert len(data["gaps"]) == 1
    assert data["gaps"][0]["id"] == "G1"
    assert len(data["hypotheses"]) == 1
    assert data["hypotheses"][0]["id"] == "H1"
    assert len(data["experiments"]) == 1
    assert data["experiments"][0]["id"] == "E1"
    assert data["confidence"] == "high"
    assert data["llm_model"] == "mocked-llm"
    assert data["planning_time_ms"] >= 0
    assert data["total_time_ms"] >= 0


def test_create_plan_with_explicit_document_ids(client, mock_llm_service, planning_setup):
    """Test 2: Explicit document_ids parameter specifies exact scope."""
    p_id, d1_id, d2_id, _ = planning_setup

    response = client.post(
        f"/api/projects/{p_id}/plan",
        json={
            "research_question": "What retrieval techniques best minimize factual error?",
            "document_ids": [d1_id, d2_id],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["documents_analyzed"] == 2
    assert set(data["document_ids_used"]) == {d1_id, d2_id}
    assert data["documents_without_extraction"] == []


def test_create_plan_with_one_missing_extraction(client, mock_llm_service, planning_setup):
    """Test 3: Specifying a document lacking extraction reports it in documents_without_extraction."""
    p_id, d1_id, d2_id, d3_id = planning_setup

    response = client.post(
        f"/api/projects/{p_id}/plan",
        json={
            "research_question": "How to design better multi-hop retrieval architectures?",
            "document_ids": [d1_id, d2_id, d3_id],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["documents_analyzed"] == 2
    assert d3_id in data["documents_without_extraction"]


def test_create_plan_insufficient_extractions(client, mock_llm_service, db_session):
    """Test 4: Fewer than 2 documents with extractions returns 400."""
    project = Project(title="Single Paper Project", description="Only 1 extraction")
    db_session.add(project)
    db_session.flush()

    doc = Document(
        project_id=project.id,
        filename="single.pdf",
        mime_type="application/pdf",
        file_size=500,
        file_path="mock/single.pdf",
        page_count=2,
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add(doc)
    db_session.flush()

    ext = DocumentExtraction(
        document_id=doc.id,
        research_problem="Problem A",
    )
    db_session.add(ext)
    db_session.commit()

    response = client.post(
        f"/api/projects/{project.id}/plan",
        json={"research_question": "What is the best way to train rerankers?"},
    )
    assert response.status_code == 400
    assert "At least 2 documents with extractions are required" in response.json()["detail"]


def test_create_plan_project_not_found(client, mock_llm_service):
    """Test 5: Nonexistent project returns 404."""
    response = client.post(
        "/api/projects/999999/plan",
        json={"research_question": "How to scale cross-encoder inference latency?"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_create_plan_document_not_in_project(client, mock_llm_service, planning_setup):
    """Test 6: Requesting document_id from another project returns 404."""
    p_id, d1_id, _, _ = planning_setup

    response = client.post(
        f"/api/projects/{p_id}/plan",
        json={
            "research_question": "How to optimize dense retrieval indexing?",
            "document_ids": [d1_id, 888888],
        },
    )
    assert response.status_code == 404
    assert "not found in project" in response.json()["detail"].lower()


def test_create_plan_short_question_fails_validation(client, planning_setup):
    """Test 7: Question shorter than 10 chars fails with 422."""
    p_id, _, _, _ = planning_setup

    response = client.post(
        f"/api/projects/{p_id}/plan",
        json={"research_question": "Too short"},
    )
    assert response.status_code == 422


def test_create_plan_exceeds_max_document_ids(client, planning_setup):
    """Test 8: Request with >15 document IDs fails validation with 422."""
    p_id, _, _, _ = planning_setup

    response = client.post(
        f"/api/projects/{p_id}/plan",
        json={
            "research_question": "What are the common failure modes across large corpora?",
            "document_ids": list(range(1, 17)),
        },
    )
    assert response.status_code == 422


def test_list_plans_empty(client, planning_setup):
    """Test 9: Listing plans for project with none returns empty list."""
    p_id, _, _, _ = planning_setup

    response = client.get(f"/api/projects/{p_id}/plans")
    assert response.status_code == 200
    assert response.json() == []


def test_list_and_get_plan(client, mock_llm_service, planning_setup):
    """Test 10: Create plan, list plans, and retrieve plan by ID."""
    p_id, _, _, _ = planning_setup

    # Create plan
    create_resp = client.post(
        f"/api/projects/{p_id}/plan",
        json={"research_question": "How can reranking improve domain-specific QA?"},
    )
    assert create_resp.status_code == 200
    plan_id = create_resp.json()["id"]

    # List plans
    list_resp = client.get(f"/api/projects/{p_id}/plans")
    assert list_resp.status_code == 200
    plans = list_resp.json()
    assert len(plans) == 1
    assert plans[0]["id"] == plan_id
    assert plans[0]["research_question"] == "How can reranking improve domain-specific QA?"
    assert plans[0]["confidence"] == "high"

    # Get plan by ID
    get_resp = client.get(f"/api/projects/{p_id}/plans/{plan_id}")
    assert get_resp.status_code == 200
    plan_data = get_resp.json()
    assert plan_data["id"] == plan_id
    assert plan_data["project_id"] == p_id
    assert plan_data["reasoning"].startswith("The analyzed literature")
    assert len(plan_data["gaps"]) == 1
    assert len(plan_data["hypotheses"]) == 1
    assert len(plan_data["experiments"]) == 1


def test_get_plan_not_found(client, planning_setup):
    """Test 11: Get nonexistent plan ID returns 404."""
    p_id, _, _, _ = planning_setup

    response = client.get(f"/api/projects/{p_id}/plans/999999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_plan_wrong_project(client, mock_llm_service, planning_setup, db_session):
    """Test 12: Plan exists in Project 1, but requested under Project 2 returns 404."""
    p_id, _, _, _ = planning_setup

    # Create second project
    proj2 = Project(title="Second Project")
    db_session.add(proj2)
    db_session.commit()

    # Create plan under project 1
    create_resp = client.post(
        f"/api/projects/{p_id}/plan",
        json={"research_question": "How does cross-encoder compare to bi-encoder?"},
    )
    plan_id = create_resp.json()["id"]

    # Request under project 2
    response = client.get(f"/api/projects/{proj2.id}/plans/{plan_id}")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_plan_chain_traceability(client, mock_llm_service, planning_setup):
    """Test 13: Verify Gap -> Hypothesis -> Experiment chain integrity."""
    p_id, _, _, _ = planning_setup

    response = client.post(
        f"/api/projects/{p_id}/plan",
        json={"research_question": "What is the optimal sequence for RAG evaluation?"},
    )
    assert response.status_code == 200
    data = response.json()

    gap_ids = {g["id"] for g in data["gaps"]}
    hyp_ids = {h["id"] for h in data["hypotheses"]}

    # Every hypothesis must reference a known gap
    for hyp in data["hypotheses"]:
        for gap_ref in hyp["addresses_gaps"]:
            assert gap_ref in gap_ids

    # Every experiment must reference a known hypothesis
    for exp in data["experiments"]:
        assert exp["hypothesis"] in hyp_ids

    # Recommended sequence must contain valid experiment IDs
    exp_ids = {e["id"] for e in data["experiments"]}
    for seq_item in data["recommended_sequence"]:
        assert seq_item in exp_ids


def test_plan_persistence_and_versioning(client, mock_llm_service, planning_setup, db_session):
    """Test 14: Creating multiple plans preserves history (versioning) in DB."""
    p_id, _, _, _ = planning_setup

    # Create first plan
    resp1 = client.post(
        f"/api/projects/{p_id}/plan",
        json={"research_question": "Question Version 1: Initial exploration of RAG."},
    )
    assert resp1.status_code == 200
    plan1_id = resp1.json()["id"]

    # Create second plan
    resp2 = client.post(
        f"/api/projects/{p_id}/plan",
        json={"research_question": "Question Version 2: Deeper dive into reranker latency."},
    )
    assert resp2.status_code == 200
    plan2_id = resp2.json()["id"]

    assert plan1_id != plan2_id

    # Verify both records exist in DB
    plans_in_db = (
        db_session.query(ResearchPlan)
        .filter(ResearchPlan.project_id == p_id)
        .order_by(ResearchPlan.id.asc())
        .all()
    )
    assert len(plans_in_db) == 2
    assert plans_in_db[0].id == plan1_id
    assert plans_in_db[1].id == plan2_id
    assert plans_in_db[0].documents_analyzed == 2
    assert isinstance(plans_in_db[0].document_ids_used, list)
    assert plans_in_db[0].llm_model == "mocked-llm"
