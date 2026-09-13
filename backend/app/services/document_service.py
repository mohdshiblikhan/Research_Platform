import logging
import os
from pathlib import Path
from typing import Optional

import pymupdf
from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository

logger = logging.getLogger(__name__)

# Allowed file types — PDF only for now.
ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_MIME_TYPES = {"application/pdf"}


class DocumentService:
    """Orchestrates document upload and deletion.

    Coordinates file I/O (disk) with database operations.
    If the DB insert fails after a file is written, the file is cleaned up.
    """

    def __init__(self, db: Session):
        self.db = db
        self.doc_repo = DocumentRepository(db)
        self.project_repo = ProjectRepository(db)

    def upload(self, project_id: int, file: UploadFile) -> Document:
        """Validate, save to disk, extract page count, and persist metadata.

        Raises:
            ValueError: If the file type is not allowed or filename is duplicate.
            FileNotFoundError: If the project does not exist.
        """
        # 1. Verify project exists
        project = self.project_repo.get_by_id(project_id)
        if project is None:
            raise FileNotFoundError(f"Project {project_id} not found")

        # 2. Validate file type
        filename = file.filename or "unnamed.pdf"
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"File type '{ext}' is not allowed. Only PDF files are accepted.")

        content_type = file.content_type or ""
        if content_type not in ALLOWED_MIME_TYPES:
            raise ValueError(
                f"MIME type '{content_type}' is not allowed. Only application/pdf is accepted."
            )

        # 3. Check for duplicate filename within the same project
        existing = self.doc_repo.get_by_project_and_filename(project_id, filename)
        if existing is not None:
            raise FileExistsError(
                f"A document named '{filename}' already exists in this project."
            )

        # 4. Read file content
        file_content = file.file.read()
        file_size = len(file_content)

        # 5. Save file to disk
        project_upload_dir = Path(settings.upload_dir) / str(project_id)
        project_upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = project_upload_dir / filename

        file_path.write_bytes(file_content)
        logger.info("Saved file to %s (%d bytes)", file_path, file_size)

        # 6. Extract page count using PyMuPDF (validates PDF integrity)
        page_count: Optional[int] = None
        try:
            with pymupdf.open(str(file_path)) as pdf_doc:
                page_count = len(pdf_doc)
            logger.info("PDF has %d pages", page_count)
        except Exception:
            # File saved but not a valid PDF — clean up and reject
            file_path.unlink(missing_ok=True)
            logger.warning("File %s is not a valid PDF, cleaned up", filename)
            raise ValueError(
                f"File '{filename}' is not a valid PDF document."
            )

        # 7. Persist metadata to database
        relative_path = str(file_path)
        try:
            document = self.doc_repo.create(
                project_id=project_id,
                filename=filename,
                file_path=relative_path,
                file_size=file_size,
                mime_type="application/pdf",
                page_count=page_count,
            )
        except Exception:
            # DB insert failed — clean up the file
            file_path.unlink(missing_ok=True)
            logger.error("DB insert failed for %s, cleaned up file", filename)
            raise

        logger.info("Document %d created for project %d", document.id, project_id)
        return document

    def get_document(self, project_id: int, document_id: int) -> Document:
        """Retrieve a single document, verifying it belongs to the specified project.

        Raises:
            FileNotFoundError: If the project or document is not found,
                               or if the document doesn't belong to the project.
        """
        project = self.project_repo.get_by_id(project_id)
        if project is None:
            raise FileNotFoundError(f"Project {project_id} not found")

        document = self.doc_repo.get_by_id(document_id)
        if document is None or document.project_id != project_id:
            raise FileNotFoundError(f"Document {document_id} not found in project {project_id}")

        return document

    def list_documents(self, project_id: int) -> list[Document]:
        """List all documents for a project.

        Raises:
            FileNotFoundError: If the project does not exist.
        """
        project = self.project_repo.get_by_id(project_id)
        if project is None:
            raise FileNotFoundError(f"Project {project_id} not found")

        return self.doc_repo.list_by_project(project_id)

    def delete_document(self, project_id: int, document_id: int) -> None:
        """Delete a document's DB row and its file on disk.

        Raises:
            FileNotFoundError: If the project or document is not found,
                               or if the document doesn't belong to the project.
        """
        document = self.get_document(project_id, document_id)

        file_path = Path(document.file_path)

        # Delete DB row first
        self.doc_repo.delete(document)

        # Then delete file from disk
        if file_path.exists():
            file_path.unlink()
            logger.info("Deleted file %s", file_path)
        else:
            logger.warning("File %s not found on disk during deletion", file_path)
