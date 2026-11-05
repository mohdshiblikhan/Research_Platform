# Milestone 16: AI / RAG / Agent Evaluation Framework

- **Status**: Completed
- **Version**: `v1.6`
- **Key Files & Test Counts**:
  - `backend/app/models/evaluation.py` (Relational persistence models: `EvaluationDataset`, `EvaluationDatasetItem`, `EvaluationRun`, `EvaluationItemResult` with `ON DELETE SET NULL` historical preservation)
  - `backend/app/schemas/evaluation.py` (Pydantic validation schemas with `StrictInt` K validation, full context snapshots, claim provenance, and lifecycle states)
  - `backend/app/services/evaluation_engine.py` (Pure deterministic scoring engine: IR deduplication, Recall@K, Precision@K, MRR@K, nDCG@K, HitRate@K, citation validity vs support, agent trajectory diagnostics, error recovery success)
  - `backend/app/services/evaluation_service.py` (Orchestration service for datasets, candidate items, synthetic benchmark generation, retrieval evaluation, RAG evaluation, agent evaluation, and experiment linking)
  - `backend/app/repositories/evaluation_repository.py` (Database repository for datasets, items, runs, and per-item results)
  - `backend/app/prompts/evaluation_prompts.py` (Structured prompts for atomic claim extraction, entailment verification, answer relevance, answer correctness, single & intra-document multi-chunk generation, and self-verification)
  - `backend/app/api/endpoints/evaluation.py` (REST API endpoints for datasets, items, synthetic generation, evaluation execution, and run reporting)
  - `backend/app/api/router.py` (Registered evaluation router)
  - `backend/app/schemas/tool.py` (Added `RunEvaluationArgs` and `GetEvaluationResultsArgs`)
  - `backend/app/services/tools/implementations.py` (`RunEvaluationTool` and `GetEvaluationResultsTool`)
  - `backend/app/services/tools/registry.py` (Updated platform tool registry with 13 registered tools)
  - `backend/app/core/config.py` (Evaluation configuration parameters)
  - `backend/alembic/versions/a16e45f9c101_create_evaluation_tables.py` (Database migration for 4 evaluation tables)
  - `backend/tests/test_evaluation_engine.py` (11 unit tests for deterministic scoring and edge cases)
  - `backend/tests/test_evaluation.py` (10 comprehensive integration, CRUD, snapshot preservation, synthetic generation, and API tests)
  - `backend/tests/test_tools.py` (Updated tool registry suite: 16 tests passing)
  - 211 total tests passing across full suite, 0 failures, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
Prior to Milestone 16, the platform had powerful search (keyword, semantic, hybrid, reranked), grounded RAG answering, structured literature extraction, multi-paper comparison, ReAct agent exploration, and experiment comparison. However:
1. **No Quantitative IR Benchmarks**: Retrieval components (BM25 vs. Dense vs. Hybrid vs. Cross-Encoder) could not be benchmarked on quantitative Information Retrieval metrics (Recall@K, Precision@K, MRR@K, nDCG@K).
2. **Qualitative-Only RAG Assessment**: RAG answers could only be judged manually. There was no automated mechanism to decompose generated answers into atomic factual claims, verify entailment against retrieved sources, or quantify citation precision.
3. **No Trajectory Diagnostics for Agents**: Multi-step ReAct agent sessions could only be checked for final completion, with no metrics tracking tool redundancy, step efficiency, tool selection alignment, or error recovery.
4. **Fragile Benchmark Datasets**: Hardcoded or loosely stored evaluation queries suffered from citation drift, unvalidated ground truth, and cascade-deletion vulnerabilities.
5. **Disconnected Evaluation & Experimentation**: Evaluations were isolated from the platform's empirical experiment tracker (Milestones 14 & 15).

#### The Solution
Milestone 16 implements an **Evidence-Driven AI, RAG, and Agent Evaluation Framework**:
- **Pure Deterministic Scoring Engine (`EvaluationEngine`)**: A zero-side-effect mathematical engine for IR ranking metrics, citation link precision, and agent trajectory efficiency.
- **Strict Metric Edge Case Handling**:
  - Duplicate retrieved chunks are deduplicated by first-occurrence rank, preventing duplicate chunk IDs from inflating Recall@K, Precision@K, or DCG.
  - Queries with no valid ground truth are safely excluded from dataset means (Safe Empty Aggregation returns `None`, avoiding false 1.0 scores or zero-division errors).
  - Strict integer validation rejects booleans (`True`/`False`), floats, strings, and non-positive integers.
  - MRR is evaluated strictly at cutoff $K$ (rank > $K$ receives 0.0).
- **Two-Tier RAG Evaluation with Atomic Claim Decomposition**:
  - Tier 1: Answer is decomposed into atomic testable claims with citation markers. Answers with zero claims return `faithfulness = None` (not 1.0).
  - Tier 2: Entailment judge audits each claim against retrieved sources (`SUPPORTED`, `CONTRADICTED`, `UNSUPPORTED`).
  - Separates citation validity (pointing to a retrieved chunk) from citation semantic support (chunk entails claim). Link precision returns `None` if zero valid links exist.
