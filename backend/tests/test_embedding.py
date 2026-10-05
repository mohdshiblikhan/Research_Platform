import pytest

from app.models.document import DocumentStatus
from app.models.chunk import Chunk

def test_embed_document_success(client, db_session, sample_pdf):
    # Create project
    res = client.post("/api/projects", json={"title": "Test Project"})
    assert res.status_code == 201
    project_id = res.json()["id"]

    # Upload document
    res = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": sample_pdf}
    )
    assert res.status_code == 201
    document_id = res.json()["id"]

    # Process document
    res = client.post(f"/api/projects/{project_id}/documents/{document_id}/process")
    assert res.status_code == 200

    # Verify chunks have no embeddings initially
    chunks = db_session.query(Chunk).filter_by(document_id=document_id).all()
    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.embedding is None

    # Embed document
    res = client.post(f"/api/projects/{project_id}/documents/{document_id}/embed")
    assert res.status_code == 200
    data = res.json()
    assert data["document_id"] == document_id
    assert data["chunks_embedded"] == len(chunks)
    assert data["embedding_dimension"] == 384

    # Verify chunks now have embeddings
    db_session.expire_all()
    chunks = db_session.query(Chunk).filter_by(document_id=document_id).all()
    for chunk in chunks:
        assert chunk.embedding is not None


def test_embed_unprocessed_document_returns_400(client, db_session, sample_pdf):
    # Create project
    res = client.post("/api/projects", json={"title": "Test Project"})
    project_id = res.json()["id"]

    # Upload document (status: uploaded)
    res = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": sample_pdf}
    )
    document_id = res.json()["id"]

    # Try to embed without processing
    res = client.post(f"/api/projects/{project_id}/documents/{document_id}/embed")
    assert res.status_code == 400
    assert "Only documents with status 'processed' can be embedded" in res.json()["detail"]


def test_embed_nonexistent_project_returns_404(client):
    res = client.post(f"/api/projects/999/documents/1/embed")
    assert res.status_code == 404
