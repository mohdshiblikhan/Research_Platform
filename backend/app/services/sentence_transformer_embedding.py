from app.services.embedding_service import EmbeddingService


class SentenceTransformerEmbeddingService(EmbeddingService):
    """Local embedding using sentence-transformers."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        # Import inside the constructor to avoid loading PyTorch during early app startup
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self._dimension = self._model.get_embedding_dimension()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(texts, batch_size=64, show_progress_bar=False)
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]

    def get_dimension(self) -> int:
        return self._dimension
