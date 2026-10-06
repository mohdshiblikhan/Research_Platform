# Milestone 7: Reranking

- **Status**: Completed
- **Version**: `v0.7`
- **Migration**: None (application-level changes only)
- **Key Files & Test Counts**:
  - `backend/app/services/reranking_service.py`
  - `backend/app/services/search_service.py`
  - `backend/app/schemas/search.py`
  - `backend/tests/test_reranking.py`
  - 9 new unit and integration tests
  - 77 tests total passing, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
First-stage retrieval systems (like Keyword FTS or Semantic Bi-Encoders) are extremely fast and can scale to millions of documents. However, they lack deep contextual understanding. A bi-encoder embeds the query and document separately, meaning the attention mechanism in the transformer never compares the words in the query directly to the words in the document. This can lead to retrieving documents that contain the right concepts but in the wrong context or relationship.

#### The Solution
Milestone 7 introduces a **Cross-Encoder Reranker** (`cross-encoder/ms-marco-MiniLM-L-6-v2`). A cross-encoder takes the search query and a candidate chunk and processes them *together* in a single pass. This allows full self-attention between the query and the document, yielding a highly accurate relevance score. 

Because it is computationally expensive (O(N) where N is the number of candidates), we only apply it to the top candidates returned by the fast first-stage retrieval.

---

### 2. What the API Exposes

The existing search endpoint was updated with an optional boolean flag:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `GET` | `/api/projects/{project_id}/search` | Search over document chunks | `200 OK` |

**Query Parameters (Updated):**
- `rerank` (bool, optional, default=False): Whether to apply cross-encoder reranking to the top results.

**Response Schema Additions:**
- `SearchResultItem` now includes an optional `rerank_score` float field.

---

### 3. Architecture & Data Flow

#### Visual Flow
```
GET /api/projects/{id}/search?q="Attention"&mode=hybrid&rerank=true&limit=10
     │
     ├─ 1. SearchService: Identifies rerank=True. Sets internal fetch_limit=60, offset=0
     ├─ 2. SearchService: Fetches Top 60 from Hybrid RRF Retrieval
     ├─ 3. SearchService: Delegates the 60 items to RerankingService
     ├─ 4. RerankingService: Pairs query with each chunk: [[Q, C1], [Q, C2], ...]
     ├─ 5. RerankingService: CrossEncoder predicts scores and attaches to items
     ├─ 6. RerankingService: Sorts the 60 items descending by rerank_score
     ├─ 7. SearchService: Slices the reranked list to the requested limit/offset [0:10]
     └─ Return: SearchResponse
```

---

### 4. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|:---|:---|:---|:---|
| **Reranker Model** | **`cross-encoder/ms-marco-MiniLM-L-6-v2`** | API Models (Cohere/BGE) | We want to keep the architecture entirely local and deterministic. This model is highly effective, very small (~80MB), and matches the CPU performance profile of our bi-encoder. |
| **API Integration** | **`rerank: bool` flag** | `mode="hybrid_rerank"` | Making reranking a boolean modifier means it can be applied to purely keyword, purely semantic, or hybrid retrieval. It prevents exponential explosion of `mode` types. |
| **Pagination Strategy** | **Internal fixed candidate pool** | Apply requested limits before reranking | If a user asks for `limit=10, offset=10` and we only fetch 20 items, the reranker has poor visibility. Fetching a fixed 60 items before pagination ensures the reranker always evaluates a healthy candidate pool. |
| **Testing Isolation** | **Mocks for CI, Real models for Eval** | Real models in CI | Running a cross-encoder on real data in the unit test suite would be slow and subject to floating-point instability. We mock `predict()` for pipeline correctness tests and reserve real-model execution for dedicated evaluation datasets. |

---

### 5. RRF vs Cross-Encoder: What's the difference?

- **Reciprocal Rank Fusion (Milestone 6)** is a *combinatorial technique*. It doesn't actually "understand" the text better. It simply says: "If both Keyword Search and Semantic Search think this document is highly relevant, we should push it to the top." 
- **Cross-Encoder Reranking (Milestone 7)** is an *analytical technique*. It reads both the query and the document together, applying deep NLP attention to determine if the document actually answers the query contextually. 

Using them together (Hybrid + Reranking) is the industry standard for state-of-the-art retrieval.

---

### 6. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **Why didn't you just use the Cross-Encoder for the initial search?**
   *"Cross-encoders cannot pre-compute document representations. You must run the model at query-time for every single document in the database. For 100,000 documents, this would take hours per query. Bi-encoders (Semantic Search) let us pre-compute vectors and do lightning-fast math (cosine similarity), serving as a fast filter so the Cross-Encoder only has to read 60 documents."*

2. **How did you handle pagination with the reranker?**
   *"It's critical not to starve the reranker. If the frontend requests page 3 (`limit=10, offset=20`), we don't just fetch 30 items. We fetch a static internal candidate pool (e.g., top 60) from the first-stage retrieval, rerank all 60 of them, sort them by the new score, and *then* apply the slice for page 3. The slice must always happen after reranking."*

3. **How do you test a machine learning system without flaky CI tests?**
   *"We cleanly separated structural correctness from ranking quality. The CI pipeline unit-tests the `RerankingService` and API by mocking the Cross-Encoder to return deterministic arrays (e.g. `[0.2, 0.8, 0.5]`). This proves the pagination, routing, and data structures work flawlessly in milliseconds. True ranking quality is evaluated out-of-band on a curated evaluation dataset calculating MRR and Recall@K."*
