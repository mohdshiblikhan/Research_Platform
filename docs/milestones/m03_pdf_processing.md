# Milestone 3: PDF Processing & Chunking

- **Status**: Completed
- **Version**: `v0.3`
- **Migration**: `0293355754ef` (*create chunk table*)
- **Key Files & Test Counts**:
  - 18 integration tests in `backend/tests/test_processing.py`
  - Comprehensive suite passing, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
After Milestone 2, a researcher can upload a PDF document. However, these documents sit on disk as opaque binary files. The system cannot search them, retrieve specific passages, or perform any intelligent retrieval operations. Before we can build search (Milestone 4) or semantic retrieval (Milestone 5), we need the raw text content broken into searchable, citable units (chunks) with provenance metadata so we can always trace a chunk back to its source page and document.

#### The Solution
Milestone 3 implements a deterministic ingestion pipeline that converts uploaded PDF files into chunks with exact character offsets and page span provenance. The system:
1. Validates the document is in the `uploaded` state.
2. Extracts text from every page using PyMuPDF.
3. Cleans the extracted text (normalizing whitespace, stripping NUL bytes, and rejoining hyphenated words).
4. Splits the text into boundary-aware chunks using a hierarchical recursive text splitter (`chunk_method="recursive"` default with configurable fallback to `"fixed"` sliding window).
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
     ├─ 4. Clean: strip \x00, rejoin hyphenated words, normalize whitespace
     ├─ 5. Chunk: Hierarchical recursive boundary-aware splitting (1000 chars target, 200 overlap)
     │      ├─ Separator hierarchy: ["\n\n", "\n", ". ", " ", ""]
     │      ├─ Keeps paragraphs & sentences intact without mid-word cuts
     │      ├─ Configurable fallback to legacy fixed sliding window via CHUNK_METHOD=fixed
     │      └─ Track which page(s) each chunk spans
     ├─ 6. Bulk insert chunks → database
     ├─ 7. Status → "processed" (atomic commit with chunks)
     └─ Return: ProcessingResult
