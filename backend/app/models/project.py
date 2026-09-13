from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base

if TYPE_CHECKING:
    from app.models.document import Document


class Project(Base):
    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
