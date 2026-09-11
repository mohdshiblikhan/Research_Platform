import pytest


# ── CREATE ──────────────────────────────────────────────────────────────────

def test_create_project_success(client):
    response = client.post("/api/projects", json={"title": "RAG Hallucination Research"})
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "RAG Hallucination Research"
    assert data["description"] is None
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_create_project_with_description(client):
    response = client.post("/api/projects", json={
        "title": "Semantic Search Benchmarks",
        "description": "Comparing dense vs sparse retrieval approaches"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Semantic Search Benchmarks"
    assert data["description"] == "Comparing dense vs sparse retrieval approaches"


def test_create_project_missing_title(client):
    """Title is required. FastAPI/Pydantic should return 422 Unprocessable Entity."""
    response = client.post("/api/projects", json={"description": "No title provided"})
    assert response.status_code == 422


# ── LIST ────────────────────────────────────────────────────────────────────

def test_list_projects_empty(client):
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert response.json() == []


def test_list_projects_returns_created(client):
    client.post("/api/projects", json={"title": "Project Alpha"})
    client.post("/api/projects", json={"title": "Project Beta"})

    response = client.get("/api/projects")
    assert response.status_code == 200
    titles = [p["title"] for p in response.json()]
    assert "Project Alpha" in titles
    assert "Project Beta" in titles


# ── GET BY ID ───────────────────────────────────────────────────────────────

def test_get_project_by_id(client):
    create_response = client.post("/api/projects", json={"title": "Retrieve Me"})
    project_id = create_response.json()["id"]

    response = client.get(f"/api/projects/{project_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Retrieve Me"


def test_get_project_not_found(client):
    response = client.get("/api/projects/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


# ── UPDATE ──────────────────────────────────────────────────────────────────

def test_update_project_title(client):
    create_response = client.post("/api/projects", json={
        "title": "Old Title",
        "description": "Some description"
    })
    project_id = create_response.json()["id"]

    response = client.patch(f"/api/projects/{project_id}", json={"title": "New Title"})
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "New Title"
    # Description should be unchanged because we used exclude_unset=True
    assert data["description"] == "Some description"


def test_update_project_not_found(client):
    response = client.patch("/api/projects/999999", json={"title": "Ghost"})
    assert response.status_code == 404


# ── DELETE ───────────────────────────────────────────────────────────────────

def test_delete_project(client):
    create_response = client.post("/api/projects", json={"title": "Delete Me"})
    project_id = create_response.json()["id"]

    delete_response = client.delete(f"/api/projects/{project_id}")
    assert delete_response.status_code == 204

    # Confirm it's gone
    get_response = client.get(f"/api/projects/{project_id}")
    assert get_response.status_code == 404


def test_delete_project_not_found(client):
    response = client.delete("/api/projects/999999")
    assert response.status_code == 404
