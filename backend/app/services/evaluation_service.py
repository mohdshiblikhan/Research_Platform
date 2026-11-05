from collections import defaultdict
from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.evaluation import (
    EvaluationDataset,
    EvaluationDatasetItem,
    EvaluationItemResult,
    EvaluationRun,
)
from app.models.experiment import Experiment, ExperimentPriority, ExperimentStatus
from app.prompts.evaluation_prompts import (
    ANSWER_CORRECTNESS_SYSTEM_PROMPT,
    ANSWER_RELEVANCE_SYSTEM_PROMPT,
    CLAIM_EXTRACTION_SYSTEM_PROMPT,
    CLAIM_VERIFICATION_SYSTEM_PROMPT,
    SYNTHETIC_MULTI_CHUNK_QA_SYSTEM_PROMPT,
    SYNTHETIC_SELF_VERIFICATION_SYSTEM_PROMPT,
    SYNTHETIC_SINGLE_CHUNK_QA_SYSTEM_PROMPT,
    build_answer_correctness_prompt,
    build_answer_relevance_prompt,
    build_claim_extraction_prompt,
    build_claim_verification_prompt,
    build_synthetic_multi_chunk_prompt,
    build_synthetic_self_verification_prompt,
    build_synthetic_single_chunk_prompt,
)
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.evaluation_repository import EvaluationRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.agent import AgentResearchRequest
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
from app.schemas.experiment import ExperimentCreate, ExperimentFindings
from app.schemas.rag import AskRequest
from app.services.agent_service import AgentService
from app.services.evaluation_engine import EvaluationEngine
from app.services.experiment_service import ExperimentService
from app.services.llm_service import LLMService
from app.services.llm_service_factory import get_llm_service
from app.services.rag_service import RAGService
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)


def _clean_and_parse_json(content: str) -> Dict[str, Any]:
    """Strip markdown code blocks and parse JSON safely."""
    if not content:
        return {}
    cleaned = content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
        return {"data": data}
    except Exception as e:
        logger.warning(f"Failed to parse LLM JSON response: {e}. Raw content: {content[:200]}")
        return {}