```
*On failure: status → `"failed"`, all chunk inserts are rolled back.*

#### Text Cleaning Logic
PDFs often contain formatting artifacts. The `_clean_text` method in `ProcessingService` handles:
- Removing NUL (`\x00`) bytes incompatible with PostgreSQL `VARCHAR`/`TEXT` columns.
- Rejoining hyphenated words split across line breaks (e.g., `com-\nputer` → `computer`).
- Collapsing multiple spaces (but preserving newlines).
- Collapsing 3+ consecutive newlines into 2, preserving paragraph structures.
- Stripping leading and trailing whitespace.

#### Chunking Architecture: Recursive Boundary-Aware vs. Fixed Window Baseline

The platform supports two chunking engines selectable via `settings.chunk_method` (configured in `backend/app/core/config.py`):

1. **Recursive Boundary-Aware Splitting (`chunk_method = "recursive"`, Default)**:
   - Evaluates text against a natural structural separator hierarchy:
     $$\text{SEPARATORS} = [\text{"\textbackslash n\textbackslash n"}, \text{"\textbackslash n"}, \text{". "}, \text{" "}, \text{""}]$$
   - First attempts to split along paragraph breaks (`\n\n`). If a paragraph fits within `chunk_size` (1000 characters), it is preserved intact.
   - If a section exceeds `chunk_size`, the algorithm recursively falls back down the hierarchy: single newlines (`\n`) → sentences (`. `) → words (` `) → character slicing (`""`) only as an absolute last resort.
   - An overlapping merge pass combines split fragments up to `chunk_size` and applies `chunk_overlap` (200 characters) from the preceding chunk boundary, ensuring complete semantic continuity without arbitrarily cutting sentences or words in half.

2. **Fixed-Size Sliding Window (`chunk_method = "fixed"`, Legacy Baseline)**:
   - Slices concatenated document text strictly by character count (`step = chunk_size - chunk_overlap`).
   - Retained intentionally for empirical ablation studies in Milestone 16, allowing exact side-by-side comparison of retrieval quality between fixed and recursive chunking strategies.

#### Provenance Tracking
When chunking across the full concatenated text, the service computes:
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

Contains 18 comprehensive tests, including:
- **`test_process_multipage_document`**: Validates processing a generated 3-page PDF.
- **`test_chunk_has_correct_provenance`**: Checks that `page_start`, `page_end`, and `char_offset` fields are populated correctly.
- **`test_chunk_content_contains_original_text`**: Ensures no text is lost during chunking.
- **`test_delete_document_removes_chunks`**: Proves the database-level cascade works.
- **`test_clean_text_strips_null_bytes`**: Verifies PostgreSQL-incompatible NUL characters (`\x00`) are removed.
- **`test_chunks_respect_paragraph_boundaries`**: Asserts that paragraphs are kept cohesive within chunk boundaries rather than sliced at arbitrary offsets.
- **`test_recursive_chunking_falls_back_to_sentences`**: Verifies that when paragraphs exceed `chunk_size`, the algorithm cleanly splits along sentence boundaries (`. `).
- **`test_chunk_method_config_toggle`**: Verifies runtime switching between `"recursive"` and `"fixed"` chunking via `settings.chunk_method`.

---

### 5. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|:---|:---|:---|:---|
| **Chunking Strategy** | **Hierarchical Recursive Splitting (with Configurable Fixed Fallback)** | Blind fixed-size character slicing, semantic/LLM chunking | Blind character slicing arbitrarily cuts words and sentences in half, fragmenting semantic context for dense embeddings and BM25 lexemes. Hierarchical recursive splitting preserves natural paragraph and sentence boundaries. The legacy fixed-size sliding window is preserved via `settings.chunk_method = "fixed"` for empirical ablation studies in Milestone 16. |
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
To test just the processing pipeline (18 integration tests):
```bash
cd backend
source ../.venv/bin/activate
pytest tests/test_processing.py -v
```

To ensure no regressions across the test suite:
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

1. **Why did you start with fixed-size chunking and then upgrade to recursive boundary-aware chunking?**
   *"We followed an empirical baseline discipline. We initially built a simple, deterministic fixed-size sliding window (1,000 characters with 200 overlap) to validate transaction boundaries, PyMuPDF extraction, and page provenance. However, rigid character slicing cuts sentences and words in half, degrading embedding quality and full-text keyword proximity. We upgraded to hierarchical recursive chunking (`\n\n` → `\n` → `. ` → ` ` → `""`), which keeps paragraphs and sentences intact. Crucially, we retained the fixed sliding window as a configurable fallback (`settings.chunk_method = 'fixed'`) so that in our evaluation framework (Milestone 16), we can run empirical ablation experiments to mathematically prove the retrieval quality delta."*

2. **How does the recursive splitting algorithm prevent semantic truncation?**
   *"The algorithm inspects the text against a ordered list of natural separators. It first attempts to split on paragraph breaks (`\n\n`). If each paragraph fits within `chunk_size`, it never splits deeper. Only when an individual paragraph exceeds `chunk_size` does it recurse down to line breaks, then sentence endings (`. `), and finally words. It then merges adjacent splits up to `chunk_size` and prepends overlap from the prior boundary, ensuring that complete thoughts and propositions remain unbroken."*

3. **How do you guarantee that citations in future RAG answers can be traced to exact physical pages?**
   *"Every chunk stores `page_start`, `page_end`, and exact character offsets. Because our chunking algorithm slides across the concatenated document text while maintaining a map of page boundaries, chunks that span across a page break correctly report multiple pages. When the LLM cites a chunk, the UI can immediately look up the exact physical page and highlight the exact characters."*

4. **How do you prevent race conditions or partial writes if extraction fails midway?**
   *"We strictly control the transaction boundaries. The repositories use `flush()` to send SQL to Postgres without committing. The `ProcessingService` orchestrates the extraction, chunking, bulk insertion, and status update (`processing` → `processed`). Only if all steps succeed does it issue a `commit()`. If anything fails (like a PyMuPDF parse error), we catch it, `rollback()`, and in a new transaction, set the document status to `failed`."*
