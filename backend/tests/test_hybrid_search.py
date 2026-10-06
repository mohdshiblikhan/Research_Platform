import pytest

def test_hybrid_search_success(client, sample_pdf):
    # Setup: Create project, upload, process, and embed
    res = client.post("/api/projects", json={"title": "Hybrid Test Project"})
    project_id = res.json()["id"]

    res = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": sample_pdf}
    )
    document_id = res.json()["id"]

    client.post(f"/api/projects/{project_id}/documents/{document_id}/process")
    client.post(f"/api/projects/{project_id}/documents/{document_id}/embed")

    # Perform hybrid search
    search_res = client.get(
        f"/api/projects/{project_id}/search",
        params={"q": "research platform", "mode": "hybrid"}
    )
    
    assert search_res.status_code == 200
    data = search_res.json()
    assert data["search_mode"] == "hybrid"
    assert data["total_results"] > 0
    
    # Check result item structure
    first_result = data["results"][0]
    assert first_result["rrf_score"] is not None
    assert first_result["rrf_score"] > 0.0


def test_hybrid_search_without_embeddings_returns_keyword_results(client, sample_pdf):
    # Setup: Create project, upload, process, but DO NOT embed
    res = client.post("/api/projects", json={"title": "No Embed Project"})
    project_id = res.json()["id"]

    res = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": sample_pdf}
    )
    document_id = res.json()["id"]

    client.post(f"/api/projects/{project_id}/documents/{document_id}/process")

    # Perform hybrid search
    search_res = client.get(
        f"/api/projects/{project_id}/search",
        params={"q": "platform", "mode": "hybrid"}
    )
    
    assert search_res.status_code == 200
    data = search_res.json()
    assert data["total_results"] > 0
    
    first_result = data["results"][0]
    assert first_result["rrf_score"] is not None
    # since no embeddings, semantic_similarity should be None
    assert first_result["similarity_score"] is None
