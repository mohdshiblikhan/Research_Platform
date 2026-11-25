# System Architecture & Architecture Decision Records (ADRs)

## 1. System Overview

The Evidence-Driven AI Research & Experimentation Platform is designed as a **Modular Monolith** built on Python, FastAPI, PostgreSQL, and SQLAlchemy. The platform empowers researchers to transition from a research question to empirical, evidence-grounded conclusions through rigorous document ingestion, multi-stage retrieval, structured synthesis, autonomous planning, and mathematical evaluation.

```
+---------------------------------------------------------------------------------------------------+
|                                          FastAPI API Layer                                        |
|  /projects  |  /documents  |  /process  |  /search  |  /rag  |  /extractions  |  /plans  |  /eval   |
+---------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+---------------------------------------------------------------------------------------------------+
|                                            Service Layer                                          |
|  - ProcessingService (PyMuPDF, Recursive Splitter, Offset Tracking)                               |
|  - SearchService (FTS, Cosine Distance, Application-Level RRF)                                     |
|  - RAGService (Evidence Assembly, CoT Prompting, Citation Auditing)                              |
|  - AgentOrchestrator (ReAct Loop, Tool Registry, Scoped ToolContext)                              |
|  - EvaluationEngine (Pure Matrix Math, Precision/Recall/MRR/nDCG@K, RAG Entailment)              |
+---------------------------------------------------------------------------------------------------+
                         │                                                   │
                         ▼                                                   ▼
+--------------------------------------------------+       +----------------------------------------+
|                 Repository Layer                 |       |           Local Model Inference        |
|  - ProjectRepository, DocumentRepository         |       |  - sentence-transformers (all-MiniLM)  |
|  - ChunkRepository, SearchRepository             |       |  - cross-encoder (ms-marco-MiniLM)     |
|  - VectorSearchRepository, AgentRepository       |       |  - Local LLM via Ollama (llama3.1:8b)  |
|  - PlanRepository, ExperimentRepository          |       +----------------------------------------+
|  - EvaluationRepository                          |
+--------------------------------------------------+
                         │
                         ▼
+---------------------------------------------------------------------------------------------------+
|                                PostgreSQL 16+ with pgvector                                       |
|  - Relational entities (projects, documents, research_plans, experiments, evaluations)            |
|  - Physical chunks with character offsets & page spans                                            |
|  - GENERATED ALWAYS AS STORED tsvector column + GIN index                                         |
|  - 384-dimensional dense vector embeddings (`vector(384)`)                                        |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Ingestion, Provenance & Chunking Pipeline

Unstructured PDF papers are transformed into verifiable, citable retrieval units:

```
PDF File on Disk
       │
       ▼
1. Text Extraction (PyMuPDF page-by-page)
       │
       ▼
2. Text Sanitization
   - Strip NUL bytes (\x00) for PostgreSQL compatibility
   - Rejoin hyphenated line breaks: `(\w+)-\n(\w+)` → `$1$2`
   - Collapse excess whitespace & duplicate newlines
       │
       ▼
3. Chunking Engine Dispatch (`settings.chunk_method`)
   ├── "recursive" (Default): Hierarchical boundary-aware splitting
   │   Separator hierarchy: ["\n\n", "\n", ". ", " ", ""]
   │   Preserves paragraphs and sentences without mid-word cuts
   └── "fixed" (Legacy Fallback): Rigid character sliding window (1000 chars / 200 overlap)
       │
       ▼
4. Provenance & Coordinate Mapping
   - Global char offsets (`char_offset_start`, `char_offset_end`)
   - Multi-page boundary resolution (`page_start`, `page_end`)
       │
       ▼
5. Atomic Persistence
   - Repository `db.flush()` prepares bulk chunks and status transition
   - Service `db.commit()` finalizes transaction (or rolls back on error)
