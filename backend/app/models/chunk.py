from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base


class Chunk(Base):
    """A text chunk extracted from a document during processing.

    Each chunk preserves provenance — the ability to trace the text
    back to the exact source page(s) and character offsets in the
    original document.

    Lifecycle:
        - Created during document processing (Milestone 3).
        - Deleted when the parent document is deleted (CASCADE).
    """

    __tablename__ = "chunks"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    chunk_index: Mapped[int] = mapped_column(nullable=False)
    """Position of this chunk within the document (0-based, sequential)."""

    content: Mapped[str] = mapped_column(Text, nullable=False)
    """The actual text content of this chunk."""

    page_start: Mapped[int] = mapped_column(nullable=False)
    """First page this chunk contains text from (1-based)."""

    page_end: Mapped[int] = mapped_column(nullable=False)
    """Last page this chunk contains text from (1-based)."""

    char_offset_start: Mapped[int] = mapped_column(nullable=False)
    """Start character offset in the full concatenated document text."""

    char_offset_end: Mapped[int] = mapped_column(nullable=False)
    """End character offset in the full concatenated document text."""

    chunk_size: Mapped[int] = mapped_column(nullable=False)
    """Length of the content field in characters."""
