# Milestone 5: Semantic Retrieval

- **Status**: Completed
- **Version**: `v0.5`
- **Migration**: `65b2e998f04a` (*add embedding column to chunks*)
- **Key Files & Test Counts**:
  - 5 new integration tests in `backend/tests/test_embedding.py` and `backend/tests/test_semantic_search.py`
  - 65 tests total passing, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
Keyword search (Milestone 4) is fast and deterministic but relies on exact term matching. If a researcher searches for "AI reasoning models", they might miss chunks discussing "LLM chain-of-thought", despite the semantic similarity. We need a way to retrieve chunks based on their *meaning* rather than their literal text.

#### The Solution
Milestone 5 introduces Semantic Retrieval using dense vector embeddings:
1. Adds `pgvector` to PostgreSQL and an `embedding vector(384)` column to the `chunks` table.
2. Integrates `sentence-transformers` (`all-MiniLM-L6-v2`) to convert text chunks into 384-dimensional dense vectors locally.
3. Decouples embedding generation into a dedicated `POST /api/projects/{project_id}/documents/{document_id}/embed` endpoint.
4. Updates the `GET /api/projects/{project_id}/search` endpoint to accept a `mode` parameter (`keyword` or `semantic`), delegating to `VectorSearchRepository` for semantic queries.
5. Uses cosine distance (`<=>`) to find conceptually similar chunks, establishing our semantic retrieval capability in preparation for Hybrid Retrieval (Milestone 6).

---

### 2. What the API Exposes

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `POST` | `/api/projects/{project_id}/documents/{document_id}/embed` | Generate vectors for chunks | `200 OK` |
| `GET` | `/api/projects/{project_id}/search` | Updated with `mode=keyword\|semantic` | `200 OK` |

**New Endpoint: `POST .../embed`**
Computes and stores vector embeddings for all chunks of a processed document. 
- **Error Responses**: `400 Bad Request` if document is not in `processed` state. `404 Not Found` if project/document is invalid.

**Updated Endpoint: `GET .../search`**
- **New Parameter**: `mode` (string, default: `keyword`). Must be `keyword` or `semantic`.
- **Response**: The `SearchResponse` schema now includes `similarity_score` for semantic queries, and `search_mode` to clarify which engine was used.

---

### 3. Architecture

#### Visual Flow
```
GET /api/projects/{id}/search?q="AI reasoning"&mode=semantic
     │
     ├─ 1. Validation (SearchService)
     ├─ 2. EmbeddingService: Embeds the query into a 384-d vector
     ├─ 3. VectorSearchRepository: Performs query using cosine distance
     ├─ 4. PostgreSQL (`pgvector`): Calculates 1.0 - (embedding <=> query_vector)
     └─ Return: SearchResponse (with similarity_score)
```

---

### 4. Deep-Dive: File-by-File Breakdown

#### A. Database Schema Updates
**Migration**: `alembic/versions/65b2e998f04a_add_embedding_column_to_chunks.py`
- Executes `CREATE EXTENSION IF NOT EXISTS vector`.
- Adds `embedding` column of type `Vector(384)` to `chunks`. Nullable, allowing ingestion before embedding generation.

#### B. Embedding Services
- **`EmbeddingService` (ABC)**: Abstract interface defining `embed_texts` and `embed_query`.
- **`SentenceTransformerEmbeddingService`**: Concrete implementation utilizing `sentence-transformers/all-MiniLM-L6-v2`. Delays PyTorch import to the constructor to preserve FastAPI startup speed.
- **`EmbeddingServiceFactory`**: Singleton factory to cache the model in memory.
- **`DocumentEmbeddingService`**: Orchestrator that validates document status, batches chunk texts, generates embeddings, and executes a bulk update to the database using `bulk_update_mappings` for speed.

#### C. Search Repository & Service
- **`VectorSearchRepository`**: Runs semantic queries in PostgreSQL using `pgvector`'s cosine distance operator `<=>`. It joins `Document` to enforce `project_id` bounds.
- **`SearchService`**: Updated to route requests. If `mode == "keyword"`, it calls `SearchRepository`. If `mode == "semantic"`, it embeds the query and calls `VectorSearchRepository`.

---

### 5. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|:---|:---|:---|:---|
| **Vector DB** | **`pgvector` inside PostgreSQL** | Pinecone, Milvus, Qdrant | Keeps architecture simple (Modular Monolith). Vector data lives right next to metadata, allowing exact relational filtering (e.g., `document_id=X`) without complex pre/post filtering synchronization across separate databases. |
| **Model Hosting** | **Local `sentence-transformers`** | OpenAI / Cohere API | Cost-effective, private, and works offline. `all-MiniLM-L6-v2` is small (90MB), fast on CPUs, and provides a strong baseline. The `EmbeddingService` abstraction makes swapping to OpenAI trivial later. |
| **Embedding Generation** | **Dedicated `/embed` API** | Auto-embed during chunking | Embedding is CPU-intensive. Tying it to ingestion blocks the worker. A dedicated endpoint allows ingestion to finish quickly and sets the stage for async background tasks in the future. |
| **Vector Metric** | **Cosine Distance (`<=>`)** | L2/Euclidean (`<->`) or Inner Product (`<#>`) | `all-MiniLM-L6-v2` is optimized for Cosine Similarity. `pgvector` uses distance, so similarity is computed as `1.0 - distance`. |

---

### 6. How to Run, Test, and Verify

#### Run the tests:
```bash
cd backend
source ../.venv/bin/activate
pytest tests/test_embedding.py tests/test_semantic_search.py -v
```

#### Manual Verification via Swagger UI:
1. Ensure the server is running (`uvicorn app.main:app --reload`).
2. Run `POST /api/projects/{project_id}/documents/{document_id}/embed` for an existing processed document.
3. Run `GET /api/projects/{project_id}/search` with `mode=semantic` to see conceptually relevant results.

---

### 7. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **Why `pgvector` instead of a dedicated Vector DB like Pinecone?**
   *"Dedicated vector databases shine at massive scale, but for most applications, they introduce unnecessary distributed systems complexity. By using `pgvector`, we keep our embeddings in the same ACID-compliant store as our documents. This means we can do precise hybrid queries—like 'Find vectors similar to X, but ONLY in document Y'—using standard SQL JOINs without worrying about eventual consistency or complex pre-filtering strategies."*

2. **Why separate chunking and embedding into two API calls?**
   *"Separation of concerns and resource management. PDF parsing is I/O and CPU bound, but embedding generation is heavily compute-bound (or network-bound if using external APIs). By splitting them, we can ingest documents rapidly and queue the embedding generation for background workers later. It prevents timeouts and makes the system resilient."*

3. **How did you manage the heavy PyTorch dependency in a FastAPI app?**
   *"We defer the import of `sentence-transformers` to the constructor of `SentenceTransformerEmbeddingService`, and use a Singleton factory. This prevents PyTorch from loading during Alembic migrations, Pytest collection, or initial FastAPI boot, keeping the developer experience snappy."*
