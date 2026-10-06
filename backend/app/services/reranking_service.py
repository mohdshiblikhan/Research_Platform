import logging
from typing import Optional

from sentence_transformers import CrossEncoder

from app.schemas.search import SearchResultItem

logger = logging.getLogger(__name__)


class RerankingService:
    """
    Reranks search results using a CrossEncoder model.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """Initialize the RerankingService.

        Args:
            model_name: The HuggingFace model identifier for the cross-encoder.
        """
        logger.info(f"Initializing RerankingService with model: {model_name}")
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, results: list[SearchResultItem]) -> list[SearchResultItem]:
        """
        Rerank a list of SearchResultItems using the cross-encoder model.

        Args:
            query: The user's search query.
            results: The candidate items to rerank.

        Returns:
            A new list of SearchResultItems sorted by rerank_score descending.
        """
        if not results:
            return []

        # Create pairs of (query, document_text)
        pairs = [[query, item.content] for item in results]

        # Predict scores
        # Returns a numpy array of scores (or a single float if only 1 pair is provided)
        scores = self.model.predict(pairs)

        if isinstance(scores, float) or scores.ndim == 0:
            scores = [float(scores)]
        else:
            scores = scores.tolist()

        # We ensure length match explicitly
        if len(scores) != len(results):
            logger.error(
                "Length mismatch in reranking: "
                f"{len(scores)} scores for {len(results)} results"
            )
            raise ValueError("Model returned an incorrect number of scores.")

        # Attach scores and sort
        reranked_results = []
        for item, score in zip(results, scores):
            # Mutate the existing item to add the score
            item.rerank_score = round(float(score), 4)
            reranked_results.append(item)

        reranked_results.sort(key=lambda x: x.rerank_score, reverse=True)
        return reranked_results


# Singleton instance
_reranking_service: Optional[RerankingService] = None


def get_reranking_service() -> RerankingService:
    """Factory to get the singleton RerankingService instance."""
    global _reranking_service
    if _reranking_service is None:
        _reranking_service = RerankingService()
    return _reranking_service
