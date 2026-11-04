from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.experiment_comparison import (
    AvailableMetricItem,
    ExperimentComparisonRequest,
    ExperimentComparisonResponse,
)
from app.services.experiment_comparison_service import ExperimentComparisonService

router = APIRouter(prefix="/projects", tags=["Experiment Comparison"])


@router.post(
    "/{project_id}/experiments/compare",
    response_model=ExperimentComparisonResponse,
    status_code=status.HTTP_200_OK,
)
def compare_experiments(
    project_id: int,
    request: ExperimentComparisonRequest,
    db: Session = Depends(get_db),
):
    """
    Perform structured multi-experiment comparison with baseline deltas,
    Pareto frontier analysis, hypothesis verdict consensus, and optional LLM synthesis.
    """
    service = ExperimentComparisonService(db)
    try:
        return service.compare(project_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{project_id}/experiments/available-metrics",
    response_model=List[AvailableMetricItem],
    status_code=status.HTTP_200_OK,
)
def get_available_metrics(
    project_id: int,
    db: Session = Depends(get_db),
):
    """
    Discover all unique metrics recorded across all experiments in a project,
    returning canonical names, display titles, sample counts, and directions.
    """
    service = ExperimentComparisonService(db)
    try:
        return service.get_available_metrics(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