class EvaluationService:
    """Service orchestrating AI, RAG, and Agent evaluation workflows and persistence."""

    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.eval_repo = EvaluationRepository(db)
        self.project_repo = ProjectRepository(db)
        self.doc_repo = DocumentRepository(db)
        self.chunk_repo = ChunkRepository(db)
        self.search_service = SearchService(db)
        self.rag_service = RAGService(db)
        self.agent_service = AgentService(db)
        self.experiment_service = ExperimentService(db)
        self.llm_service = llm_service or get_llm_service()

    def _ensure_project_exists(self, project_id: int) -> None:
        """Validate that project exists or raise FileNotFoundError."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")

    # =========================================================================
    # EvaluationDataset CRUD
    # =========================================================================

    def create_dataset(
        self, project_id: int, request: EvaluationDatasetCreate
    ) -> EvaluationDataset:
        """Create a new evaluation dataset, optionally with initial items."""
        self._ensure_project_exists(project_id)

        dataset = EvaluationDataset(
            project_id=project_id,
            name=request.name,
            description=request.description,
            eval_type=request.eval_type,
            extra_metadata=request.extra_metadata,
        )
        saved_dataset = self.eval_repo.create_dataset(dataset)

        if request.items:
            items_to_create = [
                EvaluationDatasetItem(
                    dataset_id=saved_dataset.id,
                    query=it.query,
                    ground_truth_answer=it.ground_truth_answer,
                    expected_chunk_ids=it.expected_chunk_ids,
                    expected_tools=it.expected_tools,
                    question_type=it.question_type,
                    is_validated=it.is_validated,
                    item_metadata=it.item_metadata,
                )
                for it in request.items
            ]
            self.eval_repo.create_items_bulk(items_to_create)
            self.db.refresh(saved_dataset)

        return saved_dataset

    def get_dataset(self, project_id: int, dataset_id: int) -> EvaluationDataset:
        """Fetch an evaluation dataset by ID, ensuring it belongs to the project."""
        self._ensure_project_exists(project_id)
        dataset = self.eval_repo.get_dataset(dataset_id, project_id=project_id)
        if not dataset:
            raise FileNotFoundError(
                f"Evaluation dataset {dataset_id} not found in project {project_id}"
            )
        return dataset

    def list_datasets(
        self, project_id: int, limit: int = 50, offset: int = 0
    ) -> List[EvaluationDataset]:
        """List evaluation datasets for a project."""
        self._ensure_project_exists(project_id)
        return self.eval_repo.list_datasets(project_id, limit=limit, offset=offset)

    def delete_dataset(self, project_id: int, dataset_id: int) -> None:
        """Delete an evaluation dataset. Historical evaluation runs are preserved via SET NULL."""
        dataset = self.get_dataset(project_id, dataset_id)
        self.eval_repo.delete_dataset(dataset)

    # =========================================================================
    # EvaluationDatasetItem CRUD
    # =========================================================================

    def add_items(
        self, project_id: int, dataset_id: int, request: EvaluationDatasetItemAdd
    ) -> List[EvaluationDatasetItem]:
        """Add one or more items to an existing dataset."""
        dataset = self.get_dataset(project_id, dataset_id)
        items_to_create = [
            EvaluationDatasetItem(
                dataset_id=dataset.id,
                query=it.query,
                ground_truth_answer=it.ground_truth_answer,
                expected_chunk_ids=it.expected_chunk_ids,
                expected_tools=it.expected_tools,
                question_type=it.question_type,
                is_validated=it.is_validated,
                item_metadata=it.item_metadata,
            )
            for it in request.items
        ]
        return self.eval_repo.create_items_bulk(items_to_create)

    def patch_item(
        self, project_id: int, dataset_id: int, item_id: int, request: EvaluationItemUpdate
    ) -> EvaluationDatasetItem:
        """Patch fields of an evaluation dataset item."""
        self.get_dataset(project_id, dataset_id)
        item = self.eval_repo.get_item(item_id, dataset_id=dataset_id)
        if not item:
            raise FileNotFoundError(
                f"Item {item_id} not found in evaluation dataset {dataset_id}"
            )
        update_data = request.model_dump(exclude_unset=True)
        return self.eval_repo.patch_item(item, update_data)

    def get_dataset_items(
        self,
        project_id: int,
        dataset_id: int,
        validated_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[EvaluationDatasetItem]:
        """Fetch items for an evaluation dataset."""
        self.get_dataset(project_id, dataset_id)
        return self.eval_repo.list_items(
            dataset_id, validated_only=validated_only, limit=limit, offset=offset
        )

    # =========================================================================
    # Synthetic Benchmark Generation
    # =========================================================================

    def generate_synthetic_dataset(
        self, project_id: int, request: SyntheticDatasetGenerateRequest
    ) -> EvaluationDataset:
        """Synthetically generate evaluation questions and reference answers from project documents."""
        self._ensure_project_exists(project_id)

        # Query chunks in this project
        stmt = (
            select(Chunk)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.project_id == project_id)
        )
        if request.document_ids:
            stmt = stmt.where(Document.id.in_(request.document_ids))
        chunks = list(self.db.execute(stmt).scalars().all())

        if not chunks:
            raise ValueError(
                "No processed document chunks found in project to generate synthetic benchmarks from."
            )

        # Group chunks by document_id to enforce the intra-document multi-chunk requirement
        doc_chunks: Dict[int, List[Chunk]] = defaultdict(list)
        for c in chunks:
            doc_chunks[c.document_id].append(c)

        dataset = EvaluationDataset(
            project_id=project_id,
            name=request.name,
            description=request.description or "Synthetically generated benchmark dataset",
            eval_type="composite",
            extra_metadata={
                "synthetic": True,
                "question_type_requested": request.question_type,
                "num_requested": request.num_questions,
            },
        )
        saved_dataset = self.eval_repo.create_dataset(dataset)

        # Determine allocation
        total_q = min(request.num_questions, settings.eval_max_synthetic_samples)
        if request.question_type == "single_chunk":
            num_multi = 0
            num_single = total_q
        elif request.question_type == "multi_chunk":
            num_multi = total_q
            num_single = 0
        else:  # mixed
            num_multi = total_q // 2
            num_single = total_q - num_multi

        # Filter documents with at least 2 chunks for multi-chunk queries
        multi_eligible_docs = [
            d_id for d_id, c_list in doc_chunks.items() if len(c_list) >= 2
        ]
        if num_multi > 0 and not multi_eligible_docs:
            logger.warning(
                "No documents have 2 or more chunks. Falling back to all single-chunk questions."
            )
            num_single += num_multi
            num_multi = 0

        generated_items: List[EvaluationDatasetItem] = []

        # 1. Generate single-chunk questions
        chunk_idx = 0
        for i in range(num_single):
            chunk = chunks[chunk_idx % len(chunks)]
            chunk_idx += 1

            prompt = build_synthetic_single_chunk_prompt(
                chunk.content, {"chunk_id": chunk.id, "document_id": chunk.document_id}
            )
            llm_resp = self.llm_service.generate(
                system_prompt=SYNTHETIC_SINGLE_CHUNK_QA_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=settings.eval_judge_temperature,
                json_mode=True,
            )
            parsed = _clean_and_parse_json(llm_resp.content)
            query = parsed.get("query")
            ref_ans = parsed.get("reference_answer")

            if not query or not ref_ans:
                continue

            # Run self-grounding verification
            audit_prompt = build_synthetic_self_verification_prompt(
                query, ref_ans, chunk.content
            )
            audit_resp = self.llm_service.generate(
                system_prompt=SYNTHETIC_SELF_VERIFICATION_SYSTEM_PROMPT,
                user_prompt=audit_prompt,
                temperature=0.0,
                json_mode=True,
            )
            audit_data = _clean_and_parse_json(audit_resp.content)

            item = EvaluationDatasetItem(
                dataset_id=saved_dataset.id,
                query=query,
                ground_truth_answer=ref_ans,
                expected_chunk_ids=[chunk.id],
                expected_tools=[],
                question_type="single_chunk",
                is_validated=False,  # Unvalidated candidate by default
                item_metadata={
                    "self_verification": audit_data,
                    "generator_reasoning": parsed.get("reasoning"),
                    "source_chunk_id": chunk.id,
                    "source_document_id": chunk.document_id,
                },
            )
            generated_items.append(item)

        # 2. Generate intra-document multi-chunk questions
        multi_doc_idx = 0
        for i in range(num_multi):
            doc_id = multi_eligible_docs[multi_doc_idx % len(multi_eligible_docs)]
            multi_doc_idx += 1
            available = doc_chunks[doc_id]
            c1 = available[0]
            c2 = available[1]

            prompt = build_synthetic_multi_chunk_prompt(
                c1.content,
                c2.content,
                {
                    "chunk_1_id": c1.id,
                    "chunk_2_id": c2.id,
                    "document_id": doc_id,
                },
            )
            llm_resp = self.llm_service.generate(
                system_prompt=SYNTHETIC_MULTI_CHUNK_QA_SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=settings.eval_judge_temperature,
                json_mode=True,
            )
            parsed = _clean_and_parse_json(llm_resp.content)
            query = parsed.get("query")
            ref_ans = parsed.get("reference_answer")

            if not query or not ref_ans:
                continue

            combined_context = f"Chunk 1:\n{c1.content}\n\nChunk 2:\n{c2.content}"
            audit_prompt = build_synthetic_self_verification_prompt(
                query, ref_ans, combined_context
            )
            audit_resp = self.llm_service.generate(
                system_prompt=SYNTHETIC_SELF_VERIFICATION_SYSTEM_PROMPT,
                user_prompt=audit_prompt,
                temperature=0.0,
                json_mode=True,
            )
            audit_data = _clean_and_parse_json(audit_resp.content)

            item = EvaluationDatasetItem(
                dataset_id=saved_dataset.id,
                query=query,
                ground_truth_answer=ref_ans,
                expected_chunk_ids=[c1.id, c2.id],
                expected_tools=[],
                question_type="multi_chunk",
                is_validated=False,  # Unvalidated candidate by default
                item_metadata={
                    "self_verification": audit_data,
                    "generator_reasoning": parsed.get("reasoning"),
                    "source_chunk_ids": [c1.id, c2.id],
                    "source_document_id": doc_id,
                },
            )
            generated_items.append(item)

        if generated_items:
            self.eval_repo.create_items_bulk(generated_items)
            self.db.refresh(saved_dataset)

        return saved_dataset

    # =========================================================================
    # Evaluation Execution: Retrieval Evaluation
    # =========================================================================

    def run_retrieval_evaluation(
        self, project_id: int, request: RunRetrievalEvaluationRequest
    ) -> EvaluationRun:
        """Execute a retrieval evaluation run comparing search results against expected chunks."""
        dataset = self.get_dataset(project_id, request.dataset_id)
        items = self.eval_repo.list_items(
            dataset_id=dataset.id, validated_only=request.validated_only, limit=1000
        )

        if not items:
            raise ValueError(
                f"No items found in dataset {dataset.id} matching criteria (validated_only={request.validated_only})."
            )

        k_vals = list(request.k_values)
        EvaluationEngine.validate_k_values(k_vals)
        max_k = max(k_vals)

        # Initialize run in 'running' state
        run = EvaluationRun(
            project_id=project_id,
            dataset_id=dataset.id,
            name=request.name,
            eval_type="retrieval",
            status="running",
            system_configuration={
                "search_mode": request.search_mode,
                "rerank": request.rerank,
                "k_values": k_vals,
                "validated_only": request.validated_only,
                "max_k": max_k,
            },
            dataset_snapshot={
                "dataset_id": dataset.id,
                "dataset_name": dataset.name,
                "total_items_in_dataset": dataset.item_count,
                "evaluated_items_count": len(items),
            },
            total_items=len(items),
            completed_items=0,
        )
        saved_run = self.eval_repo.create_run(run)

        start_time = time.perf_counter()
        query_evaluations: List[Dict[str, Any]] = []
        item_results: List[EvaluationItemResult] = []

        try:
            for item in items:
                item_start = time.perf_counter()
                search_resp = self.search_service.search(
                    project_id=project_id,
                    query=item.query,
                    mode=request.search_mode,
                    rerank=request.rerank,
                    limit=max_k,
                )

                retrieved_chunk_ids = [r.chunk_id for r in search_resp.results]
                retrieved_chunks_snapshot = [
                    {
                        "chunk_id": r.chunk_id,
                        "document_id": r.document_id,
                        "document_title": getattr(r, "document_title", ""),
                        "page_start": getattr(r, "page_start", 1),
                        "page_end": getattr(r, "page_end", 1),
                        "content": r.content,
                        "retrieval_score": getattr(r, "score", 0.0) or 0.0,
                    }
                    for r in search_resp.results
                ]

                # Evaluate single query IR metrics
                metrics = EvaluationEngine.evaluate_retrieval_for_query(
                    retrieved_chunk_ids=retrieved_chunk_ids,
                    expected_chunk_ids=item.expected_chunk_ids,
                    k_values=k_vals,
                )
                query_evaluations.append(metrics)
                item_duration = (time.perf_counter() - item_start) * 1000

                item_result = EvaluationItemResult(
                    run_id=saved_run.id,
                    dataset_item_id=item.id,
                    query=item.query,
                    expected_chunk_ids_snapshot=list(item.expected_chunk_ids),
                    expected_tools_snapshot=[],
                    ground_truth_answer_snapshot=item.ground_truth_answer,
                    actual_output={
                        "retrieved_chunks": retrieved_chunks_snapshot,
                        "total_results": getattr(search_resp, "total_results", len(search_resp.results)),
                        "query_time_ms": search_resp.query_time_ms,
                    },
                    metrics=metrics,
                    duration_ms=item_duration,
                )
                item_results.append(item_result)

            total_duration_ms = (time.perf_counter() - start_time) * 1000
            summary_metrics = EvaluationEngine.aggregate_retrieval_metrics(
                query_evaluations, k_values=k_vals
            )

            # Persist item results and finalize run
            self.eval_repo.create_item_results_bulk(item_results)
            saved_run.completed_items = len(item_results)
            finalized_run = self.eval_repo.finalize_run(
                saved_run,
                status="completed",
                summary_metrics=summary_metrics,
                duration_ms=total_duration_ms,
            )

            # Link with Experiment if requested
            if request.create_experiment:
                self._log_to_experiment(
                    project_id=project_id,
                    run=finalized_run,
                    experiment_name=request.experiment_name,
                )

            return finalized_run

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"Retrieval evaluation run failed: {e}")
            self.eval_repo.finalize_run(
                saved_run,
                status="failed",
                summary_metrics={},
                duration_ms=elapsed_ms,
                error_message=str(e),
            )
            raise

    # =========================================================================
    # Evaluation Execution: RAG Evaluation
    # =========================================================================

    def run_rag_evaluation(
        self, project_id: int, request: RunRAGEvaluationRequest
    ) -> EvaluationRun:
        """Execute a RAG evaluation run assessing answer faithfulness, citations, and relevance."""
        dataset = self.get_dataset(project_id, request.dataset_id)
        items = self.eval_repo.list_items(
            dataset_id=dataset.id, validated_only=request.validated_only, limit=1000
        )

        if not items:
            raise ValueError(
                f"No items found in dataset {dataset.id} matching criteria (validated_only={request.validated_only})."
            )

        run = EvaluationRun(
            project_id=project_id,
            dataset_id=dataset.id,
            name=request.name,
            eval_type="rag",
            status="running",
            system_configuration={
                "search_mode": request.search_mode,
                "rerank": request.rerank,
                "top_k": request.top_k,
                "evaluate_relevance": request.evaluate_relevance,
                "validated_only": request.validated_only,
                "judge_model": self.llm_service.get_model_name(),
                "judge_temperature": settings.eval_judge_temperature,
            },
            dataset_snapshot={
                "dataset_id": dataset.id,
                "dataset_name": dataset.name,
                "evaluated_items_count": len(items),
            },
            total_items=len(items),
            completed_items=0,
        )
        saved_run = self.eval_repo.create_run(run)

        start_time = time.perf_counter()
        item_results: List[EvaluationItemResult] = []
        faithfulness_scores: List[float] = []
        validity_scores: List[float] = []
        support_scores: List[float] = []
        precision_scores: List[float] = []
        relevance_scores: List[float] = []

        try:
            for item in items:
                item_start = time.perf_counter()

                # 1. Ask RAG system
                rag_resp = self.rag_service.ask(
                    project_id=project_id,
                    request=AskRequest(
                        question=item.query,
                        search_mode=request.search_mode,
                        rerank=request.rerank,
                        top_k=request.top_k,
                    ),
                )

                sources_snapshot = [
                    {
                        "chunk_id": s.chunk_id,
                        "document_id": s.document_id,
                        "document_filename": getattr(s, "document_filename", ""),
                        "page_start": getattr(s, "page_start", 1),
                        "page_end": getattr(s, "page_end", 1),
                        "content": s.content,
                        "score": getattr(s, "relevance_score", None),
                    }
                    for s in rag_resp.sources
                ]
                retrieved_chunk_ids = [s.chunk_id for s in rag_resp.sources]
                chunk_content_map = {s.chunk_id: s.content for s in rag_resp.sources}

                answer_text = rag_resp.answer.strip() if rag_resp.answer else ""

                # 2. Extract atomic claims
                claims_data: List[Dict[str, Any]] = []
                if answer_text:
                    ext_resp = self.llm_service.generate(
                        system_prompt=CLAIM_EXTRACTION_SYSTEM_PROMPT,
                        user_prompt=build_claim_extraction_prompt(answer_text),
                        temperature=0.0,
                        json_mode=True,
                    )
                    ext_data = _clean_and_parse_json(ext_resp.content)
                    raw_claims = ext_data.get("claims", [])
                    if isinstance(raw_claims, list):
                        for c in raw_claims:
                            if isinstance(c, dict) and "claim_text" in c:
                                raw_refs = c.get("cited_chunk_references", [])
                                cited_ids: List[int] = []
                                for ref in raw_refs:
                                    ref_str = str(ref)
                                    digits = re.findall(r"\d+", ref_str)
                                    if digits:
                                        val = int(digits[0])
                                        if val in chunk_content_map:
                                            cited_ids.append(val)
                                        elif 1 <= val <= len(rag_resp.sources):
                                            cited_ids.append(rag_resp.sources[val - 1].chunk_id)
                                claims_data.append(
                                    {
                                        "claim_text": c["claim_text"],
                                        "cited_chunk_ids": list(set(cited_ids)),
                                    }
                                )

                # 3. Verify each claim via entailment judge
                for claim_dict in claims_data:
                    c_ids = claim_dict["cited_chunk_ids"]
                    valid_c_ids = [cid for cid in c_ids if cid in chunk_content_map]
                    if valid_c_ids:
                        context_for_claim = "\n\n".join(
                            [chunk_content_map[cid] for cid in valid_c_ids]
                        )
                    else:
                        context_for_claim = "\n\n".join(
                            [s.content for s in rag_resp.sources]
                        )

                    verif_resp = self.llm_service.generate(
                        system_prompt=CLAIM_VERIFICATION_SYSTEM_PROMPT,
                        user_prompt=build_claim_verification_prompt(
                            claim_dict["claim_text"], context_for_claim
                        ),
                        temperature=0.0,
                        json_mode=True,
                    )
                    verif_data = _clean_and_parse_json(verif_resp.content)
                    verdict = verif_data.get("verdict", "UNSUPPORTED")
                    if verdict not in ["SUPPORTED", "CONTRADICTED", "UNSUPPORTED"]:
                        verdict = "UNSUPPORTED"

                    claim_dict["verdict"] = verdict
                    is_supp = (verdict == "SUPPORTED")
                    claim_dict["is_supported"] = is_supp
                    claim_dict["reasoning"] = verif_data.get("reasoning", "")
                    claim_dict["supporting_chunk_ids"] = valid_c_ids if is_supp else []

                # 4. Deterministic citation metrics & faithfulness calculation
                if not claims_data:
                    faithfulness = None
                else:
                    faithfulness = sum(
                        1 for c in claims_data if c.get("is_supported")
                    ) / len(claims_data)

                citation_eval = EvaluationEngine.evaluate_citations(
                    claims_data=claims_data,
                    retrieved_chunk_ids=retrieved_chunk_ids,
                )

                # 5. Answer relevance judge
                relevance_score: Optional[float] = None
                if request.evaluate_relevance and answer_text:
                    rel_resp = self.llm_service.generate(
                        system_prompt=ANSWER_RELEVANCE_SYSTEM_PROMPT,
                        user_prompt=build_answer_relevance_prompt(item.query, answer_text),
                        temperature=0.0,
                        json_mode=True,
                    )
                    rel_data = _clean_and_parse_json(rel_resp.content)
                    try:
                        raw_score = float(rel_data.get("score", 0.0))
                        relevance_score = max(0.0, min(1.0, raw_score))
                    except (ValueError, TypeError):
                        relevance_score = None

                item_duration = (time.perf_counter() - item_start) * 1000

                metrics_dict = {
                    "faithfulness": faithfulness,
                    "citation_validity_ratio": citation_eval["citation_validity_ratio"],
                    "claim_citation_support_rate": citation_eval["claim_citation_support_rate"],
                    "citation_link_precision": citation_eval["citation_link_precision"],
                    "answer_relevance": relevance_score,
                }

                if faithfulness is not None:
                    faithfulness_scores.append(faithfulness)
                if citation_eval["citation_validity_ratio"] is not None:
                    validity_scores.append(citation_eval["citation_validity_ratio"])
                if citation_eval["claim_citation_support_rate"] is not None:
                    support_scores.append(citation_eval["claim_citation_support_rate"])
                if citation_eval["citation_link_precision"] is not None:
                    precision_scores.append(citation_eval["citation_link_precision"])
                if relevance_score is not None:
                    relevance_scores.append(relevance_score)

                item_result = EvaluationItemResult(
                    run_id=saved_run.id,
                    dataset_item_id=item.id,
                    query=item.query,
                    expected_chunk_ids_snapshot=list(item.expected_chunk_ids),
                    expected_tools_snapshot=[],
                    ground_truth_answer_snapshot=item.ground_truth_answer,
                    actual_output={
                        "answer": rag_resp.answer,
                        "retrieved_chunks": sources_snapshot,
                        "claims_provenance": claims_data,
                    },
                    metrics=metrics_dict,
                    duration_ms=item_duration,
                )
                item_results.append(item_result)

            total_duration_ms = (time.perf_counter() - start_time) * 1000

            summary_metrics = {
                "mean_faithfulness": (
                    sum(faithfulness_scores) / len(faithfulness_scores)
                    if faithfulness_scores
                    else None
                ),
                "mean_citation_validity_ratio": (
                    sum(validity_scores) / len(validity_scores)
                    if validity_scores
                    else None
                ),
                "mean_claim_citation_support_rate": (
                    sum(support_scores) / len(support_scores)
                    if support_scores
                    else None
                ),
                "mean_citation_link_precision": (
                    sum(precision_scores) / len(precision_scores)
                    if precision_scores
                    else None
                ),
                "mean_answer_relevance": (
                    sum(relevance_scores) / len(relevance_scores)
                    if relevance_scores
                    else None
                ),
                "total_items_evaluated": len(item_results),
            }

            self.eval_repo.create_item_results_bulk(item_results)
            saved_run.completed_items = len(item_results)
            finalized_run = self.eval_repo.finalize_run(
                saved_run,
                status="completed",
                summary_metrics=summary_metrics,
                duration_ms=total_duration_ms,
            )

            if request.create_experiment:
                self._log_to_experiment(
                    project_id=project_id,
                    run=finalized_run,
                    experiment_name=request.experiment_name,
                )

            return finalized_run

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"RAG evaluation run failed: {e}")
            self.eval_repo.finalize_run(
                saved_run,
                status="failed",
                summary_metrics={},
                duration_ms=elapsed_ms,
                error_message=str(e),
            )
            raise

    # =========================================================================
    # Evaluation Execution: Agent Evaluation
    # =========================================================================

    def run_agent_evaluation(
        self, project_id: int, request: RunAgentEvaluationRequest
    ) -> EvaluationRun:
        """Execute an Agent trajectory evaluation run assessing outcome, tool diagnostics, and answer correctness."""
        dataset = self.get_dataset(project_id, request.dataset_id)
        items = self.eval_repo.list_items(
            dataset_id=dataset.id, validated_only=request.validated_only, limit=1000
        )

        if not items:
            raise ValueError(
                f"No items found in dataset {dataset.id} matching criteria (validated_only={request.validated_only})."
            )

        run = EvaluationRun(
            project_id=project_id,
            dataset_id=dataset.id,
            name=request.name,
            eval_type="agent",
            status="running",
            system_configuration={
                "max_iterations": request.max_iterations,
                "validated_only": request.validated_only,
                "agent_model": self.llm_service.get_model_name(),
                "judge_model": self.llm_service.get_model_name(),
            },
            dataset_snapshot={
                "dataset_id": dataset.id,
                "dataset_name": dataset.name,
                "evaluated_items_count": len(items),
            },
            total_items=len(items),
            completed_items=0,
        )
        saved_run = self.eval_repo.create_run(run)

        start_time = time.perf_counter()
        item_results: List[EvaluationItemResult] = []
        agent_evaluations: List[Dict[str, Any]] = []

        try:
            for item in items:
                item_start = time.perf_counter()

                # 1. Run agent research session
                agent_resp = self.agent_service.run_research_session(
                    project_id=project_id,
                    request=AgentResearchRequest(
                        research_question=item.query,
                        max_iterations=request.max_iterations,
                    ),
                )

                # 2. Evaluate trajectory deterministically
                step_dicts = [s.model_dump() for s in agent_resp.trajectory]
                has_final_ans = bool(
                    agent_resp.final_answer and agent_resp.final_answer.strip()
                )
                min_steps = (
                    item.item_metadata.get("min_expected_steps")
                    if item.item_metadata
                    else None
                )

                traj_eval = EvaluationEngine.evaluate_agent_trajectory(
                    trajectory=step_dicts,
                    expected_tools=item.expected_tools,
                    session_status=agent_resp.status,
                    has_final_answer=has_final_ans,
                    min_expected_steps=min_steps,
                )

                # 3. Model-judged answer correctness against reference answer
                correctness_score: Optional[float] = None
                if item.ground_truth_answer and has_final_ans:
                    corr_resp = self.llm_service.generate(
                        system_prompt=ANSWER_CORRECTNESS_SYSTEM_PROMPT,
                        user_prompt=build_answer_correctness_prompt(
                            query=item.query,
                            reference_answer=item.ground_truth_answer,
                            candidate_answer=agent_resp.final_answer or "",
                        ),
                        temperature=0.0,
                        json_mode=True,
                    )
                    corr_data = _clean_and_parse_json(corr_resp.content)
                    try:
                        raw_c = float(corr_data.get("score", 0.0))
                        correctness_score = max(0.0, min(1.0, raw_c))
                    except (ValueError, TypeError):
                        correctness_score = None

                item_duration = (time.perf_counter() - item_start) * 1000

                metrics_dict = dict(traj_eval)
                metrics_dict["answer_correctness"] = correctness_score
                agent_evaluations.append(metrics_dict)

                item_result = EvaluationItemResult(
                    run_id=saved_run.id,
                    dataset_item_id=item.id,
                    query=item.query,
                    expected_chunk_ids_snapshot=list(item.expected_chunk_ids),
                    expected_tools_snapshot=list(item.expected_tools),  # Dedicated snapshot column
                    ground_truth_answer_snapshot=item.ground_truth_answer,
                    actual_output={
                        "status": agent_resp.status,
                        "final_answer": agent_resp.final_answer,
                        "stop_reason": agent_resp.stop_reason,
                        "citations": [c.model_dump() for c in agent_resp.citations],
                        "trajectory_summary": step_dicts,
                        "total_iterations": agent_resp.total_iterations,
                        "total_tool_calls": agent_resp.total_tool_calls,
                    },
                    metrics=metrics_dict,
                    duration_ms=item_duration,
                    tokens_used=agent_resp.total_tokens_used,
                )
                item_results.append(item_result)

            total_duration_ms = (time.perf_counter() - start_time) * 1000
            summary_metrics = EvaluationEngine.aggregate_agent_metrics(agent_evaluations)

            self.eval_repo.create_item_results_bulk(item_results)
            saved_run.completed_items = len(item_results)
            finalized_run = self.eval_repo.finalize_run(
                saved_run,
                status="completed",
                summary_metrics=summary_metrics,
                duration_ms=total_duration_ms,
            )

            if request.create_experiment:
                self._log_to_experiment(
                    project_id=project_id,
                    run=finalized_run,
                    experiment_name=request.experiment_name,
                )

            return finalized_run

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.exception(f"Agent evaluation run failed: {e}")
            self.eval_repo.finalize_run(
                saved_run,
                status="failed",
                summary_metrics={},
                duration_ms=elapsed_ms,
                error_message=str(e),
            )
            raise

    # =========================================================================
    # Run Retrieval & Listing
    # =========================================================================

    def get_run(self, project_id: int, run_id: int) -> EvaluationRun:
        """Fetch an evaluation run by ID within a project."""
        self._ensure_project_exists(project_id)
        run = self.eval_repo.get_run(run_id, project_id=project_id)
        if not run:
            raise FileNotFoundError(
                f"Evaluation run {run_id} not found in project {project_id}"
            )
        return run

    def list_runs(
        self,
        project_id: int,
        run_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[EvaluationRun]:
        """List evaluation runs for a project."""
        self._ensure_project_exists(project_id)
        return self.eval_repo.list_runs(
            project_id=project_id,
            run_type=run_type,
            status=status,
            limit=limit,
            offset=offset,
        )

    def get_run_item_results(
        self, project_id: int, run_id: int, limit: int = 100, offset: int = 0
    ) -> List[EvaluationItemResult]:
        """Fetch item results for an evaluation run."""
        self.get_run(project_id, run_id)
        return self.eval_repo.list_item_results(run_id, limit=limit, offset=offset)

    # =========================================================================
    # Experiment Logging Integration
    # =========================================================================

    def _log_to_experiment(
        self,
        project_id: int,
        run: EvaluationRun,
        experiment_name: Optional[str] = None,
    ) -> None:
        """Link completed evaluation run to an Experiment record."""
        title = experiment_name or f"Evaluation: {run.name}"
        exp_create = ExperimentCreate(
            title=title,
            description=f"Empirical evaluation run ({run.eval_type}) with {run.completed_items} items.",
            status=ExperimentStatus.COMPLETED,
            priority=ExperimentPriority.MEDIUM,
            methodology=f"Automated {run.eval_type} evaluation benchmark",
            target_metrics=list(run.summary_metrics.keys()) if run.summary_metrics else [],
            results=run.summary_metrics,
            parameters=run.system_configuration,
            findings=ExperimentFindings(
                summary=f"Automated evaluation {run.name} completed with {run.completed_items}/{run.total_items} items in {run.duration_ms:.1f}ms."
            ),
        )
        try:
            exp = self.experiment_service.create_manual_experiment(project_id, exp_create)
            run.experiment_id = exp.id
            self.eval_repo.update_run(run)
            logger.info(
                f"Evaluation run {run.id} successfully linked to experiment {exp.id}"
            )
        except Exception as e:
            logger.warning(f"Failed to log evaluation run {run.id} to experiment: {e}")
