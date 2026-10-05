from pydantic import BaseModel


class EmbeddingResponse(BaseModel):
    """Response from the embed endpoint."""

    document_id: int
    filename: str
    chunks_embedded: int
    embedding_model: str
    embedding_dimension: int
    embedding_time_ms: float
