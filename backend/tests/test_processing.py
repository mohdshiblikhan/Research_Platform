"""Integration tests for Milestone 3: PDF Processing & Chunking.

Tests cover:
- Document processing (text extraction + chunking)
- Status lifecycle (uploaded → processing → processed / failed)
- Chunk provenance (page numbers, char offsets, ordering)
- Chunk retrieval endpoints (list + get single)
- Error cases (already processed, not found, wrong project)
- Cascade delete (document deletion removes chunks)
"""

import io
import pytest


# ── Helpers ─────────────────────────────────────────────────────────────────


def _create_project(client, title="Processing Test Project"):
    """Create a project and return its ID."""
    response = client.post("/api/projects", json={"title": title})
    assert response.status_code == 201
    return response.json()["id"]


def _upload_pdf(client, project_id, pdf_tuple):
    """Upload a PDF and return the response JSON."""
    filename, file_bytes, content_type = pdf_tuple
    response = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": (filename, file_bytes, content_type)},
    )
    assert response.status_code == 201
    return response.json()


def _process_document(client, project_id, document_id):
    """Trigger document processing and return the response."""
    return client.post(
        f"/api/projects/{project_id}/documents/{document_id}/process"
    )


# ── PROCESSING: Happy Path ─────────────────────────────────────────────────


def test_process_single_page_document(client, sample_pdf, test_upload_dir):
    """Process a 1-page PDF: status should become 'processed', chunks created."""
    project_id = _create_project(client)
    doc = _upload_pdf(client, project_id, sample_pdf)

    response = _process_document(client, project_id, doc["id"])
    assert response.status_code == 200

    data = response.json()
    assert data["document_id"] == doc["id"]
    assert data["status"] == "processed"
    assert data["chunk_count"] >= 1
    assert data["page_count"] == 1

    # Verify document status updated in DB
    doc_response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}"
    )
    assert doc_response.json()["status"] == "processed"


def test_process_multipage_document(
    client, sample_multipage_pdf, test_upload_dir
):
    """Process a 3-page PDF: chunks should have correct page provenance."""
    project_id = _create_project(client)
    doc = _upload_pdf(client, project_id, sample_multipage_pdf)

    response = _process_document(client, project_id, doc["id"])
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "processed"
    assert data["page_count"] == 3
    assert data["chunk_count"] >= 1

    # Verify chunks via the list endpoint
    chunks_response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}/chunks"
    )
    assert chunks_response.status_code == 200
    chunks = chunks_response.json()
    assert len(chunks) == data["chunk_count"]


# ── CHUNK PROVENANCE ────────────────────────────────────────────────────────


def test_chunk_has_correct_provenance(
    client, sample_multipage_pdf, test_upload_dir
):
    """Each chunk should have valid page_start, page_end, and char offsets."""
    project_id = _create_project(client)
    doc = _upload_pdf(client, project_id, sample_multipage_pdf)
    _process_document(client, project_id, doc["id"])

    chunks_response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}/chunks"
    )
    chunks = chunks_response.json()

    for chunk in chunks:
        # Page numbers should be 1-based and valid
        assert chunk["page_start"] >= 1
        assert chunk["page_end"] >= chunk["page_start"]
        assert chunk["page_end"] <= 3

        # Char offsets should be non-negative
        assert chunk["char_offset_start"] >= 0
        assert chunk["char_offset_end"] > chunk["char_offset_start"]

        # chunk_size should match content length
        assert chunk["chunk_size"] == len(chunk["content"])

        # Content should not be empty
        assert len(chunk["content"]) > 0


def test_chunks_are_sequentially_indexed(
    client, sample_multipage_pdf, test_upload_dir
):
    """chunk_index should be 0, 1, 2, ... in order."""
    project_id = _create_project(client)
    doc = _upload_pdf(client, project_id, sample_multipage_pdf)
    _process_document(client, project_id, doc["id"])

    chunks_response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}/chunks"
    )
    chunks = chunks_response.json()

    indices = [c["chunk_index"] for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_content_contains_original_text(
    client, sample_multipage_pdf, test_upload_dir
):
    """The chunks, when concatenated (accounting for overlap), should
    contain the original page text."""
    project_id = _create_project(client)
    doc = _upload_pdf(client, project_id, sample_multipage_pdf)
    _process_document(client, project_id, doc["id"])

    chunks_response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}/chunks"
    )
    chunks = chunks_response.json()

    # The first chunk should contain text from page 1
    all_text = " ".join(c["content"] for c in chunks)
    assert "Page one content" in all_text
    assert "Page two content" in all_text
    assert "Page three content" in all_text


