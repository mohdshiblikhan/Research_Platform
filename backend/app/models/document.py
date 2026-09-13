import enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.project import Project


class DocumentStatus(str, enum.Enum):
    """Processing status of a document.

    Lifecycle: uploaded → processing → processed / failed
    - uploaded:   File saved to disk, no text extraction done yet.
    - processing: Text extraction in progress (Milestone 3).
    - processed:  Text extraction complete (Milestone 3).
    - failed:     Processing failed (Milestone 3).
    """

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(nullable=False)
    file_path: Mapped[str] = mapped_column(nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False)
    mime_type: Mapped[str] = mapped_column(nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=DocumentStatus.UPLOADED.value
    )

    project: Mapped["Project"] = relationship(back_populates="documents")
