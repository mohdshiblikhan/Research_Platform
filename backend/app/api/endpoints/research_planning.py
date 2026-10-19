from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.research_plan import (
    ResearchPlanRequest,
    ResearchPlanResponse,
    ResearchPlanSummary,
)
from app.services.research_planning_service import ResearchPlanningService

router = APIRouter(prefix="/projects", tags=["Research Planning"])


@router.post(
    "/{project_id}/plan",
    response_model=ResearchPlanResponse,
    status_code=status.HTTP_200_OK,
)
def create_research_plan(
    project_id: int,
    data: ResearchPlanRequest,
    db: Session = Depends(get_db),
):
    """Generate a structured, evidence-driven research plan from literature analysis."""
    service = ResearchPlanningService(db)
    try:
        return service.create_plan(project_id, data)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred during research plan generation: {str(e)}",
        )


@router.get(
    "/{project_id}/plans",
    response_model=list[ResearchPlanSummary],
    status_code=status.HTTP_200_OK,
)
def list_research_plans(
    project_id: int,
    db: Session = Depends(get_db),
):
    """List all research plans generated for a project."""
    service = ResearchPlanningService(db)
    try:
        return service.list_plans(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while listing research plans: {str(e)}",
        )


@router.get(
    "/{project_id}/plans/{plan_id}",
    response_model=ResearchPlanResponse,
    status_code=status.HTTP_200_OK,
)
def get_research_plan(
    project_id: int,
    plan_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve a specific persisted research plan by its ID."""
    service = ResearchPlanningService(db)
    try:
        return service.get_plan(project_id, plan_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while retrieving research plan: {str(e)}",
        )
