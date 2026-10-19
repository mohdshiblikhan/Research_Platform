from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


# --- LLM Output Schemas ---

class ResearchGap(BaseModel):
    """A gap identified in the existing literature."""
    id: str = Field(..., description="Unique gap identifier, e.g. G1")
    description: str = Field(..., description="Description of the unexplored problem or limitation")
    evidence: list[str] = Field(..., description="Verifiable observations from the analyzed papers or evidence")
    source_documents: list[int] = Field(..., description="Document IDs where this gap or related limitation was observed")


class ResearchHypothesis(BaseModel):
    """A testable hypothesis addressing one or more gaps."""
    id: str = Field(..., description="Unique hypothesis identifier, e.g. H1")
    statement: str = Field(..., description="The testable hypothesis statement")
    addresses_gaps: list[str] = Field(..., description="Gap IDs this hypothesis addresses, e.g. ['G1']")
    rationale: str = Field(..., description="Why this hypothesis is plausible based on literature")


class ProposedExperiment(BaseModel):
    """A concrete experiment proposed to test a hypothesis."""
    id: str = Field(..., description="Unique experiment identifier, e.g. E1")
    title: str = Field(..., description="Concise title for the experiment")
    hypothesis: str = Field(..., description="Hypothesis ID this experiment evaluates, e.g. 'H1'")
    method: str = Field(..., description="Proposed methodology and experimental setup")
    datasets: Optional[str] = Field(default=None, description="Suggested evaluation datasets or benchmarks")
    metrics: list[str] = Field(..., description="Metrics to measure outcome, e.g. ['Recall@10', 'MRR']")
    priority: Literal["high", "medium", "low"] = Field(..., description="Experimental priority")


class ResearchPlanOutput(BaseModel):
    """The structured LLM generation output."""
    reasoning: str = Field(..., description="Chain-of-thought analysis linking literature to gaps, hypotheses, and experiments")
    literature_summary: str = Field(..., description="Synthesis of what the analyzed papers establish")
    gaps: list[ResearchGap] = Field(..., description="List of identified gaps in the literature")
    hypotheses: list[ResearchHypothesis] = Field(..., description="List of hypotheses addressing the gaps")
    experiments: list[ProposedExperiment] = Field(..., description="List of proposed experiments")
    recommended_sequence: list[str] = Field(..., description="Recommended execution order of experiment IDs, e.g. ['E1', 'E2']")
    confidence: Literal["high", "medium", "low"] = Field(..., description="Confidence in the plan based on evidence")
    limitations: str = Field(..., description="Scope boundaries and caveats of this plan (e.g., bounded corpus)")


# --- API Request/Response Schemas ---

class ResearchPlanRequest(BaseModel):
    """Request body for generating a research plan."""
    research_question: str = Field(..., min_length=10, max_length=2000, description="The research question to plan for")
    document_ids: Optional[list[int]] = Field(
        default=None,
        max_length=15,
        description="Optional list of document IDs to analyze. If omitted, all documents with extractions in the project are used."
    )


class ResearchPlanResponse(BaseModel):
    """Full response for a generated or retrieved research plan."""
    id: int
    project_id: int
    research_question: str
    documents_analyzed: int
    documents_without_extraction: list[int]
    document_ids_used: list[int]

    # The structured plan
    reasoning: str
    literature_summary: str
    gaps: list[ResearchGap]
    hypotheses: list[ResearchHypothesis]
    experiments: list[ProposedExperiment]
    recommended_sequence: list[str]
    confidence: str
    limitations: str

    # Timing and metadata
    comparison_time_ms: Optional[float] = None
    retrieval_time_ms: Optional[float] = None
    planning_time_ms: float
    total_time_ms: float
    llm_model: str
    created_at: datetime


class ResearchPlanSummary(BaseModel):
    """Lightweight summary schema for listing research plans."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    research_question: str
    documents_analyzed: int
    confidence: str
    created_at: datetime
