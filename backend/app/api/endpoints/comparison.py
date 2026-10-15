from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.comparison import ComparisonRequest, ComparisonResponse
from app.services.comparison_service import ComparisonService

router = APIRouter(prefix="/projects", tags=["Comparison"])


@router.post("/{project_id}/compare", response_model=ComparisonResponse)
def compare_documents(
    project_id: int,
    data: ComparisonRequest,
    db: Session = Depends(get_db),
):
    """Compare extracted structured metadata across multiple documents in a project."""
    service = ComparisonService(db)
    try:
        return service.compare(project_id, data)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred during literature comparison: {str(e)}",
        )
