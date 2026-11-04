from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field, model_validator


# --- Metric Models ---

class MetricDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    UNKNOWN = "unknown"


class ComparisonMetricValue(BaseModel):
    """A single experiment's value for a specific metric."""
    experiment_id: int
    title: str
    raw_value: Any
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    baseline_delta: Optional[float] = None       # value - baseline_value
    percent_change: Optional[float] = None       # ((value - baseline) / |baseline|) * 100
    status: Literal[
        "improvement",
        "regression",
        "neutral",
        "unspecified",
        "baseline",
        "not_applicable",
        "incompatible_units",
    ] = "not_applicable"
    is_best: bool = False


class ComparisonMetricRow(BaseModel):
    """A row in the quantitative comparison matrix representing one metric."""
    metric_name: str                            # Canonical identity, e.g. "latency" or "recall@10"
    display_name: str                           # Display title, e.g. "Latency"
    direction: MetricDirection = MetricDirection.UNKNOWN
    canonical_unit: Optional[str] = None        # e.g. "ms", "%", None
    values: Dict[int, ComparisonMetricValue]    # experiment_id -> metric value
    best_experiment_ids: List[int] = Field(default_factory=list)  # Supports ties
    has_tie: bool = False
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    average_value: Optional[float] = None


# --- Configuration Models ---

class ConfigValuePresence(StrEnum):
    SET = "set"
    EXPLICIT_NULL = "explicit_null"
    MISSING = "missing"


class ComparisonConfigValue(BaseModel):
    """Configuration value with presence semantics."""
    presence: ConfigValuePresence
    value: Any = None


class ComparisonConfigRow(BaseModel):
    """A row comparing a specific parameter or variable across experiments."""
    category: Literal["parameter", "variable"]
    key: str
    values: Dict[int, ComparisonConfigValue]    # experiment_id -> config value
    is_varying: bool                            # True if values differ across compared runs


# --- Pareto Analysis Models ---

class ParetoObjectiveDirection(StrEnum):
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


class ParetoObjectiveConfig(BaseModel):
    """Specification of an objective for Pareto analysis."""
    metric: str
    direction: Optional[ParetoObjectiveDirection] = None  # Inferred if omitted, error if unknown


class ParetoPoint(BaseModel):
    """Representation of an experiment in 2D Pareto objective space."""
    experiment_id: int
    title: str
    objective_values: Dict[str, float]          # metric -> normalized numeric value
    is_pareto_optimal: bool
    dominated_by: List[int] = Field(default_factory=list)
    dominates: List[int] = Field(default_factory=list)


class ParetoExcludedExperiment(BaseModel):
    """Experiment excluded from Pareto analysis due to missing values or incompatible units."""
    experiment_id: int
    title: str
    reason: str


class ParetoAnalysis(BaseModel):
    """Algorithmic 2-objective Pareto trade-off analysis."""
    objective_x: ParetoObjectiveConfig
    objective_y: ParetoObjectiveConfig
    pareto_optimal_experiment_ids: List[int]
    points: List[ParetoPoint]
    excluded_experiments: List[ParetoExcludedExperiment] = Field(default_factory=list)
    trade_off_summary: str


# --- Hypothesis Consensus Models ---

class HypothesisConsensusState(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    MIXED = "mixed"
    INCONCLUSIVE = "inconclusive"
    INSUFFICIENT_DATA = "insufficient_data"


class HypothesisConsensusRow(BaseModel):
    """Empirical synthesis of recorded verdicts for a research hypothesis."""
    hypothesis_id: str                          # e.g. "H1"
    research_plan_id: Optional[int] = None       # Scopes hypothesis to specific research plan
    hypothesis_statement: Optional[str] = None
    statement_variants: List[str] = Field(default_factory=list)
    supporting_count: int = 0
    supporting_experiment_ids: List[int] = Field(default_factory=list)
    refuting_count: int = 0
    refuting_experiment_ids: List[int] = Field(default_factory=list)
    inconclusive_count: int = 0
    inconclusive_experiment_ids: List[int] = Field(default_factory=list)
    no_verdict_count: int = 0
    no_verdict_experiment_ids: List[int] = Field(default_factory=list)
    consensus: HypothesisConsensusState
    contributing_experiment_ids: List[int]


# --- LLM Synthesis Models ---

class ExperimentComparisonSynthesis(BaseModel):
    """Structured analytical synthesis produced by LLM."""
    key_performance_tradeoffs: str
    pareto_insights: str
    hypothesis_consistency: str
    anomalies_or_contradictions: Optional[str] = None
    recommended_next_steps: List[str] = Field(default_factory=list)
    executive_summary: str


# --- Available Metrics Catalog Model ---

class AvailableMetricItem(BaseModel):
    """Descriptor for an available metric in a project."""
    metric_name: str
    display_name: str
    experiment_count: int                       # Number of distinct experiments containing this metric
    direction: MetricDirection
    canonical_unit: Optional[str] = None


# --- API Request & Response Models ---

class ExperimentComparisonRequest(BaseModel):
    """Request payload for comparing experiments."""
    experiment_ids: List[int] = Field(
        ..., min_length=2, max_length=20, description="List of 2 to 20 experiment IDs to compare"
    )
    baseline_experiment_id: Optional[int] = Field(
        default=None, description="Experiment to treat as baseline for deltas (defaults to first ID)"
    )
    metrics: Optional[List[str]] = Field(
        default=None, description="Optional subset of metrics to focus on. If omitted, compares all available metrics."
    )
    pareto_objectives: Optional[Tuple[ParetoObjectiveConfig, ParetoObjectiveConfig]] = Field(
        default=None, description="Optional two distinct objectives for Pareto trade-off analysis"
    )
    include_synthesis: bool = Field(
        default=False, description="If True, calls LLM to generate structured analytical synthesis"
    )

    @model_validator(mode="after")
    def validate_request_invariants(self) -> "ExperimentComparisonRequest":
        # Reject duplicate experiment IDs (triggers 422)
        if len(self.experiment_ids) != len(set(self.experiment_ids)):
            raise ValueError("Duplicate experiment IDs provided in comparison request")
        return self


class ExperimentComparisonResponse(BaseModel):
    """Full empirical comparison response."""
    project_id: int
    experiments_compared: int
    experiment_summaries: List[Dict[str, Any]]  # id, title, status, plan_experiment_id
    baseline_experiment_id: int
    configuration_matrix: List[ComparisonConfigRow]
    metrics_matrix: List[ComparisonMetricRow]
    pareto_analysis: Optional[ParetoAnalysis] = None
    hypothesis_consensus: List[HypothesisConsensusRow]
    manual_hypothesis_experiment_ids: List[int] = Field(default_factory=list)  # Isolated manual runs
    unassigned_experiment_ids: List[int] = Field(default_factory=list)         # Lacking hypothesis_id
    synthesis: Optional[ExperimentComparisonSynthesis] = None
    synthesis_status: Literal["completed", "failed", "skipped"] = "skipped"
    synthesis_error: Optional[str] = None
    llm_model: Optional[str] = None
    synthesis_time_ms: Optional[float] = None
    export_markdown: str                        # Formatted GitHub-Flavored Markdown table
