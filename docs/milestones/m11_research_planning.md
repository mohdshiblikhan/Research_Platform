# Milestone 11: Research Planning

- **Status**: Completed
- **Version**: `v1.1`
- **Migration**: `52539dbbef14` (`create research plans table`)
- **Key Files & Test Counts**:
  - `backend/app/models/research_plan.py` (New `ResearchPlan` ORM model)
  - `backend/app/schemas/research_plan.py` (Request, Response, Summary, and structured output schemas)
  - `backend/app/repositories/research_plan_repository.py` (Plan persistence, retrieval, listing, deletion)
  - `backend/app/repositories/extraction_repository.py` (Added `get_by_project_id` project-wide bulk fetch)
  - `backend/app/prompts/research_planning_prompts.py` (System prompt, provenance formatter, context builder)
  - `backend/app/services/research_planning_service.py` (Multi-stage orchestrator connecting extractions, comparison, RAG search, and planning)
  - `backend/app/api/endpoints/research_planning.py` (API endpoints: POST `/plan`, GET `/plans`, GET `/plans/{plan_id}`)
  - `backend/app/api/router.py` (Registered research planning router)
  - `backend/tests/test_research_planning.py` (14 new integration tests)
  - 110 tests total passing across full suite, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
Prior milestones allowed researchers to retrieve evidence (M4–M7), synthesize answers with citations (M8), extract structured methodology metadata from papers (M9), and compare approaches side by side (M10). However, the platform remained passive: it could answer *"what does the literature say?"* but could not answer *"what should I investigate next?"* 

Translating literature findings into a defensible research roadmap requires identifying literature gaps, formulating falsifiable hypotheses that address those gaps, and designing concrete experiments to test those hypotheses. Without automated assistance, researchers struggle with ungrounded brainstorming, missing subtle literature contradictions, or designing experiments disconnected from identified limitations.

#### The Solution
Milestone 11 introduces an evidence-driven **Research Planning Engine**. Given a user research question and a project's literature corpus, the system automatically:
1. Synthesizes cross-paper extractions and comparative themes (reusing M9 extractions and M10 comparison).
2. Retrieves question-specific text evidence with exact page-level provenance (reusing M6/M7 hybrid search with reranking).
3. Produces a structured, traceable research plan with an explicit chain:
   $$\text{Gaps (G1, G2, ...)} \longrightarrow \text{Hypotheses (H1, H2, ...)} \longrightarrow \text{Experiments (E1, E2, ...)}$$
4. Persists each generated plan into a versioned `research_plans` table so researchers can track how their research strategy evolves over time.

---

### 2. What the API Exposes

Three new RESTful endpoints are exposed under the Research Planning group:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `POST` | `/api/projects/{p_id}/plan` | Generate and persist a structured research plan | `200 OK` |
| `GET` | `/api/projects/{p_id}/plans` | List summaries of all historical plans for a project | `200 OK` |
| `GET` | `/api/projects/{p_id}/plans/{plan_id}` | Retrieve a specific persisted research plan by ID | `200 OK` |

#### Request Schema (`ResearchPlanRequest`)
- `research_question`: `str` (10–2000 characters)
- `document_ids`: `Optional[list[int]]` (max length 15; if omitted, all documents with extractions in the project are analyzed)

#### Response Schema (`ResearchPlanResponse`)
- `id`: Unique database ID of the persisted research plan
- `project_id`: ID of the project
- `research_question`: User's input question
- `documents_analyzed`: Number of documents analyzed
- `documents_without_extraction`: List of requested document IDs lacking extractions
- `document_ids_used`: Exact list of document IDs analyzed (for reproducibility)
- `reasoning`: Chain-of-thought analysis linking literature findings to gaps, hypotheses, and experiments
- `literature_summary`: Comprehensive synthesis of what the analyzed papers establish
- `gaps`: List of `ResearchGap` objects:
  - `id`: e.g., `"G1"`
  - `description`: Detailed description of the literature gap or limitation
  - `evidence`: Verifiable observations citing findings or retrieved passages
  - `source_documents`: IDs of documents where this gap/limitation was observed
