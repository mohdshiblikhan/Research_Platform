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
| 7 | Reranking | ✅ Completed | [m07_reranking.md](milestones/m07_reranking.md) |
| 8 | RAG & Evidence-Grounded Answers | ✅ Completed | [m08_rag.md](milestones/m08_rag.md) |
| 9 | Structured Research Extraction | ✅ Completed | [m09_structured_extraction.md](milestones/m09_structured_extraction.md) |
| 10 | Literature Comparison | ✅ Completed | [m10_literature_comparison.md](milestones/m10_literature_comparison.md) |
| 11 | Research Planning | ✅ Completed | [m11_research_planning.md](milestones/m11_research_planning.md) |
| 12 | Tool Calling | ✅ Completed | [m12_tool_calling.md](milestones/m12_tool_calling.md) |
| 13 | Agentic Research Workflow | ✅ Completed | [m13_agentic_research_workflow.md](milestones/m13_agentic_research_workflow.md) |
| 14 | Experiment Planning & Tracking | ✅ Completed | [m14_experiment_tracking.md](milestones/m14_experiment_tracking.md) |
| 15 | Experiment Comparison | ✅ Completed | [m15_experiment_comparison.md](milestones/m15_experiment_comparison.md) |
| 16 | AI / RAG / Agent Evaluation | ✅ Completed | [m16_evaluation_framework.md](milestones/m16_evaluation_framework.md) |
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

### Milestone 7 — Reranking
**Version**: `v0.7` | **Migration**: None (App level changes only)  
**Full Chronicle**: [m07_reranking.md](milestones/m07_reranking.md)

**What was built**: Introduced a two-stage retrieval architecture by integrating a Cross-Encoder reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) via `RerankingService`. Added an orthogonal `rerank: bool` flag to `GET /api/projects/{project_id}/search` and extended `SearchResultItem` with `rerank_score`. When enabled, `SearchService` retrieves an internal candidate pool of 60 items from the first-stage retriever (keyword, semantic, or hybrid), computes full cross-attention relevance scores, sorts candidates descending by `rerank_score`, and slices the pagination window (`offset` and `limit`) post-rerank. 9 new unit and integration tests, 77 total tests passing, 0 regressions.

**Key Architectural Decision**: **Orthogonal boolean flag over dedicated mode & Post-rerank pagination** — Reranking was exposed as a `rerank: bool` parameter rather than a `mode="rerank"` or `mode="hybrid_rerank"` to allow layering over any first-stage retriever (keyword, semantic, or hybrid) without combinatorial explosion of search modes. For pagination, `SearchService` deliberately fetches a fixed pool of 60 candidates before reranking and applies the caller's pagination slice *after* scoring and sorting, ensuring the reranker always evaluates a healthy candidate pool regardless of requested page depth. Unit and API tests mock the CrossEncoder for deterministic, sub-second CI validation, separating structural correctness testing from model quality evaluation.

---

### Milestone 8 — RAG & Evidence-Grounded Answers
**Version**: `v0.8` | **Migration**: None (App level changes only)  
**Full Chronicle**: [m08_rag.md](milestones/m08_rag.md)

**What was built**: Introduced Retrieval-Augmented Generation (RAG) to answer questions directly from documents. Created an abstract `LLMService` and an implementation for local generation via Ollama. Built the `RAGService` orchestrator that retrieves evidence (using Hybrid + Rerank), formats a strict JSON-mode system prompt, and parses the LLM's response. Added a new `POST /api/projects/{project_id}/ask` endpoint that returns a deeply structured payload including `evidence_analysis`, the synthesized `answer`, verified `citations` mapped to database chunk IDs, and latency metrics. Added 5 integration tests mocking the LLM to ensure deterministic CI validation. 82 total tests passing.

