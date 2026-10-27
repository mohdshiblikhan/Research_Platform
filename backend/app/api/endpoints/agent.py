from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.agent_session_repository import AgentSessionRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.agent import (
    AgentResearchRequest,
    AgentResearchResponse,
    AgentSessionSummary,
)
from app.services.agent_service import AgentService

router = APIRouter(prefix="/projects", tags=["Agentic Research"])


@router.post(
    "/{project_id}/agent/research",
    response_model=AgentResearchResponse,
    status_code=status.HTTP_200_OK,
)
def run_agent_research(
    project_id: int,
    request: AgentResearchRequest,
    db: Session = Depends(get_db),
):
    """Run an autonomous agent research session to investigate a research question."""
    project = ProjectRepository(db).get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found.",
        )

    service = AgentService(db=db)
    try:
        return service.run_research_session(project_id=project_id, request=request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred during agent research execution: {str(e)}",
        )


@router.get(
    "/{project_id}/agent/sessions",
    response_model=list[AgentSessionSummary],
    status_code=status.HTTP_200_OK,
)
def list_agent_sessions(
    project_id: int,
    db: Session = Depends(get_db),
):
    """List all agent research sessions for a project."""
    project = ProjectRepository(db).get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found.",
        )

    repo = AgentSessionRepository(db)
    sessions = repo.list_by_project(project_id)
    return [
        AgentSessionSummary(
            session_id=s.id,
            project_id=s.project_id,
            research_question=s.research_question,
            status=s.status,
            total_iterations=s.total_iterations,
            total_tool_calls=s.total_tool_calls,
            total_time_ms=s.total_time_ms,
            stop_reason=s.stop_reason,
            created_at=s.created_at,
            completed_at=s.completed_at,
        )
        for s in sessions
    ]


@router.get(
    "/{project_id}/agent/sessions/{session_id}",
    response_model=AgentResearchResponse,
    status_code=status.HTTP_200_OK,
)
def get_agent_session(
    project_id: int,
    session_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve full details and observable trajectory of a specific agent research session."""
    project = ProjectRepository(db).get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project with ID {project_id} not found.",
        )

    repo = AgentSessionRepository(db)
    session = repo.get_by_id(session_id)
    if not session or session.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent session with ID {session_id} not found in project {project_id}.",
        )

    return AgentResearchResponse(
        session_id=session.id,
        project_id=session.project_id,
        research_question=session.research_question,
        status=session.status,
        final_answer=session.final_answer,
        citations=session.citations,
        trajectory=session.trajectory,
        total_iterations=session.total_iterations,
        total_tool_calls=session.total_tool_calls,
        total_tokens_used=session.total_tokens_used,
        total_time_ms=session.total_time_ms,
        model_used=session.model_used,
        stop_reason=session.stop_reason,
        created_at=session.created_at,
        completed_at=session.completed_at,
    )
