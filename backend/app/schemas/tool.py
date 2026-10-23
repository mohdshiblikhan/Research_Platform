from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class ToolSafetyTier(str, Enum):
    """Safety classification for tools."""
    READ_ONLY = "read_only"
    ANALYTICAL = "analytical"


class ToolCall(BaseModel):
    """A tool call requested by an LLM."""
    id: str = Field(default="", description="Unique identifier for the tool call")
    name: str = Field(..., description="The name of the tool to execute")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Parsed arguments for the tool")


class ToolResult(BaseModel):
    """Internal standardized execution result produced by a BaseTool."""
    success: bool
    tool_name: str
    result_summary: str = Field(..., description="Token-optimized text summary for LLM context windows")
    data: Optional[dict[str, Any]] = Field(default=None, description="Full structured data payload")
    error: Optional[str] = Field(default=None, description="Error message if execution failed")


# --- Tool Argument Schemas (args_schema) ---

class SearchChunksArgs(BaseModel):
    """Arguments for search_chunks tool."""
    query: str = Field(..., min_length=3, max_length=500, description="Search query or research question")
    mode: Literal["keyword", "semantic", "hybrid"] = Field(
        default="hybrid", description="Retrieval mode: keyword, semantic, or hybrid"
    )
    document_id: Optional[int] = Field(default=None, ge=1, description="Optional document ID to scope search")
    rerank: bool = Field(default=True, description="Whether to apply cross-encoder reranking")
    limit: int = Field(default=5, ge=1, le=20, description="Maximum number of relevant chunks to return (1-20)")


class GetChunkArgs(BaseModel):
    """Arguments for get_chunk tool."""
    chunk_id: int = Field(..., ge=1, description="Unique primary key of the chunk to inspect")


class ListDocumentsArgs(BaseModel):
    """Arguments for list_documents tool."""
    status: Optional[Literal["uploaded", "processing", "processed", "failed"]] = Field(
        default=None, description="Optional filter by ingestion status"
    )


class GetDocumentMetadataArgs(BaseModel):
    """Arguments for get_document_metadata tool."""
    document_id: int = Field(..., ge=1, description="Document ID to inspect")


class GetPaperExtractionArgs(BaseModel):
    """Arguments for get_paper_extraction tool."""
    document_id: int = Field(..., ge=1, description="Document ID whose structured extraction to retrieve")


class ComparePapersArgs(BaseModel):
    """Arguments for compare_papers tool."""
    document_ids: list[int] = Field(
        ..., min_length=2, max_length=15, description="List of 2 to 15 document IDs to compare"
    )
    include_synthesis: bool = Field(
        default=True, description="Whether to generate LLM analytical synthesis (differences, gaps)"
    )


class GetResearchPlanArgs(BaseModel):
    """Arguments for get_research_plan tool."""
    plan_id: int = Field(..., ge=1, description="Research plan ID to inspect")


class ListResearchPlansArgs(BaseModel):
    """Arguments for list_research_plans tool (no arguments required)."""
    pass


# --- API Request & Response Schemas ---

class ToolExecutionRequest(BaseModel):
    """Request body for POST /api/projects/{p_id}/tools/execute."""
    tool_name: str = Field(..., description="Name of the registered tool to execute")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Dictionary of arguments matching tool's args_schema"
    )


class ToolDefinitionResponse(BaseModel):
    """Exported tool definition conforming to OpenAI/Ollama function-calling format."""
    name: str
    description: str
    parameters: dict[str, Any]
    safety_tier: ToolSafetyTier


class ToolExecutionResponse(BaseModel):
    """API response body for tool execution."""
    success: bool
    tool_name: str
    execution_time_ms: float
    result_summary: str
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
