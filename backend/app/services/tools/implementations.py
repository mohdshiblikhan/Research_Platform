from typing import Any, Optional
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.research_plan_repository import ResearchPlanRepository
from app.schemas.comparison import ComparisonRequest
from app.schemas.tool import (
    ComparePapersArgs,
    GetChunkArgs,
    GetDocumentMetadataArgs,
    GetPaperExtractionArgs,
    GetResearchPlanArgs,
    ListDocumentsArgs,
    ListResearchPlansArgs,
    SearchChunksArgs,
    ToolResult,
    ToolSafetyTier,
)
from app.services.comparison_service import ComparisonService
from app.services.search_service import SearchService
from app.services.tools.base import BaseTool, ToolContext


class SearchChunksTool(BaseTool):
    name = "search_chunks"
    description = (
        "Retrieve relevant text passages from research papers in the project using "
        "keyword, semantic, or hybrid search with optional cross-encoder reranking."
    )
    args_schema = SearchChunksArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        try:
            service = SearchService(context.db)
            response = service.search(
                project_id=context.project_id,
                query=kwargs["query"],
                mode=kwargs.get("mode", "hybrid"),
                document_id=kwargs.get("document_id"),
                rerank=kwargs.get("rerank", True),
                limit=kwargs.get("limit", 5),
                offset=0,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Search failed: {e}",
                error=str(e),
            )

        if not response.results:
            return ToolResult(
                success=True,
                tool_name=self.name,
                result_summary=f"No passages found matching '{kwargs['query']}'.",
                data=response.model_dump(),
            )

        lines = [f"Found {len(response.results)} relevant passages (Mode: {response.search_mode}):"]
        for r in response.results:
            score_str = f"Rerank Score: {r.rerank_score:.3f}" if r.rerank_score is not None else f"Rank/Sim: {r.rank or r.similarity_score or 0.0:.3f}"
            doc_name = r.document_filename or "Unknown Document"
            lines.append(
                f"- [Chunk {r.chunk_id} | Doc {r.document_id} ({doc_name}) | "
                f"Page {r.page_start}-{r.page_end} | {score_str}]:\n  \"{r.content[:300]}...\""
            )
        return ToolResult(
            success=True,
            tool_name=self.name,
            result_summary="\n".join(lines),
            data=response.model_dump(),
        )


class GetChunkTool(BaseTool):
    name = "get_chunk"
    description = (
        "Inspect the full verbatim text and page provenance of a specific chunk by chunk ID."
    )
    args_schema = GetChunkArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        chunk_repo = ChunkRepository(context.db)
        doc_repo = DocumentRepository(context.db)
        chunk_id = kwargs["chunk_id"]

        chunk = chunk_repo.get_by_id(chunk_id)
        if not chunk:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Chunk {chunk_id} not found in this project.",
                error="Chunk not found.",
            )

        doc = doc_repo.get_by_id(chunk.document_id)
        if not doc or doc.project_id != context.project_id:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Chunk {chunk_id} not found in this project.",
                error="Chunk not found or does not belong to project.",
            )

        summary = (
            f"Chunk ID {chunk.id} (Document ID {doc.id}: '{doc.filename}', "
            f"Pages {chunk.page_start} to {chunk.page_end}, Chars {chunk.char_offset_start}-{chunk.char_offset_end}):\n\n"
            f"{chunk.content}"
        )
        return ToolResult(
            success=True,
            tool_name=self.name,
            result_summary=summary,
            data={
                "id": chunk.id,
                "document_id": doc.id,
                "document_filename": doc.filename,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "char_offset_start": chunk.char_offset_start,
                "char_offset_end": chunk.char_offset_end,
                "content": chunk.content,
            },
        )


