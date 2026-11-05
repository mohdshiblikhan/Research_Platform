import json
from unittest.mock import MagicMock, patch
import pytest
from pydantic import ValidationError

from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.evaluation import (
    EvaluationDataset,
    EvaluationDatasetItem,
    EvaluationItemResult,
    EvaluationRun,
)
from app.models.experiment import Experiment
from app.models.project import Project
from app.schemas.agent import AgentCitation, AgentResearchResponse, AgentStepRecord, AgentToolCallRecord
from app.schemas.evaluation import (
    EvaluationDatasetCreate,
    EvaluationDatasetItemAdd,
    EvaluationItemCreate,
    EvaluationItemUpdate,
    RunAgentEvaluationRequest,
    RunRAGEvaluationRequest,
    RunRetrievalEvaluationRequest,
    SyntheticDatasetGenerateRequest,
)
from app.schemas.rag import AskResponse, Citation, CitationVerification, SourcePassage
from app.schemas.search import SearchResponse, SearchResultItem
from app.services.evaluation_service import EvaluationService
from app.services.llm_service import LLMResponse
from app.services.tools.base import ToolContext
from app.services.tools.implementations import GetEvaluationResultsTool, RunEvaluationTool


@pytest.fixture
def eval_project(db_session):
    """Fixture providing a test Project entity."""
    project = Project(
        title="Evaluation Test Project",
        description="Testing AI/RAG/Agent evaluation framework",
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project


@pytest.fixture
def eval_documents_and_chunks(db_session, eval_project):
    """Fixture providing documents with multiple chunks in the same document."""
    doc1 = Document(
        project_id=eval_project.id,
        filename="paper1.pdf",
        file_path="/tmp/paper1.pdf",
        file_size=1024,
        mime_type="application/pdf",
        status=DocumentStatus.PROCESSED.value,
    )
    doc2 = Document(
        project_id=eval_project.id,
        filename="paper2.pdf",
        file_path="/tmp/paper2.pdf",
        file_size=2048,
        mime_type="application/pdf",
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add_all([doc1, doc2])
    db_session.commit()
    db_session.refresh(doc1)
    db_session.refresh(doc2)

    c1 = Chunk(
        document_id=doc1.id,
        chunk_index=0,
        content="Dense retrieval leverages vector embeddings for semantic search.",
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=len("Dense retrieval leverages vector embeddings for semantic search."),
        chunk_size=len("Dense retrieval leverages vector embeddings for semantic search."),
        embedding=[0.1] * 384,
    )
    c2 = Chunk(
        document_id=doc1.id,
        chunk_index=1,
        content="Cross-encoders act as rerankers to improve top-k precision.",
        page_start=1,
        page_end=1,
        char_offset_start=66,
        char_offset_end=66 + len("Cross-encoders act as rerankers to improve top-k precision."),
        chunk_size=len("Cross-encoders act as rerankers to improve top-k precision."),
        embedding=[0.2] * 384,
    )
    c3 = Chunk(
        document_id=doc2.id,
        chunk_index=0,
        content="BM25 is a strong deterministic lexical search baseline.",
        page_start=1,
        page_end=1,
        char_offset_start=0,
        char_offset_end=len("BM25 is a strong deterministic lexical search baseline."),
        chunk_size=len("BM25 is a strong deterministic lexical search baseline."),
        embedding=[0.3] * 384,
    )
    db_session.add_all([c1, c2, c3])
    db_session.commit()
    db_session.refresh(c1)
    db_session.refresh(c2)
    db_session.refresh(c3)

    return doc1, doc2, [c1, c2, c3]


# =============================================================================
# 1. Strict Pydantic K Validation Tests
# =============================================================================

def test_strict_k_validation():
    """Verify strict validation rejects booleans, floats, non-integers, and K < 1."""
    # Booleans are rejected (not coerced to 1/0)
    with pytest.raises(ValidationError):
        RunRetrievalEvaluationRequest(
            dataset_id=1,
            name="Test",
            k_values=[True, 5],  # type: ignore
        )

    with pytest.raises(ValidationError):
        RunRAGEvaluationRequest(
            dataset_id=1,
            name="Test",
            top_k=False,  # type: ignore
        )

    # Floats are rejected
    with pytest.raises(ValidationError):
        RunRetrievalEvaluationRequest(
            dataset_id=1,
            name="Test",
            k_values=[3.5],  # type: ignore
        )

    # Strings are rejected
    with pytest.raises(ValidationError):
        RunRAGEvaluationRequest(
            dataset_id=1,
            name="Test",
            top_k="5",  # type: ignore
        )

    # Non-positive integers rejected
    with pytest.raises(ValidationError):
        RunRetrievalEvaluationRequest(
            dataset_id=1,
            name="Test",
            k_values=[0, 5],
        )

    with pytest.raises(ValidationError):
        RunRAGEvaluationRequest(
            dataset_id=1,
            name="Test",
            top_k=0,
        )


# =============================================================================
# 2. Dataset CRUD & Item Lifecycle
# =============================================================================

def test_dataset_crud_and_patch_item(db_session, eval_project):
    """Test dataset creation, item adding, patching, listing, and defaults."""
    service = EvaluationService(db_session)

    # 1. Create dataset with initial items
    req = EvaluationDatasetCreate(
        name="Test IR Dataset",
        description="Dataset for retrieval testing",
        eval_type="retrieval",
        items=[
            EvaluationItemCreate(
                query="What is dense retrieval?",
                ground_truth_answer="Dense retrieval uses vector representations.",
                expected_chunk_ids=[101, 102],
                question_type="manual",
                is_validated=True,  # Manual item defaults to validated
            ),
            EvaluationItemCreate(
                query="What is BM25?",
                ground_truth_answer="BM25 is a term-frequency ranking function.",
                expected_chunk_ids=[103],
                question_type="manual",
                is_validated=False,  # Explicitly unvalidated
            ),
        ],
    )
    dataset = service.create_dataset(eval_project.id, req)
    assert dataset.id is not None
    assert dataset.item_count == 2

    # 2. List items respecting validated_only
    all_items = service.get_dataset_items(eval_project.id, dataset.id, validated_only=False)
    assert len(all_items) == 2

    validated_items = service.get_dataset_items(eval_project.id, dataset.id, validated_only=True)
    assert len(validated_items) == 1
    assert validated_items[0].query == "What is dense retrieval?"

    # 3. Patch item to validate it
    unval_item = [it for it in all_items if not it.is_validated][0]
    patched = service.patch_item(
        eval_project.id,
        dataset.id,
        unval_item.id,
        EvaluationItemUpdate(is_validated=True, query="Updated: What is BM25 lexical search?"),
    )
    assert patched.is_validated is True
    assert patched.query == "Updated: What is BM25 lexical search?"

    val_after = service.get_dataset_items(eval_project.id, dataset.id, validated_only=True)
    assert len(val_after) == 2

    # 4. Add items bulk
    added = service.add_items(
        eval_project.id,
        dataset.id,
        EvaluationDatasetItemAdd(
            items=[
                EvaluationItemCreate(
                    query="What is cross-encoder reranking?",
                    expected_chunk_ids=[104],
                )
            ]
        ),
    )
    assert len(added) == 1
    assert service.get_dataset(eval_project.id, dataset.id).item_count == 3


# =============================================================================
# 3. Historical Run Preservation on Dataset / Item Deletion (SET NULL)
# =============================================================================

def test_historical_preservation_on_deletion(db_session, eval_project):
    """Verify that deleting a dataset or dataset item does NOT delete historical runs/results (ON DELETE SET NULL)."""
    service = EvaluationService(db_session)

    dataset = service.create_dataset(
        eval_project.id,
        EvaluationDatasetCreate(
            name="Ephemeral Dataset",
            eval_type="retrieval",
            items=[
                EvaluationItemCreate(
                    query="Ephemeral query?",
                    expected_chunk_ids=[1],
                )
            ],
        ),
    )
    items = service.get_dataset_items(eval_project.id, dataset.id)
    item = items[0]

    # Create run and item result referencing dataset and item
    run = EvaluationRun(
        project_id=eval_project.id,
        dataset_id=dataset.id,
        name="Historical Run",
        eval_type="retrieval",
        status="completed",
        summary_metrics={"recall@5": 1.0},
        total_items=1,
        completed_items=1,
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    item_res = EvaluationItemResult(
        run_id=run.id,
        dataset_item_id=item.id,
        query=item.query,
        expected_chunk_ids_snapshot=[1],
        expected_tools_snapshot=[],
        actual_output={"retrieved_chunks": []},
        metrics={"recall@5": 1.0},
    )
    db_session.add(item_res)
    db_session.commit()
    db_session.refresh(item_res)

    run_id = run.id
    item_res_id = item_res.id

    # Now delete the dataset!
    service.delete_dataset(eval_project.id, dataset.id)

    # Check that run still exists with dataset_id set to None!
    preserved_run = service.get_run(eval_project.id, run_id)
    assert preserved_run is not None
    assert preserved_run.dataset_id is None
    assert preserved_run.status == "completed"

    # Check that item result still exists with dataset_item_id set to None!
    preserved_results = service.get_run_item_results(eval_project.id, run_id)
    assert len(preserved_results) == 1
    assert preserved_results[0].id == item_res_id
    assert preserved_results[0].dataset_item_id is None
    assert preserved_results[0].query == "Ephemeral query?"


# =============================================================================
# 4. Synthetic Benchmark Generation (Intra-Document & Self-Verification)
# =============================================================================

def test_synthetic_dataset_generation_intra_document(db_session, eval_project, eval_documents_and_chunks):
    """Verify synthetic generation creates single and intra-document multi-chunk items defaulting to is_validated=False."""
    doc1, doc2, chunks = eval_documents_and_chunks

    mock_llm = MagicMock()
    mock_llm.get_model_name.return_value = "mock_model"

    # Sequence of mock LLM responses:
    # 1. Single chunk generation -> Q&A
    # 2. Self-verification -> is_supported=True
    # 3. Multi-chunk generation -> Q&A
    # 4. Self-verification -> is_supported=True
    single_qa = json.dumps({"query": "What does dense retrieval use?", "reference_answer": "Vector embeddings.", "reasoning": "Direct."})
    audit_ok = json.dumps({"is_supported": True, "confidence": 0.98, "reasoning": "Fully entailed."})
    multi_qa = json.dumps({"query": "How do dense retrieval and rerankers interact?", "reference_answer": "Dense retrieves candidates, rerankers refine.", "reasoning": "Needs both."})

    mock_llm.generate.side_effect = [
        LLMResponse(content=single_qa, model="mock_model"),
        LLMResponse(content=audit_ok, model="mock_model"),
        LLMResponse(content=multi_qa, model="mock_model"),
        LLMResponse(content=audit_ok, model="mock_model"),
    ]

    service = EvaluationService(db_session, llm_service=mock_llm)
    req = SyntheticDatasetGenerateRequest(
        name="Synthetic Benchmark",
        num_questions=2,
        question_type="mixed",
    )
    dataset = service.generate_synthetic_dataset(eval_project.id, req)
    assert dataset.item_count == 2

    items = service.get_dataset_items(eval_project.id, dataset.id, validated_only=False)
    assert len(items) == 2

    # All synthetic items must default to is_validated=False!
    for it in items:
        assert it.is_validated is False
        assert "self_verification" in it.item_metadata
        assert it.item_metadata["self_verification"]["is_supported"] is True

    # Check multi-chunk item has 2 chunks from the SAME document
    multi_items = [it for it in items if it.question_type == "multi_chunk"]
    assert len(multi_items) == 1
    m_item = multi_items[0]
    assert len(m_item.expected_chunk_ids) == 2
    assert m_item.item_metadata["source_document_id"] == doc1.id


# =============================================================================
# 5. Retrieval Evaluation Run & Experiment Linking
# =============================================================================

def test_retrieval_evaluation_run_and_experiment_linking(db_session, eval_project, eval_documents_and_chunks):
    """Test retrieval evaluation execution, deterministic scoring, snapshots, and experiment linking."""
    doc1, doc2, chunks = eval_documents_and_chunks
    c1, c2, c3 = chunks

    service = EvaluationService(db_session)

    dataset = service.create_dataset(
        eval_project.id,
        EvaluationDatasetCreate(
            name="Retrieval Benchmark",
            eval_type="retrieval",
            items=[
                EvaluationItemCreate(
                    query="What is dense retrieval?",
                    expected_chunk_ids=[c1.id],
                    is_validated=True,
                ),
                EvaluationItemCreate(
                    query="Unvalidated candidate",
                    expected_chunk_ids=[c2.id],
                    is_validated=False,  # Should be skipped by default (validated_only=True)
                ),
            ],
        ),
    )

    # Mock SearchService.search
    mock_search_resp = SearchResponse(
        query="What is dense retrieval?",
        project_id=eval_project.id,
        search_mode="hybrid",
        total_results=2,
        limit=5,
        offset=0,
        results=[
            SearchResultItem(
                chunk_id=c1.id,
                document_id=c1.document_id,
                document_filename="paper1.pdf",
                chunk_index=0,
                content=c1.content,
                page_start=1,
                page_end=1,
                char_offset_start=0,
                char_offset_end=len(c1.content),
                similarity_score=0.95,
            ),
            SearchResultItem(
                chunk_id=c3.id,
                document_id=c3.document_id,
                document_filename="paper2.pdf",
                chunk_index=0,
                content=c3.content,
                page_start=1,
                page_end=1,
                char_offset_start=0,
                char_offset_end=len(c3.content),
                similarity_score=0.45,
            ),
        ],
        query_time_ms=12.5,
    )

    with patch.object(service.search_service, "search", return_value=mock_search_resp):
        req = RunRetrievalEvaluationRequest(
            dataset_id=dataset.id,
            name="Eval-Run-1",
            k_values=[1, 3, 5],
            validated_only=True,
            create_experiment=True,
            experiment_name="Exp-Retrieval-Run-1",
        )
        run = service.run_retrieval_evaluation(eval_project.id, req)

    assert run.status == "completed"
    assert run.completed_items == 1
    assert run.total_items == 1
    assert run.summary_metrics["recall@1"] == 1.0
    assert run.summary_metrics["hit_rate@1"] == 1.0
    assert run.experiment_id is not None

    # Check linked experiment
    exp = db_session.get(Experiment, run.experiment_id)
    assert exp is not None
    assert exp.title == "Exp-Retrieval-Run-1"
    assert exp.results == run.summary_metrics

    # Check item result snapshots
    results = service.get_run_item_results(eval_project.id, run.id)
    assert len(results) == 1
    res = results[0]
    assert res.query == "What is dense retrieval?"
    assert res.expected_chunk_ids_snapshot == [c1.id]
    assert len(res.actual_output["retrieved_chunks"]) == 2
    # Verify exact retrieved content was stored (not truncated)
    assert res.actual_output["retrieved_chunks"][0]["content"] == c1.content


# =============================================================================
# 6. RAG Evaluation Run (Empty Claims vs Entailed Claims)
# =============================================================================

def test_rag_evaluation_run_faithfulness_and_citations(db_session, eval_project, eval_documents_and_chunks):
    """Test RAG evaluation with claim decomposition, faithfulness, and citation metrics."""
    doc1, doc2, chunks = eval_documents_and_chunks
    c1, c2, c3 = chunks

    mock_llm = MagicMock()
    mock_llm.get_model_name.return_value = "mock_model"

    # LLM responses:
    # 1. Claim extraction -> 2 claims (one citing c1, one citing c2)
    # 2. Claim 1 verification -> SUPPORTED
    # 3. Claim 2 verification -> UNSUPPORTED
    # 4. Relevance evaluation -> 0.9
    claim_ext = json.dumps({
        "claims": [
            {"claim_text": "Dense retrieval uses vector representations.", "cited_chunk_references": [str(c1.id)]},
            {"claim_text": "Rerankers eliminate 100% of hallucinations.", "cited_chunk_references": [str(c2.id)]},
        ]
    })
    verif_1 = json.dumps({"verdict": "SUPPORTED", "reasoning": "Directly stated."})
    verif_2 = json.dumps({"verdict": "UNSUPPORTED", "reasoning": "Not claimed in text."})
    relevance_data = json.dumps({"score": 0.9, "reasoning": "Directly answers the query."})

    mock_llm.generate.side_effect = [
        LLMResponse(content=claim_ext, model="mock_model"),
        LLMResponse(content=verif_1, model="mock_model"),
        LLMResponse(content=verif_2, model="mock_model"),
        LLMResponse(content=relevance_data, model="mock_model"),
    ]

    service = EvaluationService(db_session, llm_service=mock_llm)

    dataset = service.create_dataset(
        eval_project.id,
        EvaluationDatasetCreate(
            name="RAG Benchmark",
            eval_type="rag",
            items=[
                EvaluationItemCreate(
                    query="How does dense retrieval work?",
                    is_validated=True,
                )
            ],
        ),
    )

    mock_rag_resp = AskResponse(
        question="How does dense retrieval work?",
        project_id=eval_project.id,
        answer="Dense retrieval uses vector representations [1]. Rerankers eliminate 100% of hallucinations [2].",
        sources=[
            SourcePassage(
                index=1,
                chunk_id=c1.id,
                document_id=c1.document_id,
                document_filename="paper1.pdf",
                page_start=1,
                page_end=1,
                content=c1.content,
                relevance_score=0.9,
            ),
            SourcePassage(
                index=2,
                chunk_id=c2.id,
                document_id=c2.document_id,
                document_filename="paper1.pdf",
                page_start=1,
                page_end=1,
                content=c2.content,
                relevance_score=0.8,
            ),
        ],
        citations=[
            Citation(
                source_index=1,
                chunk_id=c1.id,
                document_id=c1.document_id,
                document_filename="paper1.pdf",
                page_start=1,
                page_end=1,
                cited_text="vector representations",
            ),
            Citation(
                source_index=2,
                chunk_id=c2.id,
                document_id=c2.document_id,
                document_filename="paper1.pdf",
                page_start=1,
                page_end=1,
                cited_text="eliminate 100% of hallucinations",
            ),
        ],
        search_mode="hybrid",
        reranked=True,
        top_k=5,
        retrieval_time_ms=10.0,
        generation_time_ms=50.0,
        total_time_ms=60.0,
        llm_model="mock_model",
        citation_verification=CitationVerification(total=2, valid=2, invalid=0),
        confidence="HIGH",
        has_sufficient_evidence=True,
    )

    with patch.object(service.rag_service, "ask", return_value=mock_rag_resp):
        req = RunRAGEvaluationRequest(
            dataset_id=dataset.id,
            name="RAG-Eval-Run",
            top_k=5,
            evaluate_relevance=True,
            create_experiment=False,
        )
        run = service.run_rag_evaluation(eval_project.id, req)

    assert run.status == "completed"
    # 1 out of 2 claims supported -> faithfulness = 0.5
    assert run.summary_metrics["mean_faithfulness"] == 0.5
    assert run.summary_metrics["mean_citation_validity_ratio"] == 1.0  # both c1 and c2 exist in sources
    assert run.summary_metrics["mean_claim_citation_support_rate"] == 0.5  # only claim 1 supported
    assert run.summary_metrics["mean_answer_relevance"] == 0.9


def test_rag_evaluation_empty_answer_gives_none_faithfulness(db_session, eval_project):
    """Verify that an empty answer or answer with zero extractable claims returns faithfulness=None."""
    mock_llm = MagicMock()
    mock_llm.get_model_name.return_value = "mock_model"
    # Claim extraction returns empty claims list
    mock_llm.generate.return_value = LLMResponse(content=json.dumps({"claims": []}), model="mock_model")

    service = EvaluationService(db_session, llm_service=mock_llm)
    dataset = service.create_dataset(
        eval_project.id,
        EvaluationDatasetCreate(
            name="Empty RAG Benchmark",
            eval_type="rag",
            items=[EvaluationItemCreate(query="Can you answer?", is_validated=True)],
        ),
    )

    mock_rag_resp = AskResponse(
        question="Can you answer?",
        project_id=eval_project.id,
        answer="I do not have enough information to answer.",
        sources=[],
        citations=[],
        search_mode="hybrid",
        reranked=False,
        top_k=5,
        retrieval_time_ms=5.0,
        generation_time_ms=10.0,
        total_time_ms=15.0,
        llm_model="mock_model",
        citation_verification=CitationVerification(total=0, valid=0, invalid=0),
        confidence="LOW",
        has_sufficient_evidence=False,
    )

    with patch.object(service.rag_service, "ask", return_value=mock_rag_resp):
        req = RunRAGEvaluationRequest(
            dataset_id=dataset.id,
            name="Empty-RAG-Run",
            evaluate_relevance=False,
            create_experiment=False,
        )
        run = service.run_rag_evaluation(eval_project.id, req)

    assert run.status == "completed"
    assert run.summary_metrics["mean_faithfulness"] is None


# =============================================================================
# 7. Agent Evaluation Run & Canonical Snapshot Storage
# =============================================================================

def test_agent_evaluation_run_and_expected_tools_snapshot(db_session, eval_project):
    """Test Agent evaluation trajectory analysis, answer correctness, and dedicated expected_tools_snapshot storage."""
    mock_llm = MagicMock()
    mock_llm.get_model_name.return_value = "mock_judge"
    # Answer correctness returns 0.92
    mock_llm.generate.return_value = LLMResponse(
        content=json.dumps({"score": 0.92, "reasoning": "Strong alignment with ground truth."}),
        model="mock_judge",
    )

    service = EvaluationService(db_session, llm_service=mock_llm)
    dataset = service.create_dataset(
        eval_project.id,
        EvaluationDatasetCreate(
            name="Agent Benchmark",
            eval_type="agent",
            items=[
                EvaluationItemCreate(
                    query="Investigate hybrid search architectures.",
                    ground_truth_answer="Hybrid search fuses BM25 and vector search using RRF.",
                    expected_tools=["search_chunks", "compare_papers"],
                    is_validated=True,
                )
            ],
        ),
    )

    mock_agent_resp = AgentResearchResponse(
        session_id=10,
        project_id=eval_project.id,
        research_question="Investigate hybrid search architectures.",
        status="completed",
        final_answer="Hybrid search combines lexical BM25 and dense retrieval with RRF.",
        citations=[AgentCitation(chunk_id=1, claim="Hybrid fuses BM25 and vector.")],
        trajectory=[
            AgentStepRecord(
                iteration=1,
                action_type="tool_call",
                tool_calls=[
                    AgentToolCallRecord(tool_name="search_chunks", success=True, execution_time_ms=10.0),
                    AgentToolCallRecord(tool_name="get_chunk", success=True, execution_time_ms=5.0),
                ],
            ),
            AgentStepRecord(
                iteration=2,
                action_type="final_answer",
            ),
        ],
        total_iterations=2,
        total_tool_calls=2,
        total_tokens_used=500,
        total_time_ms=150.0,
        model_used="test_model",
        stop_reason="Final answer reached",
        created_at=dataset.created_at,
    )

    with patch.object(service.agent_service, "run_research_session", return_value=mock_agent_resp):
        req = RunAgentEvaluationRequest(
            dataset_id=dataset.id,
            name="Agent-Eval-Run",
            create_experiment=False,
        )
        run = service.run_agent_evaluation(eval_project.id, req)

    assert run.status == "completed"
    assert run.summary_metrics["mean_task_completion"] == 1.0
    assert run.summary_metrics["mean_answer_correctness"] == 0.92
    assert run.summary_metrics["mean_tool_precision"] == 0.5  # search_chunks in expected, get_chunk not
    assert run.summary_metrics["mean_tool_recall"] == 0.5  # 1 out of 2 expected tools used

    # Verify dedicated expected_tools_snapshot column in EvaluationItemResult
    item_results = service.get_run_item_results(eval_project.id, run.id)
    assert len(item_results) == 1
    it_res = item_results[0]
    assert it_res.expected_tools_snapshot == ["search_chunks", "compare_papers"]
    assert it_res.ground_truth_answer_snapshot == "Hybrid search fuses BM25 and vector search using RRF."
    assert it_res.metrics["answer_correctness"] == 0.92


# =============================================================================
# 8. Platform Tools #12 and #13 Integration
# =============================================================================

def test_run_evaluation_tool_and_get_results_tool(db_session, eval_project):
    """Test Tool #12 (run_evaluation) and Tool #13 (get_evaluation_results) execution."""
    service = EvaluationService(db_session)
    dataset = service.create_dataset(
        eval_project.id,
        EvaluationDatasetCreate(
            name="Tool Eval Benchmark",
            eval_type="retrieval",
            items=[EvaluationItemCreate(query="Sample query", expected_chunk_ids=[1], is_validated=True)],
        ),
    )

    # Mock SearchService within run_evaluation tool
    mock_search_resp = SearchResponse(
        query="Sample query",
        project_id=eval_project.id,
        search_mode="hybrid",
        total_results=1,
        limit=5,
        offset=0,
        results=[
            SearchResultItem(
                chunk_id=1,
                document_id=1,
                document_filename="paper1.pdf",
                chunk_index=0,
                content="Passage 1",
                page_start=1,
                page_end=1,
                char_offset_start=0,
                char_offset_end=9,
                similarity_score=0.9,
            )
        ],
        query_time_ms=5.0,
    )

    ctx = ToolContext(project_id=eval_project.id, db=db_session)

    # 1. Execute RunEvaluationTool
    run_tool = RunEvaluationTool()
    with patch("app.services.search_service.SearchService.search", return_value=mock_search_resp):
        res = run_tool.run(
            ctx,
            dataset_id=dataset.id,
            eval_type="retrieval",
            name="Tool-Run-1",
            create_experiment=False,
        )

    assert res.success is True
    assert "completed" in res.result_summary
    run_id = res.data["run_id"]
    assert run_id is not None

    # 2. Execute GetEvaluationResultsTool
    get_tool = GetEvaluationResultsTool()
    get_res = get_tool.run(ctx, run_id=run_id, include_item_results=True)
    assert get_res.success is True
    assert f"Evaluation Run {run_id}" in get_res.result_summary
    assert get_res.data["run_id"] == run_id
    assert len(get_res.data["item_results"]) == 1


# =============================================================================
# 9. REST API Integration Endpoints via TestClient
# =============================================================================

def test_evaluation_rest_api_endpoints(client, eval_project):
    """Verify REST API routes for datasets, items, and runs."""
    p_id = eval_project.id

    # 1. Create dataset via API
    resp = client.post(
        f"/api/projects/{p_id}/evaluation/datasets",
        json={
            "name": "API Benchmark",
            "eval_type": "retrieval",
            "items": [{"query": "What is AI?", "expected_chunk_ids": [1]}],
        },
    )
    assert resp.status_code == 201
    dataset_data = resp.json()
    d_id = dataset_data["id"]
    assert dataset_data["name"] == "API Benchmark"

    # 2. List datasets
    list_resp = client.get(f"/api/projects/{p_id}/evaluation/datasets")
    assert list_resp.status_code == 200
    assert any(d["id"] == d_id for d in list_resp.json())

    # 3. Patch item
    items_resp = client.get(f"/api/projects/{p_id}/evaluation/datasets/{d_id}/items")
    assert items_resp.status_code == 200
    item_id = items_resp.json()[0]["id"]

    patch_resp = client.patch(
        f"/api/projects/{p_id}/evaluation/datasets/{d_id}/items/{item_id}",
        json={"is_validated": True, "query": "Updated query?"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["query"] == "Updated query?"

    # 4. Strict K validation error returns 422
    bad_run_resp = client.post(
        f"/api/projects/{p_id}/evaluation/runs/retrieval",
        json={
            "dataset_id": d_id,
            "name": "Bad Run",
            "k_values": [True, 5],  # Invalid boolean
        },
    )
    assert bad_run_resp.status_code == 422
