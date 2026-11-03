from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.experiment import (
    Experiment,
    ExperimentPriority,
    ExperimentStatus,
)
from app.repositories.document_repository import DocumentRepository
from app.repositories.experiment_repository import ExperimentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.research_plan_repository import ResearchPlanRepository
from app.schemas.experiment import (
    ExperimentBatchPromotionResponse,
    ExperimentCreate,
    ExperimentLogResultsRequest,
    ExperimentPromoteRequest,
    ExperimentUpdate,
)


class ExperimentService:
    """Service orchestrating experiment planning, promotion, tracking, and results logging."""

    def __init__(self, db: Session):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.doc_repo = DocumentRepository(db)
        self.plan_repo = ResearchPlanRepository(db)
        self.exp_repo = ExperimentRepository(db)

    def _ensure_project_exists(self, project_id: int) -> None:
        """Validate that project exists or raise FileNotFoundError."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise FileNotFoundError(f"Project {project_id} not found")

    def promote_from_plan(
        self, project_id: int, plan_id: int, request: ExperimentPromoteRequest
    ) -> ExperimentBatchPromotionResponse:
        """Promote proposed experiments from a ResearchPlan into tracked Experiment records."""
        self._ensure_project_exists(project_id)

        plan = self.plan_repo.get_by_id(plan_id)
        if not plan or plan.project_id != project_id:
            raise FileNotFoundError(f"Research plan {plan_id} not found in project {project_id}")

        plan_output = plan.plan_output or {}
        proposed_exps = plan_output.get("experiments", [])
        if not proposed_exps:
            return ExperimentBatchPromotionResponse(
                plan_id=plan_id,
                total_proposed=0,
                promoted_count=0,
                already_promoted_count=0,
                experiments=[],
            )

        # Validate requested experiment IDs if provided
        if request.plan_experiment_ids:
            available_ids = {e.get("id") for e in proposed_exps}
            for req_id in request.plan_experiment_ids:
                if req_id not in available_ids:
                    raise ValueError(
                        f"Proposed experiment '{req_id}' not found in research plan {plan_id}"
                    )
            proposed_exps = [e for e in proposed_exps if e.get("id") in request.plan_experiment_ids]

        hypotheses = {h.get("id"): h for h in plan_output.get("hypotheses", [])}
        gaps = {g.get("id"): g for g in plan_output.get("gaps", [])}

        promoted_count = 0
        already_promoted_count = 0
        promoted_experiments: List[Experiment] = []

        for exp_data in proposed_exps:
            plan_exp_id = exp_data.get("id")
            existing = self.exp_repo.get_by_plan_and_exp_id(plan_id, plan_exp_id)
            if existing:
                already_promoted_count += 1
                promoted_experiments.append(existing)
                continue

            hyp_id = exp_data.get("hypothesis")
            hyp = hypotheses.get(hyp_id, {})
            hyp_statement = hyp.get("statement")
            gap_ids = hyp.get("addresses_gaps", [])

            # Collect source document IDs from linked gaps
            doc_ids: List[int] = []
            for g_id in gap_ids:
                gap_docs = gaps.get(g_id, {}).get("source_documents", [])
                doc_ids.extend(gap_docs)
            deduped_doc_ids = sorted(list(set(doc_ids)))

            new_experiment = Experiment(
                project_id=project_id,
                research_plan_id=plan_id,
                plan_experiment_id=plan_exp_id,
                title=exp_data.get("title", f"Experiment {plan_exp_id}"),
                status=ExperimentStatus.PLANNED.value,
                priority=exp_data.get("priority", ExperimentPriority.MEDIUM.value),
                hypothesis_id=hyp_id,
                hypothesis_statement=hyp_statement,
                methodology=exp_data.get("method", ""),
                datasets=exp_data.get("datasets"),
                target_metrics=exp_data.get("metrics", []),
                provenance={"gap_ids": gap_ids, "document_ids": deduped_doc_ids},
            )

            try:
                saved = self.exp_repo.create(new_experiment)
                promoted_count += 1
                promoted_experiments.append(saved)
            except IntegrityError:
                self.db.rollback()
                existing = self.exp_repo.get_by_plan_and_exp_id(plan_id, plan_exp_id)
                if existing:
                    already_promoted_count += 1
                    promoted_experiments.append(existing)

        return ExperimentBatchPromotionResponse(
            plan_id=plan_id,
            total_proposed=len(proposed_exps),
            promoted_count=promoted_count,
            already_promoted_count=already_promoted_count,
            experiments=promoted_experiments,
        )

    def create_manual_experiment(
        self, project_id: int, request: ExperimentCreate
    ) -> Experiment:
        """Create a new experiment manually across any valid lifecycle status."""
        self._ensure_project_exists(project_id)

        # Invariant: plan_experiment_id requires a valid research_plan_id
        if request.plan_experiment_id and not request.research_plan_id:
            raise ValueError("Cannot specify plan_experiment_id without a research_plan_id")

        # Validate research plan references if plan_id is provided
        if request.research_plan_id is not None:
            plan = self.plan_repo.get_by_id(request.research_plan_id)
            if not plan or plan.project_id != project_id:
                raise FileNotFoundError(
                    f"Research plan {request.research_plan_id} not found in project {project_id}"
                )
            plan_output = plan.plan_output or {}

            if request.plan_experiment_id:
                proposed_ids = {e.get("id") for e in plan_output.get("experiments", [])}
                if request.plan_experiment_id not in proposed_ids:
                    raise ValueError(
                        f"Proposed experiment '{request.plan_experiment_id}' not found in research plan {request.research_plan_id}"
                    )
                existing = self.exp_repo.get_by_plan_and_exp_id(
                    request.research_plan_id, request.plan_experiment_id
                )
                if existing:
                    raise ValueError(
                        f"Experiment already exists for plan {request.research_plan_id} and ID '{request.plan_experiment_id}'"
                    )

            if request.hypothesis_id:
                plan_hypotheses = {h.get("id") for h in plan_output.get("hypotheses", [])}
                if request.hypothesis_id not in plan_hypotheses:
                    raise ValueError(
                        f"Hypothesis '{request.hypothesis_id}' not found in research plan {request.research_plan_id}"
                    )

            if request.provenance and request.provenance.gap_ids:
                plan_gaps = {g.get("id") for g in plan_output.get("gaps", [])}
                for g_id in request.provenance.gap_ids:
                    if g_id not in plan_gaps:
                        raise ValueError(
                            f"Gap '{g_id}' not found in research plan {request.research_plan_id}"
                        )

        # Validate document IDs against project
        if request.provenance and request.provenance.document_ids:
            proj_docs = {d.id for d in self.doc_repo.list_by_project(project_id)}
            for doc_id in request.provenance.document_ids:
                if doc_id not in proj_docs:
                    raise ValueError(f"Document {doc_id} does not belong to project {project_id}")

        completed_at = (
            datetime.now(timezone.utc)
            if request.status == ExperimentStatus.COMPLETED
            else None
        )

        provenance_dict = (
            request.provenance.model_dump()
            if request.provenance
            else {}
        )
        findings_dict = (
            request.findings.model_dump()
            if request.findings
            else {}
        )

        experiment = Experiment(
            project_id=project_id,
            research_plan_id=request.research_plan_id,
            plan_experiment_id=request.plan_experiment_id,
            title=request.title,
            description=request.description,
            status=request.status.value,
            priority=request.priority.value,
            hypothesis_id=request.hypothesis_id,
            hypothesis_statement=request.hypothesis_statement,
            methodology=request.methodology,
            datasets=request.datasets,
            variables=request.variables,
            parameters=request.parameters,
            target_metrics=request.target_metrics,
            results=request.results,
            findings=findings_dict,
            provenance=provenance_dict,
            abandonment_reason=request.abandonment_reason,
            completed_at=completed_at,
        )

        return self.exp_repo.create(experiment)

    def get_experiment(self, project_id: int, experiment_id: int) -> Experiment:
        """Fetch an experiment by ID within a project or raise FileNotFoundError."""
        self._ensure_project_exists(project_id)
        experiment = self.exp_repo.get_by_id(experiment_id, project_id=project_id)
        if not experiment:
            raise FileNotFoundError(
                f"Experiment {experiment_id} not found in project {project_id}"
            )
        return experiment

    def list_experiments(
        self,
        project_id: int,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        plan_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Experiment]:
        """List experiments for a project with optional filters and pagination."""
        self._ensure_project_exists(project_id)
        return self.exp_repo.list_by_project(
            project_id=project_id,
            status=status,
            priority=priority,
            research_plan_id=plan_id,
            limit=limit,
            offset=offset,
        )

    def update_experiment(
        self, project_id: int, experiment_id: int, request: ExperimentUpdate
    ) -> Experiment:
        """Partially update an experiment, enforcing lifecycle transition invariants."""
        experiment = self.get_experiment(project_id, experiment_id)

        if request.status is not None:
            curr_status = experiment.status
            new_status = request.status.value

            if curr_status != new_status:
                # Transition validation
                if new_status == ExperimentStatus.COMPLETED.value:
                    if curr_status not in (
                        ExperimentStatus.PLAN_PLANNED if hasattr(ExperimentStatus, "PLAN_PLANNED") else ExperimentStatus.PLANNED.value,
                        ExperimentStatus.IN_PROGRESS.value,
                    ):
                        raise ValueError(
                            f"Cannot complete experiment from '{curr_status}' status. It must be planned or in_progress."
                        )
                    has_outcome = bool(
                        (experiment.results and len(experiment.results) > 0)
                        or (experiment.findings and experiment.findings.get("summary"))
                    )
                    if not has_outcome:
                        raise ValueError(
                            "To complete an experiment, provide either non-empty results or qualitative findings with a summary."
                        )
                    experiment.completed_at = datetime.now(timezone.utc)

                elif new_status == ExperimentStatus.ABANDONED.value:
                    reason = request.abandonment_reason or experiment.abandonment_reason
                    if not reason or not reason.strip():
                        raise ValueError(
                            "An abandonment reason is required to abandon an experiment."
                        )

                elif curr_status == ExperimentStatus.COMPLETED.value:
                    # Reopening from completed
                    if new_status in (
                        ExperimentStatus.IN_PROGRESS.value,
                        ExperimentStatus.PLANNED.value,
                    ):
                        experiment.completed_at = None
                    else:
                        raise ValueError(
                            f"Cannot transition experiment from 'completed' to '{new_status}'."
                        )

                elif curr_status == ExperimentStatus.ABANDONED.value:
                    # Reopening from abandoned
                    if new_status in (
                        ExperimentStatus.PLANNED.value,
                        ExperimentStatus.IN_PROGRESS.value,
                    ):
                        experiment.abandonment_reason = None
                    else:
                        raise ValueError(
                            f"Cannot transition experiment from 'abandoned' to '{new_status}'."
                        )

                elif curr_status == ExperimentStatus.DRAFT.value:
                    if new_status not in (
                        ExperimentStatus.PLANNED.value,
                        ExperimentStatus.ABANDONED.value,
                    ):
                        raise ValueError(
                            f"Cannot transition experiment from 'draft' to '{new_status}'."
                        )

                experiment.status = new_status

        # Update remaining non-status fields if supplied
        if request.title is not None:
            experiment.title = request.title
        if request.description is not None:
            experiment.description = request.description
        if request.priority is not None:
            experiment.priority = request.priority.value
        if request.methodology is not None:
            experiment.methodology = request.methodology
        if request.datasets is not None:
            experiment.datasets = request.datasets
        if request.variables is not None:
            experiment.variables = request.variables
        if request.parameters is not None:
            experiment.parameters = request.parameters
        if request.target_metrics is not None:
            experiment.target_metrics = request.target_metrics
        if request.abandonment_reason is not None:
            experiment.abandonment_reason = request.abandonment_reason

        return self.exp_repo.update(experiment)

    def log_results(
        self, project_id: int, experiment_id: int, request: ExperimentLogResultsRequest
    ) -> Experiment:
        """Record empirical metric results and/or qualitative findings with selective replacement."""
        experiment = self.get_experiment(project_id, experiment_id)

        # Selective field update: replace only non-None supplied values
        if request.results is not None:
            experiment.results = request.results
        if request.findings is not None:
            experiment.findings = request.findings.model_dump()
        if request.provenance_notes is not None:
            prov = dict(experiment.provenance or {})
            prov["notes"] = request.provenance_notes
            experiment.provenance = prov

        if request.mark_completed:
            if experiment.status in (
                ExperimentStatus.DRAFT.value,
                ExperimentStatus.ABANDONED.value,
            ):
                raise ValueError(
                    f"Cannot complete experiment from '{experiment.status}' status. It must be planned or in_progress."
                )

            has_outcome = bool(
                (experiment.results and len(experiment.results) > 0)
                or (experiment.findings and experiment.findings.get("summary"))
            )
            if not has_outcome:
                raise ValueError(
                    "To complete an experiment, provide either non-empty results or qualitative findings with a summary."
                )

            experiment.status = ExperimentStatus.COMPLETED.value
            experiment.completed_at = datetime.now(timezone.utc)

        return self.exp_repo.update(experiment)

    def delete_experiment(self, project_id: int, experiment_id: int) -> None:
        """Delete an experiment entity."""
        experiment = self.get_experiment(project_id, experiment_id)
        self.exp_repo.delete(experiment)
