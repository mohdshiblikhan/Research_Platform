import logging
from typing import Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.chunk import Chunk
from app.models.document import Document
from app.schemas.search import SearchResultItem

logger = logging.getLogger(__name__)


class SearchRepository:
    """Database operations for full-text search over document chunks.

    Encapsulates all PostgreSQL FTS query logic:
    - websearch_to_tsquery for safe, Google-like query parsing.
    - ts_rank_cd for cover-density relevance ranking.
    - ts_headline for <mark>-tagged highlighted snippets.
    - JOIN with documents to filter by project_id and retrieve filenames.
    - Pagination via LIMIT / OFFSET.

    Kept separate from ChunkRepository (which handles CRUD during ingestion)
    because search is a fundamentally different query pattern. This separation
    also makes Milestone 5 (VectorSearchRepository) and Milestone 6
    (hybrid fusion in SearchService) easier to add without touching this class.
    """

    def __init__(self, db: Session):
        self.db = db

    def search(
        self,
        project_id: int,
        query: str,
        document_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SearchResultItem], int]:
        """Execute a full-text search over chunks in a project.

        Args:
            project_id: Scope the search to this project's documents.
            query: Raw user query string (will be parsed by websearch_to_tsquery).
            document_id: If provided, restrict search to this document only.
            limit: Maximum results to return (page size).
            offset: Pagination offset.

        Returns:
            A tuple of (result_items, total_count) where total_count is the
            full matching count regardless of limit/offset.

        Notes on the SQL approach:
            - websearch_to_tsquery('english', :query) parses Google-like syntax
              safely — quoted phrases, OR, - for NOT. Never raises a syntax error.
            - c.search_vector @@ tsquery is the FTS match operator.
            - ts_rank_cd(c.search_vector, tsquery, 32) uses cover density ranking
              (normalization flag 32 divides by rank+1, keeping scores in (0,1)).
            - ts_headline generates <mark>-tagged snippets from the raw content text.
        """
        # Build the tsquery expression once (reused for match, rank, and headline)
        tsquery = func.websearch_to_tsquery("english", query)

        # --- Core query -------------------------------------------------------
        base_q = (
            self.db.query(
                Chunk.id.label("chunk_id"),
                Chunk.document_id,
                Document.filename.label("document_filename"),
                Chunk.chunk_index,
                Chunk.content,
                func.ts_headline(
                    "english",
                    Chunk.content,
                    tsquery,
                    text(
                        "'StartSel=<mark>, StopSel=</mark>,"
                        " MaxWords=60, MinWords=20, MaxFragments=3'"
                    ),
                ).label("headline"),
                Chunk.page_start,
                Chunk.page_end,
                Chunk.char_offset_start,
                Chunk.char_offset_end,
                func.ts_rank_cd(Chunk.search_vector, tsquery, 32).label("rank"),
            )
            .join(Document, Chunk.document_id == Document.id)
            .filter(Document.project_id == project_id)
            .filter(Chunk.search_vector.op("@@")(tsquery))
        )

        # Optionally narrow to a specific document
        if document_id is not None:
            base_q = base_q.filter(Chunk.document_id == document_id)

        # --- Total count (before pagination) ----------------------------------
        # We need total_results for the pagination UI. A subquery count is the
        # cleanest approach — it reuses all the same WHERE conditions.
        total_count: int = base_q.count()

        # --- Paginated results ------------------------------------------------
        rows = (
            base_q
            .order_by(text("rank DESC"))
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
                headline=row.headline,
                page_start=row.page_start,
                page_end=row.page_end,
                char_offset_start=row.char_offset_start,
                char_offset_end=row.char_offset_end,
                rank=float(row.rank),
            )
            for row in rows
        ]

        logger.debug(
            "fts_search_complete",
            extra={
                "project_id": project_id,
                "query": query,
                "document_id": document_id,
                "total_count": total_count,
                "returned": len(results),
                "limit": limit,
                "offset": offset,
            },
        )

        return results, total_count
