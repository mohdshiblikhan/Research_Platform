from typing import Optional

from sqlalchemy.orm import Session

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


class ProjectRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, project_id: int) -> Optional[Project]:
        """Fetch a single project by its primary key. Returns None if not found."""
        return self.db.get(Project, project_id)

    def list_all(self) -> list[Project]:
        """Return all projects ordered by newest first."""
        return self.db.query(Project).order_by(Project.created_at.desc()).all()

    def create(self, data: ProjectCreate) -> Project:
        """Insert a new project row and return the persisted object."""
        project = Project(
            title=data.title,
            description=data.description,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def update(self, project: Project, data: ProjectUpdate) -> Project:
        """Apply partial updates to a project. Only changes fields that are provided."""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(project, field, value)
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete(self, project: Project) -> None:
        """Delete a project row."""
        self.db.delete(project)
        self.db.commit()
