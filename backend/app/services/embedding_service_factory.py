from typing import Optional

from app.core.config import settings
from app.services.embedding_service import EmbeddingService
from app.services.sentence_transformer_embedding import SentenceTransformerEmbeddingService

_instance: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _instance
    if _instance is None:
        _instance = SentenceTransformerEmbeddingService(settings.embedding_model)
    return _instance