**Key Architectural Decision**: **Single-Call Chain-of-Thought with Strict JSON** — By requiring the LLM to return JSON with an `evidence_analysis` field *before* the `answer` field, the model is forced to evaluate the evidence autoregressively before synthesizing its conclusion. This delivers the reasoning quality of multi-step agentic workflows without the 2x latency/cost penalty. **Index-based Citation Verification** was implemented at the orchestrator level to actively catch and strip hallucinated citation indices, maintaining complete provenance back to the original PDF chunks.

---

### Milestone 9 — Structured Research Extraction
**Version**: `v0.9` | **Migration**: `2bb26245693e`  
**Full Chronicle**: [m09_structured_extraction.md](milestones/m09_structured_extraction.md)

**What was built**: Introduced the `DocumentExtraction` entity to move beyond simple document chunking. Created an extraction pipeline that fetches the most information-dense sections of a document (using edge chunks + hybrid semantic search) and feeds them to an LLM running in strict JSON mode to extract structured metadata fields like `research_problem`, `methodology`, `datasets`, and `evaluation_metrics`. Implemented the `POST /api/projects/{project_id}/documents/{document_id}/extract` API to trigger this process. 3 new integration tests written, passing successfully.

**Key Architectural Decision**: **Dedicated DB Schema over JSONB**: Added a new `document_extractions` table with explicitly typed `Text` columns for extraction fields, rather than just dumping JSON into a `JSONB` column. This enforces structure and sets up the ability to query, index, and systematically compare methodologies and datasets across multiple papers in Milestone 10. **Hybrid Context Gathering**: To handle LLM context limits efficiently, the `ExtractionService` concatenates the first 3 chunks (Abstract/Intro), the last 3 chunks (Conclusion/Limitations), and the top 5 chunks returned from a hybrid semantic search for methodology keywords. This avoids the cost and fragility of running Map-Reduce across the entire paper while ensuring critical insights are not missed.

---

### Milestone 10 — Literature Comparison
**Version**: `v1.0` | **Migration**: None (App level changes only)  
**Full Chronicle**: [m10_literature_comparison.md](milestones/m10_literature_comparison.md)

**What was built**: Implemented a multi-document literature comparison engine. Added the `POST /api/projects/{project_id}/compare` endpoint, accepting 2-10 document IDs and an optional `include_synthesis` boolean flag. Added bulk-fetch querying (`get_by_document_ids`) to `ExtractionRepository` for O(1) database lookups. Created `ComparisonService` to deterministically assemble an 8-field tabular comparison matrix across documents and optionally orchestrate an analytical LLM synthesis summarizing key differences, common themes, conflicting findings, and research gaps. 10 new integration tests written, 95 total tests passing, 0 regressions.

**Key Architectural Decision**: **Hybrid comparison (Deterministic Matrix + Optional LLM Synthesis)**: Assembly of the comparison table is treated as a pure, fast, deterministic data transformation reading directly from PostgreSQL relational columns, eliminating LLM latency and hallucination risks for tabular views. LLM synthesis is decoupled as an optional flag that feeds on the compact, structured extraction fields (~500 tokens) rather than raw paper chunks, drastically reducing inference latency and context overflow risks.

---

### Milestone 11 — Research Planning
**Version**: `v1.1` | **Migration**: `52539dbbef14`  
**Full Chronicle**: [m11_research_planning.md](milestones/m11_research_planning.md)

**What was built**: Introduced an evidence-driven Research Planning engine that converts a research question into a structured, verifiable research plan (Gap → Hypothesis → Experiment chain). Implemented `ResearchPlanningService` orchestrating Option C context assembly (structured extractions + analytical comparison synthesis + hybrid-retrieved evidence passages with source provenance). Built `POST /api/projects/{id}/plan`, `GET /api/projects/{id}/plans`, and `GET /api/projects/{id}/plans/{id}` endpoints. Persisted all plans into a versioned `research_plans` table using JSONB and relational foreign keys. 14 new integration tests, 110 total tests passing, 0 regressions.

