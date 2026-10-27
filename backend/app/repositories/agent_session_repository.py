from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_session import AgentSession


class AgentSessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        project_id: int,
        research_question: str,
        model_used: str = "",
    ) -> AgentSession:
        """Create and persist a new agent research session in 'running' status."""
        session = AgentSession(
            project_id=project_id,
            research_question=research_question,
            status="running",
            trajectory=[],
            citations=[],
            model_used=model_used,
            total_iterations=0,
            total_tool_calls=0,
            total_tokens_used=0,
            total_time_ms=0.0,
            stop_reason="",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def checkpoint_trajectory(
        self,
        session_id: int,
        trajectory: list[dict[str, Any]],
        total_iterations: int,
        total_tool_calls: int,
        total_tokens_used: int,
        total_time_ms: float,
    ) -> Optional[AgentSession]:
        """Checkpoint trajectory and running metrics periodically during the session."""
        session = self.get_by_id(session_id)
        if not session:
            return None
        session.trajectory = trajectory
        session.total_iterations = total_iterations
        session.total_tool_calls = total_tool_calls
        session.total_tokens_used = total_tokens_used
        session.total_time_ms = total_time_ms
        self.db.commit()
        self.db.refresh(session)
        return session

    def finalize_session(
        self,
        session_id: int,
        status: str,
        final_answer: Optional[str],
        citations: list[dict[str, Any]],
        trajectory: list[dict[str, Any]],
        total_iterations: int,
        total_tool_calls: int,
        total_tokens_used: int,
        total_time_ms: float,
        stop_reason: str,
    ) -> Optional[AgentSession]:
        """Finalize an agent session with outcome, citations, and completion metrics."""
        session = self.get_by_id(session_id)
        if not session:
            return None
        session.status = status
        session.final_answer = final_answer
        session.citations = citations
        session.trajectory = trajectory
        session.total_iterations = total_iterations
        session.total_tool_calls = total_tool_calls
        session.total_tokens_used = total_tokens_used
        session.total_time_ms = total_time_ms
        session.stop_reason = stop_reason
        session.completed_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get_by_id(self, session_id: int) -> Optional[AgentSession]:
        """Fetch a single agent session by primary key."""
        stmt = select(AgentSession).where(AgentSession.id == session_id)
        result = self.db.execute(stmt)
        return result.scalars().first()

    def list_by_project(self, project_id: int) -> list[AgentSession]:
        """List all agent sessions for a project, newest first."""
        stmt = (
            select(AgentSession)
            .where(AgentSession.project_id == project_id)
            .order_by(AgentSession.created_at.desc())
        )
        result = self.db.execute(stmt)
        return list(result.scalars().all())

    def delete(self, session_id: int) -> bool:
        """Delete an agent session by primary key."""
        session = self.get_by_id(session_id)
        if not session:
            return False
        self.db.delete(session)
        self.db.commit()
        return True
