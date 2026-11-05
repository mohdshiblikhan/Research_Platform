from datetime import datetime
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


# --- Dataset Items ---
class EvaluationItemCreate(BaseModel):
    query: str = Field(..., min_length=3)
    ground_truth_answer: Optional[str] = None
    expected_chunk_ids: list[int] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    question_type: Literal["manual", "single_chunk", "multi_chunk"] = "manual"
    is_validated: bool = True  # Manual items default to validated
    item_metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationDatasetItemAdd(BaseModel):
    items: list[EvaluationItemCreate] = Field(..., min_length=1)


class EvaluationItemUpdate(BaseModel):
    query: Optional[str] = None
    ground_truth_answer: Optional[str] = None
    expected_chunk_ids: Optional[list[int]] = None
    expected_tools: Optional[list[str]] = None
    is_validated: Optional[bool] = None
    item_metadata: Optional[dict[str, Any]] = None


class EvaluationItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: int
    query: str
    ground_truth_answer: Optional[str]
    expected_chunk_ids: list[int]
    expected_tools: list[str]
    question_type: str
    is_validated: bool
    item_metadata: dict[str, Any]
    created_at: datetime


# --- Datasets ---
class EvaluationDatasetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    eval_type: Literal["retrieval", "rag", "agent", "composite"] = "retrieval"
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    items: list[EvaluationItemCreate] = Field(default_factory=list)


class EvaluationDatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    description: Optional[str]
    eval_type: str
    extra_metadata: dict[str, Any]
    item_count: int = 0
    created_at: datetime
    updated_at: datetime


# --- Synthetic Generation ---
class SyntheticDatasetGenerateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    num_questions: int = Field(default=10, ge=1, le=50)
    question_type: Literal["single_chunk", "multi_chunk", "mixed"] = "mixed"
    document_ids: Optional[list[int]] = None


# --- Run Execution Requests (StrictInt rejects booleans, floats, and strings) ---
class RunRetrievalEvaluationRequest(BaseModel):
    dataset_id: int
    name: str
    search_mode: Literal["keyword", "semantic", "hybrid"] = "hybrid"
    rerank: bool = False
    k_values: list[StrictInt] = Field(default_factory=lambda: [1, 3, 5, 10])
    validated_only: bool = True  # Default: requires explicit opt-in for unvalidated candidates
    create_experiment: bool = True
    experiment_name: Optional[str] = None

    @field_validator("k_values")
    @classmethod
    def validate_k_values(cls, v: list[StrictInt]) -> list[StrictInt]:
        if not v:
            raise ValueError("k_values cannot be empty")
        for k in v:
            if k < 1:
                raise ValueError(f"All K values must be positive integers >= 1, got {k}")
        return v


class RunRAGEvaluationRequest(BaseModel):
    dataset_id: int
    name: str
    search_mode: Literal["keyword", "semantic", "hybrid"] = "hybrid"
    rerank: bool = True
    top_k: StrictInt = Field(default=5)
    evaluate_relevance: bool = True
    validated_only: bool = True  # Default: requires explicit opt-in for unvalidated candidates
    create_experiment: bool = True
    experiment_name: Optional[str] = None

    @field_validator("top_k")
    @classmethod
    def validate_top_k(cls, v: StrictInt) -> StrictInt:
        if v < 1:
            raise ValueError(f"top_k must be a positive integer >= 1, got {v}")
        return v


class RunAgentEvaluationRequest(BaseModel):
    dataset_id: int
    name: str
    max_iterations: StrictInt = Field(default=10)
    validated_only: bool = True  # Default: requires explicit opt-in for unvalidated candidates
    create_experiment: bool = True
    experiment_name: Optional[str] = None

    @field_validator("max_iterations")
    @classmethod
    def validate_max_iterations(cls, v: StrictInt) -> StrictInt:
        if v < 1:
            raise ValueError(f"max_iterations must be >= 1, got {v}")
        return v


# --- Retrieved Context Snapshot Model (Full Text) ---
class RetrievedChunkSnapshot(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    page_start: int
    page_end: int
    content: str  # Exact full text content passed to evaluator
    retrieval_score: float


# --- Item Result with Claim Provenance ---
class ClaimEvaluationRecord(BaseModel):
    claim: str
    cited_chunk_ids: list[int]
    valid_chunk_ids: list[int]  # Exist in retrieved set
    entailment_verdict: Literal["SUPPORTED", "CONTRADICTED", "UNSUPPORTED"]
    supporting_chunk_ids: list[int]  # Actually entail claim
    verdict_reason: Optional[str] = None


class EvaluationItemResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_item_id: Optional[int]
    query: str
    expected_chunk_ids_snapshot: list[int]
    expected_tools_snapshot: list[str]  # Sourced directly from dedicated column
    ground_truth_answer_snapshot: Optional[str]
    actual_output: dict[str, Any]  # Contains retrieved_chunks with full content
    metrics: dict[str, Any]
    duration_ms: float
    tokens_used: Optional[int]


# --- Run Read Schemas ---
class EvaluationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    dataset_id: Optional[int]
    experiment_id: Optional[int]
    name: str
    eval_type: str
    status: str
    system_configuration: dict[str, Any]
    dataset_snapshot: dict[str, Any]
    summary_metrics: dict[str, Any]
    total_items: int
    completed_items: int
    duration_ms: float
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]


class EvaluationRunDetail(EvaluationRunRead):
    item_results: list[EvaluationItemResultRead] = Field(default_factory=list)
