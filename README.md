# Evidence-Driven AI Research & Experimentation Platform

> An end-to-end, evidence-driven AI research and experimentation platform that guides researchers from an initial research question to empirical, reproducible conclusions through structured literature ingestion, multi-stage hybrid retrieval, automated scientific planning, autonomous agentic exploration, experiment tracking, and quantitative evaluation.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-0.5+-336791.svg)](https://github.com/pgvector/pgvector)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-black.svg)](https://ollama.ai/)
[![Tests Passing](https://img.shields.io/badge/tests-211%20passed-brightgreen.svg)]()
[![Status](https://img.shields.io/badge/status-v1.6_Active_Development-orange.svg)]()

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation & Environment Setup](#installation--environment-setup)
  - [Database Provisioning & Migrations](#database-provisioning--migrations)
  - [Local LLM Configuration](#local-llm-configuration)
  - [Running the Server](#running-the-server)
  - [Running the Test Suite](#running-the-test-suite)
- [API Overview & Examples](#api-overview--examples)
- [End-to-End Research Workflow](#end-to-end-research-workflow)
- [Current Development Status](#current-development-status)
- [Future Roadmap](#future-roadmap)
- [Contributing & License](#contributing--license)

---

## Overview

Most AI research tools act as simple conversational chatbots or naive Retrieval-Augmented Generation (RAG) wrappers. While they can summarize text, they lack **traceability**, **structured understanding**, **empirical rigor**, and **reproducibility**. They cannot formulate testable hypotheses, coordinate multi-step research investigations, track real-world experiment parameters, compare competing empirical runs on Pareto frontiers, or benchmark their own retrieval and generation quality against objective standards.

This platform is engineered as a **general-purpose, evidence-driven scientific workspace**. Large Language Models (LLMs) and retrieval pipelines are not treated as black boxes, but as observable components embedded inside a strictly typed, modular monolith architecture backed by relational storage and deterministic computational engines.

The platform unifies the full scientific discovery cycle:

$$\text{Research Question} \longrightarrow \text{Ingestion \& Provenance} \longrightarrow \text{Hybrid Retrieval \& Reranking} \longrightarrow \text{Structured Extraction} \longrightarrow \text{Research Planning} \longrightarrow \text{Autonomous ReAct Agent} \longrightarrow \text{Experiment Tracking} \longrightarrow \text{Pareto Comparison} \longrightarrow \text{Deterministic Evaluation}$$

Every major architectural decision—from Reciprocal Rank Fusion ($k=60$) to two-tier claim entailment verification—is grounded in empirical baselines and mathematical defensibility.

---

## Key Features

### 1. Document Management & Boundary-Aware Recursive Chunking
- **Project Isolation**: Partition research papers, notes, plans, and experiments into isolated project workspaces.
- **Physical Page & Offset Provenance**: PyMuPDF extracts text page-by-page, recording global character offsets (`char_offset_start`, `char_offset_end`) and page boundaries (`page_start`, `page_end`).
- **Hierarchical Recursive Splitter**: Splits text across natural boundaries (`["\n\n", "\n", ". ", " ", ""]`) to preserve paragraph and sentence cohesion, with configurable fallback to sliding-window chunking.
- **Text Normalization**: Strips null bytes, rejoins hyphenated line breaks, and standardizes whitespace.

### 2. Multi-Stage Hybrid Retrieval & Neural Reranking
- **PostgreSQL Full-Text Search (FTS)**: Lexical matching via precomputed `tsvector` columns, GIN indexing, `websearch_to_tsquery` Google-style query parsing, and `ts_rank_cd` cover-density proximity ranking.
- **Dense Vector Search**: 384-dimensional semantic embeddings via local `sentence-transformers/all-MiniLM-L6-v2` and native PostgreSQL `pgvector` cosine distance (`<=>`).
- **Reciprocal Rank Fusion (RRF)**: Application-layer rank fusion merging top-60 lexical and vector candidates using parameter-free RRF:
  $$\text{RRF Score}(d) = \sum_{m \in \{\text{FTS}, \text{vec}\}} \frac{1}{60 + r_m(d)}$$
- **Cross-Encoder Reranking**: 2nd-stage neural reranking via `cross-encoder/ms-marco-MiniLM-L-6-v2` over candidate pools with post-rerank pagination, capturing joint token-to-token cross-attention interactions.

### 3. Evidence-Grounded RAG with Single-Call Chain-of-Thought
- **Single-Call CoT Prompting**: Enforces an `evidence_analysis` field in the JSON schema before generating the final `answer`, reducing factual hallucination without multi-call latency penalties.
- **Programmatic Citation Verification**: Audits emitted citations against retrieved passages, mapping valid references to exact chunk IDs and page numbers while flagging hallucinated source indices.

### 4. Structured Research Extraction & Literature Comparison
- **8-Dimensional Paper Extraction**: Extracts structured scientific dimensions (`research_problem`, `methodology`, `models_used`, `datasets`, `evaluation_metrics`, `results`, `limitations`, `baselines`) into dedicated PostgreSQL columns.
- **Hybrid Context Gathering**: Selects head chunks (Abstract/Intro), tail chunks (Conclusion/Limitations), and semantically retrieved internal passages, extracting metadata in a single fast inference pass.
- **Deterministic Literature Comparison**: Compiles side-by-side tabular comparison matrices in $<10\text{ms}$ with zero hallucination risk, paired with optional LLM comparative synthesis.

### 5. Evidence-Driven Research Planning
- **Traceable Chain of Inquiry**: Enforces strict structural relational dependencies:
  $$\text{Literature Gaps } (G_i) \longrightarrow \text{Hypotheses } (H_j) \longrightarrow \text{Proposed Experiments } (E_k)$$
- **Bounded-Context Guardrails**: Prevents the "unobserved topic fallacy" by explicitly conditioning the planner to distinguish between universal scientific gaps and topics unobserved in the local document sample.

### 6. Declarative Sandboxed Tool Calling & ReAct Agent
- **13 Platform Tools**: Declarative tools exposing search, chunk retrieval, document inspection, extractions, comparative matrices, research plans, experiment tracking, and evaluation runs.
- **Zero-Trust Scoping (`ToolContext`)**: Server-injected execution context guarantees `project_id` is never accepted from or controlled by the LLM, eliminating prompt-injection tenant leaks.
- **Autonomous ReAct Loop**: Multi-turn reasoning loop with 4 orthogonal safety boundaries (10 iterations, 25 tool calls, 300s timeout, 3 consecutive errors), canonical duplicate signature hashing, context budget trimming (~3.5 chars/token), and intermediate trajectory checkpointing.
- **Forced Synthesis Fallback**: Guaranteed evidence-grounded synthesis pass when loop limits trigger.

### 7. Empirical Experiment Tracking & Pareto Analysis
- **Scientific Provenance**: Relational `experiments` table linking tracked runs to research plans, specific hypotheses, gaps, and source documents with `ON DELETE SET NULL` preservation.
- **Idempotent Promotion**: Unique constraint on `(research_plan_id, plan_experiment_id)` ensures idempotent batch or selective promotion of proposed experiments.
- **Pure Comparison Engine**: Decouples mathematical computation from database queries.
- **Metric Normalization**: Disentangles metric identities from units via an alias registry, strictly distinguishing decimal ($1\text{ GB} = 1000\text{ MB}$) from binary ($1\text{ GiB} = 1024\text{ MiB}$) memory.
- **Two-Objective Pareto Frontier**: Identifies non-dominated experimental configurations across competing trade-offs (e.g., maximizing Recall@10 while minimizing latency).
- **Plan-Scoped Hypothesis Consensus**: Aggregates empirical verdicts into deterministic states (`supported`, `contradicted`, `mixed`, `inconclusive`).

### 8. Native AI, RAG & Agent Evaluation Framework
- **Pure Scoring Engine (`EvaluationEngine`)**: Zero-dependency mathematical implementations of classical Information Retrieval (IR) metrics:
  - $\text{Precision@K}$, $\text{Recall@K}$, $\text{MRR@K}$ (evaluated strictly at cutoff $K$), $\text{nDCG@K}$ (logarithmic position discounting), and $\text{HitRate@K}$.
  - Rank-preserving deduplication preventing duplicate chunk IDs from inflating metrics.
  - Safe Empty Aggregation returning `None` instead of division-by-zero or false $1.0$ scores.
- **Two-Tier RAG Evaluation**: Decomposes answers into atomic claims via LLMs and evaluates semantic entailment (`SUPPORTED`, `CONTRADICTED`, `UNSUPPORTED`) against retrieved passages, separating citation validity from semantic support.
- **Outcome-Focused Trajectory Diagnostics**: Evaluates primary task completion independently from non-penalizing tool diagnostics (tool precision, recall, Jaccard, redundancy ratio, error recovery success).
- **Historical Run Preservation**: Foreign keys use `ON DELETE SET NULL`, and per-item results freeze immutable JSONB snapshots of retrieved chunk text and expected tools.

---

## System Architecture

The platform follows a **5-layer modular monolith architecture**:

```
+---------------------------------------------------------------------------------------------+
|                                         Client Layer                                        |
|               FastAPI REST API  |  Interactive Swagger UI  |  Autonomous Agent              |
+---------------------------------------------------------------------------------------------+
                                               │
                                               ▼
+---------------------------------------------------------------------------------------------+
|                                      API & Routing Layer                                    |
|   13 Domain Routers  |  Pydantic Validation  |  Dependency Injection (get_db, ToolContext)  |
+---------------------------------------------------------------------------------------------+
                                               │
                                               ▼
+---------------------------------------------------------------------------------------------+
|                                        Service Layer                                        |
|   ProcessingService  |  SearchService  |  RAGService  |  ExtractionService                  |
|   ComparisonService  |  ResearchPlanningService  |  AgentService  |  ExperimentService      |
|   ExperimentComparisonService  |  EvaluationService  |  ToolExecutionService                |
+---------------------------------------------------------------------------------------------+
                     │                                                     │
                     ▼                                                     ▼
+------------------------------------------+     +--------------------------------------------+
|         Pure Computational Engines       |     |           Repositories (Data Access)       |
|   - experiment_comparison_engine.py      |     |   ProjectRepo  |  DocumentRepo  | ChunkRepo |
|   - evaluation_engine.py                 |     |   SearchRepo   |  VectorSearchRepo          |
|   (Zero I/O, Side-Effect-Free Math)      |     |   ExtractionRepo  |  ResearchPlanRepo       |
+------------------------------------------+     |   AgentSessionRepo  |  EvaluationRepo      |
                                                 +--------------------------------------------+
                                                                       │
                                                                       ▼
+---------------------------------------------------------------------------------------------+
|                                    Database & Storage Layer                                 |
|   PostgreSQL 16 (ACID Relational Core)  |  GIN Index (Generated TSVECTOR)                   |
|   pgvector (384-dim Cosine Distance)    |  JSONB Semi-Structured Payloads                   |
|   Local File Storage (data/uploads/)    |  ON DELETE CASCADE / SET NULL Integrity           |
+---------------------------------------------------------------------------------------------+
```

### High-Level Component Flow

```mermaid
flowchart TD
    subgraph Ingestion ["1. Document Ingestion"]
        PDF["Academic PDF"] --> Upload["DocumentService.upload()"]
        Upload --> PyMuPDF["PyMuPDF Extraction & Page Tracking"]
        PyMuPDF --> Splitter["ProcessingService (Recursive Chunking)"]
        Splitter --> Chunks[("PostgreSQL Chunks Table")]
    end

    subgraph Retrieval ["2. Multi-Stage Retrieval"]
        Chunks --> FTS["PostgreSQL FTS (tsvector + GIN)"]
        Chunks --> Embed["EmbeddingService (all-MiniLM-L6-v2)"]
        Embed --> PGV[("pgvector (Cosine Distance)")]
        Query["User Search / Agent Query"] --> FTS
        Query --> PGV
        FTS --> RRF["Reciprocal Rank Fusion (k=60)"]
        PGV --> RRF
        RRF --> Rerank["Cross-Encoder Reranker (ms-marco)"]
        Rerank --> Passages["Top K Evidence Passages"]
    end

    subgraph Intelligence ["3. Research Intelligence & Planning"]
        Passages --> RAG["RAGService (Single-Call CoT + Citations)"]
        Chunks --> Extract["ExtractionService (8 Scientific Dimensions)"]
        Extract --> Compare["ComparisonService (Tabular Matrix + Synthesis)"]
        Compare --> Plan["ResearchPlanningService (Gaps -> Hypotheses -> Experiments)"]
    end

    subgraph Execution ["4. Autonomous Agent & Experimentation"]
        Plan --> Agent["AgentService (Adaptive ReAct Loop)"]
        Agent --> Tools["13 Sandboxed Platform Tools"]
        Tools -.-> Retrieval
        Tools -.-> Intelligence
        Plan --> Tracking["ExperimentService (Promotion & Status Lifecycle)"]
        Tracking --> Pareto["ExperimentComparisonService (Baseline Deltas & Pareto Analysis)"]
    end

    subgraph Benchmarking ["5. Quantitative Evaluation"]
        Pareto --> Eval["EvaluationService (Retrieval, RAG & Agent Runs)"]
        Eval --> EvalEngine["Pure EvaluationEngine (Recall, Precision, MRR, nDCG)"]
        EvalEngine -.-> Tracking
    end
```

---

## Technology Stack

| Category | Technology | Purpose & Implementation Details |
|---|---|---|
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/) | Asynchronous web framework, dependency injection (`Depends`), OpenAPI docs. |
| **Data Validation** | [Pydantic v2](https://docs.pydantic.dev/) | Strict input validation, data normalization, and schema generation (`model_validate`). |
| **Configuration** | [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | Centralized environment variable management via `backend/app/core/config.py`. |
| **Database & ORM** | [PostgreSQL 16](https://www.postgresql.org/) & [SQLAlchemy 2.0](https://www.sqlalchemy.org/) | Relational database with modern `Mapped[...]` typed declarative modeling. |
| **Database Driver** | [psycopg 3](https://www.psycopg.org/psycopg3/) | High-performance PostgreSQL driver with native binary copy support. |
| **Database Migrations** | [Alembic](https://alembic.sqlalchemy.org/) | Versioned, auditable database schema migrations. |
| **Vector Storage** | [pgvector](https://github.com/pgvector/pgvector) | Native vector storage (`vector(384)`) and cosine distance indexing (`<=>`). |
| **PDF Extraction** | [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`) | Fast C-based text extraction, page tracking, and structural PDF validation. |
| **Dense Embeddings** | [Sentence-Transformers](https://sbert.net/) | `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, local inference). |
| **Neural Reranking** | [Cross-Encoder](https://www.sbert.net/docs/pretrained_cross-encoders.html) | `cross-encoder/ms-marco-MiniLM-L-6-v2` for 2nd-stage candidate reranking. |
| **Local LLM Engine** | [Ollama](https://ollama.ai/) (`ollama-python`) | Local LLM hosting (`llama3.1:8b`) with JSON mode and native tool calling. |
| **Testing Harness** | [pytest](https://docs.pytest.org/) & `pytest-httpx` | 211 tests with transactional rollback isolation on a dedicated test database. |

> **Architectural Note:** Frameworks such as LangChain, LlamaIndex, CrewAI, and Ragas were **intentionally omitted**. Building native services, tool registries, ReAct loops, and evaluation engines guarantees complete architectural transparency, zero dependency churn, and 100% explainability.

---

## Project Structure

```text
research-platform/
├── backend/
│   ├── alembic/                      # Alembic database migrations
│   │   ├── versions/                 # 10 chronological schema migration scripts
│   │   └── env.py                    # Migration runtime environment
│   ├── alembic.ini                   # Alembic configuration
│   ├── app/
│   │   ├── api/                      # REST API routing and endpoints
│   │   │   ├── endpoints/            # 13 domain-specific route modules
│   │   │   │   ├── projects.py       # Project workspace management
│   │   │   │   ├── documents.py      # PDF upload, listing, deletion, extraction triggers
│   │   │   │   ├── processing.py     # Document text chunking & passage retrieval
│   │   │   │   ├── embedding.py      # Batch vector embedding endpoints
│   │   │   │   ├── search.py         # Keyword, semantic, and hybrid search
│   │   │   │   ├── rag.py            # Evidence-grounded Q&A with citation verification
│   │   │   │   ├── comparison.py     # Cross-document literature comparison
│   │   │   │   ├── research_planning.py # Traceable research roadmap generation
│   │   │   │   ├── tools.py          # Sandboxed tool catalog and execution
│   │   │   │   ├── agent.py          # Autonomous ReAct agent sessions
│   │   │   │   ├── experiments.py    # Experiment tracking & plan promotion
│   │   │   │   ├── experiment_comparison.py # Multi-experiment comparison & Pareto analysis
│   │   │   │   └── evaluation.py     # Benchmarks, synthetic generation & eval runs
│   │   │   └── router.py             # Central APIRouter mounting all modules
│   │   ├── core/
│   │   │   └── config.py             # Centralized settings and runtime boundaries
│   │   ├── db/
│   │   │   ├── base_class.py         # Declarative Base with auto id & timestamps
│   │   │   └── session.py            # Engine, sessionmaker, and get_db dependency
│   │   ├── models/                   # SQLAlchemy 2.0 ORM models
│   │   │   ├── project.py            # Project entity & cascade relationships
│   │   │   ├── document.py           # Document entity & status lifecycle
│   │   │   ├── chunk.py              # Chunk model with TSVECTOR & pgvector columns
│   │   │   ├── extraction.py         # 8-dimensional structured metadata model
│   │   │   ├── research_plan.py      # Research plan entity with JSONB plan_output
│   │   │   ├── agent_session.py      # Agent session with JSONB step trajectory
│   │   │   ├── experiment.py         # Experiment model with composite index & constraints
│   │   │   └── evaluation.py         # Dataset, DatasetItem, Run, and ItemResult models
│   │   ├── prompts/                  # Structured prompts with JSON schemas
│   │   │   ├── rag_prompts.py        # Single-call CoT RAG prompts
│   │   │   ├── research_planning_prompts.py # Bounded-context research planning prompts
│   │   │   ├── agent_prompts.py      # ReAct strategy heuristics & forced synthesis
│   │   │   ├── experiment_comparison_prompts.py # Analytical comparison synthesis prompts
│   │   │   └── evaluation_prompts.py # Claim decomposition, entailment, and synthetic Q&A
│   │   ├── repositories/             # Data Access Layer (encapsulates SQL queries)
│   │   │   ├── project_repository.py
│   │   │   ├── document_repository.py
│   │   │   ├── chunk_repository.py
│   │   │   ├── search_repository.py  # FTS query parser, ranking & headlines
│   │   │   ├── vector_search_repository.py # pgvector cosine distance queries
│   │   │   ├── extraction_repository.py
│   │   │   ├── research_plan_repository.py
│   │   │   ├── agent_session_repository.py
│   │   │   ├── experiment_repository.py
│   │   │   └── evaluation_repository.py
│   │   ├── schemas/                  # Pydantic validation & response schemas
│   │   │   ├── project.py, document.py, chunk.py, search.py, rag.py
│   │   │   ├── extraction.py, comparison.py, research_plan.py, tool.py
│   │   │   ├── agent.py, experiment.py, experiment_comparison.py, evaluation.py
│   │   ├── services/                 # Business logic and orchestrators
│   │   │   ├── document_service.py   # PDF upload & validation orchestration
│   │   │   ├── processing_service.py # Text cleaning & recursive chunking engine
│   │   │   ├── search_service.py     # Hybrid search & candidate pool coordinator
│   │   │   ├── sentence_transformer_embedding.py # Local embedding generation
│   │   │   ├── reranking_service.py  # Cross-encoder candidate reranker
│   │   │   ├── rag_service.py        # Evidence grounding & citation verification
│   │   │   ├── extraction_service.py # Hybrid context extraction coordinator
│   │   │   ├── comparison_service.py # Tabular matrix & synthesis coordinator
│   │   │   ├── research_planning_service.py # Research plan generator
│   │   │   ├── tool_execution_service.py # Sandboxed tool execution & timing
│   │   │   ├── agent_service.py      # Adaptive ReAct loop orchestrator
│   │   │   ├── experiment_service.py # Lifecycle management & plan promotion
│   │   │   ├── experiment_comparison_engine.py # Pure mathematical comparison engine
│   │   │   ├── experiment_comparison_service.py # Experiment comparison coordinator
│   │   │   ├── evaluation_engine.py  # Pure mathematical IR & evaluation engine
│   │   │   ├── evaluation_service.py # Benchmark execution & synthetic generator
│   │   │   └── tools/                # Declarative tool catalog
│   │   │       ├── base.py           # BaseTool ABC & server-injected ToolContext
│   │   │       ├── implementations.py# All 13 platform tool implementations
│   │   │       └── registry.py       # Central ToolRegistry & schema exporter
│   │   └── main.py                   # FastAPI app creation & router registration
│   ├── tests/                        # 211 automated integration & unit tests
│   │   ├── conftest.py               # Transactional rollback isolation fixtures
│   │   ├── test_projects.py, test_documents.py, test_processing.py
│   │   ├── test_search.py, test_semantic_search.py, test_hybrid_search.py
│   │   ├── test_reranking.py, test_rag.py, test_extractions.py
│   │   ├── test_comparison.py, test_research_planning.py, test_tools.py
│   │   ├── test_agent.py, test_experiments.py, test_experiment_comparison.py
│   │   ├── test_evaluation_engine.py, test_evaluation.py
│   │   └── test_llm_service.py
│   ├── .env.example                  # Documented environment variable template
│   └── pytest.ini                    # Test path configuration
├── data/                             # Local file storage (gitignored uploads)
├── docs/                             # Project documentation
│   ├── technical_concepts.md         # In-depth architectural & conceptual reference
│   ├── interview_questions.md        # 72 interview questions with technical answers
│   ├── architecture.md               # System design notes
│   ├── milestone_log.md              # Executive milestone log
│   └── milestones/                   # Detailed write-ups for Milestones 0 to 16
├── agents.md                         # Long-term engineering rules & development principles
├── milestone.md                      # Authoritative living project-state memory
├── requirements.txt                  # Python dependencies
└── README.md                         # This file
```

---

## Getting Started

### Prerequisites
- **Python**: Version `3.11` or higher.
- **PostgreSQL**: Version `16+` with the `pgvector` extension installed.
- **Ollama**: Installed locally with the `llama3.1:8b` model pulled.

---

### Installation & Environment Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/mohdshiblikhan/research-platform.git
   cd research-platform
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   Copy the example environment configuration into `backend/.env`:
   ```bash
   cp backend/.env.example backend/.env
   ```
   Edit `backend/.env` to configure your local PostgreSQL connection strings:
   ```env
   DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/research_platform
   TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/research_platform_test
   LLM_PROVIDER=ollama
   LLM_MODEL=llama3.1:8b
   LLM_BASE_URL=http://localhost:11434
   ```

---

### Database Provisioning & Migrations

1. **Create the development and test databases in PostgreSQL:**
   ```bash
   psql -U postgres -c "CREATE DATABASE research_platform;"
   psql -U postgres -c "CREATE DATABASE research_platform_test;"
   ```

2. **Enable the `pgvector` extension on both databases:**
   ```bash
   psql -U postgres -d research_platform -c "CREATE EXTENSION IF NOT EXISTS vector;"
   psql -U postgres -d research_platform_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```

3. **Apply Alembic migrations:**
   ```bash
   cd backend
   alembic upgrade head
   cd ..
   ```

---

### Local LLM Configuration

Ensure Ollama is running and pull the default model:
```bash
ollama serve
# In a separate terminal:
ollama pull llama3.1:8b
```

---

### Running the Server

Start the FastAPI application with Uvicorn:
```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The interactive documentation will be available at:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

---

### Running the Test Suite

The test suite runs with transactional rollback isolation on the dedicated test database (`research_platform_test`). Tests roll back automatically, leaving the test database clean.

Run the entire test suite:
```bash
cd backend
pytest tests
```

To run a specific test suite:
```bash
cd backend
pytest tests/test_evaluation_engine.py -v
pytest tests/test_experiment_comparison.py -v
pytest tests/test_agent.py -v
```

---

## API Overview & Examples

All API routes are mounted under `/api/projects`.

| Module | Method | Endpoint | Description |
|---|:---:|---|---|
| **Projects** | `POST` | `/api/projects` | Create a research project workspace |
| | `GET` | `/api/projects` | List all research projects |
| **Documents** | `POST` | `/api/projects/{p_id}/documents` | Upload a PDF paper (multipart/form-data) |
| | `POST` | `/api/projects/{p_id}/documents/{d_id}/process` | Extract text & generate recursive chunks |
| | `POST` | `/api/projects/{p_id}/documents/{d_id}/embed` | Generate 384d pgvector embeddings |
| | `POST` | `/api/projects/{p_id}/documents/{d_id}/extract` | Extract 8 structured research dimensions |
| **Search & RAG**| `GET` | `/api/projects/{p_id}/search` | Query chunks (mode=`keyword` \| `semantic` \| `hybrid`, `rerank=true`) |
| | `POST` | `/api/projects/{p_id}/ask` | Evidence-grounded RAG with citation verification |
| **Comparison** | `POST` | `/api/projects/{p_id}/compare` | Cross-paper tabular comparison & synthesis |
| **Planning** | `POST` | `/api/projects/{p_id}/plan` | Generate Gap $\to$ Hypothesis $\to$ Experiment plan |
| **Tools** | `GET` | `/api/projects/{p_id}/tools` | List registered tools with OpenAI-compatible schemas |
| | `POST` | `/api/projects/{p_id}/tools/execute` | Execute a tool inside a sandboxed context |
| **Agent** | `POST` | `/api/projects/{p_id}/agent/research` | Launch an autonomous ReAct research investigation |
| | `GET` | `/api/projects/{p_id}/agent/sessions/{s_id}` | Retrieve agent execution trajectory & citations |
| **Experiments** | `POST` | `/api/projects/{p_id}/plans/{plan_id}/experiments` | Idempotently promote proposed experiments from plan |
| | `POST` | `/api/projects/{p_id}/experiments` | Manually record an experiment in any status |
| | `POST` | `/api/projects/{p_id}/experiments/{e_id}/results`| Log empirical results, metrics, and findings |
| | `POST` | `/api/projects/{p_id}/experiments/compare` | Compare runs with baseline deltas & Pareto analysis |
| **Evaluation** | `POST` | `/api/projects/{p_id}/evaluation/datasets` | Create a benchmark evaluation dataset |
| | `POST` | `/api/projects/{p_id}/evaluation/datasets/generate-synthetic` | Generate synthetic Q&A benchmarks from papers |
| | `POST` | `/api/projects/{p_id}/evaluation/runs/retrieval` | Benchmark IR metrics (Recall@K, MRR@K, nDCG@K) |
| | `POST` | `/api/projects/{p_id}/evaluation/runs/rag` | Benchmark RAG faithfulness & citation link precision |
| | `POST` | `/api/projects/{p_id}/evaluation/runs/agent` | Benchmark agent task completion & step efficiency |

---

### Example Request: Hybrid Search with Cross-Encoder Reranking

```bash
curl -X GET "http://localhost:8000/api/projects/1/search?q=hallucination+mitigation+techniques&mode=hybrid&rerank=true&limit=3" \
  -H "Accept: application/json"
```

**Response:**
```json
{
  "query": "hallucination mitigation techniques",
  "project_id": 1,
  "search_mode": "hybrid",
  "total_results": 42,
  "limit": 3,
  "offset": 0,
  "query_time_ms": 48.6,
  "results": [
    {
      "chunk_id": 104,
      "document_id": 12,
      "document_filename": "self_reflective_rag.pdf",
      "chunk_index": 7,
      "content": "Self-reflective retrieval addresses hallucination by evaluating retrieved evidence...",
      "page_start": 4,
      "page_end": 4,
      "rrf_score": 0.0321,
      "rerank_score": 0.8942
    }
  ]
}
```

---

### Example Request: Multi-Experiment Comparison with Pareto Frontier

```bash
curl -X POST "http://localhost:8000/api/projects/1/experiments/compare" \
  -H "Content-Type: application/json" \
  -d '{
    "experiment_ids": [101, 102, 103],
    "baseline_experiment_id": 101,
    "pareto_objectives": [
      {"metric_name": "recall@10", "direction": "maximize"},
      {"metric_name": "latency", "direction": "minimize"}
    ],
    "include_synthesis": true
  }'
```

**Response:**
```json
{
  "project_id": 1,
  "baseline_experiment_id": 101,
  "experiments_compared": 3,
  "metric_rows": [
    {
      "canonical_name": "recall@10",
      "display_name": "Recall@10",
      "direction": "higher_is_better",
      "baseline_value": 0.72,
      "values": [
        {"experiment_id": 101, "normalized_value": 0.72, "is_best": false},
        {"experiment_id": 102, "normalized_value": 0.84, "absolute_delta": 0.12, "percent_change": 16.67, "delta_status": "improvement", "is_best": false},
        {"experiment_id": 103, "normalized_value": 0.89, "absolute_delta": 0.17, "percent_change": 23.61, "delta_status": "improvement", "is_best": true}
      ]
    }
  ],
  "pareto_analysis": {
    "is_enabled": true,
    "objective_1": {"metric_name": "recall@10", "direction": "maximize"},
    "objective_2": {"metric_name": "latency", "direction": "minimize"},
    "frontier_experiment_ids": [101, 103],
    "dominated_experiment_ids": [102],
    "points": [
      {"experiment_id": 101, "val_1": 0.72, "val_2": 15.2, "is_frontier": true, "dominated_by": [], "dominates": []},
      {"experiment_id": 102, "val_1": 0.84, "val_2": 52.0, "is_frontier": false, "dominated_by": [103], "dominates": []},
      {"experiment_id": 103, "val_1": 0.89, "val_2": 48.5, "is_frontier": true, "dominated_by": [], "dominates": [102]}
    ]
  },
  "hypothesis_consensus": [
    {
      "hypothesis_id": "H1",
      "consensus_state": "supported",
      "supported_count": 2,
      "contradicted_count": 0,
      "inconclusive_count": 0
    }
  ]
}
```

---

## End-to-End Research Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Researcher as Researcher
    participant API as FastAPI Platform
    participant DB as PostgreSQL (pgvector + FTS)
    participant Engine as Computational Engines
    participant LLM as Local LLM (Ollama)

    Researcher->>API: 1. Create Project & Upload PDFs
    API->>DB: Persist Document Metadata & Raw Chunks (with Page Provenance)
    Researcher->>API: 2. Generate Embeddings
    API->>DB: Batch Encode via all-MiniLM-L6-v2 (pgvector)
    Researcher->>API: 3. Extract 8-Dimensional Scientific Metadata
    API->>LLM: Hybrid Edge + Semantic Context Extraction (JSON Mode)
    API->>DB: Persist Structured Dimensions (Problem, Method, Results, Limitations)
    Researcher->>API: 4. Request Literature Comparison
    API->>DB: Bulk Fetch Extractions
    API-->>Researcher: Return Deterministic Tabular Matrix & Analytical Synthesis
    Researcher->>API: 5. Generate Research Plan
    API->>DB: Retrieve Evidence Passages Filtered to Analyzed Papers
    API->>LLM: Synthesize Gap -> Hypothesis -> Experiment Chain
    API->>DB: Persist ResearchPlan
    Researcher->>API: 6. Launch Autonomous ReAct Agent Session
    loop Adaptive ReAct Reasoning (up to 10 iterations)
        Agent->>LLM: Generate Thought & Select Tool
        LLM-->>Agent: Emit Tool Call (e.g. search_chunks, compare_papers)
        Agent->>API: Execute Tool in Sandboxed ToolContext
        API-->>Agent: Return Token-Efficient Summary & Provenance
    end
    Agent-->>Researcher: Return Evidence-Grounded Answer with Page Citations
    Researcher->>API: 7. Promote Plan Experiments into Tracked Entities
    API->>DB: Idempotent Insertion into experiments Table
    Researcher->>API: 8. Log Empirical Results & Findings
    API->>DB: Update Results, Target Metrics & Hypothesis Verdict
    Researcher->>API: 9. Compare Experiments & Pareto Analysis
    API->>Engine: Run experiment_comparison_engine (Metric Normalization, Deltas, Pareto)
    Engine-->>Researcher: Return Non-Dominated Frontier & Hypothesis Consensus
    Researcher->>API: 10. Benchmark System Quality
    API->>Engine: Run evaluation_engine (Recall@K, MRR@K, nDCG@K, Faithfulness)
    Engine->>DB: Record Immutable Snapshots & Summary Metrics
```

---

## Current Development Status

- **Current Version:** `v1.6`
- **Test Suite Status:** **211 tests passing**, 0 failures, 0 regressions across all suites.
- **Active Development Phase:** Planning Milestone 17 (Knowledge Graph & Advanced Research Intelligence).

### Milestone Completion Record

| Milestone | Status | Core Capability Implemented | Test Count |
|:---:|:---:|---|:---:|
| **M00** | Completed | Backend scaffolding, PostgreSQL connection, Alembic, transactional test fixtures | 2 |
| **M01** | Completed | Research project workspace CRUD & Pydantic validation | 11 |
| **M02** | Completed | PDF upload, structural validation (PyMuPDF), filesystem storage, cascade deletion | 13 |
| **M03** | Completed | Document ingestion, text cleaning, recursive boundary-aware chunking, page provenance | 14 |
| **M04** | Completed | Baseline keyword search (PostgreSQL `tsvector`, GIN index, `ts_rank_cd` cover density) | 20 |
| **M05** | Completed | Semantic search (`sentence-transformers/all-MiniLM-L6-v2`, `pgvector` cosine distance) | 5 |
| **M06** | Completed | Hybrid retrieval via application-layer Reciprocal Rank Fusion (RRF, $k=60$) | 2 |
| **M07** | Completed | Neural reranking via `cross-encoder/ms-marco-MiniLM-L-6-v2` with post-rerank slicing | 9 |
| **M08** | Completed | Evidence-grounded RAG with single-call CoT and programmatic citation verification | 5 |
| **M09** | Completed | 8-dimensional structured research extraction via local LLMs in JSON mode | 3 |
| **M10** | Completed | Multi-document literature comparison matrix ($<10\text{ms}$) & analytical synthesis | 10 |
| **M11** | Completed | Evidence-driven research planning ($\text{Gaps } \to \text{Hypotheses } \to \text{Experiments}$) | 14 |
| **M12** | Completed | Declarative sandboxed tool calling (8 tools, zero-trust server-injected `ToolContext`) | 16 |
| **M13** | Completed | Autonomous ReAct research agent (safety boundaries, duplicate hashing, context trimming) | 20 |
| **M14** | Completed | Experiment planning & tracking (lifecycle machine, idempotent promotion, provenance) | 18 |
| **M15** | Completed | Deterministic experiment comparison (metric normalization, baseline deltas, Pareto analysis) | 26 |
| **M16** | Completed | AI/RAG/Agent evaluation framework (pure `EvaluationEngine`, classical IR metrics, claim entailment) | 23 |
| **Total** | | **17 Completed Milestones** | **211 Passed** |

---

## Future Roadmap

The following phases represent the forward architectural roadmap:

- **Milestone 17: Research Knowledge Graph / GraphRAG** *(In Progress)*:
  - Graph representation linking papers, methods, datasets, claims, experiments, and evaluation results.
  - Entity-relation extraction pipeline from literature.
  - Graph-Augmented Generation (GAG) traversing graph relationships for literature discovery.
- **Milestone 18: Advanced Research Intelligence & Multimodal Understanding**:
  - Multimodal extraction for tables, charts, figures, and mathematical formulas from papers.
  - Query decomposition and sub-query execution over complex, comparative research questions.
- **Milestone 19: Productionization & Distributed Scaling**:
  - Distributed asynchronous task queues using Celery or ARQ backed by Redis.
  - S3 / Google Cloud Storage object storage integration for uploaded PDFs.
  - HNSW approximate nearest neighbor (ANN) vector indexing for $100\text{k}+$ chunk collections.
  - Server-Sent Events (SSE) token streaming for RAG and agent responses.
  - Role-based access control (RBAC), API key authentication, and rate limiting.

---

## Contributing & License

### Contributing
This repository is developed following strict milestone engineering discipline. Code contributions, feature suggestions, and bug reports are welcome. Please ensure that:
1. Every new feature includes integration and unit tests demonstrating zero regressions across existing test suites.
2. Architectural decisions are documented with explicit rationale, alternatives, and trade-offs.
3. Database changes include an Alembic migration script.

### License
This project is currently developed for educational and research engineering purposes. All rights are reserved by the author. Contact the repository owner for licensing terms and permissions regarding commercial or institutional reuse.
