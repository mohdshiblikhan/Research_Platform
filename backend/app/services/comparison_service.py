import json
import logging
import time
from typing import Optional

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.extraction import DocumentExtraction
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.comparison import (
    ComparisonField,
    ComparisonFieldValue,
    ComparisonRequest,
    ComparisonResponse,
    ComparisonSynthesis,
)
from app.services.llm_service import LLMService
from app.services.llm_service_factory import get_llm_service

logger = logging.getLogger(__name__)

EXTRACTION_FIELDS: list[tuple[str, str]] = [
    ("research_problem", "Research Problem"),
    ("methodology", "Methodology"),
    ("models_used", "Models Used"),
    ("datasets", "Datasets"),
    ("evaluation_metrics", "Evaluation Metrics"),
    ("results", "Results"),
    ("limitations", "Limitations"),
    ("baselines", "Baselines"),
]


class ComparisonService:
    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.doc_repo = DocumentRepository(db)
        self.extraction_repo = ExtractionRepository(db)
        self.llm_service = llm_service or get_llm_service()

    def compare(self, project_id: int, request: ComparisonRequest) -> ComparisonResponse:
        """Compare extracted structured metadata across multiple documents in a project."""
        # 1. Validate project exists
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise FileNotFoundError("Project not found")

        # 2. Validate all document_ids belong to this project
        doc_map: dict[int, Document] = {}
        for doc_id in request.document_ids:
            doc = self.doc_repo.get_by_id(doc_id)
            if not doc or doc.project_id != project_id:
                raise FileNotFoundError(f"Document {doc_id} not found in project")
            doc_map[doc_id] = doc

        # 3. Bulk fetch extractions
        extractions = self.extraction_repo.get_by_document_ids(request.document_ids)
        extraction_map: dict[int, DocumentExtraction] = {
            ext.document_id: ext for ext in extractions
        }

        # 4. Separate documents with extractions from missing
        docs_with_extractions: list[Document] = []
        missing_ids: list[int] = []
        for doc_id in request.document_ids:
            if doc_id in extraction_map:
                docs_with_extractions.append(doc_map[doc_id])
            else:
                missing_ids.append(doc_id)

        # 5. Validate extraction counts
        if len(docs_with_extractions) == 0:
            raise ValueError("None of the specified documents have extractions")
        if len(docs_with_extractions) < 2:
            raise ValueError("At least 2 documents must have extractions for comparison")

        # 6. Assemble comparison matrix
        fields = self._build_comparison_matrix(docs_with_extractions, extraction_map)

        # 7. Optional LLM synthesis
        synthesis: Optional[ComparisonSynthesis] = None
        llm_model: Optional[str] = None
        synthesis_time_ms: Optional[float] = None

        if request.include_synthesis:
            synthesis, llm_model, synthesis_time_ms = self._generate_synthesis(
                docs_with_extractions, extraction_map
            )

        return ComparisonResponse(
            project_id=project_id,
            documents_compared=len(docs_with_extractions),
            documents_missing_extraction=missing_ids,
            fields=fields,
            synthesis=synthesis,
            llm_model=llm_model,
            synthesis_time_ms=synthesis_time_ms,
        )

    def _build_comparison_matrix(
        self,
        docs: list[Document],
        extraction_map: dict[int, DocumentExtraction],
    ) -> list[ComparisonField]:
        """Assemble deterministic field-by-document matrix."""
        fields: list[ComparisonField] = []
        for field_name, field_label in EXTRACTION_FIELDS:
            values: list[ComparisonFieldValue] = []
            for doc in docs:
                ext = extraction_map[doc.id]
                val = getattr(ext, field_name, None)
                values.append(
                    ComparisonFieldValue(
                        document_id=doc.id,
                        filename=doc.filename,
                        value=val,
                    )
                )
            fields.append(
                ComparisonField(
                    field_name=field_name,
                    field_label=field_label,
                    values=values,
                )
            )
        return fields

    def _generate_synthesis(
        self,
        docs: list[Document],
        extraction_map: dict[int, DocumentExtraction],
    ) -> tuple[Optional[ComparisonSynthesis], Optional[str], Optional[float]]:
        """Call the LLM to generate an analytical comparison synthesis."""
        system_prompt = (
            "You are an expert research analyst. You are given structured metadata extracted "
            "from multiple research papers. Your job is to analyze the comparison and produce "
            "a concise synthesis.\n\n"
            "Return a JSON object with these keys:\n"
            "- key_differences: Main ways the papers differ in approach, data, or findings.\n"
            "- common_themes: Shared approaches, datasets, or conclusions.\n"
            "- conflicting_findings: Any contradictory claims or results (null if none).\n"
            "- research_gaps: Opportunities or unanswered questions revealed by the comparison (null if none).\n"
            "- summary: A brief 2-3 sentence overall summary.\n\n"
            "Only output the valid JSON object. Do not output any markdown or extra text."
        )

        paper_sections = []
        for i, doc in enumerate(docs, start=1):
            ext = extraction_map[doc.id]
            lines = [f'=== Paper {i}: "{doc.filename}" ===']
            for field_name, field_label in EXTRACTION_FIELDS:
                val = getattr(ext, field_name, None) or "Not specified"
                lines.append(f"{field_label}: {val}")
            paper_sections.append("\n".join(lines))

        user_prompt = (
            "Compare the following research papers based on their extracted metadata:\n\n"
            + "\n\n".join(paper_sections)
            + "\n\nAnalyze the comparison and return a JSON synthesis."
        )

        model_name = self.llm_service.get_model_name()
        start_time = time.perf_counter()
        try:
            llm_response = self.llm_service.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                json_mode=True,
            )
            synthesis_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            raw_json = json.loads(llm_response.content)
            synthesis = ComparisonSynthesis(
                key_differences=raw_json.get("key_differences", ""),
                common_themes=raw_json.get("common_themes", ""),
                conflicting_findings=raw_json.get("conflicting_findings"),
                research_gaps=raw_json.get("research_gaps"),
                summary=raw_json.get("summary", ""),
            )
            return synthesis, model_name, synthesis_time_ms
        except Exception as e:
            logger.error(f"Failed to generate or parse LLM comparison synthesis: {e}")
            synthesis_time_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return None, model_name, synthesis_time_ms