- `hypotheses`: List of `ResearchHypothesis` objects:
  - `id`: e.g., `"H1"`
  - `statement`: Testable, falsifiable hypothesis statement
  - `addresses_gaps`: List of gap IDs this hypothesis addresses (e.g., `["G1"]`)
  - `rationale`: Why this hypothesis is plausible based on literature evidence
- `experiments`: List of `ProposedExperiment` objects:
  - `id`: e.g., `"E1"`
  - `title`: Concise title
  - `hypothesis`: Hypothesis ID this experiment tests (e.g., `"H1"`)
  - `method`: Experimental methodology, baseline comparisons, and setup
  - `datasets`: Suggested benchmark datasets (e.g., `"MedQA, PubMedQA"`)
  - `metrics`: Evaluation metrics (e.g., `["Recall@10", "Faithfulness"]`)
  - `priority`: `"high" | "medium" | "low"`
- `recommended_sequence`: Ordered list of experiment IDs to run first to last (e.g., `["E1", "E2"]`)
- `confidence`: `"high" | "medium" | "low"`
- `limitations`: Explicit caveats regarding the scope and bounded corpus
- Timing and metadata: `comparison_time_ms`, `retrieval_time_ms`, `planning_time_ms`, `total_time_ms`, `llm_model`, `created_at`

---

### 3. Architecture & Context Assembly (Option C)

The system employs **Option C Context Assembly** (Extractions + Comparison Synthesis + RAG Evidence), orchestrating 2 LLM calls and 1 retrieval pass:

```text
POST /api/projects/{p_id}/plan
Body: { "research_question": "...", "document_ids": [1, 2]? }
     │
     ├─ 1. Resolve Document Scope:
     │     ├─ If document_ids provided: validate docs belong to project, partition present vs missing extractions.
     │     └─ If omitted: bulk fetch all extractions for project via ExtractionRepository.get_by_project_id().
     │     └─ Validate >= 2 documents with extractions (400 if < 2, max 15 docs).
     │
     ├─ 2. Cross-Document Comparison (1st LLM Call):
     │     └─ ComparisonService.compare(document_ids, include_synthesis=True)
     │        Returns deterministic 8-field matrix + LLM analytical synthesis (differences, gaps, themes).
     │
     ├─ 3. Question-Specific Evidence Retrieval (Search Pass):
     │     ├─ SearchService.search(query=research_question, mode="hybrid", rerank=True, limit=20)
     │     └─ Strict Scope Bounding: filters chunks so that ONLY chunks from analyzed_doc_ids are retained.
     │     └─ Retains top-5 chunks with full provenance: (Doc ID, filename, page range, chunk ID).
     │
     ├─ 4. Assemble Rich Multi-Layer Context:
     │     ├─ Layer 1: Structured metadata from each paper (problem, method, results, limitations).
     │     ├─ Layer 2: Comparative synthesis (key differences, common themes, existing literature gaps).
     │     └─ Layer 3: Question-specific retrieved evidence passages with exact source provenance.
     │
     ├─ 5. Plan Generation (2nd LLM Call):
     │     ├─ Single-call prompt with strict JSON mode enforcing:
     │     │  - Bounded claims (distinguishing unobserved topics from universal gaps).
     │     │  - Explicit Gap -> Hypothesis -> Experiment ID linkage.
     │     └─ Pydantic validation via ResearchPlanOutput.
     │
     ├─ 6. Persistence:
     │     └─ ResearchPlanRepository.create() persists plan to PostgreSQL research_plans table.
     │
     └─ Return: ResearchPlanResponse (200 OK)
```

---

### 4. Key Design Decisions & Tradeoffs

