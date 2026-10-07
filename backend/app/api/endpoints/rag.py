from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.rag import AskRequest, AskResponse
from app.services.rag_service import RAGService

router = APIRouter(prefix="/projects", tags=["RAG"])


@router.post(
    "/{project_id}/ask",
    response_model=AskResponse,
    summary="Ask a question and get an evidence-grounded answer",
    description=(
        "Retrieves relevant chunks from the project's documents "
        "and uses an LLM to generate an answer with citations."
    ),
)
def ask_question(
    project_id: int,
    request: AskRequest,
    db: Session = Depends(get_db),
) -> AskResponse:
    """Ask a question against a project's documents using RAG.
    
    Raises:
        400 Bad Request: If input is invalid.
        404 Not Found: If the project or document does not exist.
        503 Service Unavailable: If the LLM is unreachable.
    """
    service = RAGService(db)
    try:
        return service.ask(project_id=project_id, request=request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except RuntimeError as e:
        # e.g., LLM connection failure
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
