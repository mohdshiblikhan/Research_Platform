from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.experiment import ExperimentPriority, ExperimentStatus, HypothesisVerdict


# --- Sub-Schemas for Structured JSONB ---
class ExperimentFindings(BaseModel):
    """Structured qualitative findings and research conclusions."""

    hypothesis_verdict: Optional[HypothesisVerdict] = Field(
        default=None, description="Verdict regarding hypothesis"
    )
    summary: str = Field(
        ..., description="High-level narrative synthesis of observations/findings"
    )
    observations: list[str] = Field(
        default_factory=list, description="Granular empirical observations noticed during runs"
    )
    limitations: Optional[str] = Field(
        default=None, description="Known experimental or corpus limitations"
    )


class ExperimentProvenance(BaseModel):
    """Scientific provenance tracing experiment to literature and plans."""

    gap_ids: list[str] = Field(
        default_factory=list, description="Research gap IDs this experiment addresses"
    )
    document_ids: list[int] = Field(
        default_factory=list, description="Corpus document IDs providing motivating evidence"
    )
    external_urls: list[str] = Field(
        default_factory=list, description="Links to external code, datasets, or notebooks"
    )
    notes: Optional[str] = Field(default=None, description="Free-text research notes")


# --- API Request Models ---
class ExperimentCreate(BaseModel):
    """Payload for manual experiment creation across any lifecycle status."""

    title: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = None
    priority: ExperimentPriority = ExperimentPriority.MEDIUM
    status: ExperimentStatus = ExperimentStatus.PLANNED
    hypothesis_id: Optional[str] = None
    hypothesis_statement: Optional[str] = None
    methodology: str = Field(..., min_length=5)
    datasets: Optional[Any] = None
    variables: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    target_metrics: List[str] = Field(default_factory=list)
    results: Dict[str, Any] = Field(default_factory=dict)
    findings: Optional[ExperimentFindings] = None
    provenance: Optional[ExperimentProvenance] = None
    abandonment_reason: Optional[str] = None
    research_plan_id: Optional[int] = None
    plan_experiment_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_create_invariants(self) -> "ExperimentCreate":
        if self.plan_experiment_id and not self.research_plan_id:
            raise ValueError("Cannot specify plan_experiment_id without a research_plan_id.")

        if self.status == ExperimentStatus.COMPLETED:
            has_results = bool(self.results and len(self.results) > 0)
            has_findings = bool(self.findings and self.findings.summary.strip())
            if not has_results and not has_findings:
                raise ValueError(
                    "To create an experiment as completed, provide either non-empty results or qualitative findings with a summary."
                )
        if self.status == ExperimentStatus.ABANDONED:
            if not self.abandonment_reason or not self.abandonment_reason.strip():
                raise ValueError(
                    "An abandonment reason is required when creating an experiment as abandoned."
                )
        return self


class ExperimentUpdate(BaseModel):
    """Payload for updating experiment specifications or status."""

    title: Optional[str] = Field(default=None, min_length=3, max_length=255)
    description: Optional[str] = None
    priority: Optional[ExperimentPriority] = None
    status: Optional[ExperimentStatus] = None
    methodology: Optional[str] = None
    datasets: Optional[Any] = None
    variables: Optional[Dict[str, Any]] = None
    parameters: Optional[Dict[str, Any]] = None
    target_metrics: Optional[List[str]] = None
    abandonment_reason: Optional[str] = None


class ExperimentLogResultsRequest(BaseModel):
    """Payload for logging empirical results and/or qualitative findings."""

    results: Optional[Dict[str, Any]] = Field(
        default=None, description="Quantitative or qualitative metric/outcome results"
    )
    findings: Optional[ExperimentFindings] = Field(
        default=None, description="Qualitative findings and hypothesis verdict"
    )
    provenance_notes: Optional[str] = Field(
        default=None, description="Additional notes or references"
    )
    mark_completed: bool = Field(
        default=True, description="Whether to transition status to 'completed'"
    )

    @model_validator(mode="after")
    def validate_meaningful_update(self) -> "ExperimentLogResultsRequest":
        has_results = self.results is not None and len(self.results) > 0
        has_findings = self.findings is not None and bool(self.findings.summary.strip())
        has_notes = self.provenance_notes is not None and bool(self.provenance_notes.strip())

        if not has_results and not has_findings and not has_notes:
            raise ValueError("The request must contain results, findings, or provenance notes.")

        if self.mark_completed and not has_results and not has_findings:
            raise ValueError(
                "To complete an experiment, provide either non-empty results or qualitative findings with a summary."
            )
        return self


class ExperimentPromoteRequest(BaseModel):
    """Options when promoting experiments from a research plan."""

    plan_experiment_ids: Optional[List[str]] = Field(
        default=None,
        description="List of proposed experiment IDs (e.g. ['E1']) to promote. If omitted or empty, promotes all.",
    )


# --- API Response Models ---
class ExperimentRead(BaseModel):
    """Full detailed experiment response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    research_plan_id: Optional[int] = None
    plan_experiment_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: ExperimentStatus
    priority: ExperimentPriority
    hypothesis_id: Optional[str] = None
    hypothesis_statement: Optional[str] = None
    methodology: str
    datasets: Optional[Any] = None
    variables: Dict[str, Any]
    parameters: Dict[str, Any]
    target_metrics: List[str]
    results: Dict[str, Any]
    findings: Dict[str, Any]
    provenance: Dict[str, Any]
    abandonment_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class ExperimentSummary(BaseModel):
    """Lightweight summary schema for experiment lists."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    research_plan_id: Optional[int] = None
    plan_experiment_id: Optional[str] = None
    title: str
    status: ExperimentStatus
    priority: ExperimentPriority
    hypothesis_id: Optional[str] = None
    target_metrics: List[str]
    has_results: bool
    created_at: datetime
    completed_at: Optional[datetime] = None


class ExperimentBatchPromotionResponse(BaseModel):
    """Response returned when promoting experiments from a research plan."""

    plan_id: int
    total_proposed: int
    promoted_count: int
    already_promoted_count: int
    experiments: List[ExperimentRead]
