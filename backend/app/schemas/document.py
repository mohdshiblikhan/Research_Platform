from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentRead(BaseModel):
    """Data returned to the client for a document."""

    id: int
    project_id: int
    filename: str
    file_path: str
    file_size: int
    mime_type: str
    page_count: Optional[int]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
