from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.chunk import ChunkRead, ProcessingResult
from app.services.document_service import DocumentService
from app.services.processing_service import ProcessingService
from app.repositories.chunk_repository import ChunkRepository

router = APIRouter(prefix="/projects", tags=["Processing"])


@router.post(
    "/{project_id}/documents/{document_id}/process",
    response_model=ProcessingResult,
    status_code=status.HTTP_200_OK,
)
def process_document(
    project_id: int,
    document_id: int,
    db: Session = Depends(get_db),
):
    """Extract text from a PDF, chunk it, and store the chunks.

    The document must be in 'uploaded' status. After processing,
    its status transitions to 'processed' (or 'failed' on error).
    """
    service = ProcessingService(db)
    try:
        result = service.process_document(project_id, document_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return result


@router.get(
    "/{project_id}/documents/{document_id}/chunks",
    response_model=list[ChunkRead],
)
def list_chunks(
    project_id: int,
    document_id: int,
    db: Session = Depends(get_db),
):
    """List all chunks for a processed document, ordered by chunk_index."""
    # Validate document exists and belongs to project
    doc_service = DocumentService(db)
    try:
        doc_service.get_document(project_id, document_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    chunk_repo = ChunkRepository(db)
    return chunk_repo.list_by_document(document_id)


@router.get(
    "/{project_id}/documents/{document_id}/chunks/{chunk_id}",
    response_model=ChunkRead,
)
def get_chunk(
    project_id: int,
    document_id: int,
    chunk_id: int,
    db: Session = Depends(get_db),
):
    """Get a single chunk by ID. Validates it belongs to the specified document."""
    # Validate document exists and belongs to project
    doc_service = DocumentService(db)
    try:
        doc_service.get_document(project_id, document_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    chunk_repo = ChunkRepository(db)
    chunk = chunk_repo.get_by_id(chunk_id)

    if chunk is None or chunk.document_id != document_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chunk {chunk_id} not found in document {document_id}",
        )

    return chunk
