from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class Project(Base):
    __tablename__ = "projects"

    title: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[Optional[str]] = mapped_column(nullable=True)