# ── CHUNK RETRIEVAL ENDPOINTS ──────────────────────────────────────────────


def test_list_chunks_for_unprocessed_document(
    client, sample_pdf, test_upload_dir
):
    """Listing chunks for a document that hasn't been processed returns empty list."""
    project_id = _create_project(client)
    doc = _upload_pdf(client, project_id, sample_pdf)

    response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}/chunks"
    )
    assert response.status_code == 200
    assert response.json() == []


def test_get_single_chunk(client, sample_multipage_pdf, test_upload_dir):
    """GET .../chunks/{chunk_id} returns the correct chunk."""
    project_id = _create_project(client)
    doc = _upload_pdf(client, project_id, sample_multipage_pdf)
    _process_document(client, project_id, doc["id"])

    # List chunks and pick the first one
    chunks_response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}/chunks"
    )
    chunks = chunks_response.json()
    first_chunk = chunks[0]

    # Get it individually
    response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}/chunks/{first_chunk['id']}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == first_chunk["id"]
    assert data["content"] == first_chunk["content"]
    assert data["chunk_index"] == 0


def test_get_chunk_not_found(client, sample_pdf, test_upload_dir):
    """Getting a nonexistent chunk returns 404."""
    project_id = _create_project(client)
    doc = _upload_pdf(client, project_id, sample_pdf)

    response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}/chunks/999999"
    )
    assert response.status_code == 404


def test_get_chunk_wrong_document(
    client, sample_pdf, sample_multipage_pdf, test_upload_dir
):
    """Getting a chunk with a document_id it doesn't belong to returns 404."""
    project_id = _create_project(client)
    doc_a = _upload_pdf(client, project_id, sample_pdf)
    doc_b = _upload_pdf(client, project_id, sample_multipage_pdf)

    # Process doc_b to create chunks
    _process_document(client, project_id, doc_b["id"])

    chunks_response = client.get(
        f"/api/projects/{project_id}/documents/{doc_b['id']}/chunks"
    )
    chunk_id = chunks_response.json()[0]["id"]

    # Try to access doc_b's chunk via doc_a's URL
    response = client.get(
        f"/api/projects/{project_id}/documents/{doc_a['id']}/chunks/{chunk_id}"
    )
    assert response.status_code == 404


# ── ERROR CASES ─────────────────────────────────────────────────────────────


def test_process_already_processed_document(
    client, sample_pdf, test_upload_dir
):
    """Processing a document that's already 'processed' should return 400."""
    project_id = _create_project(client)
    doc = _upload_pdf(client, project_id, sample_pdf)

    # Process once — should succeed
    response1 = _process_document(client, project_id, doc["id"])
    assert response1.status_code == 200

    # Process again — should fail
    response2 = _process_document(client, project_id, doc["id"])
    assert response2.status_code == 400
    assert "cannot be processed" in response2.json()["detail"].lower()


def test_process_nonexistent_document(client, test_upload_dir):
    """Processing a nonexistent document returns 404."""
    project_id = _create_project(client)
    response = _process_document(client, project_id, 999999)
    assert response.status_code == 404


def test_process_document_wrong_project(
    client, sample_pdf, test_upload_dir
):
    """Processing a document with a project_id it doesn't belong to returns 404."""
    project_a = _create_project(client, title="Project A")
    project_b = _create_project(client, title="Project B")

    doc = _upload_pdf(client, project_a, sample_pdf)

    response = _process_document(client, project_b, doc["id"])
    assert response.status_code == 404


def test_process_nonexistent_project(client, test_upload_dir):
    """Processing with a nonexistent project_id returns 404."""
    response = _process_document(client, 999999, 1)
    assert response.status_code == 404


# ── CASCADE DELETE ──────────────────────────────────────────────────────────


def test_delete_document_removes_chunks(
    client, sample_multipage_pdf, test_upload_dir
):
    """Deleting a processed document should also delete its chunks."""
    project_id = _create_project(client)
    doc = _upload_pdf(client, project_id, sample_multipage_pdf)
    _process_document(client, project_id, doc["id"])

    # Verify chunks exist
    chunks_response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}/chunks"
    )
    assert len(chunks_response.json()) > 0

    # Delete the document
    delete_response = client.delete(
        f"/api/projects/{project_id}/documents/{doc['id']}"
    )
    assert delete_response.status_code == 204

    # Chunks should be gone (document is gone, so 404 on the chunks endpoint)
    chunks_response = client.get(
        f"/api/projects/{project_id}/documents/{doc['id']}/chunks"
    )
    assert chunks_response.status_code == 404
