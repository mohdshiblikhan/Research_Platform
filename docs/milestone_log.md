# Milestone Execution & Revision Log

> **Purpose of this Document**  
> This is the **master index and executive summary hub** for the Evidence-Driven AI Research & Experimentation Platform.  
> While `milestone.md` tracks the immediate living state (current status, immediate tasks), this document provides:
> - A structured Table of Contents linking to each milestone's full deep-dive chronicle.
> - A concise executive summary per milestone (what was built, key architectural decision).
>
> Each milestone's complete technical detail (file-by-file breakdown, design tradeoffs, interview talking points, test suite, database schema) lives in its own dedicated file under `docs/milestones/`.

---

## Table of Contents

| # | Milestone | Status | Deep-Dive File |
|:--|:---|:---|:---|
| 0 | Foundation & Development Environment | ✅ Completed | [m00_foundation.md](milestones/m00_foundation.md) |
| 1 | Research Project Management | ✅ Completed | [m01_project_management.md](milestones/m01_project_management.md) |
| 2 | Document Upload & Management | ✅ Completed | [m02_document_management.md](milestones/m02_document_management.md) |
| 3 | PDF Processing & Chunking | ✅ Completed | [m03_pdf_processing.md](milestones/m03_pdf_processing.md) |
| 4 | Baseline Keyword Search | ✅ Completed | [m04_baseline_search.md](milestones/m04_baseline_search.md) |
| 5 | Semantic Retrieval | ✅ Completed | [m05_semantic_retrieval.md](milestones/m05_semantic_retrieval.md) |
| 6 | Hybrid Retrieval | ✅ Completed | [m06_hybrid_retrieval.md](milestones/m06_hybrid_retrieval.md) |
| 7 | Reranking | 🔄 In Progress | (coming soon) |
| 8 | RAG & Evidence-Grounded Answers | ⏳ Upcoming | — |
| 9 | Structured Research Extraction | ⏳ Upcoming | — |
| 10 | Literature Comparison | ⏳ Upcoming | — |
| 11 | Research Planning | ⏳ Upcoming | — |
| 12 | Tool Calling | ⏳ Upcoming | — |
| 13 | Agentic Research Workflow | ⏳ Upcoming | — |
| 14 | Experiment Planning & Tracking | ⏳ Upcoming | — |
| 15 | Experiment Comparison | ⏳ Upcoming | — |
| 16 | AI / RAG / Agent Evaluation | ⏳ Upcoming | — |
| 17 | Knowledge Graph | ⏳ Upcoming | — |
| 18 | Productionization | ⏳ Upcoming | — |

---

## Milestone Summaries

---

### Milestone 0 — Foundation & Development Environment
**Version**: `v0.1` | **Commit**: `efa8436`  
**Full Chronicle**: [m00_foundation.md](milestones/m00_foundation.md)

**What was built**: Established the complete engineering foundation for the platform — FastAPI application structure, PostgreSQL integration via SQLAlchemy 2.0, Alembic for schema migrations, Pydantic Settings for environment-variable management, and a Pytest suite with transactional rollback isolation. No domain logic yet — only the infrastructure every future feature depends on.

**Key Architectural Decision**: Used **transactional rollback isolation** for testing instead of wiping and recreating tables between tests. Each test opens a database connection, begins a transaction, runs against real PostgreSQL, then rolls back — leaving the database in a pristine state. This gives genuine database confidence at near-zero overhead.

---

### Milestone 1 — Research Project Management
**Version**: `v0.1` | **Commit**: `3bc3355` | **Migration**: `2bb6b4a6e6d4`  
**Full Chronicle**: [m01_project_management.md](milestones/m01_project_management.md)

**What was built**: Introduced the `Project` entity — the top-level research workspace. Implemented complete CRUD (Create, List, Get, Patch, Delete) with 5 API endpoints under `/api/projects`. Established the full 4-layer architecture pattern (ORM Model → Pydantic Schema → Repository → API Endpoint) that all future features follow. 11 integration tests, all passing.

**Key Architectural Decision**: **PATCH over PUT** for updates, using `model_dump(exclude_unset=True)` to apply only the fields the client explicitly sent — preventing accidental overwrites of existing data with `None` values when fields are omitted. **No service layer** was introduced because Project CRUD has no multi-resource coordination — it would have been empty pass-through code.

---

### Milestone 2 — Document Upload & Management
**Version**: `v0.2` | **Migration**: `959decb82d1f`  
**Full Chronicle**: [m02_document_management.md](milestones/m02_document_management.md)

**What was built**: Introduced the `Document` entity and multipart PDF upload. The system validates files (extension + MIME type + PyMuPDF structural parse), saves them to `data/uploads/{project_id}/`, extracts page count, and stores structured metadata in PostgreSQL. Supports listing, retrieval, and deletion (with cascade). Introduced the **Service Layer** (`DocumentService`) to coordinate disk I/O + database operations atomically, with cleanup guarantees on partial failure. 13 integration tests, 26 total passing.

**Key Architectural Decision**: **Service layer introduced only for documents**, not retroactively for projects, because document upload is the first feature that requires coordinating two independent side effects (filesystem write + database insert). The service guarantees that a file on disk is never left without a matching database record, and vice versa. `DocumentStatus` was added as a **VARCHAR column** (not PostgreSQL ENUM) to avoid `ALTER TYPE` DDL migration complexity when new statuses are needed.

---

### Milestone 3 — PDF Processing & Chunking
**Version**: `v0.3` | **Migration**: `0293355754ef`  
**Full Chronicle**: [m03_pdf_processing.md](milestones/m03_pdf_processing.md)

