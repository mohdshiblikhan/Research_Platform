import json
import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.extraction import DocumentExtraction
from app.models.research_plan import ResearchPlan
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.research_plan_repository import ResearchPlanRepository
from app.schemas.comparison import ComparisonRequest
from app.schemas.research_plan import (
    ProposedExperiment,
    ResearchGap,
    ResearchHypothesis,
    ResearchPlanOutput,
    ResearchPlanRequest,
    ResearchPlanResponse,
    ResearchPlanSummary,
)
from app.core.config import settings
from app.services.comparison_service import ComparisonService
from app.services.llm_service import LLMService
from app.services.llm_service_factory import get_llm_service
from app.services.search_service import SearchService
from app.prompts.research_planning_prompts import (
    RESEARCH_PLANNING_SYSTEM_PROMPT,
    build_research_planning_prompt,
    format_evidence_passage,
    format_extraction_for_planning,
)

logger = logging.getLogger(__name__)


class ResearchPlanningService:
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.doc_repo = DocumentRepository(db)
        self.extraction_repo = ExtractionRepository(db)
        self.plan_repo = ResearchPlanRepository(db)
        self.llm_service = llm_service or get_llm_service()
        self.comparison_service = ComparisonService(db, self.llm_service)
        self.search_service = SearchService(db)

    def create_plan(
        self,
        project_id: int,
        request: ResearchPlanRequest,
    ) -> ResearchPlanResponse:
        """Generate and persist a structured research plan from literature analysis."""
        start_total = time.perf_counter()

        # 1. Validate project existence
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")

        # 2. Resolve document scope
        docs_with_extractions, missing_ids, extraction_map = self._resolve_documents(
            project_id=project_id,
            document_ids=request.document_ids,
        )

        if len(docs_with_extractions) == 0:
            raise ValueError("None of the specified documents have extractions")
        if len(docs_with_extractions) < 2:
            raise ValueError(
                "At least 2 documents with extractions are required for research planning"
            )
        if len(docs_with_extractions) > settings.max_documents_per_plan:
            raise ValueError(
                f"Planning currently supports a maximum of {settings.max_documents_per_plan} documents per plan. "
                f"Please specify a subset using document_ids."
            )

        analyzed_doc_ids = [doc.id for doc in docs_with_extractions]

        # 3. Cross-document comparison with analytical synthesis (1st LLM call)
        comparison_request = ComparisonRequest(
            document_ids=analyzed_doc_ids,
            include_synthesis=True,
        )
        comparison_response = self.comparison_service.compare(
            project_id=project_id,
            request=comparison_request,
        )
        comparison_time_ms = comparison_response.synthesis_time_ms

        # 4. Question-specific evidence retrieval with consistent document scope
        evidence_context, retrieval_time_ms = self._retrieve_evidence(
            project_id=project_id,
            research_question=request.research_question,
            analyzed_doc_ids=analyzed_doc_ids,
        )

        # 5. Assemble planning context
        extractions_context = self._build_extractions_context(
            docs=docs_with_extractions,
            extraction_map=extraction_map,
        )
        comparison_context = self._build_comparison_context(comparison_response)

        planning_prompt = build_research_planning_prompt(
            research_question=request.research_question,
            extractions_context=extractions_context,
            comparison_context=comparison_context,
            evidence_context=evidence_context,
        )

        # 6. LLM Plan Generation (2nd LLM call)
        start_plan = time.perf_counter()
        llm_response = self.llm_service.generate(
            system_prompt=RESEARCH_PLANNING_SYSTEM_PROMPT,
            user_prompt=planning_prompt,
            temperature=0.1,
            json_mode=True,
        )
        planning_time_ms = round((time.perf_counter() - start_plan) * 1000, 2)

        # 7. Parse and validate LLM output
        try:
            raw_json = json.loads(llm_response.content)
            plan_output = ResearchPlanOutput.model_validate(raw_json)
        except Exception as e:
            logger.error(
                f"Failed to parse LLM research plan output: {e}. Raw content: {llm_response.content}"
            )
            raise ValueError(f"LLM failed to generate a valid structured research plan: {e}")

        # 8. Persist plan to database
        plan_dict = plan_output.model_dump()
        model_name = self.llm_service.get_model_name()
        plan_record = self.plan_repo.create(
            project_id=project_id,
            research_question=request.research_question,
            document_ids_used=analyzed_doc_ids,
            plan_output=plan_dict,
            llm_model=model_name,
            planning_time_ms=planning_time_ms,
            documents_analyzed=len(docs_with_extractions),
        )

        total_time_ms = round((time.perf_counter() - start_total) * 1000, 2)

        return self._build_response(
            plan=plan_record,
            plan_output=plan_output,
            documents_without_extraction=missing_ids,
            comparison_time_ms=comparison_time_ms,
            retrieval_time_ms=retrieval_time_ms,
            total_time_ms=total_time_ms,
        )

    def get_plan(self, project_id: int, plan_id: int) -> ResearchPlanResponse:
        """Fetch a specific persisted research plan."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")

        plan = self.plan_repo.get_by_id(plan_id)
        if not plan or plan.project_id != project_id:
            raise FileNotFoundError(f"Research plan {plan_id} not found in project {project_id}")

        plan_output = ResearchPlanOutput.model_validate(plan.plan_output)
        return self._build_response(
            plan=plan,
            plan_output=plan_output,
            documents_without_extraction=[],
            comparison_time_ms=None,
            retrieval_time_ms=None,
            total_time_ms=plan.planning_time_ms,
        )

    def list_plans(self, project_id: int) -> list[ResearchPlanSummary]:
        """List all research plans for a project."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")

        plans = self.plan_repo.list_by_project(project_id)
        summaries: list[ResearchPlanSummary] = []
        for p in plans:
            confidence = p.plan_output.get("confidence", "medium") if isinstance(p.plan_output, dict) else "medium"
            summaries.append(
                ResearchPlanSummary(
                    id=p.id,
                    project_id=p.project_id,
                    research_question=p.research_question,
                    documents_analyzed=p.documents_analyzed,
                    confidence=confidence,
                    created_at=p.created_at,
                )
            )
        return summaries

    def _resolve_documents(
        self,
        project_id: int,
        document_ids: Optional[list[int]],
    ) -> tuple[list[Document], list[int], dict[int, DocumentExtraction]]:
        """Resolve document scope, returning (docs_with_extractions, missing_ids, extraction_map)."""
        if document_ids is not None:
            doc_map: dict[int, Document] = {}
            for doc_id in document_ids:
                doc = self.doc_repo.get_by_id(doc_id)
                if not doc or doc.project_id != project_id:
                    raise FileNotFoundError(
                        f"Document {doc_id} not found in project {project_id}"
                    )
                doc_map[doc_id] = doc

            extractions = self.extraction_repo.get_by_document_ids(document_ids)
            extraction_map = {ext.document_id: ext for ext in extractions}

            docs_with_extractions = []
            missing_ids = []
            for doc_id in document_ids:
                if doc_id in extraction_map:
                    docs_with_extractions.append(doc_map[doc_id])
                else:
                    missing_ids.append(doc_id)

            return docs_with_extractions, missing_ids, extraction_map
        else:
            # Automatic path: fetch all extractions for the project
            extractions = self.extraction_repo.get_by_project_id(project_id)
            extraction_map = {ext.document_id: ext for ext in extractions}

            all_docs = self.doc_repo.list_by_project(project_id)
            docs_with_extractions = [doc for doc in all_docs if doc.id in extraction_map]
            missing_ids = [doc.id for doc in all_docs if doc.id not in extraction_map]

            return docs_with_extractions, missing_ids, extraction_map

    def _retrieve_evidence(
        self,
        project_id: int,
        research_question: str,
        analyzed_doc_ids: list[int],
    ) -> tuple[str, float]:
        """Retrieve question-specific evidence passages bounded strictly to analyzed documents."""
        try:
            search_response = self.search_service.search(
                project_id=project_id,
                query=research_question,
                mode="hybrid",
                rerank=True,
                limit=20,
                offset=0,
            )
            # Enforce consistent document scope: keep only chunks from analyzed documents
            scoped_results = [
                r for r in search_response.results if r.document_id in analyzed_doc_ids
            ][:5]

            evidence_blocks = []
            for i, item in enumerate(scoped_results, start=1):
                block = format_evidence_passage(
                    index=i,
                    doc_id=item.document_id,
                    filename=item.document_filename,
                    page_start=item.page_start,
                    page_end=item.page_end,
                    chunk_id=item.chunk_id,
                    content=item.content,
                )
                evidence_blocks.append(block)

            return "\n\n".join(evidence_blocks), search_response.query_time_ms
        except Exception as e:
            logger.warning(f"Evidence retrieval failed or found no chunks: {e}")
            return "", 0.0

    def _build_extractions_context(
        self,
        docs: list[Document],
        extraction_map: dict[int, DocumentExtraction],
    ) -> str:
        """Format extraction metadata for all analyzed documents."""
        blocks = []
        for doc in docs:
            ext = extraction_map[doc.id]
            blocks.append(format_extraction_for_planning(doc.id, doc.filename, ext))
        return "\n\n".join(blocks)

    def _build_comparison_context(self, comparison_response) -> str:
        """Format comparison synthesis into context for the prompt."""
        synthesis = comparison_response.synthesis
        if not synthesis:
            return "(No analytical comparison synthesis available)"

        lines = [
            f"Key Differences Across Papers:\n{synthesis.key_differences}",
            f"Common Themes:\n{synthesis.common_themes}",
        ]
        if synthesis.conflicting_findings:
            lines.append(f"Conflicting Findings:\n{synthesis.conflicting_findings}")
        if synthesis.research_gaps:
            lines.append(f"Previously Identified Literature Gaps:\n{synthesis.research_gaps}")
        if synthesis.summary:
            lines.append(f"Overall Comparison Summary:\n{synthesis.summary}")

        return "\n\n".join(lines)

    def _build_response(
        self,
        plan: ResearchPlan,
        plan_output: ResearchPlanOutput,
        documents_without_extraction: list[int],
        comparison_time_ms: Optional[float],
        retrieval_time_ms: Optional[float],
        total_time_ms: float,
    ) -> ResearchPlanResponse:
        """Assemble the complete API response."""
        return ResearchPlanResponse(
            id=plan.id,
            project_id=plan.project_id,
            research_question=plan.research_question,
            documents_analyzed=plan.documents_analyzed,
            documents_without_extraction=documents_without_extraction,
            document_ids_used=plan.document_ids_used,
            reasoning=plan_output.reasoning,
            literature_summary=plan_output.literature_summary,
            gaps=plan_output.gaps,
            hypotheses=plan_output.hypotheses,
            experiments=plan_output.experiments,
            recommended_sequence=plan_output.recommended_sequence,
            confidence=plan_output.confidence,
            limitations=plan_output.limitations,
            comparison_time_ms=comparison_time_ms,
            retrieval_time_ms=retrieval_time_ms,
            planning_time_ms=plan.planning_time_ms,
            total_time_ms=total_time_ms,
            llm_model=plan.llm_model,
            created_at=plan.created_at,
        )
