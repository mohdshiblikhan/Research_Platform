# Milestone 3: PDF Processing & Chunking

- **Status**: Completed
- **Version**: `v0.3`
- **Migration**: `0293355754ef` (*create chunk table*)
- **Key Files & Test Counts**:
  - 14 new integration tests in `backend/tests/test_processing.py`
  - 40 tests total passing, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
After Milestone 2, a researcher can upload a PDF document. However, these documents sit on disk as opaque binary files. The system cannot search them, retrieve specific passages, or perform any intelligent retrieval operations. Before we can build search (Milestone 4) or semantic retrieval (Milestone 5), we need the raw text content broken into searchable, citable units (chunks) with provenance metadata so we can always trace a chunk back to its source page and document.

#### The Solution
Milestone 3 implements a deterministic ingestion pipeline that converts uploaded PDF files into chunks with exact character offsets and page span provenance. The system:
1. Validates the document is in the `uploaded` state.
2. Extracts text from every page using PyMuPDF.
3. Cleans the extracted text (normalizing whitespace and rejoining hyphenated words).
4. Splits the text into fixed-size overlapping chunks.
5. Stores each chunk in the database with strict provenance metadata (`page_start`, `page_end`, `char_offset_start`, `char_offset_end`).
6. Transitions the document's `status` field through the lifecycle: `uploaded → processing → processed` (or `→ failed`).

---

### 2. What the API Exposes

A new set of endpoints dedicated to processing and chunk retrieval:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `POST` | `/api/projects/{project_id}/documents/{document_id}/process` | Trigger PDF text extraction & chunking | `200 OK` |
| `GET` | `/api/projects/{project_id}/documents/{document_id}/chunks` | List all chunks for a processed document | `200 OK` |
| `GET` | `/api/projects/{project_id}/documents/{document_id}/chunks/{chunk_id}` | Get a single chunk by ID | `200 OK` |

**Error responses:**

| Scenario | HTTP Status | Detail |
|:---|:---|:---|
| Project or Document not found | `404 Not Found` | `"Project {id} not found"` or `"Document {id} not found..."` |
| Processing an already processed document | `400 Bad Request` | `"Document {id} cannot be processed: current status is 'processed'..."` |
| Chunk not found | `404 Not Found` | `"Chunk {id} not found in document {id}"` |
| Server processing failure | `500 Internal Server Error` | Unhandled exceptions during PyMuPDF parsing or database errors |

---

### 3. Ingestion Pipeline & Architecture

#### Visual Flow
```
POST /api/projects/{id}/documents/{doc_id}/process
     │
     ├─ 1. Validate: document exists, status == "uploaded"
     ├─ 2. Status → "processing" (atomic flush)
     ├─ 3. PyMuPDF: extract text from each page
     ├─ 4. Clean: rejoin hyphenated words, normalize whitespace
     ├─ 5. Chunk: fixed-size window (1000 chars) with overlap (200 chars)
     │      └─ Track which page(s) each chunk spans
     ├─ 6. Bulk insert chunks → database
     ├─ 7. Status → "processed" (atomic commit with chunks)
     └─ Return: ProcessingResult
```
*On failure: status → `"failed"`, all chunk inserts are rolled back.*

#### Text Cleaning Logic
PDFs often contain formatting artifacts. The `_clean_text` method in `ProcessingService` handles:
- Rejoining hyphenated words split across line breaks (e.g., `com-\nputer` → `computer`).
- Collapsing multiple spaces (but preserving newlines).
- Collapsing 3+ consecutive newlines into 2, preserving paragraph structures.
- Stripping leading and trailing whitespace.

#### Provenance Tracking
When sliding the chunk window across the full concatenated text, the service computes:
- `char_offset_start` and `char_offset_end`: Exact string indices in the full document text.
- `page_start` and `page_end`: The algorithm maintains a list of page boundary offsets. For each chunk, it checks which page boundaries the `char_offset_start` and `char_offset_end` fall into, yielding accurate page spans (even if a chunk crosses from the bottom of page 3 to the top of page 4).

