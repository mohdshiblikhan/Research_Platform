from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.document import DocumentRead
from app.services.document_service import DocumentService

router = APIRouter(prefix="/projects", tags=["Documents"])


@router.post(
    "/{project_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    project_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
):
    """Upload a PDF document to a project."""
    service = DocumentService(db)
    try:
        document = service.upload(project_id, file)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return document


@router.get("/{project_id}/documents", response_model=list[DocumentRead])
def list_documents(project_id: int, db: Session = Depends(get_db)):
    """List all documents for a project."""
    service = DocumentService(db)
    try:
        return service.list_documents(project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{project_id}/documents/{document_id}", response_model=DocumentRead)
def get_document(project_id: int, document_id: int, db: Session = Depends(get_db)):
    """Get metadata for a single document. Validates it belongs to the specified project."""
    service = DocumentService(db)
    try:
        return service.get_document(project_id, document_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete(
    "/{project_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(project_id: int, document_id: int, db: Session = Depends(get_db)):
    """Delete a document and its file from disk."""
    service = DocumentService(db)
    try:
        service.delete_document(project_id, document_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
