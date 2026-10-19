from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.research_plan import ResearchPlan


class ResearchPlanRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        project_id: int,
        research_question: str,
        document_ids_used: List[int],
        plan_output: Dict[str, Any],
        llm_model: str,
        planning_time_ms: float,
        documents_analyzed: int,
    ) -> ResearchPlan:
        """Create and persist a new research plan."""
        plan = ResearchPlan(
            project_id=project_id,
            research_question=research_question,
            document_ids_used=document_ids_used,
            plan_output=plan_output,
            llm_model=llm_model,
            planning_time_ms=planning_time_ms,
            documents_analyzed=documents_analyzed,
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        return plan

    def get_by_id(self, plan_id: int) -> Optional[ResearchPlan]:
        """Fetch a single research plan by primary key."""
        stmt = select(ResearchPlan).where(ResearchPlan.id == plan_id)
        result = self.db.execute(stmt)
        return result.scalars().first()

    def list_by_project(self, project_id: int) -> List[ResearchPlan]:
        """List all research plans for a project, newest first."""
        stmt = (
            select(ResearchPlan)
            .where(ResearchPlan.project_id == project_id)
            .order_by(ResearchPlan.created_at.desc())
        )
        result = self.db.execute(stmt)
        return list(result.scalars().all())

    def delete(self, plan_id: int) -> bool:
        """Delete a plan by ID. Returns True if deleted, False if not found."""
        plan = self.get_by_id(plan_id)
        if not plan:
            return False
        self.db.delete(plan)
        self.db.commit()
        return True
