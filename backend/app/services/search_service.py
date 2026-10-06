import logging
import time
from typing import Optional, Literal

from sqlalchemy.orm import Session

from app.repositories.project_repository import ProjectRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.search_repository import SearchRepository
from app.repositories.vector_search_repository import VectorSearchRepository
from app.services.embedding_service_factory import get_embedding_service
from app.services.reranking_service import get_reranking_service
from app.schemas.search import SearchResponse, SearchResultItem

logger = logging.getLogger(__name__)


class SearchService:
    """Orchestrates keyword search over project chunks.

    Responsibilities:
    1. Validate the query string (non-empty, within length limit).
    2. Confirm the project exists (raises FileNotFoundError if not).
    3. Confirm the document (if provided) belongs to the project
       (raises FileNotFoundError if not).
    4. Delegate to SearchRepository or VectorSearchRepository for the actual query.
    5. Measure and record query execution time.
    6. Assemble and return a SearchResponse.
    """

    MAX_QUERY_LENGTH = 500

    def __init__(self, db: Session):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.doc_repo = DocumentRepository(db)
        self.search_repo = SearchRepository(db)
        self.vector_search_repo = VectorSearchRepository(db)
        self.embedding_service = get_embedding_service()
        self.reranking_service = get_reranking_service()

    def search(
        self,
        project_id: int,
        query: str,
        mode: Literal["keyword", "semantic", "hybrid"] = "keyword",
        rerank: bool = False,
        document_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Run a full-text keyword search over chunks within a project.

        Args:
            project_id: The project to search within.
            query: Raw user search string. Parsed by websearch_to_tsquery.
            mode: Search mode ('keyword', 'semantic', or 'hybrid').
            rerank: Whether to apply cross-encoder reranking to the top results.
            document_id: Optional document filter. If given, only chunks
                from that document are returned.
            limit: Max results per page (1-100).
            offset: Pagination offset (>= 0).

        Returns:
            SearchResponse with ranked results and timing metadata.

        Raises:
            ValueError: If the query is empty or exceeds MAX_QUERY_LENGTH,
                        or if mode is invalid.
            FileNotFoundError: If the project does not exist, or if
                document_id is provided but not found in the project.
        """
        # --- Input validation -------------------------------------------------
        query = query.strip()
        if not query:
            raise ValueError("Search query cannot be empty")
        if len(query) > self.MAX_QUERY_LENGTH:
            raise ValueError(
                f"Search query must be {self.MAX_QUERY_LENGTH} characters or fewer"
            )
            
        if mode not in ["keyword", "semantic", "hybrid"]:
            raise ValueError(f"Unknown search mode: {mode}")

        # --- Project validation -----------------------------------------------
        project = self.project_repo.get_by_id(project_id)
        if project is None:
            raise FileNotFoundError(f"Project {project_id} not found")

        # --- Document validation (optional filter) ----------------------------
        if document_id is not None:
            document = self.doc_repo.get_by_id(document_id)
            if document is None or document.project_id != project_id:
                raise FileNotFoundError(
                    f"Document {document_id} not found in project {project_id}"
                )

        # --- Execute search and measure latency -------------------------------
        start = time.perf_counter()
        
        
        # If reranking, we fetch a larger candidate pool first
        fetch_limit = 60 if rerank else limit
        fetch_offset = 0 if rerank else offset
        
        if mode == "keyword":
            results, total_count = self.search_repo.search(
                project_id=project_id,
                query=query,
                document_id=document_id,
                limit=fetch_limit,
                offset=fetch_offset,
            )
        elif mode == "semantic":
            query_embedding = self.embedding_service.embed_query(query)
            results, total_count = self.vector_search_repo.search(
                project_id=project_id,
                query_embedding=query_embedding,
                document_id=document_id,
                limit=fetch_limit,
                offset=fetch_offset,
            )
        else:
            # Hybrid mode
            # We don't pass offset directly to hybrid because it fetches 60 and applies it later.
            # But if we're reranking, we need to pass a larger limit and not apply the offset yet.
            results, total_count = self._perform_hybrid_search(
                project_id=project_id,
                query=query,
                document_id=document_id,
                limit=fetch_limit,
                offset=fetch_offset,
            )
            
        if rerank and results:
            results = self.reranking_service.rerank(query, results)
            # Apply limit and offset after reranking
            results = results[offset : offset + limit]
            
        query_time_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "search_query",
            extra={
                "project_id": project_id,
                "query": query,
                "mode": mode,
                "rerank": rerank,
                "document_id": document_id,
                "total_results": total_count,
                "returned": len(results),
                "limit": limit,
                "offset": offset,
                "query_time_ms": query_time_ms,
            },
        )

        return SearchResponse(
            query=query,
            project_id=project_id,
            search_mode=mode,
            total_results=total_count,
            limit=limit,
            offset=offset,
            query_time_ms=query_time_ms,
            document_id=document_id,
            results=results,
        )

    def _perform_hybrid_search(
        self,
        project_id: int,
        query: str,
        document_id: Optional[int],
        limit: int,
        offset: int,
    ) -> tuple[list[SearchResultItem], int]:
        """Perform Reciprocal Rank Fusion (RRF) on keyword and semantic results."""
        fusion_k = 60
        fetch_limit = 60

        # Fetch from Keyword Search
        keyword_results, keyword_count = self.search_repo.search(
            project_id=project_id,
            query=query,
            document_id=document_id,
            limit=fetch_limit,
            offset=0,
        )

        # Fetch from Vector Search
        query_embedding = self.embedding_service.embed_query(query)
        vector_results, vector_count = self.vector_search_repo.search(
            project_id=project_id,
            query_embedding=query_embedding,
            document_id=document_id,
            limit=fetch_limit,
            offset=0,
        )

        # RRF Fusion
        scores: dict[int, float] = {}
        items: dict[int, SearchResultItem] = {}

        for rank, item in enumerate(keyword_results, start=1):
            if item.chunk_id not in scores:
                scores[item.chunk_id] = 0.0
                items[item.chunk_id] = item
            scores[item.chunk_id] += 1.0 / (fusion_k + rank)

        for rank, item in enumerate(vector_results, start=1):
            if item.chunk_id not in scores:
                scores[item.chunk_id] = 0.0
                items[item.chunk_id] = item
            else:
                # Merge semantic data into existing item
                items[item.chunk_id].similarity_score = item.similarity_score
                # Vector search doesn't return headline, so keep the keyword one
                
            scores[item.chunk_id] += 1.0 / (fusion_k + rank)

        # Sort by RRF score descending
        fused_items = []
        for chunk_id, rrf_score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
            item = items[chunk_id]
            item.rrf_score = round(rrf_score, 4)
            fused_items.append(item)

        # Apply limit and offset
        paginated_results = fused_items[offset : offset + limit]
        
        # Approximate total count
        total_count = max(keyword_count, vector_count)
        
        return paginated_results, total_count

