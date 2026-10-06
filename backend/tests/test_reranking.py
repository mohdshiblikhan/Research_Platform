import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from app.services.reranking_service import RerankingService, get_reranking_service
from app.schemas.search import SearchResultItem


# -------------------------------------------------------------------
# 1. Unit tests for RerankingService
# -------------------------------------------------------------------

@pytest.fixture
def mock_cross_encoder():
    with patch("app.services.reranking_service.CrossEncoder") as MockClass:
        mock_instance = MagicMock()
        MockClass.return_value = mock_instance
        yield mock_instance

@pytest.fixture
def reranking_service(mock_cross_encoder):
    # This will initialize using the mocked CrossEncoder
    return RerankingService()

def build_mock_results(n: int) -> list[SearchResultItem]:
    return [
        SearchResultItem(
            chunk_id=i,
            document_id=1,
            document_filename="test.pdf",
            chunk_index=i,
            content=f"content {i}",
            page_start=1,
            page_end=1,
            char_offset_start=0,
            char_offset_end=10
        )
        for i in range(1, n + 1)
    ]

def test_empty_results_returns_empty(reranking_service, mock_cross_encoder):
    results = reranking_service.rerank("query", [])
    assert results == []
    mock_cross_encoder.predict.assert_not_called()

def test_single_candidate_receives_score(reranking_service, mock_cross_encoder):
    mock_cross_encoder.predict.return_value = np.array(0.75) # model can return 0d array for single pair
    
    candidates = build_mock_results(1)
    results = reranking_service.rerank("query", candidates)
    
    assert len(results) == 1
    assert results[0].rerank_score == 0.75
    
    # Assert correct pair passed
    mock_cross_encoder.predict.assert_called_once_with([["query", "content 1"]])

def test_every_candidate_receives_exactly_one_score_and_sorted(reranking_service, mock_cross_encoder):
    # Mocking scores such that candidate 2 is first, candidate 3 is second, candidate 1 is third.
    mock_cross_encoder.predict.return_value = np.array([0.2, 0.8, 0.5])
    
    candidates = build_mock_results(3)
    results = reranking_service.rerank("query", candidates)
    
    assert len(results) == 3
    # Check exact order
    assert results[0].chunk_id == 2
    assert results[0].rerank_score == 0.8
    assert results[1].chunk_id == 3
    assert results[1].rerank_score == 0.5
    assert results[2].chunk_id == 1
    assert results[2].rerank_score == 0.2
    
    # Assert batch predict
    mock_cross_encoder.predict.assert_called_once_with([
        ["query", "content 1"],
        ["query", "content 2"],
        ["query", "content 3"]
    ])

def test_length_mismatch_raises_error(reranking_service, mock_cross_encoder):
    mock_cross_encoder.predict.return_value = np.array([0.5, 0.6]) # Only 2 scores for 3 candidates
    
    candidates = build_mock_results(3)
    with pytest.raises(ValueError, match="Model returned an incorrect number of scores."):
        reranking_service.rerank("query", candidates)


# -------------------------------------------------------------------
# 2. SearchService / API Integration Tests
# -------------------------------------------------------------------

@pytest.fixture
def setup_project_with_docs(client, sample_pdf):
    res = client.post("/api/projects", json={"title": "Rerank Project"})
    project_id = res.json()["id"]

    res = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": sample_pdf}
    )
    document_id = res.json()["id"]

    client.post(f"/api/projects/{project_id}/documents/{document_id}/process")
    client.post(f"/api/projects/{project_id}/documents/{document_id}/embed")
    
    return project_id

def test_rerank_false_never_invokes_reranker(client, setup_project_with_docs):
    project_id = setup_project_with_docs
    
    with patch.object(RerankingService, "rerank") as mock_rerank:
        search_res = client.get(
            f"/api/projects/{project_id}/search",
            params={"q": "research", "mode": "keyword", "rerank": "false"}
        )
        assert search_res.status_code == 200
        mock_rerank.assert_not_called()
        
        data = search_res.json()
        if len(data["results"]) > 0:
            assert data["results"][0].get("rerank_score") is None


def test_rerank_true_populates_score_and_metrics(client, setup_project_with_docs):
    project_id = setup_project_with_docs
    
    search_res = client.get(
        f"/api/projects/{project_id}/search",
        params={"q": "research", "mode": "keyword", "rerank": "true"}
    )
    assert search_res.status_code == 200
    data = search_res.json()
    
    assert data["query_time_ms"] >= 0
    if len(data["results"]) > 0:
        assert data["results"][0].get("rerank_score") is not None

def test_rerank_empty_retrieval(client, setup_project_with_docs):
    project_id = setup_project_with_docs
    
    with patch.object(RerankingService, "rerank") as mock_rerank:
        search_res = client.get(
            f"/api/projects/{project_id}/search",
            params={"q": "a_query_that_matches_nothing_12345", "mode": "keyword", "rerank": "true"}
        )
        assert search_res.status_code == 200
        data = search_res.json()
        assert len(data["results"]) == 0
        mock_rerank.assert_not_called()

def test_pagination_operates_on_reranked_order():
    # To test that pagination slice happens AFTER reranking, we mock search_repo and vector_repo.
    # We will test this via the Service layer directly to easily inject mocks.
    from app.services.search_service import SearchService
    from unittest.mock import MagicMock

    db_mock = MagicMock()
    service = SearchService(db_mock)
    
    # Generate 20 candidates
    candidates = build_mock_results(20)
    
    # Mock search_repo to return all 20 candidates
    service.search_repo.search = MagicMock(return_value=(candidates, 20))
    
    # Mock RerankingService to reverse the order
    reversed_candidates = list(reversed(candidates))
    for i, c in enumerate(reversed_candidates):
        c.rerank_score = float(20 - i)
        
    service.reranking_service.rerank = MagicMock(return_value=reversed_candidates)
    
    # Request limit=10, offset=5
    response = service.search(
        project_id=1, 
        query="test", 
        mode="keyword", 
        rerank=True, 
        limit=10, 
        offset=5
    )
    
    # Check that search_repo was called with fetch_limit=60, fetch_offset=0
    service.search_repo.search.assert_called_once_with(
        project_id=1,
        query="test",
        document_id=None,
        limit=60,
        offset=0
    )
    
    # The output should be items 5 to 14 of the REVERSED list
    # The original IDs were 1 to 20.
    # Reversed IDs are 20, 19, 18, ...
    # So offset 5 means skipping 20, 19, 18, 17, 16.
    # The first item should have chunk_id 15.
    assert len(response.results) == 10
    assert response.results[0].chunk_id == 15
    assert response.results[-1].chunk_id == 6

# -------------------------------------------------------------------
# 5. Model Lifecycle
# -------------------------------------------------------------------

def test_reranking_service_is_singleton():
    service1 = get_reranking_service()
    service2 = get_reranking_service()
    assert service1 is service2