- **Outcome-Focused Agent Trajectory Diagnostics**:
  - Primary outcome (`task_completion`, `answer_correctness`) is evaluated independently from tool selection.
  - Tool precision, recall, and Jaccard measure deviation from annotated expected tools as secondary diagnostics, never penalizing valid alternative tool sequences.
  - Trajectory efficiency measures $\min(1.0, \text{min\_expected\_steps} / \text{total\_steps})$, returning `None` when a baseline step count is unavailable.
  - `error_recovery_success` measures whether the agent successfully recovered and completed the task after encountering tool failures.
- **Relational Persistence with Historical Run Preservation**:
  - Four relational tables: `evaluation_datasets`, `evaluation_dataset_items`, `evaluation_runs`, `evaluation_item_results`.
  - Foreign keys use `ON DELETE SET NULL` on `dataset_id` and `dataset_item_id`. Deleting a dataset or benchmark item never deletes completed evaluation runs or per-item records.
  - Per-item results preserve immutable snapshots of full retrieved chunk texts, ground-truth answers, expected tools, and claim provenance.
- **Synthetic Benchmark Generation**:
  - Generates realistic single-chunk and intra-document multi-chunk Q&A pairs (enforcing that multi-chunk pairs originate from the exact same paper).
  - Evaluates candidates through self-grounding verification before persistence.
  - Candidate items default to `is_validated = False`. Evaluation runs default to `validated_only = True`, requiring explicit opt-in to evaluate unvalidated candidates.
- **Seamless Experiment Integration**: Evaluation runs can automatically log summary metrics and configurations to the experiment tracking and comparison platform (`create_experiment = True`).
- **12th and 13th Platform Tools**: Added `run_evaluation` and `get_evaluation_results` to the central `ToolRegistry`.

---

### 2. What the API Exposes

Mounted under `/api/projects`:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---:|
| `POST` | `/api/projects/{p_id}/evaluation/datasets` | Create benchmark dataset | `201 Created` |
| `GET` | `/api/projects/{p_id}/evaluation/datasets` | List benchmark datasets | `200 OK` |
| `GET` | `/api/projects/{p_id}/evaluation/datasets/{d_id}` | Fetch dataset metadata | `200 OK` |
| `DELETE` | `/api/projects/{p_id}/evaluation/datasets/{d_id}` | Delete dataset (preserves runs via SET NULL) | `204 No Content` |
| `POST` | `/api/projects/{p_id}/evaluation/datasets/{d_id}/items` | Add benchmark items | `201 Created` |
| `GET` | `/api/projects/{p_id}/evaluation/datasets/{d_id}/items` | List items (with `validated_only` filter) | `200 OK` |
| `PATCH` | `/api/projects/{p_id}/evaluation/datasets/{d_id}/items/{i_id}` | Validate or update benchmark item | `200 OK` |
| `POST` | `/api/projects/{p_id}/evaluation/datasets/generate-synthetic` | Generate synthetic benchmarks from papers | `201 Created` |
| `POST` | `/api/projects/{p_id}/evaluation/runs/retrieval` | Execute retrieval evaluation run | `201 Created` |
| `POST` | `/api/projects/{p_id}/evaluation/runs/rag` | Execute RAG faithfulness & citation run | `201 Created` |
| `POST` | `/api/projects/{p_id}/evaluation/runs/agent` | Execute Agent trajectory evaluation run | `201 Created` |
| `GET` | `/api/projects/{p_id}/evaluation/runs` | List evaluation runs with status/type filters | `200 OK` |
| `GET` | `/api/projects/{p_id}/evaluation/runs/{r_id}` | Fetch run details and summary metrics | `200 OK` |
| `GET` | `/api/projects/{p_id}/evaluation/runs/{r_id}/results` | Fetch per-item evaluation records and snapshots | `200 OK` |

---

### 3. Key Architectural Decisions

1. **Native Pure Engine Decoupling**:
   Deterministic metrics (Precision@K, Recall@K, MRR@K, nDCG@K, HitRate@K, Citation Validity, Link Precision, Redundancy, Trajectory Efficiency, Error Recovery) are calculated by `EvaluationEngine` with zero database or network dependencies.
2. **Distinguishing Objective Invariants from Model-Based Estimates**:
   Deterministic calculations are explicitly separated from LLM-as-a-judge scores (faithfulness entailment, answer relevance, answer correctness) across summary metrics, item results, and documentation.
3. **Preserving Historical Provenance**:
   Foreign keys to datasets and items use `ON DELETE SET NULL`. Historical evaluation records preserve exact retrieved chunk texts in `actual_output`, ground-truth answers in `ground_truth_answer_snapshot`, and expected tools in `expected_tools_snapshot`.
4. **Separation of Outcome vs. Diagnostics**:
   Agent task completion and answer correctness are never penalized by tool selection diagnostics. Valid alternative tool sequences are not penalized.
5. **Zero External Framework Dependencies**:
   Avoided heavy third-party evaluation frameworks (Ragas, TruLens, LangSmith) in favor of transparent, defensible, native implementations that can be explained in an interview.
