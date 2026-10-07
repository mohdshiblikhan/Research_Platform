# Evidence-Driven AI Research & Experimentation Platform

> An AI-powered research and experimentation platform that helps researchers move from a research question to evidence-backed conclusions through structured document ingestion, multi-stage retrieval, evidence grounding, and empirical evaluation.

---

> 🚧 **Status: Under Active Development**

## 📌 Overview

Most AI research tools act as simple conversational chatbots or naive RAG wrappers that lack traceability, structured understanding, and empirical rigor. 

This platform is engineered as an **evidence-driven research system** where LLMs and search pipelines are components inside a robust, observable backend. The long-term goal is to build a genuine AI/ML research system where every major architectural decision is evaluated against empirical baselines.

The system supports the full scientific inquiry cycle:
$$\text{Research Question} \to \text{Literature Ingestion} \to \text{Multi-Stage Retrieval} \to \text{Evidence Grounding} \to \text{Structured Analysis} \to \text{Experimentation} \to \text{Evaluation}$$

---

## 🏗️ Architecture

The platform starts as a **modular monolith** backend designed for maintainability, testability, and clear separation of concerns. It deliberately avoids microservices or unnecessary abstractions until empirical data justifies them.

### High-Level System Flow

```text
[ Research User / Client ]
            │
            ▼
    [ FastAPI Layer ] (REST API Endpoints & Request Validation)
            │
    ┌───────┴───────────────────────┐
    ▼                               ▼
[ Service Orchestrator ]     [ Repositories ]
(Ingestion, Search, RAG)    (Data Access Layer)
    │                               │
    ├───────────────────────────────┤
    ▼                               ▼
[ File Storage / PDFs ]      [ PostgreSQL (SQLAlchemy + Alembic) ]
```

### Ingestion & Evidence Pipeline
1. **Upload**: Research papers (PDFs) are uploaded and linked to specific projects.
2. **Extraction & Chunking**: PDFs are parsed using `PyMuPDF`, preserving exact page boundaries and chunk ordering.
3. **Indexing**: Chunks are stored in PostgreSQL, indexed for full-text keyword search, and embedded via local sentence-transformers for semantic retrieval (using `pgvector`).
4. **Hybrid Retrieval & Reranking**: Queries pass through Reciprocal Rank Fusion (RRF) combining keyword and dense embeddings, followed by a cross-encoder reranking stage.
5. **Synthesis & Grounding**: Local LLMs (Ollama) generate responses strictly grounded in retrieved evidence with exact page-level citations.

---

## 📂 Project Structure

```text
research-platform/
├── backend/                  # FastAPI Application
│   ├── alembic/              # Database Migrations
│   ├── app/                  # Main Application Logic
│   │   ├── api/              # REST API Routers and Endpoints
│   │   ├── core/             # Pydantic Settings & App Configuration
│   │   ├── db/               # SQLAlchemy Session Setup & Base Class
│   │   ├── models/           # SQLAlchemy ORM Models (Project, Document, Chunk)
│   │   ├── prompts/          # LLM Prompt Templates (e.g., RAG)
│   │   ├── repositories/     # Data Access Layer (CRUD, Vector Search, FTS)
│   │   ├── schemas/          # Pydantic Validation & Response Models
│   │   └── services/         # Business Logic (Ingestion, Hybrid Search, LLMs)
│   └── tests/                # Pytest Suite (Transactional DB Rollbacks)
├── docs/                     # Architectural Decisions & Milestone Chronicles
│   ├── milestone_log.md      # Master index and executive summary hub for each milestone
│   └── milestones/           # Detailed write-ups for each completed phase
└── README.md                 # This file
```

---

## 🎯 Core Features (Implemented)

- **Project-Centric Organization**: Manage research questions, papers, and notes within isolated research projects.
- **Strict Provenance & Citations**: Exact document provenance (page numbers, chunk indices) is preserved to eliminate hallucinated references.
- **Multi-Stage Retrieval**: Deterministic keyword search (FTS), semantic search (Embeddings), Hybrid Retrieval (RRF), and Cross-Encoder Reranking.
- **Evidence-Grounded Answers (RAG)**: Single-Call Chain-of-Thought prompting that enforces index-based citation verification against real chunks.

---

## 🛠️ Technology Stack

- **Backend**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.11+)
- **Validation**: [Pydantic v2](https://docs.pydantic.dev/)
- **Database & ORM**: [PostgreSQL](https://www.postgresql.org/) & [SQLAlchemy 2.0](https://www.sqlalchemy.org/)
- **Database Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
- **Document Processing**: [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`)
- **AI / ML Ecosystem**:
  - Embeddings: `sentence-transformers` (`all-MiniLM-L6-v2`) & `pgvector`
  - Reranking: `cross-encoder/ms-marco-MiniLM-L-6-v2`
  - Generation: Local LLMs via `Ollama`
- **Testing**: [pytest](https://docs.pytest.org/) (with Async TestClient & Transactional DB Isolation)

---

## 🗺️ Progressive Roadmap

Development follows a strict milestone discipline where every AI addition is evaluated against empirical baselines. The project is currently at **Milestone 9** (Structured Research Extraction).

- [x] **Milestone 0: Foundation** — Project scaffolding, database configuration, testing setup, Alembic migrations.
- [x] **Milestone 1: Project Management** — Full CRUD APIs and schemas for research projects.
- [x] **Milestone 2: Document Management & Ingestion** — PDF upload, file storage, and metadata management.
- [x] **Milestone 3: PDF Processing & Chunking** — Page preservation, text cleaning, chunking with strict provenance.
- [x] **Milestone 4: Baseline Keyword Search** — Deterministic FTS keyword search baseline.
- [x] **Milestone 5: Semantic Retrieval** — Embeddings and vector similarity search (`pgvector`).
- [x] **Milestone 6: Hybrid Retrieval** — Dense + sparse fusion via Reciprocal Rank Fusion (RRF).
- [x] **Milestone 7: Reranking** — Cross-encoder reranking for improved candidate relevance.
- [x] **Milestone 8: RAG & Evidence-Grounded Answers** — Local LLM synthesis with strict index-based citation verification.
- [ ] **Milestone 9: Structured Research Extraction** — Extracting methods, datasets, and claims *(In Progress)*.
- [ ] **Milestone 10: Literature Comparison** — Systematically comparing multiple approaches.
- [ ] **Milestone 11-13: Research Planning & Agents** — Tool calling, multi-step reasoning, and workflows.
- [ ] **Milestone 14-16: Evaluation & Experimentation** — Experiment tracking and quantitative AI evaluation.
- [ ] **Milestone 17-19: Advanced Graph & Production** — Knowledge graphs, advanced scaling, and productionization.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- PostgreSQL instance running locally or via Docker
- Ollama installed locally for LLM generation

### 1. Clone the repository
```bash
git clone https://github.com/your-username/research-platform.git
cd research-platform
```

### 2. Set up virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the project root:
```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/research_platform
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/research_platform_test
```

### 4. Run Migrations
```bash
alembic upgrade head
```

### 5. Start the Development Server
```bash
uvicorn backend.app.main:app --reload
```

Interactive API documentation will be available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### 6. Run Tests
The project uses strict transactional rollback isolation for testing. Ensure your test database exists, then run:
```bash
pytest backend/tests
```
