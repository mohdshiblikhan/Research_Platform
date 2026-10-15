from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.document import Document


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    
    research_problem: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    methodology: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    models_used: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    datasets: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evaluation_metrics: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    results: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    limitations: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    baselines: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    raw_llm_output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    document: Mapped["Document"] = relationship(back_populates="extraction")