**Key Architectural Decision**: **Option C Context Assembly with Provenance & Scope Consistency**: The planner combines macro-level paper extractions (M9), cross-paper synthesis (M10), and micro-level verbatim evidence passages (M6/M7) bounded strictly to the analyzed documents. Guardrails in the prompt and schema prevent the "unobserved topic fallacy" by requiring verifiable observations for gaps and linking every experiment to a hypothesis and gap ID.

---

### Milestone 12 — Tool Calling
**Version**: `v1.2` | **Migration**: None (App level changes only)  
**Full Chronicle**: [m12_tool_calling.md](milestones/m12_tool_calling.md)

**What was built**: Introduced a declarative, sandboxed, and auditable Tool-Calling Layer wrapping existing platform capabilities. Built a modular `BaseTool` class hierarchy and central `ToolRegistry` pre-populated with 8 safe analytical tools (`search_chunks`, `get_chunk`, `list_documents`, `get_document_metadata`, `get_paper_extraction`, `compare_papers`, `get_research_plan`, `list_research_plans`). Built `ToolExecutionService` for Pydantic argument validation, timing, logging, and error containment. Extended `LLMService` and `OllamaLLMService` to support native tool schemas and parse `ToolCall` responses. Added `GET /api/projects/{p_id}/tools` and `POST /api/projects/{p_id}/tools/execute` REST endpoints. 16 new integration and unit tests, 126 total tests passing, 0 regressions.

**Key Architectural Decision**: **Server-Injected `ToolContext` & Dual-Representation Output**: To prevent cross-project hallucination or data leakage, `project_id` is never exposed in the LLM's tool parameter schema; it is strictly injected by the server runtime. Every tool produces a `ToolResult` with dual representations: a token-optimized, human/LLM-readable text summary preserving chunk and page provenance for context windows, alongside the full structured JSON payload for application rendering and programmatic auditing.

---

### Milestone 13 — Agentic Research Workflow
**Version**: `v1.3` | **Migration**: `d47427ab4920_create_agent_sessions_table.py`  
**Full Chronicle**: [m13_agentic_research_workflow.md](milestones/m13_agentic_research_workflow.md)

**What was built**: Introduced an autonomous Agentic Research Workflow powered by an adaptive ReAct (Reasoning + Acting) loop. The agent dynamically selects, chains, and dispatches across all 8 platform tools to investigate high-level research questions, persisting observable execution trajectories into PostgreSQL. Implemented multi-dimensional safety boundaries (max 10 iterations, max 25 tool calls, 300s timeout, max 3 consecutive errors), duplicate tool call skipping, observation truncation (1,500 chars), context budget pruning, intermediate trajectory checkpointing every 3 iterations, and forced final answer synthesis with `json_mode=True`. Extended `LLMService` with multi-turn `generate_chat()`. Added `POST /api/projects/{p_id}/agent/research`, `GET /api/projects/{p_id}/agent/sessions`, and `GET /api/projects/{p_id}/agent/sessions/{s_id}` endpoints. 20 new unit and integration tests, 146 total tests passing, 0 regressions.

**Key Architectural Decision**: **Single Adaptive ReAct Loop with Multi-Dimensional Stopping & Checkpointing**: Rather than hard-coding brittle sequential graphs (Discovery -> Extraction -> Comparison -> Synthesis), a single adaptive ReAct loop with heuristic guidance in the prompt allows the agent to self-direct its exploration path. Runaway execution is prevented by 4 orthogonal limits, duplicate calls are skipped via canonical signature hashing, and partial progress is safely checkpointed to PostgreSQL every 3 iterations, ensuring resilience on long research tasks.

---

### Milestone 14 — Experiment Planning & Tracking
**Version**: `v1.4` | **Migration**: `7792f4a5525d_create_experiments_table.py`  
**Full Chronicle**: [m14_experiment_tracking.md](milestones/m14_experiment_tracking.md)

