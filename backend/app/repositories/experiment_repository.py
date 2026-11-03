from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.experiment import Experiment


class ExperimentRepository:
    """Repository handling database operations for Experiment entities."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, experiment: Experiment) -> Experiment:
        """Persist a new experiment."""
        self.db.add(experiment)
        self.db.commit()
        self.db.refresh(experiment)
        return experiment

    def get_by_id(
        self, experiment_id: int, project_id: Optional[int] = None
    ) -> Optional[Experiment]:
        """Fetch a single experiment by ID, optionally validating project ownership."""
        stmt = select(Experiment).where(Experiment.id == experiment_id)
        if project_id is not None:
            stmt = stmt.where(Experiment.project_id == project_id)
        return self.db.execute(stmt).scalars().first()

    def get_by_plan_and_exp_id(
        self, research_plan_id: int, plan_experiment_id: str
    ) -> Optional[Experiment]:
        """Fetch an experiment promoted from a specific research plan."""
        stmt = select(Experiment).where(
            Experiment.research_plan_id == research_plan_id,
            Experiment.plan_experiment_id == plan_experiment_id,
        )
        return self.db.execute(stmt).scalars().first()

    def list_by_project(
        self,
        project_id: int,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        research_plan_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Experiment]:
        """List experiments for a project with optional filters and pagination."""
        stmt = select(Experiment).where(Experiment.project_id == project_id)
        if status:
            stmt = stmt.where(Experiment.status == status)
        if priority:
            stmt = stmt.where(Experiment.priority == priority)
        if research_plan_id is not None:
            stmt = stmt.where(Experiment.research_plan_id == research_plan_id)
        stmt = stmt.order_by(Experiment.created_at.desc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def update(self, experiment: Experiment) -> Experiment:
        """Update and commit changes to an existing experiment."""
        self.db.add(experiment)
        self.db.commit()
        self.db.refresh(experiment)
        return experiment

    def delete(self, experiment: Experiment) -> None:
        """Delete an experiment entity."""
        self.db.delete(experiment)
        self.db.commit()
