from typing import Optional, Literal
from pydantic import BaseModel


class SearchResultItem(BaseModel):
    """A single search result: a matched chunk with relevance metadata.

    Attributes:
        chunk_id: Primary key of the matching chunk.
        document_id: Primary key of the document containing this chunk.
        document_filename: Filename of the source document (denormalized from
            the JOIN — avoids N+1 lookups when rendering a results list).
        chunk_index: Position of this chunk in the document (0-based).
        content: Full text content of the chunk.
        headline: PostgreSQL ts_headline snippet with <mark>...</mark> tags
            wrapping matching query terms. Used for search result previews.
            None for semantic search results.
        page_start: First page this chunk overlaps (1-based).
        page_end: Last page this chunk overlaps (1-based).
        char_offset_start: Start character offset in the full document text.
        char_offset_end: End character offset in the full document text.
        rank: ts_rank_cd relevance score, normalized to (0, 1). None for semantic.
        similarity_score: 1.0 - cosine_distance. None for FTS keyword search.
        rrf_score: Reciprocal Rank Fusion score. None for keyword and semantic.
        rerank_score: Cross-encoder reranking score. None if reranking is disabled.
    """

    chunk_id: int
    document_id: int
    document_filename: str
    chunk_index: int
    content: str
    headline: Optional[str] = None
    page_start: int
    page_end: int
    char_offset_start: int
    char_offset_end: int
    rank: Optional[float] = None
    similarity_score: Optional[float] = None
    rrf_score: Optional[float] = None
    rerank_score: Optional[float] = None


class SearchResponse(BaseModel):
    """Top-level response for a keyword search query.

    Attributes:
        query: The original search query string (echoed back).
        project_id: The project that was searched.
        search_mode: 'keyword', 'semantic', or 'hybrid'
        total_results: Total number of matching chunks (ignores limit/offset).
            Used by clients to build pagination UI.
        limit: The page size used for this response.
        offset: The pagination offset used for this response.
        query_time_ms: Server-side search execution time in milliseconds.
            Logged and returned to establish the baseline retrieval latency
            for comparison against future semantic and hybrid retrieval.
        document_id: The optional document filter used in the request.
        results: The ranked search result items for this page.
    """

    query: str
    project_id: int
    search_mode: Literal["keyword", "semantic", "hybrid"]
    total_results: int
    limit: int
    offset: int
    query_time_ms: float
    document_id: Optional[int] = None
    results: list[SearchResultItem]
