from typing import Optional

from sqlalchemy.orm import Session

from app.models.chunk import Chunk


class ChunkRepository:
    """Database operations for chunks."""

    def __init__(self, db: Session):
        self.db = db

    def bulk_create(self, chunks: list[Chunk]) -> list[Chunk]:
        """Insert multiple chunks in a single transaction.

        All chunks are added and flushed together for efficiency.
        The caller is responsible for committing the transaction.
        """
        self.db.add_all(chunks)
        self.db.flush()
        return chunks

    def list_by_document(self, document_id: int) -> list[Chunk]:
        """Return all chunks for a document, ordered by chunk_index."""
        return (
            self.db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
            .all()
        )

    def get_by_id(self, chunk_id: int) -> Optional[Chunk]:
        """Fetch a single chunk by its primary key."""
        return self.db.get(Chunk, chunk_id)

    def delete_by_document(self, document_id: int) -> int:
        """Delete all chunks for a document. Returns the number deleted."""
        count = (
            self.db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .delete()
        )
        self.db.flush()
        return count

    def count_by_document(self, document_id: int) -> int:
        """Return the number of chunks for a document."""
        return (
            self.db.query(Chunk)
            .filter(Chunk.document_id == document_id)
            .count()
        )

    def update_embeddings(
        self, chunk_ids: list[int], embeddings: list[list[float]]
    ) -> int:
        """Bulk-update embedding vectors for the given chunks.

        Returns the number of rows updated.
        """
        if len(chunk_ids) != len(embeddings):
            raise ValueError("Number of chunks and embeddings must match.")

        if not chunk_ids:
            return 0

        # Create mapping of id -> embedding
        updates = [{"id": cid, "embedding": emb} for cid, emb in zip(chunk_ids, embeddings)]
        
        # Use bulk_update_mappings for fast bulk updates
        self.db.bulk_update_mappings(Chunk, updates)
        self.db.flush()
        return len(chunk_ids)
