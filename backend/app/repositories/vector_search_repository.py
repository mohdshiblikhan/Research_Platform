import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document
from app.schemas.search import SearchResultItem

logger = logging.getLogger(__name__)


class VectorSearchRepository:
    """Database operations for vector similarity search over document chunks."""

    def __init__(self, db: Session):
        self.db = db

    def search(
        self,
        project_id: int,
        query_embedding: list[float],
        document_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SearchResultItem], int]:
        """Semantic search using cosine distance.
        
        Args:
            project_id: Scope the search to this project's documents.
            query_embedding: 384-dimensional query vector.
            document_id: Optional document filter.
            limit: Pagination limit.
            offset: Pagination offset.
            
        Returns:
            A tuple of (result_items, total_count).
        """
        # Distance calculation expression
        cosine_distance = Chunk.embedding.cosine_distance(query_embedding)
        similarity_score = 1.0 - cosine_distance

        base_q = (
            self.db.query(
                Chunk.id.label("chunk_id"),
                Chunk.document_id,
                Document.filename.label("document_filename"),
                Chunk.chunk_index,
                Chunk.content,
                Chunk.page_start,
                Chunk.page_end,
                Chunk.char_offset_start,
                Chunk.char_offset_end,
                similarity_score.label("similarity_score"),
            )
            .join(Document, Chunk.document_id == Document.id)
            .filter(Document.project_id == project_id)
            .filter(Chunk.embedding.isnot(None))
        )

        if document_id is not None:
            base_q = base_q.filter(Chunk.document_id == document_id)

        total_count = base_q.count()

        rows = (
            base_q.order_by(cosine_distance)
            .limit(limit)
            .offset(offset)
            .all()
        )

        results = [
            SearchResultItem(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                document_filename=row.document_filename,
                chunk_index=row.chunk_index,
                content=row.content,
                headline=None,
                page_start=row.page_start,
                page_end=row.page_end,
                char_offset_start=row.char_offset_start,
                char_offset_end=row.char_offset_end,
                rank=None,
                similarity_score=float(row.similarity_score),
            )
            for row in rows
        ]
        
        logger.debug(
            "vector_search_complete",
            extra={
                "project_id": project_id,
                "document_id": document_id,
                "total_count": total_count,
                "returned": len(results),
                "limit": limit,
                "offset": offset,
            },
        )

        return results, total_count
