# Milestone 4: Baseline Keyword Search

- **Status**: Completed
- **Version**: `v0.4`
- **Migration**: `8991abfba909` (*add search_vector column to chunks*)
- **Key Files & Test Counts**:
  - 20 new integration tests in `backend/tests/test_search.py`
  - 60 tests total passing, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
After Milestone 3, we had documents chunked and stored in PostgreSQL with strict provenance. However, to retrieve information to support the research process, we need a way to search those chunks. Jumping straight to vector embeddings (Semantic Search) is tempting but violates our core philosophy: we must establish a clear, deterministic baseline first. Without a keyword search baseline, we cannot objectively measure if, or by how much, embeddings actually improve retrieval quality for our specific use cases.

#### The Solution
Milestone 4 implements a fast, deterministic full-text search (FTS) engine directly inside PostgreSQL. The system:
1. Adds a `search_vector tsvector` column to the `chunks` table, which is automatically generated and updated by PostgreSQL whenever a chunk is inserted.
2. Creates a GIN index on this column for high-performance querying.
3. Exposes a `GET /api/projects/{project_id}/search` endpoint supporting advanced Google-like queries (quotes, OR, minus for exclusion).
4. Returns paginated results ranked by cover-density (`ts_rank_cd`), including the document filename and highlighted text snippets (`ts_headline`) where matched terms are wrapped in `<mark>` tags.
5. Captures and returns `query_time_ms` to establish our retrieval latency baseline.

---

### 2. What the API Exposes

A new endpoint dedicated to searching across a project's chunks:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `GET` | `/api/projects/{project_id}/search` | Keyword search over document chunks | `200 OK` |

**Query Parameters:**
- `q` (string, required): The search query. Supports plain terms, `"quoted phrases"`, `OR`, and `-exclusion`.
- `document_id` (int, optional): Restrict search to a specific document.
- `limit` (int, default=10): Number of results to return.
- `offset` (int, default=0): Pagination offset.

**Error responses:**
| Scenario | HTTP Status | Detail |
|:---|:---|:---|
| Empty Query | `422 Unprocessable Entity` | Pydantic validation error (`String should have at least 1 characters`) |
| Project not found | `404 Not Found` | `"Project {id} not found"` |
| Document not found (when filtering) | `404 Not Found` | `"Document {id} not found in project {project_id}"` |

---

### 3. Search Architecture

#### Visual Flow
```
GET /api/projects/{id}/search?q="attention mechanism"
     │
     ├─ 1. Validate: project exists, document exists (if provided)
     ├─ 2. SearchService: starts timing the query execution
     ├─ 3. SearchRepository: parses query via `websearch_to_tsquery`
     ├─ 4. PostgreSQL: uses GIN index to find matching `tsvector`s
     ├─ 5. PostgreSQL: ranks results using `ts_rank_cd` (cover density)
     ├─ 6. PostgreSQL: generates `<mark>` snippets via `ts_headline`
     ├─ 7. SearchService: stops timing, formats response
     └─ Return: SearchResponse (with query_time_ms, total_results, results)
```

#### The Power of PostgreSQL FTS
By leveraging native PostgreSQL FTS, we achieved powerful search capabilities with zero extra infrastructure (no Elasticsearch, no Solr). 
- **`websearch_to_tsquery`**: Unlike `to_tsquery` which throws errors on malformed input, `websearch_to_tsquery` safely parses human-like input (e.g. `retrieval "augmented generation" -hallucination`).
- **`ts_rank_cd`**: Standard ranking counts term frequency. Cover-density ranking considers the proximity of terms. In a 1000-character chunk, two search terms appearing right next to each other are far more relevant than one term at the beginning and one at the end.
- **`ts_headline`**: Instead of having the frontend manually highlight terms, PostgreSQL returns the exact matched snippet with `<mark>` tags injected.

---

### 4. Deep-Dive: File-by-File Breakdown

#### A. Database Schema Updates
**Migration**: `alembic/versions/8991abfba909_add_search_vector_column_to_chunks.py`
```python
op.execute("""
    ALTER TABLE chunks
    ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
""")
op.create_index("ix_chunks_search_vector", "chunks", ["search_vector"], postgresql_using="gin")
```
- **`GENERATED ALWAYS AS ... STORED`**: This guarantees that the `tsvector` representation of the chunk's content is calculated by the database engine at write time, eliminating the need for Python to parse text or manage search vectors. Existing chunks were automatically backfilled when the migration ran.

#### B. ORM Model: `backend/app/models/chunk.py`
```python
search_vector = mapped_column(
    TSVectorType(),
    Computed("to_tsvector('english', content)", persisted=True),
)
```
- We used `sqlalchemy.schema.Computed` to tell SQLAlchemy that this column is generated by the database and should not be included in `INSERT` statements.

