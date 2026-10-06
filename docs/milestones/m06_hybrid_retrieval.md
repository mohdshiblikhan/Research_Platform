# Milestone 6: Hybrid Retrieval

- **Status**: Completed
- **Version**: `v0.6`
- **Migration**: None (application-level changes only)
- **Key Files & Test Counts**:
  - `backend/app/services/search_service.py`
  - `backend/app/schemas/search.py`
  - `backend/tests/test_hybrid_search.py`
  - 2 new integration tests
  - 68 tests total passing, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
Keyword search (Milestone 4) is highly precise for exact matches but misses synonyms and conceptual relationships. Semantic search (Milestone 5) is great for conceptual similarity but often fails at finding specific nouns, acronyms, or exact phrases. Using only one limits the quality of evidence retrieved for the researcher.

#### The Solution
Milestone 6 implements a Hybrid Retrieval engine that combines both approaches into a single ranked list using Reciprocal Rank Fusion (RRF). The system:
1. Adds a `mode="hybrid"` option to the existing `/api/projects/{project_id}/search` endpoint.
2. In hybrid mode, fires both the FTS query and the semantic vector query to fetch the top 60 candidates from each.
3. Fuses the two candidate lists in memory using the RRF algorithm.
4. Includes the computed `rrf_score` in the returned results.
5. Paginates the final fused list accurately according to the user's request.

---

### 2. What the API Exposes

The existing search endpoint was expanded:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `GET` | `/api/projects/{project_id}/search` | Search over document chunks | `200 OK` |

**Query Parameters (Updated):**
- `q` (string, required): The search query.
- `mode` (string, optional, default="keyword"): Search mode. Now accepts `keyword`, `semantic`, or `hybrid`.
- `document_id` (int, optional): Restrict search to a specific document.
- `limit` (int, default=20): Number of results to return.
- `offset` (int, default=0): Pagination offset.

**Response Schema Additions:**
- `SearchResponse.search_mode` can now be `"hybrid"`.
- `SearchResultItem` now includes an optional `rrf_score` float field.

---

### 3. Search Architecture

#### Visual Flow
```
GET /api/projects/{id}/search?q="attention mechanism"&mode=hybrid
     │
     ├─ 1. SearchService: begins timing query execution
     ├─ 2. SearchService: delegates to FTS backend (limit=60)
     ├─ 3. SearchService: delegates to Vector backend (limit=60)
     ├─ 4. SearchService: applies Reciprocal Rank Fusion (RRF) in memory
     ├─ 5. SearchService: sorts by descending RRF score, slices to limit/offset
     ├─ 6. SearchService: stops timing, formats response
     └─ Return: SearchResponse
```

#### Why Reciprocal Rank Fusion (RRF)?
RRF is an algorithm that ignores the raw scores returned by different retrieval systems (which are often completely different scales) and focuses purely on the *rank* (position) of each item in the results.
The formula is: `RRF_Score = 1 / (k + rank_system_a) + 1 / (k + rank_system_b)`
Where `k` is a constant (commonly 60).
This elegantly sidesteps the complex process of normalizing unbounded FTS scores (`ts_rank`) against bounded vector cosine distances.

---

### 4. Deep-Dive: File-by-File Breakdown

#### A. Pydantic Schemas: `backend/app/schemas/search.py`
```python
class SearchResultItem(BaseModel):
    # ... existing fields ...
    rrf_score: Optional[float] = None

class SearchResponse(BaseModel):
    # ...
    search_mode: Literal["keyword", "semantic", "hybrid"]
```
- Added `rrf_score` to clearly surface the fusion score back to the client.
- Expanded `search_mode` literal to type-check the new mode.

#### B. API Endpoint: `backend/app/api/endpoints/search.py`
```python
    mode: str = Query(
        "keyword",
        pattern="^(keyword|semantic|hybrid)$",
        description="Search mode: 'keyword' (FTS), 'semantic' (vector similarity), or 'hybrid'.",
    )
```
- A simple extension to the validation regex to allow `"hybrid"`.

