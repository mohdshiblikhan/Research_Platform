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
| 4 | Baseline Keyword Search | 🔄 In Progress | *(coming soon)* |
| 5 | Semantic Retrieval | ⏳ Upcoming | — |
| 6 | Hybrid Retrieval | ⏳ Upcoming | — |
| 7 | Reranking | ⏳ Upcoming | — |
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

*(Add each new milestone summary here after its deep-dive file is written.)*
