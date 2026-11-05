from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.experiment import Experiment
    from app.models.project import Project


class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    eval_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "retrieval", "rag", "agent", "composite"
    extra_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="evaluation_datasets")
    items: Mapped[list["EvaluationDatasetItem"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )
    # Deleting dataset does NOT delete historical runs:
    runs: Mapped[list["EvaluationRun"]] = relationship(back_populates="dataset")

    @property
    def item_count(self) -> int:
        return len(self.items) if self.items is not None else 0


class EvaluationDatasetItem(Base):
    __tablename__ = "evaluation_dataset_items"

    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    ground_truth_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expected_chunk_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    expected_tools: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    question_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    is_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    item_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # Relationships
    dataset: Mapped["EvaluationDataset"] = relationship(back_populates="items")
    # Deleting item does NOT delete historical item results:
    item_results: Mapped[list["EvaluationItemResult"]] = relationship(back_populates="dataset_item")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL preserves run even if dataset is deleted:
    dataset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    experiment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    eval_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "retrieval", "rag", "agent"
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="running", index=True)

    # Provenance snapshots: evaluated_system vs judge_configuration
    system_configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dataset_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    summary_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="evaluation_runs")
    dataset: Mapped[Optional["EvaluationDataset"]] = relationship(back_populates="runs")
    experiment: Mapped[Optional["Experiment"]] = relationship(back_populates="evaluation_runs")
    item_results: Mapped[list["EvaluationItemResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EvaluationItemResult(Base):
    __tablename__ = "evaluation_item_results"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL preserves item result even if original dataset item is deleted:
    dataset_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("evaluation_dataset_items.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Immutable item snapshot at run time
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_chunk_ids_snapshot: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    expected_tools_snapshot: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    ground_truth_answer_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Actual output snapshot with full retrieved chunk text
    actual_output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    run: Mapped["EvaluationRun"] = relationship(back_populates="item_results")
    dataset_item: Mapped[Optional["EvaluationDatasetItem"]] = relationship(back_populates="item_results")