**What was built**: Implemented the PDF-to-chunk ingestion pipeline. A new `POST .../process` endpoint triggers `ProcessingService`, which orchestrates: document status validation → `uploaded → processing` transition → PyMuPDF page-by-page text extraction → text cleaning (hyphenation rejoining, whitespace normalization) → fixed-size chunking (1000 chars, 200-char overlap) → bulk chunk insert → atomic commit with final `processing → processed` status transition (or `→ failed` on error). Three API endpoints: process, list chunks, get chunk. Chunk provenance preserved: `page_start`, `page_end`, `char_offset_start`, `char_offset_end`, `chunk_index`. 14 new integration tests, 40 total passing, 0 regressions.

**Key Architectural Decision**: **Fixed-size chunking with overlap** (1000 chars / 200-char overlap) chosen as the baseline — the simplest, most predictable strategy that establishes a measurable retrieval baseline before introducing section-aware or semantic chunking. **`flush()` over `commit()`** in repositories allows `ProcessingService` to own the transaction boundary, committing chunks and status atomically in a single transaction. **Separate `POST .../process` endpoint** (not auto-process on upload) keeps upload fast and debuggable, and cleanly maps to background job processing in a future milestone.

---

### Milestone 4 — Baseline Keyword Search
**Version**: `v0.4` | **Migration**: `8991abfba909`
**Full Chronicle**: [m04_baseline_search.md](milestones/m04_baseline_search.md)

**What was built**: Implemented deterministic full-text keyword search over document chunks using PostgreSQL's native FTS engine. A `search_vector tsvector` column — declared `GENERATED ALWAYS AS (to_tsvector('english', content)) STORED` — was added to the `chunks` table and indexed with a GIN index. A new `SearchRepository` encapsulates all FTS query logic: `websearch_to_tsquery` for Google-like query parsing, `ts_rank_cd` for cover-density relevance ranking (normalized to `(0,1)`), and `ts_headline` for highlighted `<mark>`-tagged result snippets. A `SearchService` orchestrates validation, project/document scoping, and query timing. A single `GET /api/projects/{project_id}/search` endpoint exposes search with pagination and optional document filtering. The `SearchResponse` includes `query_time_ms` to establish the retrieval latency baseline for future milestones. 20 new integration tests, 60 total passing, 0 regressions.

**Key Architectural Decision**: **PostgreSQL FTS over in-memory BM25 or Elasticsearch** — zero additional infrastructure, transactionally consistent (chunks are searchable the instant they are committed), and the lexical arm plugs directly into Milestone 6's hybrid retrieval architecture where both FTS and pgvector queries run in the same database. The **`GENERATED ALWAYS AS STORED`** generated column is the critical design choice: the `tsvector` is pre-computed at write time (chunks are written once, searched many times), eliminating per-query recomputation. The **`SearchRepository` / `SearchService` separation** mirrors the established pattern and ensures that adding a `VectorSearchRepository` in Milestone 5 requires zero changes to the FTS code.

---

### Milestone 5 — Semantic Retrieval
**Version**: `v0.5` | **Migration**: `65b2e998f04a`
**Full Chronicle**: [m05_semantic_retrieval.md](milestones/m05_semantic_retrieval.md)

**What was built**: Introduced dense vector embeddings and semantic search. Added `pgvector` to PostgreSQL and an `embedding vector(384)` column to the `chunks` table. Decoupled embedding generation into a dedicated `POST /api/projects/{project_id}/documents/{document_id}/embed` endpoint that batches texts and generates vectors locally using `sentence-transformers/all-MiniLM-L6-v2`. Created a `VectorSearchRepository` for computing cosine distance. The existing `GET /api/projects/{project_id}/search` endpoint was updated to accept a `mode` parameter (`keyword` or `semantic`), delegating semantic queries to `VectorSearchRepository`. 5 new integration tests, 65 total passing, 0 regressions.

**Key Architectural Decision**: **`pgvector` vs Dedicated Vector DB** — Keeps architecture strictly relational; vector data lives alongside metadata for precise, fast filtering without synchronization overhead. **Local sentence-transformers vs OpenAI** — Provides a cost-free, private, offline-capable baseline. **Dedicated `/embed` API vs Auto-embed** — Embedding is heavily compute-bound; decoupling it ensures fast document ingestion and paves the way for background task processing in production.

---

### Milestone 6 — Hybrid Retrieval
**Version**: `v0.6` | **Migration**: None (App level changes only)
**Full Chronicle**: [m06_hybrid_retrieval.md](milestones/m06_hybrid_retrieval.md)

**What was built**: Implemented a Hybrid Retrieval engine combining the exact-match precision of keyword search with the conceptual matching of semantic search. Added a new `mode="hybrid"` to the search endpoint. The system independently queries both the `SearchRepository` and `VectorSearchRepository` (fetching up to 60 chunks from each), and dynamically computes a Reciprocal Rank Fusion (RRF) score in memory to return a single paginated list of unified results. 2 new integration tests, 68 total tests passing, 0 regressions.

**Key Architectural Decision**: **Rank-based fusion (RRF) in the Application Layer** — RRF avoids the fragility of normalizing fundamentally different score scales (unbounded `ts_rank` vs bounded vector distance). Pushing the fusion logic to the Python application layer rather than a complex SQL CTE keeps the repositories purely focused on single-mode retrieval and makes the fusion orchestrator fully isolated and easily testable.

---

*(Add each new milestone summary here after its deep-dive file is written.)*