class ListDocumentsTool(BaseTool):
    name = "list_documents"
    description = "List all research papers available in the current project."
    args_schema = ListDocumentsArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        doc_repo = DocumentRepository(context.db)
        chunk_repo = ChunkRepository(context.db)
        docs = doc_repo.list_by_project(context.project_id)
        status_filter = kwargs.get("status")
        if status_filter:
            docs = [d for d in docs if d.status == status_filter]

        if not docs:
            return ToolResult(
                success=True,
                tool_name=self.name,
                result_summary="No documents found in this project.",
                data={"documents": []},
            )

        lines = [f"Project contains {len(docs)} document(s):"]
        doc_list = []
        for d in docs:
            chunk_count = chunk_repo.count_by_document(d.id)
            lines.append(
                f"- [Doc ID {d.id}]: '{d.filename}' (Status: {d.status}, Pages: {d.page_count or 'N/A'}, "
                f"Chunks: {chunk_count})"
            )
            doc_list.append({
                "id": d.id,
                "filename": d.filename,
                "status": d.status,
                "page_count": d.page_count,
                "chunks_count": chunk_count,
            })
        return ToolResult(
            success=True,
            tool_name=self.name,
            result_summary="\n".join(lines),
            data={"documents": doc_list},
        )


class GetDocumentMetadataTool(BaseTool):
    name = "get_document_metadata"
    description = (
        "Retrieve detailed metadata for a single research document, including processing status "
        "and extraction status."
    )
    args_schema = GetDocumentMetadataArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        doc_repo = DocumentRepository(context.db)
        chunk_repo = ChunkRepository(context.db)
        ext_repo = ExtractionRepository(context.db)
        doc_id = kwargs["document_id"]

        doc = doc_repo.get_by_id(doc_id)
        if not doc or doc.project_id != context.project_id:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Document {doc_id} not found in this project.",
                error="Document not found.",
            )

        ext = ext_repo.get_by_document_id(doc.id)
        has_ext = ext is not None
        chunk_count = chunk_repo.count_by_document(doc.id)
        summary = (
            f"Document ID {doc.id}: '{doc.filename}'\n"
            f"- Status: {doc.status}\n"
            f"- Pages: {doc.page_count or 'N/A'}\n"
            f"- Chunks: {chunk_count}\n"
            f"- Structured Extraction Available: {'Yes' if has_ext else 'No'}\n"
            f"- Uploaded: {doc.created_at.strftime('%Y-%m-%d')}"
        )
        return ToolResult(
            success=True,
            tool_name=self.name,
            result_summary=summary,
            data={
                "id": doc.id,
                "filename": doc.filename,
                "status": doc.status,
                "page_count": doc.page_count,
                "chunks_count": chunk_count,
                "has_extraction": has_ext,
                "created_at": doc.created_at.isoformat(),
            },
        )


class GetPaperExtractionTool(BaseTool):
    name = "get_paper_extraction"
    description = (
        "Retrieve pre-extracted structured metadata for a research paper: "
        "problem, methodology, models used, datasets, evaluation metrics, results, and limitations."
    )
    args_schema = GetPaperExtractionArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        doc_repo = DocumentRepository(context.db)
        ext_repo = ExtractionRepository(context.db)
        doc_id = kwargs["document_id"]

        doc = doc_repo.get_by_id(doc_id)
        if not doc or doc.project_id != context.project_id:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Document {doc_id} not found in this project.",
                error="Document not found.",
            )

        ext = ext_repo.get_by_document_id(doc.id)
        if not ext:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"No structured extraction found for Document {doc.id} ('{doc.filename}').",
                error="Extraction not found. Document may not have been extracted yet.",
            )

        summary = (
            f"Structured Extraction for Document ID {doc.id} ('{doc.filename}'):\n"
            f"- Research Problem: {ext.research_problem}\n"
            f"- Methodology: {ext.methodology}\n"
            f"- Models Used: {ext.models_used}\n"
            f"- Datasets: {ext.datasets}\n"
            f"- Evaluation Metrics: {ext.evaluation_metrics}\n"
            f"- Results: {ext.results}\n"
            f"- Limitations: {ext.limitations}\n"
            f"- Baselines: {ext.baselines}"
        )
        return ToolResult(
            success=True,
            tool_name=self.name,
            result_summary=summary,
            data={
                "document_id": doc.id,
                "research_problem": ext.research_problem,
                "methodology": ext.methodology,
                "models_used": ext.models_used,
                "datasets": ext.datasets,
                "evaluation_metrics": ext.evaluation_metrics,
                "results": ext.results,
                "limitations": ext.limitations,
                "baselines": ext.baselines,
            },
        )


