from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.evaluation import EvaluationRun
    from app.models.project import Project
    from app.models.research_plan import ResearchPlan


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class ExperimentPriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class HypothesisVerdict(StrEnum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


class Experiment(Base):
    """Database model representing a planned or conducted scientific experiment."""

    __tablename__ = "experiments"

    # --- Foreign Keys ---
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    research_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("research_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # --- Identity & Descriptor ---
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plan_experiment_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g. "E1"

    # --- Lifecycle & Prioritization ---
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=ExperimentStatus.PLANNED.value, index=True
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExperimentPriority.MEDIUM.value
    )

    # --- Scientific Context (Hypothesis & Methodology) ---
    hypothesis_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g. "H1"
    hypothesis_statement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    methodology: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Flexible Specifications (JSONB) ---
    # Flexible dataset reference: list of names, structured dict, descriptor string, or null
    datasets: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True, default=None)

    # Flexible experimental variables or factors
    variables: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Parameters / Hyperparameters: e.g. {"top_k": 10, "retriever": "hybrid"}
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Target Metrics list (optional): e.g. ["Recall@10", "MRR"]
    target_metrics: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)

    # --- Empirical Results & Outcomes (JSONB) ---
    # Quantitative or domain-specific results: e.g. {"Recall@10": 0.84, "optimal_variant": "prompt_a"}
    results: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Qualitative findings: {"hypothesis_verdict": "supported", "summary": "...", "observations": [...]}
    findings: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Scientific Provenance: {"gap_ids": ["G1"], "document_ids": [1, 2], "notes": "..."}
    provenance: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # --- Lifecycle Metadata ---
    abandonment_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Relationships ---
    project: Mapped["Project"] = relationship(back_populates="experiments")
    research_plan: Mapped[Optional["ResearchPlan"]] = relationship(back_populates="experiments")
    evaluation_runs: Mapped[list["EvaluationRun"]] = relationship(back_populates="experiment")

    __table_args__ = (
        Index("ix_experiments_project_status", "project_id", "status"),
        UniqueConstraint("research_plan_id", "plan_experiment_id", name="uq_experiments_plan_experiment"),
    )

    @property
    def has_results(self) -> bool:
        """Check whether any results or findings have been recorded."""
        has_metrics = bool(self.results and len(self.results) > 0)
        has_findings = bool(self.findings and self.findings.get("summary"))
        return has_metrics or has_findings
