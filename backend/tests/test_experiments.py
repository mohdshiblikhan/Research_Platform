import pytest
from sqlalchemy.exc import IntegrityError

from app.models.document import Document, DocumentStatus
from app.models.experiment import Experiment, ExperimentPriority, ExperimentStatus
from app.models.project import Project
from app.models.research_plan import ResearchPlan


@pytest.fixture
def project(db_session):
    """Fixture creating a test project."""
    p = Project(title="Experiment Testing Project", description="Test Project")
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


@pytest.fixture
def documents(db_session, project):
    """Fixture creating two sample documents in the project."""
    d1 = Document(
        project_id=project.id,
        filename="paper1.pdf",
        file_path="/tmp/paper1.pdf",
        file_size=1024,
        mime_type="application/pdf",
        status=DocumentStatus.PROCESSED.value,
    )
    d2 = Document(
        project_id=project.id,
        filename="paper2.pdf",
        file_path="/tmp/paper2.pdf",
        file_size=2048,
        mime_type="application/pdf",
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add_all([d1, d2])
    db_session.commit()
    db_session.refresh(d1)
    db_session.refresh(d2)
    return [d1, d2]


@pytest.fixture
def research_plan(db_session, project, documents):
    """Fixture creating a sample ResearchPlan with structured output."""
    plan_output = {
        "reasoning": "Test reasoning linking gaps and hypotheses",
        "literature_summary": "Test literature summary",
        "gaps": [
            {
                "id": "G1",
                "description": "Lack of evaluation on specialized medical domain QA benchmarks.",
                "evidence": ["Doc 1 tested only SQuAD"],
                "source_documents": [documents[0].id, documents[1].id],
            },
            {
                "id": "G2",
                "description": "Context dilution in long-context models.",
                "evidence": ["Doc 2 notes context degradation"],
                "source_documents": [documents[1].id],
            },
        ],
        "hypotheses": [
            {
                "id": "H1",
                "statement": "Domain-adaptive retrieval rerankers will achieve higher precision on medical QA.",
                "addresses_gaps": ["G1"],
                "rationale": "Medical vocabulary requires specialized domain embeddings.",
            },
            {
                "id": "H2",
                "statement": "Hierarchical chunking mitigates context dilution in long documents.",
                "addresses_gaps": ["G2"],
                "rationale": "Smaller chunk windows preserve term density.",
            },
        ],
        "experiments": [
            {
                "id": "E1",
                "title": "Evaluate Cross-Encoder Reranking on PubMedQA",
                "hypothesis": "H1",
                "method": "Run hybrid retrieval followed by cross-encoder reranking.",
                "datasets": "PubMedQA, MedQA",
                "metrics": ["Recall@10", "MRR"],
                "priority": "high",
            },
            {
                "id": "E2",
                "title": "Compare Recursive vs Fixed Chunking on Long Papers",
                "hypothesis": "H2",
                "method": "Split 50 papers recursively vs fixed 1000 chars.",
                "datasets": "ArXiv CS Dataset",
                "metrics": ["nDCG@10"],
                "priority": "medium",
            },
        ],
        "recommended_sequence": ["E1", "E2"],
        "confidence": "high",
        "limitations": "Bounded corpus of 2 papers.",
    }

    plan = ResearchPlan(
        project_id=project.id,
        research_question="How to reduce retrieval hallucination in specialized domains?",
        document_ids_used=[d.id for d in documents],
        plan_output=plan_output,
        llm_model="mocked-model",
        planning_time_ms=120.0,
        documents_analyzed=len(documents),
    )
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


# ── Core Experiment Tests (1–17) ──────────────────────────────────────────


def test_create_manual_experiment_planned(client, project):
    """Test 1: Verify manual creation with custom parameters, flexible datasets, and status planned."""
    payload = {
        "title": "Custom Exploratory Experiment",
        "methodology": "Test custom prompt variations on zero-shot reasoning.",
        "status": "planned",
        "priority": "high",
        "datasets": ["CustomBenchmark-V1"],
        "parameters": {"temperature": 0.2, "top_p": 0.95},
        "target_metrics": ["accuracy"],
    }
    response = client.post(f"/api/projects/{project.id}/experiments", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == payload["title"]
    assert data["status"] == "planned"
    assert data["priority"] == "high"
    assert data["datasets"] == ["CustomBenchmark-V1"]
    assert data["parameters"] == {"temperature": 0.2, "top_p": 0.95}
    assert data["completed_at"] is None


def test_create_manual_experiment_directly_completed(client, project):
    """Test 2: Verify direct manual creation with status completed when results/findings are provided."""
    payload = {
        "title": "Pre-Executed Retrospective Experiment",
        "methodology": "Conducted external benchmark evaluation across 500 queries.",
        "status": "completed",
        "priority": "medium",
        "results": {"Recall@10": 0.88, "latency_ms": 34.2},
        "findings": {
            "summary": "Achieved significant recall improvement with minimal latency penalty.",
            "hypothesis_verdict": "supported",
            "observations": ["Observed strong performance on short queries."],
        },
    }
    response = client.post(f"/api/projects/{project.id}/experiments", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "completed"
    assert data["completed_at"] is not None
    assert data["results"] == {"Recall@10": 0.88, "latency_ms": 34.2}
    assert data["findings"]["hypothesis_verdict"] == "supported"


def test_create_manual_experiment_without_target_metrics(client, project):
    """Test 3: Verify that exploratory experiments can be created without target metrics."""
    payload = {
        "title": "Qualitative Error Analysis",
        "methodology": "Manually inspect 50 failure cases for qualitative classification.",
        "status": "planned",
    }
    response = client.post(f"/api/projects/{project.id}/experiments", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["target_metrics"] == []
    assert data["status"] == "planned"


def test_create_manual_experiment_rejects_plan_exp_id_without_plan_id(client, project):
    """Test 4: Assert 400 or 422 error when supplying plan_experiment_id without research_plan_id."""
    payload = {
        "title": "Invalid Experiment",
        "methodology": "Methodology description",
        "plan_experiment_id": "E1",
    }
    response = client.post(f"/api/projects/{project.id}/experiments", json=payload)
    assert response.status_code in (400, 422)
    assert "Cannot specify plan_experiment_id without a research_plan_id" in response.text


def test_promote_all_experiments_from_plan(client, project, research_plan):
    """Test 5: Verify batch promotion of all ProposedExperiment entries from a ResearchPlan."""
    response = client.post(
        f"/api/projects/{project.id}/plans/{research_plan.id}/experiments",
        json={},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["plan_id"] == research_plan.id
    assert data["total_proposed"] == 2
    assert data["promoted_count"] == 2
    assert data["already_promoted_count"] == 0
    assert len(data["experiments"]) == 2

    # Verify promoted attributes
    e1 = next(e for e in data["experiments"] if e["plan_experiment_id"] == "E1")
    assert e1["status"] == "planned"
    assert e1["priority"] == "high"
    assert e1["hypothesis_id"] == "H1"
    assert e1["hypothesis_statement"] is not None
    assert e1["provenance"]["gap_ids"] == ["G1"]


def test_promote_selective_experiments_from_plan(client, project, research_plan):
    """Test 6: Verify selective promotion of specific IDs (plan_experiment_ids=['E1'])."""
    response = client.post(
        f"/api/projects/{project.id}/plans/{research_plan.id}/experiments",
        json={"plan_experiment_ids": ["E1"]},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["total_proposed"] == 1
    assert data["promoted_count"] == 1
    assert data["already_promoted_count"] == 0
    assert len(data["experiments"]) == 1
    assert data["experiments"][0]["plan_experiment_id"] == "E1"


def test_promote_rejects_invalid_experiment_ids(client, project, research_plan):
    """Test 7: Verify that requesting nonexistent IDs (e.g. ['E99']) returns 400 Bad Request."""
    response = client.post(
        f"/api/projects/{project.id}/plans/{research_plan.id}/experiments",
        json={"plan_experiment_ids": ["E99"]},
    )
    assert response.status_code == 400
    assert "Proposed experiment 'E99' not found in research plan" in response.json()["detail"]


def test_promote_all_already_promoted_returns_200(client, project, research_plan):
    """Test 8: Verify that re-promoting an already fully promoted plan returns 200 OK with promoted_count=0."""
    # First promotion
    res1 = client.post(
        f"/api/projects/{project.id}/plans/{research_plan.id}/experiments",
        json={"plan_experiment_ids": ["E1"]},
    )
    assert res1.status_code == 201

    # Second promotion of same experiment
    res2 = client.post(
        f"/api/projects/{project.id}/plans/{research_plan.id}/experiments",
        json={"plan_experiment_ids": ["E1"]},
    )
    assert res2.status_code == 200
    data = res2.json()
    assert data["promoted_count"] == 0
    assert data["already_promoted_count"] == 1
    assert len(data["experiments"]) == 1
    assert data["experiments"][0]["plan_experiment_id"] == "E1"


def test_promote_experiments_db_unique_constraint(db_session, project, research_plan):
    """Test 9: Verify database unique constraint prevents duplicate rows on (research_plan_id, plan_experiment_id)."""
    exp1 = Experiment(
        project_id=project.id,
        research_plan_id=research_plan.id,
        plan_experiment_id="E1",
        title="Duplicate Test 1",
        methodology="Test methodology",
    )
    db_session.add(exp1)
    db_session.commit()

    exp2 = Experiment(
        project_id=project.id,
        research_plan_id=research_plan.id,
        plan_experiment_id="E1",
        title="Duplicate Test 2",
        methodology="Test methodology",
    )
    db_session.add(exp2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_promote_preserves_provenance_and_m11_field_mapping(client, project, research_plan, documents):
    """Test 10: Verify promoted experiments inherit hypothesis, gap IDs, and document IDs from M11 fields."""
    response = client.post(
        f"/api/projects/{project.id}/plans/{research_plan.id}/experiments",
        json={"plan_experiment_ids": ["E1"]},
    )
    assert response.status_code == 201
    exp = response.json()["experiments"][0]
    assert exp["hypothesis_id"] == "H1"
    assert "Domain-adaptive retrieval" in exp["hypothesis_statement"]
    assert exp["provenance"]["gap_ids"] == ["G1"]
    # G1 links to documents 0 and 1
    assert set(exp["provenance"]["document_ids"]) == {documents[0].id, documents[1].id}


def test_provenance_validation_standalone_vs_plan_linked(client, project, research_plan, documents):
    """Test 11: Standalone allows independent hypothesis; plan-linked strictly validates against plan gaps/hypotheses."""
    # Valid standalone with independent hypothesis
    standalone = {
        "title": "Standalone Custom Hypothesis",
        "methodology": "Evaluating novel prompt technique",
        "hypothesis_id": "CUSTOM-H1",
        "hypothesis_statement": "Novel prompts improve code synthesis",
        "provenance": {"document_ids": [documents[0].id]},
    }
    res_s = client.post(f"/api/projects/{project.id}/experiments", json=standalone)
    assert res_s.status_code == 201
    assert res_s.json()["hypothesis_id"] == "CUSTOM-H1"

    # Plan-linked with invalid hypothesis ID
    invalid_plan_linked = {
        "title": "Plan Linked Experiment",
        "methodology": "Testing methodology",
        "research_plan_id": research_plan.id,
        "hypothesis_id": "NONEXISTENT-H",
    }
    res_inv = client.post(f"/api/projects/{project.id}/experiments", json=invalid_plan_linked)
    assert res_inv.status_code == 400
    assert "Hypothesis 'NONEXISTENT-H' not found in research plan" in res_inv.json()["detail"]


def test_list_experiments_filtered_and_has_results_property(client, project):
    """Test 12: Verify filtering by status/priority and assert has_results property on summaries."""
    # Create planned experiment without results
    client.post(
        f"/api/projects/{project.id}/experiments",
        json={"title": "Planned Exp", "methodology": "Method", "status": "planned", "priority": "low"},
    )
    # Create completed experiment with results
    client.post(
        f"/api/projects/{project.id}/experiments",
        json={
            "title": "Completed Exp",
            "methodology": "Method",
            "status": "completed",
            "priority": "high",
            "results": {"acc": 0.9},
        },
    )

    # List all
    res_all = client.get(f"/api/projects/{project.id}/experiments")
    assert res_all.status_code == 200
    summaries = res_all.json()
    assert len(summaries) == 2

    # Check has_results property
    planned_summary = next(s for s in summaries if s["title"] == "Planned Exp")
    completed_summary = next(s for s in summaries if s["title"] == "Completed Exp")
    assert planned_summary["has_results"] is False
    assert completed_summary["has_results"] is True

    # Filter by status
    res_filter_status = client.get(f"/api/projects/{project.id}/experiments?status=completed")
    assert len(res_filter_status.json()) == 1
    assert res_filter_status.json()[0]["title"] == "Completed Exp"

    # Filter by priority
    res_filter_priority = client.get(f"/api/projects/{project.id}/experiments?priority=low")
    assert len(res_filter_priority.json()) == 1
    assert res_filter_priority.json()[0]["title"] == "Planned Exp"


def test_get_experiment_by_id(client, project):
    """Test 13: Retrieve single experiment and assert all JSONB and relational fields deserialize properly."""
    payload = {
        "title": "Inspectable Experiment",
        "methodology": "Deep inspection methodology",
        "variables": {"factor_a": ["opt1", "opt2"]},
        "parameters": {"batch_size": 16},
        "target_metrics": ["MRR", "Recall@5"],
    }
    create_res = client.post(f"/api/projects/{project.id}/experiments", json=payload)
    exp_id = create_res.json()["id"]

    get_res = client.get(f"/api/projects/{project.id}/experiments/{exp_id}")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["title"] == payload["title"]
    assert data["variables"] == payload["variables"]
    assert data["parameters"] == payload["parameters"]
    assert data["target_metrics"] == payload["target_metrics"]


def test_lifecycle_transitions_and_reopen_clears_timestamps(client, project):
    """Test 14: Transition from planned to completed sets completed_at, reopening clears it, reopening abandoned clears reason."""
    create_res = client.post(
        f"/api/projects/{project.id}/experiments",
        json={"title": "Lifecycle Exp", "methodology": "Method", "status": "planned"},
    )
    exp_id = create_res.json()["id"]
    assert create_res.json()["completed_at"] is None

    # Transition to in_progress
    patch_in_progress = client.patch(
        f"/api/projects/{project.id}/experiments/{exp_id}",
        json={"status": "in_progress"},
    )
    assert patch_in_progress.status_code == 200
    assert patch_in_progress.json()["status"] == "in_progress"

    # Complete via results endpoint
    complete_res = client.post(
        f"/api/projects/{project.id}/experiments/{exp_id}/results",
        json={"results": {"accuracy": 0.94}, "mark_completed": True},
    )
    assert complete_res.status_code == 200
    assert complete_res.json()["status"] == "completed"
    assert complete_res.json()["completed_at"] is not None

    # Reopen to in_progress -> completed_at must be cleared to None
    reopen_res = client.patch(
        f"/api/projects/{project.id}/experiments/{exp_id}",
        json={"status": "in_progress"},
    )
    assert reopen_res.status_code == 200
    assert reopen_res.json()["status"] == "in_progress"
    assert reopen_res.json()["completed_at"] is None

    # Abandon with reason
    abandon_res = client.patch(
        f"/api/projects/{project.id}/experiments/{exp_id}",
        json={"status": "abandoned", "abandonment_reason": "Superseded by alternate method"},
    )
    assert abandon_res.status_code == 200
    assert abandon_res.json()["status"] == "abandoned"
    assert abandon_res.json()["abandonment_reason"] == "Superseded by alternate method"

    # Reopen from abandoned to planned -> abandonment_reason must be cleared to None
    reopen_abandon_res = client.patch(
        f"/api/projects/{project.id}/experiments/{exp_id}",
        json={"status": "planned"},
    )
    assert reopen_abandon_res.status_code == 200
    assert reopen_abandon_res.json()["status"] == "planned"
    assert reopen_abandon_res.json()["abandonment_reason"] is None


def test_log_results_partial_update_preserves_existing_data(client, project):
    """Test 15: Logging findings does not erase existing metric results, and updating notes preserves gap/doc IDs."""
    create_res = client.post(
        f"/api/projects/{project.id}/experiments",
        json={"title": "Data Preservation Exp", "methodology": "Method", "status": "planned"},
    )
    exp_id = create_res.json()["id"]

    # Step 1: Log quantitative results only
    res1 = client.post(
        f"/api/projects/{project.id}/experiments/{exp_id}/results",
        json={"results": {"latency_ms": 42.0}, "mark_completed": False},
    )
    assert res1.status_code == 200
    assert res1.json()["results"] == {"latency_ms": 42.0}
    assert res1.json()["findings"] == {}

    # Step 2: Log qualitative findings only -> results must NOT be erased
    res2 = client.post(
        f"/api/projects/{project.id}/experiments/{exp_id}/results",
        json={"findings": {"summary": "Stable execution confirmed."}, "mark_completed": False},
    )
    assert res2.status_code == 200
    assert res2.json()["results"] == {"latency_ms": 42.0}
    assert res2.json()["findings"]["summary"] == "Stable execution confirmed."

    # Step 3: Add provenance notes -> existing results & findings must remain intact
    res3 = client.post(
        f"/api/projects/{project.id}/experiments/{exp_id}/results",
        json={"provenance_notes": "Tested on machine A40.", "mark_completed": False},
    )
    assert res3.status_code == 200
    assert res3.json()["results"] == {"latency_ms": 42.0}
    assert res3.json()["findings"]["summary"] == "Stable execution confirmed."
    assert res3.json()["provenance"]["notes"] == "Tested on machine A40."


def test_log_results_rejects_empty_payload(client, project):
    """Test 16: Assert 400 validation error when submitting POST /results with no results, findings, or notes."""
    create_res = client.post(
        f"/api/projects/{project.id}/experiments",
        json={"title": "Empty Log Exp", "methodology": "Method", "status": "planned"},
    )
    exp_id = create_res.json()["id"]

    res = client.post(
        f"/api/projects/{project.id}/experiments/{exp_id}/results",
        json={},
    )
    assert res.status_code == 422 or res.status_code == 400


def test_abandon_experiment_requires_reason(client, project):
    """Test 17: Transition or creation with abandoned strictly requires abandonment_reason."""
    # Attempt creation as abandoned without reason -> fails
    res_create = client.post(
        f"/api/projects/{project.id}/experiments",
        json={"title": "Failed Abandon", "methodology": "Method", "status": "abandoned"},
    )
    assert res_create.status_code == 422 or res_create.status_code == 400

    # Create planned then attempt PATCH to abandoned without reason -> fails
    create_res = client.post(
        f"/api/projects/{project.id}/experiments",
        json={"title": "Valid Planned", "methodology": "Method", "status": "planned"},
    )
    exp_id = create_res.json()["id"]

    patch_res = client.patch(
        f"/api/projects/{project.id}/experiments/{exp_id}",
        json={"status": "abandoned"},
    )
    assert patch_res.status_code == 400
    assert "abandonment reason is required" in patch_res.json()["detail"].lower()


# ── Agent Tool Tests (18) ─────────────────────────────────────────────────


def test_agent_experiment_tools_read_only(db_session, project):
    """Test 18: Execute ListExperimentsTool and GetExperimentTool via ToolExecutionService; assert correct summaries and read-only safety tier."""
    from app.schemas.tool import ToolCall, ToolSafetyTier
    from app.services.tool_execution_service import ToolExecutionService
    from app.services.tools.base import ToolContext
    from app.services.tools.implementations import GetExperimentTool, ListExperimentsTool

    # Assert tool metadata
    list_tool = ListExperimentsTool()
    get_tool = GetExperimentTool()
    assert list_tool.safety_tier == ToolSafetyTier.READ_ONLY
    assert get_tool.safety_tier == ToolSafetyTier.READ_ONLY

    # Seed an experiment
    exp = Experiment(
        project_id=project.id,
        title="Agent Tool Test Exp",
        methodology="Methodology for agent inspection",
        status=ExperimentStatus.COMPLETED.value,
        priority=ExperimentPriority.HIGH.value,
        results={"Recall@10": 0.89},
        findings={"summary": "Agent tool inspection finding", "hypothesis_verdict": "supported"},
    )
    db_session.add(exp)
    db_session.commit()
    db_session.refresh(exp)

    tool_service = ToolExecutionService()

    # Test list_experiments tool
    list_res = tool_service.execute(
        db=db_session,
        project_id=project.id,
        tool_name="list_experiments",
        arguments={"status": "completed"},
    )
    assert list_res.success is True
    assert "Found 1 experiment(s):" in list_res.result_summary
    assert "Agent Tool Test Exp" in list_res.result_summary
    assert len(list_res.data["experiments"]) == 1

    # Test get_experiment tool
    get_res = tool_service.execute(
        db=db_session,
        project_id=project.id,
        tool_name="get_experiment",
        arguments={"experiment_id": exp.id},
    )
    assert get_res.success is True
    assert "Agent Tool Test Exp" in get_res.result_summary
    assert "Recall@10" in get_res.result_summary
    assert get_res.data["id"] == exp.id
    assert get_res.data["findings"]["hypothesis_verdict"] == "supported"

