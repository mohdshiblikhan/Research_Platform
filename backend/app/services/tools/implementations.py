from typing import Any, Optional
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.experiment_repository import ExperimentRepository
from app.repositories.extraction_repository import ExtractionRepository
from app.repositories.research_plan_repository import ResearchPlanRepository
from app.schemas.comparison import ComparisonRequest
from app.schemas.experiment_comparison import ExperimentComparisonRequest
from app.schemas.tool import (
    CompareExperimentsArgs,
    ComparePapersArgs,
    GetChunkArgs,
    GetDocumentMetadataArgs,
    GetEvaluationResultsArgs,
    GetExperimentArgs,
    GetPaperExtractionArgs,
    GetResearchPlanArgs,
    ListDocumentsArgs,
    ListExperimentsArgs,
    ListResearchPlansArgs,
    RunEvaluationArgs,
    SearchChunksArgs,
    ToolResult,
    ToolSafetyTier,
)
from app.schemas.evaluation import (
    RunAgentEvaluationRequest,
    RunRAGEvaluationRequest,
    RunRetrievalEvaluationRequest,
)
from app.services.comparison_service import ComparisonService
from app.services.experiment_comparison_service import ExperimentComparisonService
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


class ListExperimentsTool(BaseTool):
    name = "list_experiments"
    description = (
        "List planned, in-progress, or completed research experiments in the project, "
        "with optional filtering by status, priority, or research plan ID."
    )
    args_schema = ListExperimentsArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        repo = ExperimentRepository(context.db)
        experiments = repo.list_by_project(
            project_id=context.project_id,
            status=kwargs.get("status"),
            priority=kwargs.get("priority"),
            research_plan_id=kwargs.get("plan_id"),
        )
        if not experiments:
            return ToolResult(
                success=True,
                tool_name=self.name,
                result_summary="No experiments found matching the specified criteria in this project.",
                data={"experiments": []},
            )

        lines = [f"Found {len(experiments)} experiment(s):"]
        exp_list = []
        for e in experiments:
            has_res = e.has_results
            lines.append(
                f"- [ID {e.id}] '{e.title}' | Status: {e.status} | Priority: {e.priority} "
                f"| Hypothesis: {e.hypothesis_id or 'N/A'} | Has Results: {has_res}"
            )
            exp_list.append({
                "id": e.id,
                "title": e.title,
                "status": e.status,
                "priority": e.priority,
                "hypothesis_id": e.hypothesis_id,
                "has_results": has_res,
                "research_plan_id": e.research_plan_id,
                "plan_experiment_id": e.plan_experiment_id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            })
        return ToolResult(
            success=True,
            tool_name=self.name,
            result_summary="\n".join(lines),
            data={"experiments": exp_list},
        )


class GetExperimentTool(BaseTool):
    name = "get_experiment"
    description = (
        "Retrieve the full specifications, methodology, parameters, logged results, "
        "and qualitative findings of a specific experiment."
    )
    args_schema = GetExperimentArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        repo = ExperimentRepository(context.db)
        experiment = repo.get_by_id(kwargs["experiment_id"], project_id=context.project_id)
        if not experiment:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Experiment {kwargs['experiment_id']} not found in this project.",
                error=f"Experiment {kwargs['experiment_id']} not found in project {context.project_id}",
            )

        summary_lines = [
            f"Experiment [ID {experiment.id}]: {experiment.title}",
            f"- Status: {experiment.status} (Priority: {experiment.priority})",
            f"- Methodology: {experiment.methodology}",
        ]
        if experiment.hypothesis_id or experiment.hypothesis_statement:
            summary_lines.append(
                f"- Hypothesis: [{experiment.hypothesis_id or 'N/A'}] {experiment.hypothesis_statement or 'N/A'}"
            )
        if experiment.datasets:
            summary_lines.append(f"- Datasets: {experiment.datasets}")
        if experiment.parameters:
            summary_lines.append(f"- Parameters: {experiment.parameters}")
        if experiment.results:
            summary_lines.append(f"- Results: {experiment.results}")
        if experiment.findings:
            findings_summary = experiment.findings.get("summary", "N/A")
            verdict = experiment.findings.get("hypothesis_verdict", "N/A")
            summary_lines.append(f"- Findings: {findings_summary} (Verdict: {verdict})")

        return ToolResult(
            success=True,
            tool_name=self.name,
            result_summary="\n".join(summary_lines),
            data={
                "id": experiment.id,
                "project_id": experiment.project_id,
                "research_plan_id": experiment.research_plan_id,
                "plan_experiment_id": experiment.plan_experiment_id,
                "title": experiment.title,
                "status": experiment.status,
                "priority": experiment.priority,
                "hypothesis_id": experiment.hypothesis_id,
                "hypothesis_statement": experiment.hypothesis_statement,
                "methodology": experiment.methodology,
                "datasets": experiment.datasets,
                "variables": experiment.variables,
                "parameters": experiment.parameters,
                "target_metrics": experiment.target_metrics,
                "results": experiment.results,
                "findings": experiment.findings,
                "provenance": experiment.provenance,
                "abandonment_reason": experiment.abandonment_reason,
                "completed_at": experiment.completed_at.isoformat() if experiment.completed_at else None,
            },
        )


