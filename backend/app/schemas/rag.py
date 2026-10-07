from typing import Optional, Literal
from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """Request body for the /ask endpoint."""
    question: str = Field(..., min_length=1, max_length=1000)
    search_mode: Literal["keyword", "semantic", "hybrid"] = "hybrid"
    rerank: bool = True
    top_k: int = Field(default=5, ge=1, le=20)
    document_id: Optional[int] = None


class Citation(BaseModel):
    """A single citation linking a claim to its source evidence."""
    source_index: int           # Index into the sources list (1-based)
    chunk_id: int               # Database ID of the cited chunk
    document_id: int            # Document containing the chunk
    document_filename: str      # Human-readable source name
    page_start: int             # Page range of the source chunk
    page_end: int
    cited_text: str             # The relevant excerpt from the chunk


class SourcePassage(BaseModel):
    """A retrieved evidence passage used in generation."""
    index: int                  # 1-based index for referencing in answer
    chunk_id: int
    document_id: int
    document_filename: str
    page_start: int
    page_end: int
    content: str                # Full chunk text
    relevance_score: Optional[float] = None  # Best available score


class CitationVerification(BaseModel):
    total: int
    valid: int
    invalid: int


class AskResponse(BaseModel):
    """Full response from the /ask endpoint."""
    question: str
    project_id: int
    evidence_analysis: Optional[str] = None
    answer: str
    citations: list[Citation]
    sources: list[SourcePassage]
    search_mode: str
    reranked: bool
    top_k: int
    retrieval_time_ms: float
    generation_time_ms: float
    total_time_ms: float
    llm_model: str
    citation_verification: CitationVerification
    confidence: str
    has_sufficient_evidence: bool
