import logging
import time
from typing import Optional, Literal

from sqlalchemy.orm import Session

from app.repositories.project_repository import ProjectRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.search_repository import SearchRepository
from app.repositories.vector_search_repository import VectorSearchRepository
from app.services.embedding_service_factory import get_embedding_service
from app.schemas.search import SearchResponse

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

    def search(
        self,
        project_id: int,
        query: str,
        mode: Literal["keyword", "semantic"] = "keyword",
        document_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Run a full-text keyword search over chunks within a project.

        Args:
            project_id: The project to search within.
            query: Raw user search string. Parsed by websearch_to_tsquery.
            mode: Search mode ('keyword' or 'semantic').
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
            
        if mode not in ["keyword", "semantic"]:
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
        
        if mode == "keyword":
            results, total_count = self.search_repo.search(
                project_id=project_id,
                query=query,
                document_id=document_id,
                limit=limit,
                offset=offset,
            )
        else:
            # Semantic mode
            query_embedding = self.embedding_service.embed_query(query)
            results, total_count = self.vector_search_repo.search(
                project_id=project_id,
                query_embedding=query_embedding,
                document_id=document_id,
                limit=limit,
                offset=offset,
            )
            
        query_time_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "search_query",
            extra={
                "project_id": project_id,
                "query": query,
                "mode": mode,
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
