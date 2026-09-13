from typing import Optional

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, document_id: int) -> Optional[Document]:
        """Fetch a single document by its primary key. Returns None if not found."""
        return self.db.get(Document, document_id)

    def list_by_project(self, project_id: int) -> list[Document]:
        """Return all documents for a project, ordered by newest first."""
        return (
            self.db.query(Document)
            .filter(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
            .all()
        )

    def get_by_project_and_filename(
        self, project_id: int, filename: str
    ) -> Optional[Document]:
        """Check if a document with the same filename already exists in a project."""
        return (
            self.db.query(Document)
            .filter(Document.project_id == project_id, Document.filename == filename)
            .first()
        )

    def create(
        self,
        project_id: int,
        filename: str,
        file_path: str,
        file_size: int,
        mime_type: str,
        page_count: Optional[int],
    ) -> Document:
        """Insert a new document row and return the persisted object."""
        document = Document(
            project_id=project_id,
            filename=filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type,
            page_count=page_count,
            status=DocumentStatus.UPLOADED.value,
        )
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def delete(self, document: Document) -> None:
        """Delete a document row."""
        self.db.delete(document)
        self.db.commit()
