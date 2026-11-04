# Milestone 15: Experiment Comparison

- **Status**: Completed
- **Version**: `v1.5`
- **Key Files & Test Counts**:
  - `backend/app/schemas/experiment_comparison.py` (Pydantic models: `MetricDirection`, `ComparisonMetricValue`, `ComparisonMetricRow`, `ComparisonConfigValue`, `ComparisonConfigRow`, `ParetoObjectiveConfig`, `ParetoPoint`, `ParetoExcludedExperiment`, `ParetoAnalysis`, `HypothesisConsensusRow`, `ExperimentComparisonSynthesis`, `AvailableMetricItem`, `ExperimentComparisonRequest`, `ExperimentComparisonResponse`)
  - `backend/app/services/experiment_comparison_engine.py` (Pure deterministic computational engine: metric canonicalization, unit normalization, baseline deltas, Pareto analysis, hypothesis consensus, deep configuration comparison, and markdown formatting)
  - `backend/app/services/experiment_comparison_service.py` (Orchestrator service: data retrieval, validation responsibilities, engine coordination, optional LLM synthesis with resilient error containment, available metrics discovery)
  - `backend/app/prompts/experiment_comparison_prompts.py` (System prompt and structured context builder for LLM analytical synthesis)
  - `backend/app/api/endpoints/experiment_comparison.py` (REST API endpoints: `POST /api/projects/{project_id}/experiments/compare` and `GET /api/projects/{project_id}/experiments/available-metrics`)
  - `backend/app/api/router.py` (Registered experiment comparison router)
  - `backend/app/schemas/tool.py` (Added `CompareExperimentsArgs` with `pareto_objectives`)
  - `backend/app/services/tools/implementations.py` (`CompareExperimentsTool` with `ToolSafetyTier.READ_ONLY`)
  - `backend/app/services/tools/registry.py` (Updated tool registry pre-populated with 11 platform tools)
  - `backend/app/core/config.py` (Added `max_experiments_per_comparison: int = 20` and `max_experiments_agent: int = 10`)
  - `backend/tests/test_experiment_comparison.py` (26 comprehensive unit, integration, validation, and tool tests)
  - 190 total tests passing across full suite, 0 failures, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
In Milestone 14, researchers could plan, promote, and track individual experiments with flexible variables (`variables`), hyperparameters (`parameters`), target metrics (`target_metrics`), empirical results (`results`), qualitative findings (`findings`), and hypothesis verdicts (`hypothesis_verdict`).

However, each experiment existed as an isolated database row. When researchers conducted multiple runs (e.g., evaluating retrieval strategies across different chunk sizes and rerankers):
1. **No side-by-side alignment**: Configuration differences and metric values had to be inspected one-by-one across individual JSON payloads.
2. **Metric naming and unit disparities**: Different runs logged `Recall@10` vs `recall_10`, and `latency_ms` vs `latency_s` vs bare `latency: 0.15`. Without separating metric identity from units and validating metadata, comparisons were fragile.
3. **Lack of baseline delta tracking**: Researchers could not instantly see quantitative absolute deltas or percentage improvements over a baseline configuration.
4. **Invisible multi-objective trade-offs**: Higher retrieval quality almost always trades off with latency or cost. Without Pareto frontier analysis, researchers could not systematically identify non-dominated configurations.
5. **Scattered hypothesis evidence**: If multiple experiments tested hypothesis H1, there was no aggregated consensus on whether collective empirical evidence supported, contradicted, or presented mixed findings.
6. **Agent blind spot**: The Autonomous Research Agent (Milestone 13) could only inspect single experiments, lacking the ability to compare runs and evaluate optimal trade-offs.