**What was built**: Introduced a lightweight, domain-agnostic scientific experiment planning and tracking ledger that connects literature research and structured research plans (Milestone 11) with empirical experiment management. Built a dedicated `experiments` table with foreign keys to `projects` (`ON DELETE CASCADE`) and `research_plans` (`ON DELETE SET NULL`). Implemented dual creation workflows: unified batch/selective plan promotion via `POST /api/projects/{p_id}/experiments/promote` and unrestricted manual experiment recording across any initial status (`draft`, `planned`, `in_progress`, `completed`, `abandoned`) via `POST /api/projects/{p_id}/experiments`. Uniformly enforced strict completion outcome validation (requiring non-empty quantitative results OR qualitative findings with a summary, or both) across creation, status updates, and results logging. Implemented contextual provenance verification for gap IDs, document IDs, and hypothesis IDs against actual project data. Built selective results replacement, reopening logic clearing completion timestamps, and registered two secondary read-only agent tools (`list_experiments`, `get_experiment`) for the Milestone 13 research agent. 18 new unit, integration, lifecycle, and tool tests written; 164 total tests passing, 0 regressions.

**Key Architectural Decision**: **Hybrid Relational Core with JSONB Attributes & Domain-Agnostic Outcomes**: Avoided monolithic JSON blobs and rigid tabular schemas by splitting experiment data into indexed, strictly typed relational columns for invariants (`status`, `priority`, `hypothesis_verdict`, timestamps, FKs) alongside validated, open-ended JSONB columns for flexible datasets, variables, hyperparameters, metric results, and qualitative findings. The platform treats quantitative metrics and qualitative findings as independently optional first-class outcomes, supporting exploratory, theoretical, and qualitative research without forcing artificial benchmark metrics or execution engines.

---

### Milestone 15 — Experiment Comparison
**Version**: `v1.5` | **Migration**: None (App level changes only)  
**Full Chronicle**: [m15_experiment_comparison.md](milestones/m15_experiment_comparison.md)

**What was built**: Introduced an empirical, deterministic experiment comparison engine and service to compare multiple internally tracked experiments (from Milestone 14) side-by-side. Created `experiment_comparison_engine.py` as a pure, side-effect-free computational module handling metric canonicalization, alias resolution, strict unit normalization (with exact binary vs decimal memory conversions), directional baseline deltas ($\Delta$ and $\%$), parameter divergence tracking with deep JSON equality, 2-objective Pareto frontier trade-off analysis, plan-scoped hypothesis consensus, and markdown report generation. Created `experiment_comparison_service.py` to coordinate database retrieval, clean validation separation (422 Pydantic schema validation vs 400 service business rule validation vs 404 entity resolution), and optional LLM analytical synthesis with resilient failure containment. Added `POST /api/projects/{p_id}/experiments/compare` and `GET /api/projects/{p_id}/experiments/available-metrics` REST endpoints. Added the 11th platform tool (`compare_experiments`) registered in `ToolRegistry` with a 10-experiment safety limit. 26 comprehensive unit, integration, validation, and tool tests written; 190 total tests passing across full suite, 0 regressions.

**Key Architectural Decision**: **Pure Deterministic Engine Decoupling & Strict Metric/Unit Separation**: Completely separated side-effect-free math/comparison logic (`experiment_comparison_engine.py`) from database lookups and LLM generation (`experiment_comparison_service.py`). Canonical metric identities (`latency`) are decoupled from units (`ms`, `s`), with bare metrics lacking required unit metadata marked `incompatible_units` rather than assuming default units. Pareto analysis is strictly opt-in and restricted to two distinct objectives with explicit directions to prevent dominance ambiguity. If the optional LLM synthesis layer fails or times out, the service preserves the complete deterministic matrix and returns `synthesis_status: "failed"` without disrupting user analysis.

---