#### C. Service Layer: `backend/app/services/search_service.py`
The orchestration lives inside `SearchService._perform_hybrid_search`:
1. **Parallel Fetching**: We fetch `fetch_limit=60` chunks from both `SearchRepository` and `VectorSearchRepository`.
2. **Scoring**: For each result in both lists, its `rrf_score` is computed and aggregated in a dictionary keyed by `chunk_id`.
3. **Merging**: If a chunk appears in both lists, the scores are added. The semantic similarity is merged into the existing item.
4. **Sorting & Pagination**: The merged dictionary is sorted by the final RRF score descending, and Python slice notation (`[offset : offset + limit]`) applies the pagination.
5. **Total Results Approx**: In hybrid mode, `total_results` uses `max(keyword_count, vector_count)` as a reasonable approximation.

---

### 5. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|:---|:---|:---|:---|
| **Fusion Strategy** | **Rank-based (RRF)** | Score-based (Convex Combination) | FTS `ts_rank` is unbounded, while Vector cosine distance is `[0,2]`. Normalizing them is highly fragile and sensitive to query terms. RRF is mathematically simple, robust, and the industry standard for un-normalized systems. |
| **Execution Layer** | **Application Layer (Python)** | Database Layer (CTE) | Doing this in Postgres would require a complex CTE with window functions `row_number()`, heavily coupling fusion logic to the database. Python lists of size 60 are extremely fast to process in memory and easy to test. |
| **Internal Fetch Limit** | **`fusion_k = 60`** | `limit` (from client) | If the user requests `limit=10`, fusing only the top 10 from both engines provides poor overlap. Fetching 60 internally ensures a healthy candidate pool before we slice it back to 10 for the user. |
| **Total Count** | **`max(count_a, count_b)`** | Exact UNION count | Calculating the exact total unique matches across both systems would require returning all IDs to Python or complex SQL. The max is a highly performant and perfectly acceptable estimate for UI pagination. |

---

### 6. How to Run, Test, and Verify

#### Run the tests:
```bash
cd backend
PYTHONPATH=. ../.venv/bin/pytest tests/test_hybrid_search.py -v
```

#### Manual Verification via Swagger UI:
1. Ensure the server is running (`uvicorn app.main:app --reload`).
2. Verify you have a project with at least one processed and embedded PDF document.
3. Open `http://localhost:8000/docs` and use the `GET /api/projects/{project_id}/search` endpoint.
4. Try `mode=hybrid` with a query like `"research platform"`.
5. Observe the response containing `search_mode: "hybrid"` and `rrf_score` attached to each result.

---

### 7. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **Why did you use Reciprocal Rank Fusion instead of normalizing scores?**
   *"FTS uses TF-IDF or BM25-like scoring which produces completely unbounded numbers. Vector similarity produces numbers strictly bounded between -1 and 1. To use score-based fusion, you have to min-max scale the FTS scores, which requires knowing the max possible score for a query—something you don't know without scanning the entire database. RRF avoids this entirely by looking only at the rank order. It is mathematically elegant and empirically proven to yield highly precise top-k results without fragile calibration."*

2. **Why didn't you push the fusion logic into the database via SQL?**
   *"While you can write a CTE in Postgres with `UNION ALL` and `row_number()`, doing so tightly couples business logic to the database. By pulling the top N candidates into the application layer, we keep the repositories dumb and focused purely on retrieval. Python can easily sort and merge two lists of 60 items in less than a millisecond. This approach is significantly easier to unit test, debug, and monitor."*

3. **How does pagination work when fusing two lists?**
   *"Pagination must be applied *after* fusion, not before. When the frontend asks for `limit=10`, our backend actually asks the database for `60` results from both keyword and semantic searches. We fuse all 120 potential candidates, sort them by their final RRF score, and *then* apply the `offset` and `limit` slice. If we only fetched 10 from the database, the rank fusion would be starved of candidates."*