class ComparePapersTool(BaseTool):
    name = "compare_papers"
    description = (
        "Compare multiple papers side-by-side across structured dimensions and generate an analytical synthesis."
    )
    args_schema = ComparePapersArgs
    safety_tier = ToolSafetyTier.ANALYTICAL

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        service = ComparisonService(context.db)
        req = ComparisonRequest(
            document_ids=kwargs["document_ids"],
            include_synthesis=kwargs.get("include_synthesis", True),
        )
        try:
            res = service.compare(context.project_id, req)
        except Exception as e:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Comparison failed: {e}",
                error=str(e),
            )

        doc_names = [v.filename for v in res.fields[0].values] if res.fields and res.fields[0].values else []
        lines = [f"Comparison of {res.documents_compared} documents ({', '.join(doc_names)}):"]
        if res.synthesis:
            lines.append("\nSynthesis:")
            lines.append(f"- Key Differences: {res.synthesis.key_differences}")
            lines.append(f"- Common Themes: {res.synthesis.common_themes}")
            if res.synthesis.research_gaps:
                lines.append(f"- Research Gaps: {res.synthesis.research_gaps}")
        else:
            lines.append("Comparison matrix generated across 8 fields.")

        return ToolResult(
            success=True,
            tool_name=self.name,
            result_summary="\n".join(lines),
            data=res.model_dump(),
        )


class GetResearchPlanTool(BaseTool):
    name = "get_research_plan"
    description = "Retrieve an existing research plan by ID to inspect literature gaps, hypotheses, and experiments."
    args_schema = GetResearchPlanArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        repo = ResearchPlanRepository(context.db)
        plan_id = kwargs["plan_id"]
        plan = repo.get_by_id(plan_id)
        if not plan or plan.project_id != context.project_id:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Research Plan {plan_id} not found in this project.",
                error="Plan not found.",
            )

        output = plan.plan_output or {}
        gaps_list = [f"{g.get('id', '')}: {g.get('description', '')}" if isinstance(g, dict) else str(g) for g in output.get("gaps", [])]
        hypo_list = [f"{h.get('id', '')}: {h.get('statement', '')}" if isinstance(h, dict) else str(h) for h in output.get("hypotheses", [])]
        exp_list = [f"{e.get('id', '')}: {e.get('title', '')}" if isinstance(e, dict) else str(e) for e in output.get("experiments", [])]

        summary = (
            f"Research Plan ID {plan.id} (Created: {plan.created_at.strftime('%Y-%m-%d')}):\n"
            f"- Question: {plan.research_question}\n"
            f"- Documents Analyzed: {plan.documents_analyzed} (IDs: {plan.document_ids_used})\n"
            f"- Summary: {output.get('literature_summary', '')[:200]}...\n"
            f"- Gaps: {', '.join(gaps_list)}\n"
            f"- Hypotheses: {', '.join(hypo_list)}\n"
            f"- Experiments: {', '.join(exp_list)}\n"
            f"- Recommended Sequence: {output.get('recommended_sequence', [])}"
        )
        return ToolResult(
            success=True,
            tool_name=self.name,
            result_summary=summary,
            data={
                "id": plan.id,
                "project_id": plan.project_id,
                "research_question": plan.research_question,
                "plan_output": plan.plan_output,
                "documents_analyzed": plan.documents_analyzed,
                "document_ids_used": plan.document_ids_used,
            },
        )


class ListResearchPlansTool(BaseTool):
    name = "list_research_plans"
    description = "List all existing research plans generated in the project."
    args_schema = ListResearchPlansArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        repo = ResearchPlanRepository(context.db)
        plans = repo.list_by_project(context.project_id)
        if not plans:
            return ToolResult(
                success=True,
                tool_name=self.name,
                result_summary="No research plans found in this project.",
                data={"plans": []},
            )

        lines = [f"Project contains {len(plans)} research plan(s):"]
        plan_list = []
        for p in plans:
            lines.append(
                f"- [Plan ID {p.id}]: \"{p.research_question}\" (Docs: {p.documents_analyzed}, "
                f"Created: {p.created_at.strftime('%Y-%m-%d')})"
            )
            plan_list.append({
                "id": p.id,
                "research_question": p.research_question,
                "documents_analyzed": p.documents_analyzed,
                "created_at": p.created_at.isoformat(),
            })
        return ToolResult(
            success=True,
            tool_name=self.name,
            result_summary="\n".join(lines),
            data={"plans": plan_list},
        )
