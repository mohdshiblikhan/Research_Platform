from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.embedding import EmbeddingResponse
from app.services.document_embedding_service import DocumentEmbeddingService

router = APIRouter(prefix="/projects", tags=["Embedding"])


@router.post(
    "/{project_id}/documents/{document_id}/embed",
    response_model=EmbeddingResponse,
    summary="Generate embeddings for document chunks",
)
def embed_document_chunks(
    project_id: int, 
    document_id: int, 
    db: Session = Depends(get_db)
):
    """Compute and store vector embeddings for all chunks of a processed document.

    Prerequisites: document must be in 'processed' status (chunks exist).
    Idempotent: re-running overwrites existing embeddings.
    """
    service = DocumentEmbeddingService(db)
    try:
        return service.embed_document(project_id, document_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
