import logging
import time

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import DocumentStatus
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.embedding import EmbeddingResponse
from app.services.embedding_service_factory import get_embedding_service

logger = logging.getLogger(__name__)


class DocumentEmbeddingService:
    """Orchestrates embedding generation for processed document chunks."""

    def __init__(self, db: Session):
        self.db = db
        self.doc_repo = DocumentRepository(db)
        self.project_repo = ProjectRepository(db)
        self.chunk_repo = ChunkRepository(db)
        self.embedding_service = get_embedding_service()

    def embed_document(self, project_id: int, document_id: int) -> EmbeddingResponse:
        """Compute and store vector embeddings for all chunks of a processed document.

        Args:
            project_id: The ID of the project.
            document_id: The ID of the document to embed.

        Returns:
            EmbeddingResponse with metadata about the operation.

        Raises:
            FileNotFoundError: If project or document not found.
            ValueError: If document is not in 'processed' status.
        """
        # 1. Validate project
        if not self.project_repo.get_by_id(project_id):
            raise FileNotFoundError(f"Project {project_id} not found")

        # 2. Validate document
        document = self.doc_repo.get_by_id(document_id)
        if document is None or document.project_id != project_id:
            raise FileNotFoundError(f"Document {document_id} not found in project {project_id}")

        # 3. Validate status
        if document.status != DocumentStatus.PROCESSED.value:
            raise ValueError(
                f"Document {document_id} cannot be embedded: "
                f"current status is '{document.status}'. "
                f"Only documents with status 'processed' can be embedded."
            )

        # 4. Fetch chunks
        chunks = self.chunk_repo.list_by_document(document_id)
        if not chunks:
            raise ValueError(f"Document {document_id} has no chunks to embed.")

        start = time.perf_counter()

        # 5. Extract texts and chunk ids
        chunk_ids = [chunk.id for chunk in chunks]
        texts = [chunk.content for chunk in chunks]

        # 6. Generate embeddings (batched internally by the service)
        embeddings = self.embedding_service.embed_texts(texts)

        # 7. Bulk update chunks in DB
        self.chunk_repo.update_embeddings(chunk_ids, embeddings)
        self.db.commit()

        embedding_time_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "document_embedded",
            extra={
                "project_id": project_id,
                "document_id": document_id,
                "chunks_embedded": len(chunks),
                "embedding_time_ms": embedding_time_ms,
            },
        )

        return EmbeddingResponse(
            document_id=document.id,
            filename=document.filename,
            chunks_embedded=len(chunks),
            embedding_model=settings.embedding_model,
            embedding_dimension=self.embedding_service.get_dimension(),
            embedding_time_ms=embedding_time_ms,
        )
