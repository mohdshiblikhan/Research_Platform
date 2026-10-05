from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.search import SearchResponse
from app.services.search_service import SearchService

router = APIRouter(prefix="/projects", tags=["Search"])


@router.get(
    "/{project_id}/search",
    response_model=SearchResponse,
    summary="Keyword search over document chunks",
    description=(
        "Search all processed document chunks within a project using "
        "PostgreSQL full-text search. Supports Google-like query syntax: "
        'quoted phrases ("attention mechanism"), OR, and exclusion with -. '
        "Results are ranked by cover-density relevance (ts_rank_cd) and "
        "include highlighted snippets with matching terms wrapped in <mark> tags."
    ),
)
def search_chunks(
    project_id: int,
    q: str = Query(
        ...,
        min_length=1,
        max_length=500,
        description=(
            "Search query. Supports: plain terms (AND implicit), "
            '"quoted phrases", OR, and -exclusion.'
        ),
    ),
    document_id: Optional[int] = Query(
        None,
        description="Restrict search to a specific document within the project.",
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Number of results per page (1-100).",
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Pagination offset.",
    ),
    db: Session = Depends(get_db),
) -> SearchResponse:
    """Full-text keyword search over document chunks in a project.

    Scoped to a single project. Optionally filtered to a specific document.

    Raises:
        400 Bad Request: If the query is empty or too long.
        404 Not Found: If the project or specified document does not exist.
    """
    service = SearchService(db)
    try:
        return service.search(
            project_id=project_id,
            query=q,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
