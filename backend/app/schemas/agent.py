from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class AgentResearchRequest(BaseModel):
    """Request payload to initiate an agentic research session."""
    research_question: str = Field(..., min_length=1, max_length=2000, description="The research question to investigate")
    max_iterations: Optional[int] = Field(default=None, ge=1, le=20, description="Override maximum ReAct loop iterations")
    max_tool_calls: Optional[int] = Field(default=None, ge=1, le=50, description="Override maximum tool calls across session")
    max_time_seconds: Optional[int] = Field(default=None, ge=10, le=600, description="Override maximum execution timeout in seconds")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Override model temperature for the agent")


class AgentToolCallRecord(BaseModel):
    """Record of an individual tool call executed by the agent."""
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool
    result_summary: str = Field(default="", description="Truncated observation summary returned to agent context")
    execution_time_ms: float = 0.0
    error: Optional[str] = None


class AgentStepRecord(BaseModel):
    """An observable step in the agent's trajectory."""
    iteration: int
    action_type: str = Field(..., description="'tool_call', 'duplicate_skipped', 'final_answer', or 'forced_synthesis'")
    tool_calls: list[AgentToolCallRecord] = Field(default_factory=list)
    observation_summary: Optional[str] = None
    tokens_used: Optional[int] = None
    iteration_time_ms: float = 0.0


class AgentCitation(BaseModel):
    """Evidence citation grounding a research answer or claim."""
    chunk_id: Optional[int] = None
    document_id: Optional[int] = None
    filename: Optional[str] = None
    page_number: Optional[int] = None
    claim: Optional[str] = None


class AgentResearchResponse(BaseModel):
    """Full response representing a completed or terminated agent research session."""
    session_id: int
    project_id: int
    research_question: str
    status: str = Field(..., description="'completed', 'failed', 'max_iterations', 'max_tool_calls', 'timeout'")
    final_answer: Optional[str] = None
    citations: list[AgentCitation] = Field(default_factory=list)
    trajectory: list[AgentStepRecord] = Field(default_factory=list)
    total_iterations: int = 0
    total_tool_calls: int = 0
    total_tokens_used: int = 0
    total_time_ms: float = 0.0
    model_used: str = ""
    stop_reason: str = ""
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AgentSessionSummary(BaseModel):
    """Summary of an agent session for listing endpoints."""
    session_id: int
    project_id: int
    research_question: str
    status: str
    total_iterations: int = 0
    total_tool_calls: int = 0
    total_time_ms: float = 0.0
    stop_reason: str = ""
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
