from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.experiment import ExperimentPriority, ExperimentStatus
from app.schemas.experiment import (
    ExperimentBatchPromotionResponse,
    ExperimentCreate,
    ExperimentLogResultsRequest,
    ExperimentPromoteRequest,
    ExperimentRead,
    ExperimentSummary,
    ExperimentUpdate,
)
from app.services.experiment_service import ExperimentService

router = APIRouter(prefix="/projects", tags=["Experiments"])


@router.post(
    "/{project_id}/plans/{plan_id}/experiments",
    response_model=ExperimentBatchPromotionResponse,
    status_code=status.HTTP_201_CREATED,
)
def promote_experiments_from_plan(
    project_id: int,
    plan_id: int,
    request: ExperimentPromoteRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Promote proposed experiments from a ResearchPlan into tracked Experiment records."""
    service = ExperimentService(db)
    try:
        result = service.promote_from_plan(project_id, plan_id, request)
        if result.promoted_count == 0 and result.already_promoted_count > 0:
            response.status_code = status.HTTP_200_OK
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{project_id}/experiments",
    response_model=ExperimentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_experiment(
    project_id: int,
    request: ExperimentCreate,
    db: Session = Depends(get_db),
):
    """Create a new experiment manually across any lifecycle status."""
    service = ExperimentService(db)
    try:
        return service.create_manual_experiment(project_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{project_id}/experiments",
    response_model=List[ExperimentSummary],
    status_code=status.HTTP_200_OK,
)
def list_experiments(
    project_id: int,
    status: Optional[ExperimentStatus] = Query(default=None, description="Filter by experiment status"),
    priority: Optional[ExperimentPriority] = Query(default=None, description="Filter by priority"),
    plan_id: Optional[int] = Query(default=None, description="Filter by originating research plan ID"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List experiments for a project with optional filters and pagination."""
    service = ExperimentService(db)
    try:
        status_val = status.value if status else None
        priority_val = priority.value if priority else None
        return service.list_experiments(
            project_id=project_id,
            status=status_val,
            priority=priority_val,
            plan_id=plan_id,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/{project_id}/experiments/{experiment_id}",
    response_model=ExperimentRead,
    status_code=status.HTTP_200_OK,
)
def get_experiment(
    project_id: int,
    experiment_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve detailed specifications, parameters, and logged outcomes of an experiment."""
    service = ExperimentService(db)
    try:
        return service.get_experiment(project_id, experiment_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch(
    "/{project_id}/experiments/{experiment_id}",
    response_model=ExperimentRead,
    status_code=status.HTTP_200_OK,
)
def update_experiment(
    project_id: int,
    experiment_id: int,
    request: ExperimentUpdate,
    db: Session = Depends(get_db),
):
    """Partially update an experiment, enforcing lifecycle transition invariants."""
    service = ExperimentService(db)
    try:
        return service.update_experiment(project_id, experiment_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{project_id}/experiments/{experiment_id}/results",
    response_model=ExperimentRead,
    status_code=status.HTTP_200_OK,
)
def log_experiment_results(
    project_id: int,
    experiment_id: int,
    request: ExperimentLogResultsRequest,
    db: Session = Depends(get_db),
):
    """Record empirical metric results and/or qualitative findings with selective replacement."""
    service = ExperimentService(db)
    try:
        return service.log_results(project_id, experiment_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/{project_id}/experiments/{experiment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_experiment(
    project_id: int,
    experiment_id: int,
    db: Session = Depends(get_db),
):
    """Delete an experiment record."""
    service = ExperimentService(db)
    try:
        service.delete_experiment(project_id, experiment_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
