from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.project import Project


class ResearchPlan(Base):
    __tablename__ = "research_plans"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Input research question
    research_question: Mapped[str] = mapped_column(Text, nullable=False)

    # Exact document IDs analyzed for this plan
    document_ids_used: Mapped[List[int]] = mapped_column(JSONB, nullable=False)

    # Full structured plan output (reasoning, gaps, hypotheses, experiments, etc.)
    plan_output: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Execution metadata
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    planning_time_ms: Mapped[float] = mapped_column(Float, nullable=False)
    documents_analyzed: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="research_plans")