#### Transaction Boundary Design
To ensure we never end up with orphaned chunks or an incorrect document status, `ChunkRepository` uses `self.db.flush()` rather than `commit()`. This pushes the SQL to PostgreSQL but leaves the transaction open. The `ProcessingService` then calls `update_status(..., "processed")` (which also flushes) and finally calls `self.db.commit()`, wrapping the entire pipeline in a single, atomic database transaction.

---

### 4. Deep-Dive: File-by-File Breakdown

#### A. ORM Model: `backend/app/models/chunk.py`

```python
class Chunk(Base):
    __tablename__ = "chunks"

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int] = mapped_column(nullable=False)
    page_end: Mapped[int] = mapped_column(nullable=False)
    char_offset_start: Mapped[int] = mapped_column(nullable=False)
    char_offset_end: Mapped[int] = mapped_column(nullable=False)
    chunk_size: Mapped[int] = mapped_column(nullable=False)
```
- **Foreign Key Cascade**: `ondelete="CASCADE"` ensures chunks are automatically dropped if the parent document (or project) is deleted.
- **`Text` Column**: Used for `content` as chunk sizes may vary or increase later; `VARCHAR` without a length acts similarly in Postgres, but `Text` is semantically clearer for large text blocks.

#### B. Pydantic Schemas: `backend/app/schemas/chunk.py`

```python
class ChunkRead(BaseModel):
    id: int
    document_id: int
    # ... other provenance fields ...
    content: str
    
class ProcessingResult(BaseModel):
    document_id: int
    filename: str
    status: str
    page_count: int
    chunk_count: int
```
- **`ProcessingResult`**: Returns a summary payload from the `POST /process` endpoint, allowing the client to know exactly how many chunks were generated without fetching them all immediately.

#### C. Service Layer: `backend/app/services/processing_service.py`

This class handles the core logic. Note the exception handling block for atomic rollbacks:
```python
        try:
            # Extract, clean, chunk...
            self.chunk_repo.bulk_create(chunk_objects)
            self.doc_repo.update_status(document, DocumentStatus.PROCESSED.value)
            self.db.commit()
        except Exception:
            self.db.rollback()
            try:
                self.doc_repo.update_status(document, DocumentStatus.FAILED.value)
                self.db.commit()
            except Exception:
                logger.error("Failed to set document status to 'failed'")
            raise
```
If anything goes wrong (e.g., PyMuPDF crashes, or a DB integrity error), the current transaction is fully rolled back, leaving no half-inserted chunks. A fresh transaction then marks the document as `failed`.

#### D. Repository Layer: `backend/app/repositories/chunk_repository.py`

```python
def bulk_create(self, chunks: list[Chunk]) -> list[Chunk]:
    self.db.add_all(chunks)
    self.db.flush()
    return chunks
```
- **`bulk_create`**: Uses `add_all` and `flush()`. By avoiding `commit()`, the repository delegates transaction management to the service orchestrator.

#### E. API Endpoints: `backend/app/api/endpoints/processing.py`

Thin HTTP wrappers that validate the context (ensuring the document belongs to the requested project) and map `ValueError` or `FileNotFoundError` to standard `400` and `404` HTTP status codes.

#### F. Integration Tests: `backend/tests/test_processing.py`

Contains 14 comprehensive tests, including:
- **`test_process_multipage_document`**: Validates processing a generated 3-page PDF.
- **`test_chunk_has_correct_provenance`**: Checks that `page_start`, `page_end`, and `char_offset` fields are populated correctly.
- **`test_chunk_content_contains_original_text`**: Ensures no text is lost during chunking.
- **`test_delete_document_removes_chunks`**: Proves the database-level cascade works.

---

