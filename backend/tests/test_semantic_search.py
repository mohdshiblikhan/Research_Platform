import pytest

def test_semantic_search_success(client, sample_pdf):
    # Setup: Create project, upload, process, and embed
    res = client.post("/api/projects", json={"title": "Search Test Project"})
    project_id = res.json()["id"]

    res = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": sample_pdf}
    )
    document_id = res.json()["id"]

    client.post(f"/api/projects/{project_id}/documents/{document_id}/process")
    client.post(f"/api/projects/{project_id}/documents/{document_id}/embed")

    # Perform semantic search
    search_res = client.get(
        f"/api/projects/{project_id}/search",
        params={"q": "research platform", "mode": "semantic"}
    )
    
    assert search_res.status_code == 200
    data = search_res.json()
    assert data["search_mode"] == "semantic"
    assert data["total_results"] > 0
    
    # Check result item structure
    first_result = data["results"][0]
    assert first_result["headline"] is None
    assert first_result["rank"] is None
    assert first_result["similarity_score"] is not None
    assert 0.0 <= first_result["similarity_score"] <= 1.0


def test_semantic_search_without_embeddings_returns_empty(client, sample_pdf):
    # Setup: Create project, upload, process, but DO NOT embed
    res = client.post("/api/projects", json={"title": "Empty Embed Project"})
    project_id = res.json()["id"]

    res = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": sample_pdf}
    )
    document_id = res.json()["id"]

    client.post(f"/api/projects/{project_id}/documents/{document_id}/process")

    # Perform semantic search
    search_res = client.get(
        f"/api/projects/{project_id}/search",
        params={"q": "test", "mode": "semantic"}
    )
    
    assert search_res.status_code == 200
    data = search_res.json()
    assert data["total_results"] == 0
    assert len(data["results"]) == 0


def test_invalid_mode_returns_422(client):
    search_res = client.get(
        f"/api/projects/1/search",
        params={"q": "test", "mode": "invalid_mode"}
    )
    assert search_res.status_code == 422
    assert "String should match pattern" in search_res.json()["detail"][0]["msg"]
