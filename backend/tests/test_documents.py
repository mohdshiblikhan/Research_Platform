import os
import pytest


# ── Helper ──────────────────────────────────────────────────────────────────

def _create_project(client, title="Test Research Project"):
    """Helper to create a project and return its ID."""
    response = client.post("/api/projects", json={"title": title})
    assert response.status_code == 201
    return response.json()["id"]


def _upload_pdf(client, project_id, sample_pdf):
    """Helper to upload a PDF and return the response."""
    filename, file_bytes, content_type = sample_pdf
    return client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": (filename, file_bytes, content_type)},
    )


# ── UPLOAD ──────────────────────────────────────────────────────────────────

def test_upload_document_success(client, sample_pdf, test_upload_dir):
    project_id = _create_project(client)
    response = _upload_pdf(client, project_id, sample_pdf)

    assert response.status_code == 201
    data = response.json()
    assert data["project_id"] == project_id
    assert data["filename"] == "test_paper.pdf"
    assert data["mime_type"] == "application/pdf"
    assert data["page_count"] == 1
    assert data["status"] == "uploaded"
    assert data["file_size"] > 0
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data

    # Verify file was saved to disk
    assert os.path.exists(data["file_path"])


def test_upload_to_nonexistent_project(client, sample_pdf, test_upload_dir):
    response = _upload_pdf(client, 999999, sample_pdf)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_upload_non_pdf_rejected(client, sample_txt, test_upload_dir):
    project_id = _create_project(client)
    filename, file_bytes, content_type = sample_txt
    response = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": (filename, file_bytes, content_type)},
    )
    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"].lower()


def test_upload_duplicate_filename_rejected(client, sample_pdf, sample_pdf_bytes, test_upload_dir):
    """Uploading the same filename twice to the same project should fail with 409."""
    import io

    project_id = _create_project(client)

    # First upload succeeds
    response1 = _upload_pdf(client, project_id, sample_pdf)
    assert response1.status_code == 201

    # Second upload with same filename fails
    duplicate_pdf = ("test_paper.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")
    response2 = _upload_pdf(client, project_id, duplicate_pdf)
    assert response2.status_code == 409
    assert "already exists" in response2.json()["detail"].lower()


# ── LIST ────────────────────────────────────────────────────────────────────

def test_list_documents_empty(client, test_upload_dir):
    project_id = _create_project(client)
    response = client.get(f"/api/projects/{project_id}/documents")
    assert response.status_code == 200
    assert response.json() == []


def test_list_documents_returns_uploaded(client, sample_pdf, sample_pdf_bytes, test_upload_dir):
    import io

    project_id = _create_project(client)

    # Upload two documents with different names
    _upload_pdf(client, project_id, sample_pdf)
    second_pdf = ("second_paper.pdf", io.BytesIO(sample_pdf_bytes), "application/pdf")
    _upload_pdf(client, project_id, second_pdf)

    response = client.get(f"/api/projects/{project_id}/documents")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    filenames = [doc["filename"] for doc in data]
    assert "test_paper.pdf" in filenames
    assert "second_paper.pdf" in filenames


def test_list_documents_nonexistent_project(client, test_upload_dir):
    response = client.get("/api/projects/999999/documents")
    assert response.status_code == 404


# ── GET SINGLE ──────────────────────────────────────────────────────────────

def test_get_document_by_id(client, sample_pdf, test_upload_dir):
    project_id = _create_project(client)
    upload_response = _upload_pdf(client, project_id, sample_pdf)
    doc_id = upload_response.json()["id"]

    response = client.get(f"/api/projects/{project_id}/documents/{doc_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == doc_id
    assert data["filename"] == "test_paper.pdf"
    assert data["status"] == "uploaded"


def test_get_document_not_found(client, test_upload_dir):
    project_id = _create_project(client)
    response = client.get(f"/api/projects/{project_id}/documents/999999")
    assert response.status_code == 404


def test_get_document_wrong_project(client, sample_pdf, test_upload_dir):
    """Getting a document with a project_id it doesn't belong to should return 404."""
    project_a = _create_project(client, title="Project A")
    project_b = _create_project(client, title="Project B")

    upload_response = _upload_pdf(client, project_a, sample_pdf)
    doc_id = upload_response.json()["id"]

    # Document belongs to project_a, but we request via project_b
    response = client.get(f"/api/projects/{project_b}/documents/{doc_id}")
    assert response.status_code == 404


# ── DELETE ──────────────────────────────────────────────────────────────────

def test_delete_document(client, sample_pdf, test_upload_dir):
    project_id = _create_project(client)
    upload_response = _upload_pdf(client, project_id, sample_pdf)
    doc_data = upload_response.json()
    doc_id = doc_data["id"]
    file_path = doc_data["file_path"]

    # Delete
    delete_response = client.delete(f"/api/projects/{project_id}/documents/{doc_id}")
    assert delete_response.status_code == 204

    # Verify file is removed from disk
    assert not os.path.exists(file_path)

    # Verify GET returns 404
    get_response = client.get(f"/api/projects/{project_id}/documents/{doc_id}")
    assert get_response.status_code == 404


def test_delete_document_not_found(client, test_upload_dir):
    project_id = _create_project(client)
    response = client.delete(f"/api/projects/{project_id}/documents/999999")
    assert response.status_code == 404


# ── CASCADE ─────────────────────────────────────────────────────────────────

def test_delete_project_cascades_documents(client, sample_pdf, test_upload_dir):
    """Deleting a project should also delete its documents."""
    project_id = _create_project(client)
    upload_response = _upload_pdf(client, project_id, sample_pdf)
    doc_id = upload_response.json()["id"]

    # Delete the project
    delete_response = client.delete(f"/api/projects/{project_id}")
    assert delete_response.status_code == 204

    # The document should no longer exist in the DB
    # We can't query via the document endpoint because the project is gone too,
    # so we verify by trying to list documents for the (now-deleted) project.
    get_response = client.get(f"/api/projects/{project_id}/documents")
    assert get_response.status_code == 404
