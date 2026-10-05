from abc import ABC, abstractmethod


class EmbeddingService(ABC):
    """Abstract interface for text embedding providers."""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into vectors.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each a list of floats).
            Output order matches input order.
        """
        pass

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """Embed a single search query.

        Some models use different prefixes for queries vs documents.
        Default: delegates to embed_texts([query])[0].
        """
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        """Return the embedding dimension."""
        pass
