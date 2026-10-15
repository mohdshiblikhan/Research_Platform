# Milestone 10: Literature Comparison

- **Status**: Completed
- **Version**: `v1.0`
- **Migration**: None (App level changes only; reads from existing `document_extractions` table)
- **Key Files & Test Counts**:
  - `backend/app/schemas/comparison.py` (Pydantic Request & Response Schemas)
  - `backend/app/repositories/extraction_repository.py` (Added `get_by_document_ids` bulk-fetch)
  - `backend/app/services/comparison_service.py` (Comparison orchestrator & prompt builder)
  - `backend/app/api/endpoints/comparison.py` (API router endpoint)
  - `backend/app/api/router.py` (Registered comparison router)
  - `backend/tests/test_comparison.py` (10 new integration tests)
  - 95 tests total passing across full suite, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
After Milestone 9, the platform possessed the ability to extract structured research metadata (`research_problem`, `methodology`, `models_used`, `datasets`, `evaluation_metrics`, `results`, `limitations`, `baselines`) from individual papers. However, research workflows inherently demand comparing multiple papers side by side to identify differences in methodologies, compare benchmark results, spot conflicting claims, and discover unaddressed research gaps. Manually querying and cross-referencing individual paper endpoints across multiple tabs is inefficient and prone to oversights.

#### The Solution
Milestone 10 introduces a multi-document literature comparison engine. It accepts a list of document IDs within a project and produces a structured, tabular field-by-document comparison matrix. Additionally, users can optionally request an LLM-powered analytical synthesis that provides high-level narrative analysis of key differences, shared themes, contradictory findings, and research gaps.

---

### 2. What the API Exposes

A new endpoint is exposed under the Comparison group:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `POST` | `/api/projects/{p_id}/compare` | Compare 2-10 documents in a project | `200 OK` |

#### Request Schema (`ComparisonRequest`)
- `document_ids`: `list[int]` (min length 2, max length 10)
- `include_synthesis`: `bool` (default `False`)

#### Response Schema (`ComparisonResponse`)
- `project_id`: ID of the enclosing project
- `documents_compared`: Count of documents successfully included in the matrix
- `documents_missing_extraction`: List of requested document IDs that lacked extraction data (graceful warnings)
- `fields`: List of `ComparisonField` objects forming the comparison matrix:
  - `field_name`: Internal key (e.g., `methodology`)
  - `field_label`: Human-readable label (e.g., `Methodology`)
  - `values`: List of `ComparisonFieldValue` objects (`document_id`, `filename`, `value`)
- `synthesis`: Optional `ComparisonSynthesis` object containing:
  - `key_differences`: Primary distinctions in approaches or outcomes
  - `common_themes`: Shared methodologies, datasets, or assumptions
  - `conflicting_findings`: Contradictory empirical results or assertions (nullable)
  - `research_gaps`: Unexplored directions or limitations across the set (nullable)
  - `summary`: Concise 2-3 sentence overview
- `llm_model`: Name of model used (when synthesis requested)
- `synthesis_time_ms`: Execution time for LLM synthesis in milliseconds

---

### 3. Architecture & Data Flow

#### Visual Flow
```text
POST /api/projects/{p_id}/compare
Body: { "document_ids": [1, 2, 3], "include_synthesis": true }
     │
     ├─ 1. ComparisonService: Validates project exists (404 if not found).
     ├─ 2. ComparisonService: Validates each document belongs to project (404 if foreign/missing).
     ├─ 3. ExtractionRepository: Bulk fetches extractions via single SQL query:
     │     └─ SELECT ... WHERE document_id IN (:ids)
     ├─ 4. ComparisonService: Partitions requested IDs into present vs missing extractions.
     │     └─ Enforces at least 2 documents must have extractions (400 if < 2).
     ├─ 5. ComparisonService: Deterministically builds 8-field comparison matrix.
     │     └─ Preserves document order and populates per-document values.
     ├─ 6. (Optional) If include_synthesis is True:
     │     ├─ Formats clean text prompt using extracted metadata only (no raw chunks).
     │     ├─ Calls LLMService.generate(..., json_mode=True).
     │     └─ Parses JSON output into ComparisonSynthesis (logs error gracefully if malformed).
     └─ Return: ComparisonResponse
```

---

### 4. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Tradeoff / Rationale |
|:---|:---|:---|:---|
| **Comparison Architecture** | **Hybrid: Deterministic Matrix + Optional LLM Synthesis** | LLM-only generation OR pure table only | Pure deterministic table is fast, cheap, and always reliable; LLM synthesis offers analytical depth. Decoupling them with an optional flag ensures users do not pay the LLM latency cost (or risk offline failures) when they only need side-by-side data. |
| **Database Retrieval** | **Bulk fetch via `IN (:ids)`** | N individual repository lookups | O(1) database roundtrip regardless of whether 2 or 10 documents are compared. Added `get_by_document_ids` to `ExtractionRepository`. |
| **API Request Method** | **`POST` with JSON Body** | `GET` with query params | Comparing documents involves passing an array of IDs and optionally triggering an LLM synthesis (side effect/computation). `POST` provides clean JSON payload validation (`min_length=2`, `max_length=10`) without awkward URL query string encoding. |
| **LLM Context Input** | **Pre-extracted Structured Fields** | Raw text chunks from all papers | Papers already have clean, normalized summaries from Milestone 9. Feeding structured fields to the synthesis prompt keeps tokens minimal (~500 tokens vs 20,000+ tokens for raw chunks), preventing hallucination and fitting easily into local LLM context. |
| **Persistence** | **On-the-fly Computation** | Dedicated `comparisons` database table | The deterministic matrix takes under 10ms to assemble directly from existing records. Persisting comparison sets would require premature database migrations, schema management, and invalidation logic when individual paper extractions are updated. |
| **Missing Extractions Handling** | **Graceful Warning List** | Hard fail entire request | If a user asks to compare 3 documents and 1 lacks an extraction, the endpoint proceeds with the 2 valid documents and informs the caller via `documents_missing_extraction: [3]`, preventing unnecessary friction. |

---

### 5. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **Why did you separate the comparison matrix from the LLM synthesis instead of letting the LLM generate the whole comparison?**
   *"A fundamental rule of AI systems engineering is to never use an LLM for work that deterministic code can do faster, cheaper, and with 100% reliability. Assembling the comparison table is a pure data transformation: querying structured columns from PostgreSQL and formatting them into a matrix takes less than 10 milliseconds. The LLM is only called when higher-level semantic synthesis is required — finding contradictions, common themes, and research gaps across papers."*

2. **How does this milestone justify the database choices made in Milestone 9?**
   *"In Milestone 9, we explicitly chose strongly-typed SQL columns (`methodology`, `datasets`, `results`, etc.) over a generic JSONB dump. Milestone 10 directly demonstrates why: we can retrieve structured fields across N documents in a single indexed SQL query (`WHERE document_id IN (...)`), guarantee field alignment, and immediately format tabular data without runtime JSON schema checking or type conversion errors."*

3. **How does the system prevent prompt overflow when comparing up to 10 papers?**
   *"Instead of passing raw text chunks or entire papers into the LLM context, the synthesis prompt only consumes the 8 structured metadata fields extracted in Milestone 9. Comparing 5 papers requires only ~1,500 prompt tokens rather than 50,000 tokens of raw PDF text. This keeps local LLM inference fast, inexpensive, and sharply focused on synthesizing conclusions rather than searching for needle-in-a-haystack facts."*