```

---

## 3. Architecture Decision Records (ADRs)

### ADR 001: Modular Monolith over Microservices
- **Context**: The platform coordinates multiple computational tasks: document ingestion, lexical search, vector similarity, neural reranking, LLM generation, agent tool execution, and evaluation.
- **Alternatives**: Microservices architecture with independent document, retrieval, inference, and evaluation services communicating over gRPC/REST.
- **Decision**: Build as a strictly structured Modular Monolith with clear architectural layers (API → Service → Repository → Database).
- **Reason**: Microservices introduce distributed transaction complexity, network serialization latency, independent failure modes, and DevOps overhead without justifiable scalability requirements at this stage. Monolithic service boundaries maintain strict encapsulation while allowing in-memory object passing and single-database ACID guarantees.
- **Tradeoffs**: Cannot independently scale inference workloads from API endpoints horizontally without containerizing specific service workers later.

---

### ADR 002: PostgreSQL + pgvector as Unified Operational and Vector Store
- **Context**: Retrieval requires relational metadata filtering (by `project_id`, `document_id`), full-text keyword search, and dense semantic vector search.
- **Alternatives**: Dedicated vector databases (Qdrant, Pinecone, Milvus, Chroma) alongside PostgreSQL.
- **Decision**: Use PostgreSQL for relational data, full-text search (`tsvector` + GIN), and dense embeddings (`pgvector`).
- **Reason**: Dedicated vector databases introduce data synchronization overhead, dual-write failure vulnerabilities, network latency hops, and complex multi-source joining. With `pgvector`, vectors live alongside relational columns and full-text indexes in the same table (`chunks`), enabling atomic inserts, cascading deletes, and filtered vector search in a single SQL query.
- **Tradeoffs**: Extremely large-scale vector datasets (>10M vectors) may eventually require specialized vector partitioning or dedicated memory-optimized vector nodes.

---

### ADR 003: Hierarchical Recursive Boundary-Aware Chunking with Configurable Fallback
- **Context**: Converting academic papers into chunks requires balancing chunk size against semantic coherence.
- **Alternatives**:
  1. Rigid fixed-size sliding window (blind character slicing).
  2. Naive sentence splitting.
  3. LLM-driven semantic chunking.
- **Decision**: Implement a Hierarchical Recursive Text Splitter using separator hierarchy `["\n\n", "\n", ". ", " ", ""]`, with a runtime toggle (`settings.chunk_method = "fixed"`) to preserve the legacy fixed-size sliding window.
- **Reason**:
  - Blind character slicing (1000 chars with 200 overlap) frequently slices words and sentences in half, causing fragmented lexical lexemes for BM25 and truncated semantic thoughts for dense embedding models.
  - Hierarchical recursive splitting tries paragraph boundaries first (`\n\n`), keeping complete concepts cohesive. It recurses to single newlines (`\n`), sentences (`. `), words (` `), and characters (`""`) only when a section exceeds `chunk_size`.
  - Retaining the legacy fixed-size algorithm via `chunk_method="fixed"` is critical for empirical rigor: it enables exact apples-to-apples ablation studies in Milestone 16, mathematically proving whether recursive chunking outperforms fixed-size chunking across retrieval benchmarks.
- **Tradeoffs**: Slightly more complex string boundary tracking to ensure exact multi-page character provenance.

---

### ADR 004: Explicit Processing and Embedding Trigger Endpoints
- **Context**: Uploading a PDF, extracting text, generating chunks, and computing embeddings are distinct operations with different resource footprints.
- **Alternatives**: Automatically extract text, chunk, and embed documents in the `POST /documents` upload handler.
- **Decision**: Decouple ingestion into explicit stages:
  1. `POST /documents` (Upload & store raw PDF)
  2. `POST /documents/{id}/process` (Extract text, clean, chunk, record provenance)
  3. `POST /documents/{id}/embed` (Generate dense vector embeddings)
- **Reason**: File upload is an I/O-bound network operation; text parsing and chunking is CPU-bound; embedding generation is heavy vector mathematics. Auto-processing on upload causes HTTP connection timeouts on large PDFs, complicates error diagnosis, and prevents users from configuring chunking/embedding options. Explicit endpoints keep uploads instantaneous and cleanly map to background task queues in production.
- **Tradeoffs**: Requires clients to make sequential API calls to fully index a document.

---

### ADR 005: Application-Layer Reciprocal Rank Fusion (RRF) for Hybrid Retrieval
- **Context**: Combining lexical search (`ts_rank_cd`) and dense vector retrieval (`cosine distance`).
- **Alternatives**:
  1. Score-based linear combination ($s = \alpha \cdot s_{\text{keyword}} + (1-\alpha) \cdot s_{\text{dense}}$).
  2. Database-level complex CTE fusion queries.
- **Decision**: Retrieve candidate pools (top 60) from both repositories independently, and compute Reciprocal Rank Fusion (RRF, $k=60$) in Python application memory.
- **Reason**:
  - Score normalization is fragile: `ts_rank_cd` is unbounded, whereas cosine distance is bounded $[0, 2]$. Distribution shifts across document collections make score scaling unstable.
  - RRF operates purely on ordinal ranks ($R(d) = \sum \frac{1}{k + r_i(d)}$), making it completely invariant to score calibration discrepancies.
  - Computing fusion in application code keeps repositories isolated, modular, and cleanly unit-testable.
- **Tradeoffs**: Requires fetching $2 \times \text{candidate\_pool}$ records into application memory before returning the final top-$K$.

---

### ADR 006: Local Sentence-Transformers and Cross-Encoders over Cloud APIs
- **Context**: Vector embeddings and neural reranking required for hybrid search and RAG.
- **Alternatives**: OpenAI Text-Embedding-3 / Cohere Rerank APIs.
- **Decision**: Run local inference using `sentence-transformers/all-MiniLM-L6-v2` (384d) and `cross-encoder/ms-marco-MiniLM-L-6-v2`.
- **Reason**: Eliminates external API dependencies, eliminates per-token financial costs during development and bulk testing, avoids API rate-limit bottlenecks, guarantees researcher data privacy, and runs completely offline.
- **Tradeoffs**: Requires local CPU/GPU memory and introduces PyTorch/transformers dependencies.

---

### ADR 007: Declarative Class-Based Tool Registry & Zero-Trust Scoping (`ToolContext`)
- **Context**: ReAct agent workflows require tools to inspect search results, extractions, plans, and evaluation metrics.
- **Alternatives**: Using third-party agent frameworks (LangChain, CrewAI, AutoGen) with framework-managed tool execution.
- **Decision**: Build a custom `BaseTool` class using Pydantic schemas, standard OpenAI/Ollama function calling schemas, and a central `ToolRegistry`. The server injects a protected `ToolContext(db, project_id)` at runtime.
- **Reason**: Third-party agent frameworks introduce massive dependency graphs, high churn, hidden global states, and fragile abstractions. The custom `BaseTool` architecture gives 100% explainability. Server-side injection of `ToolContext` guarantees that the LLM can never provide or override `project_id`, preventing cross-tenant prompt injection leaks.
- **Tradeoffs**: Requires manual definition of tool schemas and dispatch logic.

---

### ADR 008: Native Pure Evaluation Engine over External Frameworks (Ragas / TruLens)
- **Context**: Need to benchmark Information Retrieval (Precision@K, Recall@K, MRR@K, nDCG@K), RAG faithfulness, and agent trajectory diagnostics.
- **Alternatives**: Heavy external evaluation libraries (Ragas, TruLens, DeepEval).
- **Decision**: Implement a native, zero-dependency pure mathematical evaluation engine (`EvaluationEngine`) in `backend/app/services/evaluation_engine.py`.
- **Reason**:
  - Full mathematical control: exact position discounting for nDCG, cutoff-strict MRR, rank-preserving deduplication, and safe empty aggregation.
  - Decoupled from database: engine functions are pure mathematical routines ($f(\text{retrieved}, \text{ground\_truth}) \to \text{score}$), enabling millisecond in-memory execution and exhaustive unit testing.
  - Deterministic evaluation: avoids library version drift and opaque heuristics.
- **Tradeoffs**: Requires authoring and maintaining scoring math and LLM-as-a-judge claim extraction prompts directly.
