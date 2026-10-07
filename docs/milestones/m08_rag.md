# Milestone 8: RAG & Evidence-Grounded Answers

- **Status**: Completed
- **Version**: `v0.8`
- **Migration**: None (application-level changes only)
- **Key Files & Test Counts**:
  - `backend/app/services/llm_service.py` (Abstract Interface)
  - `backend/app/services/ollama_llm_service.py` (Concrete implementation)
  - `backend/app/services/rag_service.py` (Orchestrator)
  - `backend/app/prompts/rag_prompts.py`
  - `backend/app/api/endpoints/rag.py`
  - `backend/app/schemas/rag.py`
  - `backend/tests/test_rag.py`
  - 5 new integration tests
  - 82 tests total passing, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
While previous milestones built a highly effective retrieval pipeline (Keyword, Semantic, Hybrid, and Reranking), returning raw text chunks to a user is often insufficient for answering complex research questions. Users must manually read the chunks to synthesize an answer. 

#### The Solution
Milestone 8 introduces Retrieval-Augmented Generation (RAG). By passing the retrieved evidence chunks to a Large Language Model (LLM) along with the user's question, the system can synthesize a coherent, evidence-grounded answer. Critically, we enforce strict citation rules and require the LLM to output structured JSON so we can map its claims back to the exact provenance of the original PDFs.

---

### 2. What the API Exposes

A new endpoint was introduced specifically for Q&A:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `POST` | `/api/projects/{project_id}/ask` | Ask a question and get a grounded answer | `200 OK` |

**Request Body (`AskRequest`):**
- `question` (string): The research question.
- `search_mode` (string, default="hybrid"): Retrieval method.
- `rerank` (bool, default=True): Whether to apply cross-encoder reranking.
- `top_k` (int, default=5): Number of evidence chunks to retrieve and feed to the LLM.

**Response Schema (`AskResponse`):**
- Returns a structured JSON payload containing the `evidence_analysis`, the synthesized `answer`, a list of verified `citations` mapped to database chunk IDs, the raw `sources` used, and precise `retrieval_time_ms` / `generation_time_ms` metrics.

---

### 3. Architecture & Data Flow

#### Visual Flow
```text
POST /api/projects/{id}/ask (question="Why is the sky blue?")
     │
     ├─ 1. RAGService: Determines top_k and search_mode
     ├─ 2. SearchService: Retrieves top 5 evidence chunks (Hybrid + Rerank)
     ├─ 3. RAGService: Formats chunks into numbered blocks ([1], [2], etc.)
     ├─ 4. RAGService: Builds system and user prompts
     ├─ 5. LLMService: Generates JSON payload requiring `evidence_analysis` then `answer`
     ├─ 6. RAGService: Parses JSON and verifies `source_indices` against actual chunks
     └─ Return: AskResponse (includes mapped Citations, metrics, and confidence)
```

---

### 4. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Why |
|:---|:---|:---|:---|
| **LLM Interface** | **Abstract `LLMService`** | Hardcoded Ollama client | By defining an abstract base class, we can easily swap between local models (Ollama) and cloud providers (OpenAI/Gemini) in the future without touching the `RAGService` orchestrator. |
| **LLM Provider** | **Ollama (`llama3.1:8b`)** | OpenAI / Anthropic | Prioritizes strict privacy, offline capability, and zero API costs during development. |
| **Output Format** | **JSON Mode** | Markdown with inline citations | JSON mode allows us to enforce a strict schema, separating the analysis, the answer, and the structured citations. This makes programmatic verification and frontend rendering much easier. |
| **Citation Verification** | **Index-based verification** | Quote matching or none | The orchestrator verifies that if the LLM cites `[3]`, source index 3 actually exists in the retrieved context. Invalid indices are stripped and logged in `citation_verification.invalid` to monitor hallucination rates. |
| **Endpoint Design** | **New `POST /ask`** | Add to `GET /search` | RAG generation is computationally expensive, stateful (if we later store answers), and requires a complex JSON body. It warrants its own dedicated POST endpoint separate from read-only search. |

---

### 5. Single-Call Chain-of-Thought vs Multi-Step

We opted for a **Single-Call Chain-of-Thought** prompt strategy.

Because LLMs generate text autoregressively, forcing the model to write an answer immediately can lead to hallucinations. By requiring an `evidence_analysis` field at the *top* of the JSON schema, the LLM is forced to explicitly evaluate and reason about the provided evidence *before* drafting the final answer.

This achieves the analytical rigor and reduced hallucination rates of a multi-step Agent/CoT approach without incurring 2x the latency and 2x the token cost.

---

### 6. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **How did you prevent the LLM from hallucinating citations?**
   *"We enforce a strict JSON schema where the LLM must provide citations as structured objects with `source_indices`. The `RAGService` then intercepts these indices and verifies they map to actual chunks passed in the context window. If the LLM hallucinates an index, we strip it out and record an `invalid` citation metric, allowing us to actively monitor the model's reliability."*

2. **Why didn't you just use LangChain or LlamaIndex?**
   *"We wanted complete architectural control. Frameworks like LangChain often obscure the underlying data flow and make it difficult to cleanly separate retrieval metrics (latency, RRF scores) from generation metrics. By building the orchestrator ourselves, we maintain a clean boundary between our `SearchService` and `LLMService`, allowing us to trace exactly what is happening at every millisecond."*

3. **How did you handle prompt engineering for complex reasoning?**
   *"Instead of doing a two-pass system where one LLM call analyzes the text and a second call writes the answer, we used a Single-Call Chain-of-Thought approach. We structured the required JSON output so the `evidence_analysis` field comes before the `answer` field. This forces the autoregressive model to 'think out loud' and ground its reasoning before committing to a final answer, achieving high quality while keeping latency low."*