### 5. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|:---|:---|:---|:---|
| **Chunking Strategy** | **Fixed-size characters with overlap (1000/200)** | Semantic chunking, sentence-based chunking | Fixed-size is the simplest, most predictable approach. It establishes a measurable retrieval baseline before we introduce complex ML-based strategies. |
| **Processing Trigger** | **Explicit `POST .../process` endpoint** | Automatic processing on upload | Keeps file upload lightning-fast. Prevents HTTP timeouts on large files. Translates cleanly to async background jobs later. |
| **Provenance Tracking** | **Character offsets (`char_offset_start`)** | Token counts | Tokenizers change depending on the embedding model (e.g., OpenAI vs. local models). Characters are model-agnostic and universally applicable for highlighting text in a UI. |
| **Failure States** | **Status `failed` on error** | Leave in `uploaded` / delete document | Explicitly tracking failure means we don't indefinitely retry corrupt PDFs, and the user gets clear feedback on the UI. |

---

### 6. Database Schema & Migration

#### Resulting `chunks` table in PostgreSQL:

| Column | PostgreSQL Type | Constraints |
|:---|:---|:---|
| `id` | `INTEGER` | PRIMARY KEY, NOT NULL, AUTO INCREMENT, INDEXED |
| `document_id` | `INTEGER` | NOT NULL, FK → `documents.id` ON DELETE CASCADE, INDEXED |
| `chunk_index` | `INTEGER` | NOT NULL |
| `content` | `TEXT` | NOT NULL |
| `page_start` | `INTEGER` | NOT NULL |
| `page_end` | `INTEGER` | NOT NULL |
| `char_offset_start` | `INTEGER` | NOT NULL |
| `char_offset_end` | `INTEGER` | NOT NULL |
| `chunk_size` | `INTEGER` | NOT NULL |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL, DEFAULT `now()` |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | NOT NULL, DEFAULT `now()` |

#### Migration commands used:
```bash
alembic revision --autogenerate -m "create chunk table"
alembic upgrade head
```
The migration (`0293355754ef`) creates the table with `ix_chunks_id` and `ix_chunks_document_id` indexes to optimize queries filtering by document.

---

### 7. How to Run, Test, and Verify

#### Run the tests:
To test just the new processing pipeline:
```bash
cd backend
source ../.venv/bin/activate
pytest tests/test_processing.py -v
```

To ensure no regressions in the full suite (40 tests):
```bash
pytest tests/ -v
```

#### Manual Verification via Swagger UI:
1. Start the server: `cd backend && uvicorn app.main:app --reload`
2. Open [http://localhost:8000/docs](http://localhost:8000/docs)
3. Create a project (`POST /api/projects`).
4. Upload a multi-page PDF (`POST /api/projects/{id}/documents`).
5. Trigger processing (`POST /api/projects/{id}/documents/{doc_id}/process`).
6. Inspect the returned `ProcessingResult` to see chunk counts.
7. Retrieve the chunks (`GET /api/projects/{id}/documents/{doc_id}/chunks`) and verify the `page_start` and `page_end` logic.

---

### 8. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **Why did you choose fixed-size chunking before embeddings?**
   *"We wanted to establish a baseline. Before introducing complex semantic chunking or section-aware splitting, we needed a deterministic system that we could evaluate. Fixed-size chunking with overlap is predictable and ensures we don't drop information across boundaries. When we eventually implement smarter chunking, we'll have a clear baseline to measure against to prove the new method is actually better."*

2. **How do you guarantee that citations in future RAG answers can be traced to exact physical pages?**
   *"Every chunk stores `page_start`, `page_end`, and exact character offsets. Because our chunking algorithm slides a window across the concatenated document text while maintaining a map of page boundaries, chunks that span across a page break correctly report multiple pages. When the LLM cites a chunk, the UI can immediately look up the exact physical page and highlight the exact characters."*

3. **How do you prevent race conditions or partial writes if extraction fails midway?**
   *"We strictly control the transaction boundaries. The repositories use `flush()` to send SQL to Postgres without committing. The `ProcessingService` orchestrates the extraction, chunking, bulk insertion, and status update (`processing` → `processed`). Only if all steps succeed does it issue a `commit()`. If anything fails (like a PyMuPDF parse error), we catch it, `rollback()`, and in a new transaction, set the document status to `failed`."*