| Decision | Chosen Approach | Alternative | Tradeoff / Rationale |
|:---|:---|:---|:---|
| **Persistence Strategy** | **Persist to `research_plans` table (Option A)** | Ephemeral on-the-fly generation | Research plans are core strategic assets that future milestones (M13 agent workflows, M14 experiment tracking) reference by ID. Persisting plans allows researchers to track how hypotheses and plans evolve over time as new papers are uploaded. |
| **Document Scope Strategy** | **Hybrid: Automatic all docs by default + optional filter (Option C)** | Mandatory explicit list OR automatic only | Provides zero-friction "one-click" planning over all available project papers, while offering an explicit `document_ids` filter when researchers wish to focus planning on a specific sub-topic or sub-collection. |
| **Context Assembly Strategy** | **Option C: Extractions + Comparison + RAG Evidence** | Extractions only OR Extractions + Comparison only | Combining high-level structured extractions (M9), cross-paper synthesis (M10), and raw verbatim evidence passages (M6/M7) gives the planning model both the macro-perspective (themes/gaps) and micro-grounding (specific numbers and claims) needed to generate concrete, falsifiable hypotheses. |
| **Document Scope Consistency** | **Strict search filtering to analyzed documents** | Search across entire project | If a user plans over papers 1 and 2 in a 10-paper project, evidence retrieval is strictly filtered to chunks from papers 1 and 2 (`document_id in analyzed_doc_ids`). This prevents information leakage from unanalyzed documents. |
| **Source Provenance** | **Rich Provenance in Evidence Blocks** | Raw text passage only | Chunks fed to the planner explicitly include `[Evidence i] (Document ID: X, File: "name.pdf", pp. A-B, Chunk: Y)`. This gives the LLM exact citations to attribute gaps and evidence. |
| **Bounded Context Guardrail** | **Prompt instruction distinguishing unobserved vs universal gaps** | Unconstrained gap generation | Without this guardrail, LLMs frequently mistake an unobserved topic in 2 papers for a global scientific void. The system prompt instructs the model to qualify unobserved topics as limitations of the provided corpus rather than universal gaps. |
| **Prompt Architecture** | **Single-Call with Chain-of-Thought `reasoning`** | Multi-call chain (3 separate calls) | A single call requiring a `reasoning` field before structured output delivers chain-of-thought rigor in ~10-20s without incurring the 3x latency, cost, and error compounding of multi-step agent chains. |
| **Corpus Cap** | **15 documents maximum** | Unbounded | Keeps token consumption within ~4,000–6,000 prompt tokens, fitting comfortably within local `llama3.1:8b` context limits and ensuring sub-minute local generation. |

---

### 5. Revision Summary & Interview Talking Points

If asked about this milestone in an interview:

1. **How does your research planning system move beyond a simple LLM prompt?**
   *"Instead of simply asking an LLM 'what experiments should I run?', our system assembles a three-tier grounded context: (1) structured relational metadata extracted from each paper, (2) an analytical comparison matrix identifying common themes and literature discrepancies, and (3) hybrid-retrieved evidence passages with exact page-level provenance. Furthermore, the output enforces a mathematically traceable chain: every experiment links to a specific hypothesis, which links back to a verifiable gap observed in the literature."*

2. **How did you prevent the LLM from hallucinating research gaps from unobserved topics?**
   *"A classic failure mode in AI-assisted literature review is the 'unobserved topic fallacy': if the user uploads 3 papers on retrieval models, the LLM might claim 'nobody in science has ever evaluated on medical data.' We addressed this through prompt engineering and data modeling: the planner is explicitly instructed to distinguish between proven empirical limitations demonstrated in the corpus versus topics simply unaddressed in the provided sample. The schema also forces gaps to cite specific document IDs, and the plan includes an explicit `limitations` field bounding the conclusions to the analyzed corpus."*

3. **Why did you decide to persist research plans when literature comparisons in Milestone 10 were on-the-fly?**
   *"Literature comparison is a read-only tabular transformation: given documents A and B, the comparison table is deterministic and takes 10 milliseconds to generate from database columns. In contrast, a Research Plan is a generative, strategic artifact created at a specific point in time. Researchers need versioning: as they upload new papers or refine their questions, they want to review how their hypotheses and experimental designs evolved over time. Furthermore, Milestone 14 (Experiment Tracking) directly references these plans to verify whether executed experiments test their intended hypotheses."*
