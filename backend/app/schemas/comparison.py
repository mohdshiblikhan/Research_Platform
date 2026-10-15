from typing import Optional
from pydantic import BaseModel, Field


class ComparisonRequest(BaseModel):
    """Request body for the /compare endpoint."""
    document_ids: list[int] = Field(
        ...,
        min_length=2,
        max_length=10,
        description="IDs of documents to compare",
    )
    include_synthesis: bool = Field(
        default=False,
        description="If True, generate an LLM-powered analytical synthesis",
    )


class ComparisonFieldValue(BaseModel):
    """One document's value for a specific extraction field."""
    document_id: int
    filename: str
    value: Optional[str] = None


class ComparisonField(BaseModel):
    """A single row in the comparison table."""
    field_name: str
    field_label: str
    values: list[ComparisonFieldValue]


class ComparisonSynthesis(BaseModel):
    """LLM-generated analysis of the comparison."""
    key_differences: str
    common_themes: str
    conflicting_findings: Optional[str] = None
    research_gaps: Optional[str] = None
    summary: str


class ComparisonResponse(BaseModel):
    """Full response from the /compare endpoint."""
    project_id: int
    documents_compared: int
    documents_missing_extraction: list[int]
    fields: list[ComparisonField]
    synthesis: Optional[ComparisonSynthesis] = None
    llm_model: Optional[str] = None
    synthesis_time_ms: Optional[float] = None