#### C. Pydantic Schemas: `backend/app/schemas/search.py`
```python
class SearchResultItem(BaseModel):
    chunk_id: int
    document_id: int
    document_filename: str
    chunk_index: int
    page_start: int
    page_end: int
    char_offset_start: int
    char_offset_end: int
    rank: float
    headline: str
    content: str

class SearchResponse(BaseModel):
    project_id: int
    query: str
    document_id: Optional[int]
    total_results: int
    limit: int
    offset: int
    query_time_ms: float
    results: list[SearchResultItem]
```
- **Provenance Included**: The result item retains all chunk provenance (pages, offsets) and immediately joins the `document_filename` so clients can display human-readable citations.

#### D. Repository Layer: `backend/app/repositories/search_repository.py`
We created a dedicated `SearchRepository` separate from `ChunkRepository` to isolate search logic. 
- Uses `func.websearch_to_tsquery('english', query)`
- Uses `func.ts_rank_cd(Chunk.search_vector, tsquery, 32)` (Flag 32 normalizes the rank to a `0-1` range).
- Returns a tuple of `(items, total_count)` where `total_count` is a `count() OVER()` window function, avoiding a second query to get the total number of hits.

#### E. Service Layer: `backend/app/services/search_service.py`
Orchestrates project validation and handles timing (`time.perf_counter()`).

#### F. API Endpoint: `backend/app/api/endpoints/search.py`
A simple `GET` endpoint mapping query parameters to the service layer.

---

### 5. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|:---|:---|:---|:---|
| **Search Technology** | **PostgreSQL Native FTS** | Elasticsearch, Typesense, In-memory BM25 | PostgreSQL FTS is powerful enough for our baseline, transactionally consistent, and requires zero new infrastructure. Keeps the architecture simple (Modular Monolith). |
| **Vector Generation** | **`GENERATED ALWAYS AS STORED`** | Triggers or Application-side | `GENERATED ALWAYS` is cleaner than database triggers and pushes the work entirely to the DB engine. Application code doesn't even have to know the column exists during ingestion. |
| **Search Endpoint Method** | **`GET`** | `POST` | Search is a read operation. `GET` is semantically correct, cacheable, and bookmarkable. We only use `POST` for searches if the query payload becomes deeply nested and exceeds URL limits. |
| **Ranking Algorithm** | **Cover Density (`ts_rank_cd`)** | Standard frequency (`ts_rank`) | Our chunks are fixed size. Cover density rewards chunks where query terms appear close together (e.g. matching a sentence) rather than scattered across the paragraph. |

---

### 6. How to Run, Test, and Verify

#### Run the tests:
```bash
cd backend
source ../.venv/bin/activate
pytest tests/test_search.py -v
```
*(20 tests verifying stemming, phrase matching, OR/NOT operations, scoping, and pagination)*

#### Manual Verification via Swagger UI:
1. Ensure the server is running (`uvicorn app.main:app --reload`).
2. Verify you have a project with at least one processed PDF document.
3. Open `http://localhost:8000/docs` and use the `GET /api/projects/{project_id}/search` endpoint.
4. Try advanced queries like:
   - `retrieval` (matches "retrieval", "retrieving")
   - `"attention mechanism"` (exact phrase)
   - `transformer OR attention` (Boolean OR)
   - `retrieval -hallucination` (Exclusion)

---

### 7. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **Why not just jump straight to embeddings/Semantic Search?**
   *"You can't prove an AI system works if you don't know what 'normal' looks like. We built a deterministic keyword search baseline first so we can empirically measure the latency, recall, and precision of FTS. When we add semantic search, we won't just guess that it's better — we will prove it by comparing the metrics."*

2. **Why use PostgreSQL for search instead of Elasticsearch?**
   *"For our current scale, bringing in Elasticsearch introduces massive operational overhead: managing a JVM cluster, keeping a separate data store in sync, and dealing with eventual consistency. Postgres FTS handles stemming, ranking, and phrase matching natively in the same ACID transaction where the document is inserted. Complexity should be earned, and we haven't hit the limits of Postgres yet."*

3. **How does your search handle performance on large tables?**
   *"We use a GIN (Generalized Inverted Index) on a pre-computed `tsvector` column. Because the column is `GENERATED ALWAYS AS STORED`, the heavy lifting of parsing text into lexemes happens once at write-time, not at read-time. The GIN index allows instantaneous lookups across millions of rows."*

4. **How do you prepare this system for Hybrid Search in the future?**
   *"We specifically isolated the FTS logic into `SearchRepository` and `SearchService`. When we introduce `pgvector`, we will create a parallel `VectorSearchRepository`. The `SearchService` will then become a fusion orchestrator — running both the FTS query and the Vector query, and combining their scores using Reciprocal Rank Fusion (RRF), without tearing down the existing infrastructure."*