### Milestone 16 — AI / RAG / Agent Evaluation Framework
**Version**: `v1.6` | **Migration**: `a16e45f9c101_create_evaluation_tables.py`  
**Full Chronicle**: [m16_evaluation_framework.md](milestones/m16_evaluation_framework.md)

**What was built**: Introduced a native, evidence-driven evaluation framework capable of benchmark-testing Information Retrieval, RAG generation faithfulness, and ReAct agent trajectories with full provenance and historical reproducibility. Built `evaluation_engine.py` as a pure, side-effect-free scoring engine implementing:
- IR metrics (Recall@K, Precision@K, MRR@K, nDCG@K, HitRate@K) with strict rank-order deduplication to prevent duplicate retrieved chunk IDs from inflating metrics, strict positive integer validation on $K$ (rejecting booleans and non-integers), and Safe Empty Aggregation returning `None` for unannotated queries.
- Two-tier RAG generation evaluation: atomic claim decomposition with citation markers (returning `faithfulness = None` for answers lacking extractable claims) followed by NLI entailment audits (`SUPPORTED`, `CONTRADICTED`, `UNSUPPORTED`), separating citation validity from semantic citation support, and evaluating multi-citation claims with OR semantics.
- Outcome-focused agent trajectory evaluation: separates primary task completion and model-judged answer correctness from secondary tool selection diagnostics (`tool_precision`, `tool_recall`, `tool_jaccard`), ensuring alternative valid tool sequences are never penalized. Measures `trajectory_efficiency` (returning `None` when minimum expected steps are unavailable) and `error_recovery_success` (whether the agent succeeded after encountering tool errors).
Created 4 relational tables (`evaluation_datasets`, `evaluation_dataset_items`, `evaluation_runs`, `evaluation_item_results`) using foreign keys with `ON DELETE SET NULL` on `dataset_id` and `dataset_item_id`, guaranteeing historical evaluation runs and item results remain permanently accessible even if the source datasets or items are deleted. Per-item results preserve immutable snapshots of exact retrieved chunk texts, reference answers, and dedicated `expected_tools_snapshot` column. Built a synthetic benchmark generator that enforces the intra-document constraint for multi-chunk queries (both chunks must come from the same paper), audits candidates via self-grounding verification, and defaults candidate items to `is_validated = False` (runs default to `validated_only = True`). Integrated evaluation runs with Milestone 14/15 experiment tracking when `create_experiment = True`. Registered the 12th (`run_evaluation`) and 13th (`get_evaluation_results`) platform tools in `ToolRegistry`. 21 new unit and integration tests written (11 engine tests + 10 service/API tests); 211 total tests passing across full repository, 0 regressions.

**Key Architectural Decision**: **Pure Mathematical Engine Decoupling, Provenance Preservation without Versioning Overhead, and Separation of Outcome from Diagnostics**:
1. Mathematical invariants (Precision, Recall, MRR, nDCG, Citation Validity/Support, Trajectory Efficiency, Error Recovery) are computed purely in `EvaluationEngine` without database or network calls, keeping deterministic calculations clean and clearly distinguished from probabilistic model-judged estimates (faithfulness entailment, relevance, answer correctness).
2. Rather than building a complicated document/dataset versioning subsystem, historical reproducibility is guaranteed by storing the exact retrieved chunk texts directly in `actual_output`, snapshotting expected tools in a dedicated column, and using `ON DELETE SET NULL` so dataset maintenance never destroys empirical evaluation history.
3. Agent evaluation treats task completion and answer correctness as primary goals, while tool precision and recall serve as secondary diagnostics to prevent penalizing researchers or agents for discovering innovative or valid alternative tool execution paths.
4. Strictly avoided external evaluation frameworks (Ragas, TruLens, LangSmith) in favor of transparent, defensible native implementations where every architectural and scoring formula can be justified and explained in an interview.

---

*(Add each new milestone summary here after its deep-dive file is written.)*
