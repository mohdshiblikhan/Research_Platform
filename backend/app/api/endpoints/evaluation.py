from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.evaluation import (
    EvaluationDatasetCreate,
    EvaluationDatasetItemAdd,
    EvaluationDatasetRead,
    EvaluationItemRead,
    EvaluationItemResultRead,
    EvaluationItemUpdate,
    EvaluationRunDetail,
    EvaluationRunRead,
    RunAgentEvaluationRequest,
    RunRAGEvaluationRequest,
    RunRetrievalEvaluationRequest,
    SyntheticDatasetGenerateRequest,
)
from app.services.evaluation_service import EvaluationService

router = APIRouter(prefix="/projects", tags=["Evaluation"])


# =============================================================================
# Dataset Endpoints
# =============================================================================

@router.post(
    "/{project_id}/evaluation/datasets",
    response_model=EvaluationDatasetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_dataset(
    project_id: int,
    request: EvaluationDatasetCreate,
    db: Session = Depends(get_db),
):
    """Create a new evaluation dataset within a project."""
    service = EvaluationService(db)
    try:
        return service.create_dataset(project_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{project_id}/evaluation/datasets",
    response_model=List[EvaluationDatasetRead],
)
def list_datasets(
    project_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List all evaluation datasets for a project."""
    service = EvaluationService(db)
    try:
        return service.list_datasets(project_id, limit=limit, offset=offset)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/{project_id}/evaluation/datasets/{dataset_id}",
    response_model=EvaluationDatasetRead,
)
def get_dataset(
    project_id: int,
    dataset_id: int,
    db: Session = Depends(get_db),
):
    """Fetch an evaluation dataset by ID."""
    service = EvaluationService(db)
    try:
        return service.get_dataset(project_id, dataset_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete(
    "/{project_id}/evaluation/datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_dataset(
    project_id: int,
    dataset_id: int,
    db: Session = Depends(get_db),
):
    """Delete an evaluation dataset. Historical evaluation runs are preserved via SET NULL."""
    service = EvaluationService(db)
    try:
        service.delete_dataset(project_id, dataset_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# =============================================================================
# Dataset Item Endpoints
# =============================================================================

@router.post(
    "/{project_id}/evaluation/datasets/{dataset_id}/items",
    response_model=List[EvaluationItemRead],
    status_code=status.HTTP_201_CREATED,
)
def add_dataset_items(
    project_id: int,
    dataset_id: int,
    request: EvaluationDatasetItemAdd,
    db: Session = Depends(get_db),
):
    """Add benchmark items to an evaluation dataset."""
    service = EvaluationService(db)
    try:
        return service.add_items(project_id, dataset_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{project_id}/evaluation/datasets/{dataset_id}/items",
    response_model=List[EvaluationItemRead],
)
def list_dataset_items(
    project_id: int,
    dataset_id: int,
    validated_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List benchmark items in an evaluation dataset."""
    service = EvaluationService(db)
    try:
        return service.get_dataset_items(
            project_id=project_id,
            dataset_id=dataset_id,
            validated_only=validated_only,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch(
    "/{project_id}/evaluation/datasets/{dataset_id}/items/{item_id}",
    response_model=EvaluationItemRead,
)
def patch_dataset_item(
    project_id: int,
    dataset_id: int,
    item_id: int,
    request: EvaluationItemUpdate,
    db: Session = Depends(get_db),
):
    """Update an evaluation dataset item (e.g. validate candidate, update ground truth)."""
    service = EvaluationService(db)
    try:
        return service.patch_item(project_id, dataset_id, item_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# =============================================================================
# Synthetic Generation Endpoint
# =============================================================================

@router.post(
    "/{project_id}/evaluation/datasets/generate-synthetic",
    response_model=EvaluationDatasetRead,
    status_code=status.HTTP_201_CREATED,
)
def generate_synthetic_dataset(
    project_id: int,
    request: SyntheticDatasetGenerateRequest,
    db: Session = Depends(get_db),
):
    """Synthetically generate evaluation questions and grounded answers from project documents."""
    service = EvaluationService(db)
    try:
        return service.generate_synthetic_dataset(project_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# =============================================================================
# Evaluation Execution Endpoints
# =============================================================================

@router.post(
    "/{project_id}/evaluation/runs/retrieval",
    response_model=EvaluationRunDetail,
    status_code=status.HTTP_201_CREATED,
)
def run_retrieval_evaluation(
    project_id: int,
    request: RunRetrievalEvaluationRequest,
    db: Session = Depends(get_db),
):
    """Execute a retrieval evaluation run against benchmark items."""
    service = EvaluationService(db)
    try:
        return service.run_retrieval_evaluation(project_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{project_id}/evaluation/runs/rag",
    response_model=EvaluationRunDetail,
    status_code=status.HTTP_201_CREATED,
)
def run_rag_evaluation(
    project_id: int,
    request: RunRAGEvaluationRequest,
    db: Session = Depends(get_db),
):
    """Execute a RAG evaluation run assessing answer faithfulness, citations, and relevance."""
    service = EvaluationService(db)
    try:
        return service.run_rag_evaluation(project_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{project_id}/evaluation/runs/agent",
    response_model=EvaluationRunDetail,
    status_code=status.HTTP_201_CREATED,
)
def run_agent_evaluation(
    project_id: int,
    request: RunAgentEvaluationRequest,
    db: Session = Depends(get_db),
):
    """Execute an agent trajectory evaluation run assessing task completion, efficiency, and answer correctness."""
    service = EvaluationService(db)
    try:
        return service.run_agent_evaluation(project_id, request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# =============================================================================
# Run Query Endpoints
# =============================================================================

@router.get(
    "/{project_id}/evaluation/runs",
    response_model=List[EvaluationRunRead],
)
def list_evaluation_runs(
    project_id: int,
    run_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List evaluation runs for a project."""
    service = EvaluationService(db)
    try:
        return service.list_runs(
            project_id=project_id,
            run_type=run_type,
            status=status,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/{project_id}/evaluation/runs/{run_id}",
    response_model=EvaluationRunDetail,
)
def get_evaluation_run(
    project_id: int,
    run_id: int,
    db: Session = Depends(get_db),
):
    """Fetch an evaluation run by ID with all item results."""
    service = EvaluationService(db)
    try:
        return service.get_run(project_id, run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get(
    "/{project_id}/evaluation/runs/{run_id}/results",
    response_model=List[EvaluationItemResultRead],
)
def get_evaluation_item_results(
    project_id: int,
    run_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Fetch per-item evaluation results for a specific run."""
    service = EvaluationService(db)
    try:
        return service.get_run_item_results(
            project_id=project_id, run_id=run_id, limit=limit, offset=offset
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