#### The Solution
Milestone 15 establishes an **empirical, deterministic experiment comparison capability**:
- **Pure Engine Decoupling**: Separates side-effect-free mathematical comparison logic (`experiment_comparison_engine.py`) from database and LLM orchestration (`experiment_comparison_service.py`).
- **Metric Identity vs. Unit Separation**: Canonicalizes metric identities (e.g. `latency`) independently from units (`ms`, `s`), resolving aliases via an explicit dictionary (`ALIAS_MAP`) while strictly preserving semantic distinctions (`recall@10` != `recall@20`).
- **Exact Unit Normalization**: Normalizes time ($1\text{ s} = 1000\text{ ms}$, $1\text{ min} = 60000\text{ ms}$) and memory ($1\text{ GB} = 1000\text{ MB}$, $1\text{ GiB} = 1024\text{ MiB}$) without silent interchangeability. Bare metrics requiring units without metadata are marked `incompatible_units` with deltas skipped to prevent false assumptions.
- **Empirical Baseline Deltas**: Computes absolute deltas ($\Delta = V - B$) and percentage changes ($\% = \frac{V - B}{|B|} \times 100$) with safe zero-baseline division guards, parameterized tolerance (`tolerance: float = 1e-6`), and strict numeric validation (`is_valid_numeric`) rejecting booleans, NaN, and inf.
- **Direction-Aware Delta Logic**: Checks `direction == UNKNOWN` first, ensuring unknown-direction metrics strictly return `unspecified` status even on zero delta; `is_best` is evaluated strictly across normalized numeric values with tie handling (`has_tie = True`).
- **Deep Configuration Divergence**: Serializes nested dictionaries and lists via `json.dumps(val, sort_keys=True, allow_nan=False)` to verify deep equality, distinguishing `SET`, `EXPLICIT_NULL`, and `MISSING` presence states.
- **Opt-in 2-Objective Pareto Frontier**: Requires exactly two distinct canonical metrics, infers or requires explicit directions (`maximize`/`minimize`), computes dominance mappings (`dominated_by`, `dominates`), handles ties, and tracks excluded experiments with reasons.
- **Plan-Scoped Hypothesis Consensus with Manual Isolation**: Groups experiments strictly by `(research_plan_id, hypothesis_id)`, deterministically mapping recorded verdicts to 4 consensus states (`supported`, `contradicted`, `mixed`, `inconclusive`). Manual experiments lacking a research plan are isolated in `manual_hypothesis_experiment_ids` to prevent accidental aggregation across unrelated hypotheses.
- **Resilient LLM Synthesis Error Containment**: If optional LLM synthesis fails or times out, the full deterministic comparison result is preserved and returned with `synthesis_status = "failed"` and error details.
- **Dual Experiment Limits**: Maintained max 20 experiments for the REST API (human ablation exploration) vs max 10 experiments for the Agent Tool (LLM context budget preservation).
- **11th Platform Tool (`compare_experiments`)**: Registered read-only agent comparison tool in `ToolRegistry` with `include_synthesis=False` default and server-injected project isolation.

---

### 2. What the API Exposes

Mounted under `/api/projects`:

| Method | Endpoint | Description | Success Status | Error Statuses |
|:---|:---|:---|:---:|:---|
| `POST` | `/api/projects/{p_id}/experiments/compare` | Multi-experiment comparison with baseline deltas and Pareto analysis | `200 OK` | `422` (schema/duplicates), `404` (not found), `400` (business rule violation) |
| `GET` | `/api/projects/{p_id}/experiments/available-metrics` | Discover unique metrics recorded in project with distinct experiment counts | `200 OK` | `404` (project not found) |

---

### 3. Key Architectural Decisions

1. **Decoupled Engine from Orchestrator**:
   Pure functions in `experiment_comparison_engine.py` handle all mathematical calculations, normalization, deltas, and Pareto dominance without database or LLM dependencies, ensuring sub-millisecond benchmarking.
2. **Exclusively Internal Experiments (M14)**:
   Focused strictly on internally tracked experiments. Literature comparison remains in Milestone 10, avoiding schema entanglement between structured numbers and narrative text.
3. **Explicit Hypothesis Grouping Across Plans**:
   Keyed by `(research_plan_id, hypothesis_id)` for plan-promoted experiments. Manual experiments are isolated in `manual_hypothesis_experiment_ids` to prevent artificial combinations.
4. **Metric Identity Separated from Units**:
   Canonical identities resolve independently from units. Strict binary vs decimal distinctions ($1\text{ GiB} = 1024\text{ MiB}$ vs $1\text{ GB} = 1000\text{ MB}$) prevent conversion inaccuracies.
5. **Strict Numeric Validation**:
   `is_valid_numeric` rejects Python booleans (subclass of int) and non-finite floats (`NaN`/`inf`).
6. **Unknown Direction Checked First**:
   Guarantees that unknown-direction metrics strictly return `unspecified` status even on zero delta.
7. **Resilient LLM Error Containment**:
   Deterministic comparison results are never discarded if optional LLM synthesis fails.
