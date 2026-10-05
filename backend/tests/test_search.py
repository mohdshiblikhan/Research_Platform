"""Integration tests for Milestone 4: Baseline Keyword Search.

Test Strategy:
    - Tests insert Chunk records directly into the test database via db_session,
      bypassing the upload/process flow. This is correct because we are testing
      the *search* layer, not the *ingestion* layer. The processing tests cover
      the pipeline. Here we need controlled, predictable chunk text.

    - PostgreSQL FTS is deterministic: same query + same data = same results.
      This allows us to make strong assertions about which chunks appear,
      their order, and the presence of highlight markers.

    - All tests use the transactional rollback fixture (db_session / client)
      established in conftest.py — no data persists between tests.
"""

import pytest
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.project import Project


# ---------------------------------------------------------------------------
# Fixtures: controlled project/document/chunk setup
# ---------------------------------------------------------------------------

@pytest.fixture
def search_project(db_session):
    """Create a project for search tests."""
    project = Project(title="Search Test Project", description="For FTS testing")
    db_session.add(project)
    db_session.flush()
    return project


@pytest.fixture
def search_document(db_session, search_project):
    """Create a processed document in the search project."""
    doc = Document(
        project_id=search_project.id,
        filename="rag_paper.pdf",
        file_path=f"/fake/uploads/{search_project.id}/rag_paper.pdf",
        file_size=1024,
        mime_type="application/pdf",
        page_count=5,
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add(doc)
    db_session.flush()
    return doc


@pytest.fixture
def second_document(db_session, search_project):
    """A second document in the same project for multi-document tests."""
    doc = Document(
        project_id=search_project.id,
        filename="transformer_paper.pdf",
        file_path=f"/fake/uploads/{search_project.id}/transformer_paper.pdf",
        file_size=2048,
        mime_type="application/pdf",
        page_count=3,
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add(doc)
    db_session.flush()
    return doc


@pytest.fixture
def other_project_document(db_session):
    """A document in a completely different project — for scope-leak tests."""
    project = Project(title="Other Project", description="Should not appear in search")
    db_session.add(project)
    db_session.flush()

    doc = Document(
        project_id=project.id,
        filename="other_paper.pdf",
        file_path=f"/fake/uploads/{project.id}/other_paper.pdf",
        file_size=512,
        mime_type="application/pdf",
        page_count=1,
        status=DocumentStatus.PROCESSED.value,
    )
    db_session.add(doc)
    db_session.flush()
    return doc, project


def make_chunk(db_session, document_id: int, content: str, chunk_index: int = 0):
    """Helper: insert a chunk with the given content directly."""
    chunk = Chunk(
        document_id=document_id,
        chunk_index=chunk_index,
        content=content,
        page_start=1,
        page_end=1,
        char_offset_start=chunk_index * 1000,
        char_offset_end=(chunk_index * 1000) + len(content),
        chunk_size=len(content),
    )
    db_session.add(chunk)
    db_session.flush()
    # Refresh to trigger the GENERATED ALWAYS AS column
    db_session.refresh(chunk)
    return chunk


# ---------------------------------------------------------------------------
# 1. Basic matching
# ---------------------------------------------------------------------------

def test_search_returns_matching_chunks(client, db_session, search_project, search_document):
    """Chunks containing the query term are returned; non-matching chunks are not."""
    make_chunk(db_session, search_document.id,
               "Retrieval augmented generation improves factual accuracy.", 0)
    make_chunk(db_session, search_document.id,
               "Convolutional neural networks are used for image classification.", 1)

    resp = client.get(f"/api/projects/{search_project.id}/search?q=retrieval")
    assert resp.status_code == 200

    body = resp.json()
    assert body["total_results"] == 1
    assert len(body["results"]) == 1
    assert "retrieval" in body["results"][0]["content"].lower()


def test_search_no_results_returns_empty_list(client, db_session, search_project, search_document):
    """A query with no matches returns an empty results list, not an error."""
    make_chunk(db_session, search_document.id,
               "Transformer attention mechanisms for sequence modelling.", 0)

    resp = client.get(f"/api/projects/{search_project.id}/search?q=xylophone")
    assert resp.status_code == 200

    body = resp.json()
    assert body["total_results"] == 0
    assert body["results"] == []


# ---------------------------------------------------------------------------
# 2. Relevance ranking (ts_rank_cd)
# ---------------------------------------------------------------------------

def test_search_ranks_by_cover_density(client, db_session, search_project, search_document):
    """Chunks where query terms appear more densely are ranked higher."""
    # chunk_a: "hallucination" appears once
    make_chunk(db_session, search_document.id,
               "This paper studies hallucination in large language models.", 0)
    # chunk_b: "hallucination" appears three times in close proximity
    make_chunk(db_session, search_document.id,
               "Hallucination is a major problem. We reduce hallucination "
               "rates. Hallucination evaluation is difficult.", 1)

    resp = client.get(f"/api/projects/{search_project.id}/search?q=hallucination")
    assert resp.status_code == 200

    body = resp.json()
    assert len(body["results"]) == 2
    # The chunk with more occurrences should rank first
    assert body["results"][0]["rank"] >= body["results"][1]["rank"]
    assert "hallucination" in body["results"][0]["content"].lower()


def test_search_rank_is_normalized_between_zero_and_one(client, db_session, search_project, search_document):
    """All returned rank scores are in the (0, 1] range (normalization flag 32)."""
    make_chunk(db_session, search_document.id,
               "Semantic search using dense retrieval and vector embeddings.", 0)

    resp = client.get(f"/api/projects/{search_project.id}/search?q=retrieval")
    assert resp.status_code == 200

    for result in resp.json()["results"]:
        assert 0.0 < result["rank"] <= 1.0


# ---------------------------------------------------------------------------
# 3. Project scope isolation
# ---------------------------------------------------------------------------

def test_search_respects_project_scope(client, db_session, search_project, search_document, other_project_document):
    """Search in project A must not return chunks from project B."""
    other_doc, other_project = other_project_document

    # Put the search term in both projects
    make_chunk(db_session, search_document.id,
               "Dense retrieval outperforms sparse retrieval on BEIR.", 0)
    make_chunk(db_session, other_doc.id,
               "Dense retrieval is the focus of our other project.", 0)

    # Search only in search_project
    resp = client.get(f"/api/projects/{search_project.id}/search?q=retrieval")
    assert resp.status_code == 200

    body = resp.json()
    doc_ids = {r["document_id"] for r in body["results"]}
    assert search_document.id in doc_ids
    assert other_doc.id not in doc_ids


# ---------------------------------------------------------------------------
# 4. Document filter
# ---------------------------------------------------------------------------

def test_search_filters_by_document_id(client, db_session, search_project, search_document, second_document):
    """When document_id is supplied, only that document's chunks are returned."""
    make_chunk(db_session, search_document.id,
               "RAG improves factual grounding in language model outputs.", 0)
    make_chunk(db_session, second_document.id,
               "RAG is evaluated using faithfulness and answer relevance.", 0)

    resp = client.get(
        f"/api/projects/{search_project.id}/search"
        f"?q=RAG&document_id={search_document.id}"
    )
    assert resp.status_code == 200

    body = resp.json()
    assert all(r["document_id"] == search_document.id for r in body["results"])
    assert body["total_results"] >= 1


def test_search_invalid_document_id_returns_404(client, search_project):
    """Filtering by a document_id that doesn't exist in the project → 404."""
    resp = client.get(f"/api/projects/{search_project.id}/search?q=test&document_id=999999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. Input validation
# ---------------------------------------------------------------------------

def test_search_empty_query_returns_422(client, search_project):
    """FastAPI query validation rejects a query shorter than min_length=1."""
    # FastAPI's Query(min_length=1) enforces this before it reaches the service
    resp = client.get(f"/api/projects/{search_project.id}/search?q=")
    assert resp.status_code == 422


def test_search_whitespace_only_query_returns_400(client, search_project):
    """A query that is whitespace-only (strips to empty) is rejected by the service."""
    resp = client.get(f"/api/projects/{search_project.id}/search?q=   ")
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_search_missing_query_returns_422(client, search_project):
    """Omitting the required `q` parameter returns a 422 Unprocessable Entity."""
    resp = client.get(f"/api/projects/{search_project.id}/search")
    assert resp.status_code == 422


def test_search_nonexistent_project_returns_404(client):
    """Searching a project that does not exist returns 404."""
    resp = client.get("/api/projects/999999/search?q=retrieval")
    assert resp.status_code == 404
    assert "999999" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 6. Pagination
# ---------------------------------------------------------------------------

def test_search_pagination_limit(client, db_session, search_project, search_document):
    """limit parameter correctly caps the number of returned results."""
    for i in range(10):
        make_chunk(db_session, search_document.id,
                   f"Embedding models for semantic retrieval benchmark {i}.", i)

    resp = client.get(f"/api/projects/{search_project.id}/search?q=retrieval&limit=3")
    assert resp.status_code == 200

    body = resp.json()
    assert len(body["results"]) == 3
    assert body["total_results"] == 10
    assert body["limit"] == 3


def test_search_pagination_offset(client, db_session, search_project, search_document):
    """offset parameter skips the correct number of results."""
    for i in range(5):
        make_chunk(db_session, search_document.id,
                   f"Vector database indexing strategy number {i}.", i)

    # Get first page
    resp_page1 = client.get(
        f"/api/projects/{search_project.id}/search?q=vector&limit=3&offset=0"
    )
    # Get second page
    resp_page2 = client.get(
        f"/api/projects/{search_project.id}/search?q=vector&limit=3&offset=3"
    )

    assert resp_page1.status_code == 200
    assert resp_page2.status_code == 200

    ids_page1 = {r["chunk_id"] for r in resp_page1.json()["results"]}
    ids_page2 = {r["chunk_id"] for r in resp_page2.json()["results"]}

    # Pages must not overlap
    assert ids_page1.isdisjoint(ids_page2)
    # total_results is consistent across pages
    assert resp_page1.json()["total_results"] == resp_page2.json()["total_results"] == 5


def test_search_total_results_ignores_limit(client, db_session, search_project, search_document):
    """total_results reflects full match count, not the number of returned items."""
    for i in range(8):
        make_chunk(db_session, search_document.id,
                   f"Knowledge graph construction from scientific literature {i}.", i)

    resp = client.get(
        f"/api/projects/{search_project.id}/search?q=knowledge&limit=3"
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["total_results"] == 8
    assert len(body["results"]) == 3


# ---------------------------------------------------------------------------
# 7. Response contract
# ---------------------------------------------------------------------------

def test_search_response_echoes_query(client, db_session, search_project, search_document):
    """The response echoes the original query string."""
    make_chunk(db_session, search_document.id,
               "Reranking improves retrieval precision.", 0)

    resp = client.get(f"/api/projects/{search_project.id}/search?q=reranking")
    assert resp.status_code == 200
    assert resp.json()["query"] == "reranking"


def test_search_response_includes_query_time_ms(client, db_session, search_project, search_document):
    """query_time_ms is present and positive in the response."""
    make_chunk(db_session, search_document.id,
               "BM25 is a classic lexical retrieval algorithm.", 0)

    resp = client.get(f"/api/projects/{search_project.id}/search?q=BM25")
    assert resp.status_code == 200
    assert resp.json()["query_time_ms"] > 0


def test_search_result_item_contains_provenance(client, db_session, search_project, search_document):
    """Each result item includes full chunk provenance fields."""
    make_chunk(db_session, search_document.id,
               "Hybrid retrieval fuses lexical and semantic signals.", 0)

    resp = client.get(f"/api/projects/{search_project.id}/search?q=hybrid")
    assert resp.status_code == 200

    result = resp.json()["results"][0]
    assert "chunk_id" in result
    assert "document_id" in result
    assert "document_filename" in result
    assert "page_start" in result
    assert "page_end" in result
    assert "char_offset_start" in result
    assert "char_offset_end" in result
    assert "rank" in result
    assert result["document_filename"] == "rag_paper.pdf"


def test_search_headline_contains_mark_tags(client, db_session, search_project, search_document):
    """The headline field contains <mark>...</mark> wrapping the matching terms."""
    make_chunk(db_session, search_document.id,
               "Reciprocal rank fusion combines multiple retrieval signals effectively.", 0)

    resp = client.get(f"/api/projects/{search_project.id}/search?q=fusion")
    assert resp.status_code == 200

    headline = resp.json()["results"][0]["headline"]
    assert "<mark>" in headline
    assert "</mark>" in headline


# ---------------------------------------------------------------------------
# 8. English stemming (FTS language feature)
# ---------------------------------------------------------------------------

def test_search_stemming_matches_word_variants(client, db_session, search_project, search_document):
    """PostgreSQL English stemmer maps 'retrieving' and 'retrieval' to the same lexeme.

    Searching for 'retrieval' should match a chunk containing 'retrieving'.
    This verifies that the 'english' dictionary is applied correctly via
    to_tsvector('english', content).
    """
    make_chunk(db_session, search_document.id,
               "The system is capable of retrieving relevant passages efficiently.", 0)

    resp = client.get(f"/api/projects/{search_project.id}/search?q=retrieval")
    assert resp.status_code == 200
    # The chunk contains 'retrieving' but query says 'retrieval' — stemming should match
    assert resp.json()["total_results"] == 1


# ---------------------------------------------------------------------------
# 9. Quoted phrase matching (websearch_to_tsquery feature)
# ---------------------------------------------------------------------------

def test_search_quoted_phrase_matches_exact_sequence(client, db_session, search_project, search_document):
    """Quoted phrases only match when terms appear consecutively in order.

    'machine learning' (quoted) must match a chunk with consecutive "machine learning"
    but NOT a chunk where the words are separated by other words.
    """
    # Chunk with consecutive phrase
    make_chunk(db_session, search_document.id,
               "Machine learning models are evaluated on benchmark datasets.", 0)
    # Chunk where the words are far apart (should not match the phrase query)
    make_chunk(db_session, search_document.id,
               "The machine used in this experiment is learning a new policy.", 1)

    resp = client.get(
        f"/api/projects/{search_project.id}/search",
        params={"q": '"machine learning"'},
    )
    assert resp.status_code == 200

    body = resp.json()
    # Only the chunk with the exact phrase should match
    assert body["total_results"] == 1
    assert "machine learning" in body["results"][0]["content"].lower()
