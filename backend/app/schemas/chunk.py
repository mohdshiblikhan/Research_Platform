from datetime import datetime

from pydantic import BaseModel


class ChunkRead(BaseModel):
    """Data returned to the client for a single chunk."""

    id: int
    document_id: int
    chunk_index: int
    content: str
    page_start: int
    page_end: int
    char_offset_start: int
    char_offset_end: int
    chunk_size: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProcessingResult(BaseModel):
    """Returned after a document is successfully processed.

    Provides the document metadata alongside a summary of the
    processing outcome (how many chunks were created).
    """

    document_id: int
    filename: str
    status: str
    page_count: int
    chunk_count: int

    model_config = {"from_attributes": True}
