from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ExtractionBase(BaseModel):
    research_problem: Optional[str] = Field(None, description="The main research problem or question addressed by the paper.")
    methodology: Optional[str] = Field(None, description="The approach or methodology used in the paper.")
    models_used: Optional[str] = Field(None, description="The machine learning models or architectures used or proposed.")
    datasets: Optional[str] = Field(None, description="The datasets used for training or evaluation.")
    evaluation_metrics: Optional[str] = Field(None, description="The metrics used to evaluate the models.")
    results: Optional[str] = Field(None, description="The main findings or results of the experiments.")
    limitations: Optional[str] = Field(None, description="The limitations or future work mentioned in the paper.")
    baselines: Optional[str] = Field(None, description="The baseline methods compared against in the paper.")


class ExtractionCreate(ExtractionBase):
    """Schema for validating LLM output and creating database records."""
    pass


class ExtractionRead(ExtractionBase):
    """Schema for returning extraction results via API."""
    id: int
    document_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ExtractionWithRawRead(ExtractionRead):
    """Schema that includes the raw LLM output, useful for debugging."""
    raw_llm_output: Optional[Dict[str, Any]] = None