class CompareExperimentsTool(BaseTool):
    name = "compare_experiments"
    description = (
        "Compare 2 to 10 experiments side-by-side across configurations, quantitative metrics, "
        "baseline deltas, Pareto frontier trade-offs, and hypothesis verdicts."
    )
    args_schema = CompareExperimentsArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        experiment_ids = kwargs.get("experiment_ids", [])
        if len(experiment_ids) > 10:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary="Error: compare_experiments tool allows at most 10 experiments per invocation to preserve context budget.",
                error="Exceeded maximum of 10 experiments for agent comparison.",
            )

        try:
            req = ExperimentComparisonRequest(
                experiment_ids=experiment_ids,
                baseline_experiment_id=kwargs.get("baseline_experiment_id"),
                metrics=kwargs.get("metrics"),
                pareto_objectives=kwargs.get("pareto_objectives"),
                include_synthesis=kwargs.get("include_synthesis", False),
            )
            service = ExperimentComparisonService(context.db)
            resp = service.compare(context.project_id, req)
            return ToolResult(
                success=True,
                tool_name=self.name,
                result_summary=resp.export_markdown,
                data=resp.model_dump(),
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Experiment comparison failed: {str(e)}",
                error=str(e),
            )


class RunEvaluationTool(BaseTool):
    name = "run_evaluation"
    description = (
        "Execute an automated evaluation benchmark (retrieval, rag, or agent) across a dataset. "
        "Evaluates retrieval quality (Recall@K, MRR@K, nDCG@K), RAG faithfulness & citation support, "
        "or agent trajectory metrics and logs results to the experiment tracker."
    )
    args_schema = RunEvaluationArgs
    safety_tier = ToolSafetyTier.ANALYTICAL

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        from app.services.evaluation_service import EvaluationService
        eval_type = kwargs.get("eval_type")
        dataset_id = kwargs.get("dataset_id")
        name = kwargs.get("name")

        service = EvaluationService(context.db)

        try:
            if eval_type == "retrieval":
                req = RunRetrievalEvaluationRequest(
                    dataset_id=dataset_id,
                    name=name,
                    search_mode=kwargs.get("search_mode", "hybrid"),
                    rerank=kwargs.get("rerank", False),
                    k_values=kwargs.get("k_values", [1, 3, 5, 10]),
                    validated_only=kwargs.get("validated_only", True),
                    create_experiment=kwargs.get("create_experiment", True),
                )
                run = service.run_retrieval_evaluation(context.project_id, req)
            elif eval_type == "rag":
                req = RunRAGEvaluationRequest(
                    dataset_id=dataset_id,
                    name=name,
                    search_mode=kwargs.get("search_mode", "hybrid"),
                    rerank=kwargs.get("rerank", True),
                    top_k=kwargs.get("top_k", 5),
                    validated_only=kwargs.get("validated_only", True),
                    create_experiment=kwargs.get("create_experiment", True),
                )
                run = service.run_rag_evaluation(context.project_id, req)
            elif eval_type == "agent":
                req = RunAgentEvaluationRequest(
                    dataset_id=dataset_id,
                    name=name,
                    max_iterations=kwargs.get("max_iterations", 10),
                    validated_only=kwargs.get("validated_only", True),
                    create_experiment=kwargs.get("create_experiment", True),
                )
                run = service.run_agent_evaluation(context.project_id, req)
            else:
                return ToolResult(
                    success=False,
                    tool_name=self.name,
                    result_summary=f"Invalid eval_type: '{eval_type}'. Must be 'retrieval', 'rag', or 'agent'.",
                    error="Invalid eval_type",
                )

            summary_lines = [
                f"Evaluation Run {run.id} ('{run.name}') completed.",
                f"- Type: {run.eval_type}",
                f"- Status: {run.status}",
                f"- Items evaluated: {run.completed_items}/{run.total_items}",
                f"- Duration: {run.duration_ms:.1f}ms",
            ]
            if run.experiment_id:
                summary_lines.append(f"- Experiment ID: {run.experiment_id}")
            if run.summary_metrics:
                summary_lines.append("- Key Summary Metrics:")
                for k, v in list(run.summary_metrics.items())[:6]:
                    val_str = f"{v:.4f}" if isinstance(v, float) else str(v)
                    summary_lines.append(f"  * {k}: {val_str}")

            return ToolResult(
                success=True,
                tool_name=self.name,
                result_summary="\n".join(summary_lines),
                data={
                    "run_id": run.id,
                    "project_id": run.project_id,
                    "dataset_id": run.dataset_id,
                    "experiment_id": run.experiment_id,
                    "name": run.name,
                    "eval_type": run.eval_type,
                    "status": run.status,
                    "completed_items": run.completed_items,
                    "total_items": run.total_items,
                    "duration_ms": run.duration_ms,
                    "summary_metrics": run.summary_metrics,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Evaluation run failed: {str(e)}",
                error=str(e),
            )


class GetEvaluationResultsTool(BaseTool):
    name = "get_evaluation_results"
    description = (
        "Retrieve summary metrics, status, execution configuration, and optional item results "
        "for a specific evaluation run."
    )
    args_schema = GetEvaluationResultsArgs
    safety_tier = ToolSafetyTier.READ_ONLY

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        from app.services.evaluation_service import EvaluationService
        run_id = kwargs.get("run_id")
        include_items = kwargs.get("include_item_results", False)

        service = EvaluationService(context.db)
        try:
            run = service.get_run(context.project_id, run_id)
            lines = [
                f"### Evaluation Run {run.id}: {run.name}",
                f"- **Type:** {run.eval_type}",
                f"- **Status:** {run.status}",
                f"- **Items:** {run.completed_items}/{run.total_items}",
                f"- **Duration:** {run.duration_ms:.1f}ms",
            ]
            if run.experiment_id:
                lines.append(f"- **Linked Experiment:** {run.experiment_id}")
            if run.summary_metrics:
                lines.append("- **Summary Metrics:**")
                for k, v in run.summary_metrics.items():
                    val_str = f"{v:.4f}" if isinstance(v, float) else str(v)
                    lines.append(f"  - `{k}`: {val_str}")

            item_data = []
            if include_items:
                results = service.get_run_item_results(context.project_id, run_id, limit=20)
                lines.append(f"\n- **Sample Item Results (first {len(results)}):**")
                for r in results:
                    lines.append(f"  - Q: \"{r.query[:60]}...\" | Metrics: {r.metrics}")
                    item_data.append({
                        "id": r.id,
                        "query": r.query,
                        "metrics": r.metrics,
                        "duration_ms": r.duration_ms,
                    })

            return ToolResult(
                success=True,
                tool_name=self.name,
                result_summary="\n".join(lines),
                data={
                    "run_id": run.id,
                    "name": run.name,
                    "eval_type": run.eval_type,
                    "status": run.status,
                    "summary_metrics": run.summary_metrics,
                    "system_configuration": run.system_configuration,
                    "dataset_snapshot": run.dataset_snapshot,
                    "experiment_id": run.experiment_id,
                    "duration_ms": run.duration_ms,
                    "item_results": item_data if include_items else None,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool_name=self.name,
                result_summary=f"Failed to fetch evaluation results for run {run_id}: {str(e)}",
                error=str(e),
            )


