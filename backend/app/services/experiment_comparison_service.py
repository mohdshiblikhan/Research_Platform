import json
import logging
import time
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.experiment import Experiment
from app.repositories.experiment_repository import ExperimentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.experiment_comparison import (
    AvailableMetricItem,
    ExperimentComparisonRequest,
    ExperimentComparisonResponse,
    ExperimentComparisonSynthesis,
    MetricDirection,
)
from app.services.experiment_comparison_engine import (
    METRIC_REGISTRY,
    build_configuration_matrix,
    build_metrics_matrix,
    compute_hypothesis_consensus,
    compute_pareto_frontier,
    generate_markdown_report,
    resolve_metric_identity,
)
from app.prompts.experiment_comparison_prompts import (
    EXPERIMENT_COMPARISON_SYSTEM_PROMPT,
    build_experiment_comparison_prompt,
)
from app.services.llm_service import LLMService
from app.services.llm_service_factory import get_llm_service

logger = logging.getLogger(__name__)


class ExperimentComparisonService:
    """Service orchestrating empirical experiment comparison, delta calculation, and synthesis."""

    def __init__(self, db: Session, llm_service: Optional[LLMService] = None):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.exp_repo = ExperimentRepository(db)
        self.llm_service = llm_service or get_llm_service()

    def _ensure_project_exists(self, project_id: int) -> None:
        """Validate project existence or raise FileNotFoundError."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")

    def compare(
        self,
        project_id: int,
        request: ExperimentComparisonRequest,
    ) -> ExperimentComparisonResponse:
        """Perform full multi-experiment comparison with baseline deltas and optional synthesis."""
        # 1. Validate project exists
        self._ensure_project_exists(project_id)

        # 2. Validate baseline membership (Service layer responsibility -> HTTP 400)
        baseline_id = request.baseline_experiment_id or request.experiment_ids[0]
        if baseline_id not in request.experiment_ids:
            raise ValueError(
                f"Baseline experiment {baseline_id} must be one of the compared experiments"
            )

        # 3. Fetch and validate experiments belonging to project (Service layer -> HTTP 404)
        experiments: List[Experiment] = []
        for exp_id in request.experiment_ids:
            exp = self.exp_repo.get_by_id(exp_id, project_id=project_id)
            if not exp:
                raise FileNotFoundError(
                    f"Experiment {exp_id} not found in project {project_id}"
                )
            experiments.append(exp)

        # 4. Tier 1: Deterministic Engine Execution
        config_rows = build_configuration_matrix(experiments)
        metric_rows = build_metrics_matrix(
            experiments=experiments,
            baseline_id=baseline_id,
            focus_metrics=request.metrics,
        )

        # Pareto Frontier Analysis (if requested)
        pareto_analysis = None
        if request.pareto_objectives:
            # compute_pareto_frontier raises ValueError on duplicate canonical metrics,
            # unknown directions, or zero eligible experiments (caught as HTTP 400).
            pareto_analysis = compute_pareto_frontier(
                experiments=experiments,
                objective_x=request.pareto_objectives[0],
                objective_y=request.pareto_objectives[1],
            )

        # Hypothesis Consensus Aggregation
        consensus_rows, manual_hyp_ids, unassigned_ids = compute_hypothesis_consensus(experiments)

        # Markdown Export Table
        markdown_table = generate_markdown_report(
            experiments=experiments,
            baseline_id=baseline_id,
            config_rows=config_rows,
            metric_rows=metric_rows,
            pareto=pareto_analysis,
            consensus=consensus_rows,
            manual_hyp_ids=manual_hyp_ids,
            unassigned_ids=unassigned_ids,
        )

        # 5. Tier 2: Optional LLM Synthesis Layer
        synthesis: Optional[ExperimentComparisonSynthesis] = None
        synthesis_status: str = "skipped"
        synthesis_error: Optional[str] = None
        llm_model: Optional[str] = None
        synthesis_time_ms: Optional[float] = None

        if request.include_synthesis:
            start_time = time.perf_counter()
            llm_model = self.llm_service.get_model_name()
            try:
                # Prepare structured context for LLM
                exp_summaries_for_prompt = [
                    {
                        "id": e.id,
                        "title": e.title,
                        "status": e.status,
                        "plan_experiment_id": e.plan_experiment_id,
                        "hypothesis_id": e.hypothesis_id,
                    }
                    for e in experiments
                ]
                varying_configs_for_prompt = [
                    {
                        "category": r.category,
                        "key": r.key,
                        "values": {str(k): v.value for k, v in r.values.items()},
                    }
                    for r in config_rows
                    if r.is_varying
                ]
                metrics_summary_for_prompt = [
                    {
                        "metric": r.metric_name,
                        "unit": r.canonical_unit,
                        "direction": r.direction.value,
                        "best_experiments": r.best_experiment_ids,
                        "values": {
                            str(k): {
                                "value": v.numeric_value,
                                "delta": v.baseline_delta,
                                "status": v.status,
                            }
                            for k, v in r.values.items()
                        },
                    }
                    for r in metric_rows
                ]
                pareto_for_prompt = (
                    {
                        "objective_x": pareto_analysis.objective_x.model_dump(),
                        "objective_y": pareto_analysis.objective_y.model_dump(),
                        "optimal_experiment_ids": pareto_analysis.pareto_optimal_experiment_ids,
                        "trade_off_summary": pareto_analysis.trade_off_summary,
                    }
                    if pareto_analysis
                    else None
                )
                consensus_for_prompt = [
                    {
                        "hypothesis_id": c.hypothesis_id,
                        "statement": c.hypothesis_statement,
                        "consensus": c.consensus.value,
                        "supporting_runs": c.supporting_experiment_ids,
                        "refuting_runs": c.refuting_experiment_ids,
                    }
                    for c in consensus_rows
                ]

                user_prompt = build_experiment_comparison_prompt(
                    experiments_data=exp_summaries_for_prompt,
                    varying_configurations=varying_configs_for_prompt,
                    metrics_summary=metrics_summary_for_prompt,
                    pareto_data=pareto_for_prompt,
                    hypothesis_consensus=consensus_for_prompt,
                )

                llm_response = self.llm_service.generate(
                    system_prompt=EXPERIMENT_COMPARISON_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.1,
                    json_mode=True,
                )
                parsed_json = json.loads(llm_response.content)
                synthesis = ExperimentComparisonSynthesis.model_validate(parsed_json)
                synthesis_status = "completed"
            except Exception as e:
                logger.error(f"Failed to generate LLM experiment comparison synthesis: {e}", exc_info=True)
                synthesis_status = "failed"
                synthesis_error = str(e)
            finally:
                synthesis_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # 6. Assemble Full Response
        experiment_summaries = [
            {
                "id": e.id,
                "title": e.title,
                "status": e.status,
                "plan_experiment_id": e.plan_experiment_id,
                "hypothesis_id": e.hypothesis_id,
            }
            for e in experiments
        ]

        return ExperimentComparisonResponse(
            project_id=project_id,
            experiments_compared=len(experiments),
            experiment_summaries=experiment_summaries,
            baseline_experiment_id=baseline_id,
            configuration_matrix=config_rows,
            metrics_matrix=metric_rows,
            pareto_analysis=pareto_analysis,
            hypothesis_consensus=consensus_rows,
            manual_hypothesis_experiment_ids=manual_hyp_ids,
            unassigned_experiment_ids=unassigned_ids,
            synthesis=synthesis,
            synthesis_status=synthesis_status,  # type: ignore[arg-type]
            synthesis_error=synthesis_error,
            llm_model=llm_model,
            synthesis_time_ms=synthesis_time_ms,
            export_markdown=markdown_table,
        )

    def get_available_metrics(self, project_id: int) -> List[AvailableMetricItem]:
        """Discover all unique metrics recorded across project experiments."""
        self._ensure_project_exists(project_id)

        experiments = self.exp_repo.list_by_project(project_id, limit=500)
        metric_exp_counts: Dict[str, Set[int]] = {}

        for exp in experiments:
            results = getattr(exp, "results", {}) or {}
            for raw_k in results.keys():
                canonical_name, _ = resolve_metric_identity(raw_k)
                if canonical_name not in metric_exp_counts:
                    metric_exp_counts[canonical_name] = set()
                metric_exp_counts[canonical_name].add(exp.id)

        items: List[AvailableMetricItem] = []
        for c_name in sorted(metric_exp_counts.keys()):
            metric_def = METRIC_REGISTRY.get(c_name)
            direction = metric_def.direction if metric_def else MetricDirection.UNKNOWN
            display_name = metric_def.display_name if metric_def else c_name.replace("_", " ").title()
            canonical_unit = metric_def.canonical_unit if metric_def else None

            items.append(
                AvailableMetricItem(
                    metric_name=c_name,
                    display_name=display_name,
                    experiment_count=len(metric_exp_counts[c_name]),
                    direction=direction,
                    canonical_unit=canonical_unit,
                )
            )

        return items
