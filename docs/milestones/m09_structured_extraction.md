# Milestone 9: Structured Research Extraction

- **Status**: Completed
- **Version**: `v0.9`
- **Migration**: `2bb26245693e` (create extraction table)
- **Key Files & Test Counts**:
  - `backend/app/models/extraction.py` (SQLAlchemy Model)
  - `backend/app/schemas/extraction.py` (Pydantic Schemas)
  - `backend/app/repositories/extraction_repository.py`
  - `backend/app/services/extraction_service.py` (Orchestrator)
  - `backend/tests/test_extractions.py`
  - 3 new integration tests
  - 85 tests total passing, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
While retrieving relevant text chunks (Milestone 8) is excellent for answering specific questions, it does not provide a holistic, structured understanding of a research paper. To systematically compare approaches across multiple papers (the goal of Milestone 10), we need structured, predictable data points such as the methodology used, datasets evaluated on, and performance metrics achieved.

#### The Solution
Milestone 9 introduces a Structured Extraction pipeline. It selectively gathers the most information-dense sections of a research paper, feeds them to an LLM running in strict JSON mode, and extracts explicit metadata fields into a dedicated, strongly-typed relational database table.

---

### 2. What the API Exposes

Two new endpoints were added to the Document API group:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `POST` | `/api/projects/{p_id}/documents/{d_id}/extract` | Trigger LLM to extract metadata | `200 OK` |
| `GET` | `/api/projects/{p_id}/documents/{d_id}/extract` | Retrieve existing extraction | `200 OK` |

**Response Schema (`ExtractionRead`):**
- Structured string fields: `research_problem`, `methodology`, `models_used`, `datasets`, `evaluation_metrics`, `results`, `limitations`, `baselines`.
- Includes `raw_llm_output` as a debugging escape hatch.

---

### 3. Architecture & Data Flow

#### Visual Flow
```text
POST /api/projects/{p_id}/documents/{d_id}/extract
     │
     ├─ 1. ExtractionService: Validates document exists.
     ├─ 2. ExtractionService: Gathers Hybrid Context
     │     ├─ Fetches Edge Chunks (First 3 + Last 3)
     │     └─ Fetches Semantic Chunks (Top 5 for "methodology, datasets...")
     ├─ 3. LLMService: Prompts LLM with gathered context & strict JSON schema.
     ├─ 4. ExtractionService: Parses JSON and filters to valid Pydantic fields.
     ├─ 5. ExtractionRepository: Upserts data to PostgreSQL `document_extractions` table.
     └─ Return: Structured Extraction Response
```

---

### 4. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|:---|:---|:---|:---|
| **Database Schema** | **Explicit Typed Columns** | Single `JSONB` blob | Since the long-term goal (M10) is literature comparison, explicit columns enforce schema integrity and make cross-paper queries (e.g. "select all papers using Dataset X") much faster and safer than parsing JSON at runtime. |
| **Context Selection** | **Hybrid Heuristic (Edges + Semantic)** | Map-Reduce over entire paper | Research papers are highly structured. The abstract, introduction, and conclusion contain 80% of the high-level metadata. Augmenting these "edge chunks" with a semantic search for methodology keywords ensures we capture deep details without the immense cost, latency, and hallucination risk of a 50-chunk Map-Reduce pipeline. |
| **Trigger Mechanism** | **Explicit API Trigger (`POST`)** | Automatic on upload | Decoupling extraction from document ingestion ensures that basic document processing remains blazing fast and highly debuggable. LLM calls can take 10-30 seconds, which should not block a file upload. |
| **LLM Output Format** | **JSON Mode + Pydantic Filtering** | Regex Parsing | Relying on Ollama's `format="json"` alongside our `ExtractionCreate` Pydantic model ensures the LLM's raw generation is strictly coerced into the application's required data types before hitting the database. |

---

### 5. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **How did you handle long documents exceeding the local LLM context window?**
   *"Instead of building a costly and fragile Map-Reduce pipeline across 50+ chunks of a paper, I built a 'Hybrid Context Selector'. Research papers follow a predictable structure, so the system automatically fetches the first 3 chunks (Abstract/Intro) and the last 3 chunks (Conclusion/Limitations). It then augments these 'edge chunks' with the top 5 chunks returned from a hybrid semantic search for keywords like 'methodology' and 'datasets'. This reliably fits into a local 4k-8k LLM context window while capturing the most critical, information-dense text."*

2. **Why did you use explicit relational columns instead of a NoSQL JSON document?**
   *"Since our immediate next milestone involves systematic literature comparison, we needed the ability to run reliable relational queries across specific fields (e.g., comparing datasets across 10 papers in a project). Explicit typed columns in PostgreSQL provide schema enforcement and better indexing capabilities than untyped JSON blobs, though I did include a `raw_llm_output` JSONB column as an escape hatch for debugging."*

3. **How did you guarantee the LLM didn't crash your API with malformed data?**
   *"We enforce `json_mode=True` at the LLM provider level, but we don't blindly trust the output. The raw JSON is passed through a Pydantic schema validation step where extra hallucinated keys are stripped, missing keys default to `None`, and types are strictly coerced before the `ExtractionRepository` touches the database."*
