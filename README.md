# Evidence-Driven AI Research & Experimentation Platform

> An AI-powered research and experimentation platform that helps researchers move from a research question to evidence-backed conclusions through structured document ingestion, multi-stage retrieval, evidence grounding, and empirical evaluation.

---

> 🚧 **Status: Under Active Development**
---

## 📌 Overview

Most AI research tools act as simple conversational chatbots or naive RAG wrappers that lack traceability, structured understanding, and empirical rigor. 

This platform is engineered as an **evidence-driven research system** where LLMs and search pipelines are components inside a robust, observable backend. The goal is to support the full scientific inquiry cycle:

$$\text{Research Question} \to \text{Literature Ingestion} \to \text{Multi-Stage Retrieval} \to \text{Evidence Grounding} \to \text{Structured Analysis} \to \text{Experimentation} \to \text{Evaluation}$$

---

## 🎯 Key Capabilities

- **Project-Centric Organization**: Manage research questions, papers, and notes within isolated research projects.
- **Strict Provenance & Citations**: Ingest research PDFs and preserve exact document provenance (page numbers, chunk indices, and source context) to eliminate hallucinated references.
- **Progressive Retrieval Pipeline**: Establish deterministic keyword baselines first, then systematically layer semantic (vector) search, hybrid fusion, and cross-encoder reranking.
- **Evidence-Grounded RAG**: Generate synthesized answers with direct lineage tracing back to source passages.
- **Structured Knowledge Extraction**: Extract structured methodologies, datasets, baselines, and findings from papers to facilitate cross-paper comparisons.
- **Experiment Tracking & Evaluation**: Track retrieval metrics (Recall@K, MRR, nDCG) and generation quality (faithfulness, citation accuracy) with empirical benchmarks.

---

## 🏗️ Architecture & How It Works

The platform starts as a **clean, modular monolith** backend designed for maintainability, testability, and clear separation of concerns:

```
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

### Ingestion & Evidence Flow
1. **Upload**: Research papers (PDFs) are uploaded and linked to specific projects.
2. **Extraction & Chunking**: PDFs are parsed while preserving page boundaries and chunk ordering.
3. **Indexing**: Chunks are indexed for full-text search and embedded for semantic retrieval.
4. **Retrieval & Reranking**: Queries pass through hybrid retrieval (keyword + dense embeddings) and reranking.
5. **Synthesis & Grounding**: LLMs generate responses strictly grounded in retrieved evidence with exact page citations.

---

## 🛠️ Tech Stack

- **Backend Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Python 3.11+)
- **Validation & Settings**: [Pydantic v2](https://docs.pydantic.dev/) & Pydantic Settings
- **Database & ORM**: [PostgreSQL](https://www.postgresql.org/) with [SQLAlchemy 2.0](https://www.sqlalchemy.org/)
- **Database Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
- **Database Driver**: `psycopg` (v3)
- **Document Processing**: [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`)
- **Testing**: [pytest](https://docs.pytest.org/) & [HTTPX](https://www.python-httpx.org/) (Async TestClient)
- **Retrieval & AI (Progressive Roadmap)**:
  - Lexical Search (PostgreSQL Full-Text / BM25)
  - Vector Embeddings & Similarity Search
  - Reciprocal Rank Fusion (Hybrid Retrieval)
  - Cross-Encoder Reranking
  - Structured LLM Orchestration & Evaluation

---

## 🗺️ Progressive Roadmap

Development follows a strict milestone discipline where every AI addition is evaluated against empirical baselines:

- [x] **Phase 0: Foundation** — Project scaffolding, database configuration, testing setup, Alembic migrations.
- [x] **Phase 1: Project Management** — Full CRUD APIs and schemas for research projects.
- [ ] **Phase 2: Document Management & Ingestion** — PDF upload, file storage, and metadata management *(In Progress)*.
- [ ] **Phase 3: Text Extraction & Chunking** — Page preservation, text cleaning, chunking with strict provenance.
- [ ] **Phase 4: Baseline Retrieval** — Deterministic keyword search baseline.
- [ ] **Phase 5: Semantic Retrieval** — Embeddings and vector similarity search.
- [ ] **Phase 6: Hybrid Retrieval & Reranking** — Dense + sparse fusion with cross-encoder rerankers.
- [ ] **Phase 7: Evidence-Grounded RAG** — LLM response synthesis with verified citations.
- [ ] **Phase 8: Structured Research Extraction** — Methods, datasets, and claims extraction.
- [ ] **Phase 9: Experiment Tracking & Evaluation** — Quantitative retrieval & generation evaluation framework.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- PostgreSQL instance running locally or via Docker

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
```bash
pytest backend/tests
```
