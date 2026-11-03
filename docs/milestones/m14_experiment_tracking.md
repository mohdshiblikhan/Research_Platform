# Milestone 14: Experiment Planning and Tracking

- **Status**: Completed
- **Version**: `v1.4`
- **Migration**: `7792f4a5525d_create_experiments_table.py`
- **Key Files & Test Counts**:
  - `backend/app/models/experiment.py` (`Experiment` ORM model, `ExperimentStatus`, `ExperimentPriority`, `HypothesisVerdict` StrEnums, `@property has_results`, composite index, unique constraint)
  - `backend/app/models/project.py` (Updated `experiments` 1:N relationship with `cascade="all, delete-orphan"`)
  - `backend/app/models/research_plan.py` (Updated `experiments` 1:N relationship without delete-orphan)
  - `backend/app/models/__init__.py` (Registered and exported `Experiment` and enums)
  - `backend/app/schemas/experiment.py` (Pydantic schemas: `ExperimentCreate`, `ExperimentUpdate`, `ExperimentLogResultsRequest`, `ExperimentPromoteRequest`, `ExperimentRead`, `ExperimentSummary`, `ExperimentBatchPromotionResponse`)
  - `backend/app/repositories/experiment_repository.py` (Database CRUD, filtered listing, unique lookups)
  - `backend/app/services/experiment_service.py` (Unified plan promotion, manual experiment creation across statuses, contextual provenance validation, lifecycle state transitions, selective results replacement)
  - `backend/app/api/endpoints/experiments.py` (7 RESTful API endpoints mounted under `/api/projects`)
  - `backend/app/api/router.py` (Registered experiments router)
  - `backend/app/schemas/tool.py` (`ListExperimentsArgs`, `GetExperimentArgs`)
  - `backend/app/services/tools/implementations.py` (`ListExperimentsTool`, `GetExperimentTool` with `ToolSafetyTier.READ_ONLY`)
  - `backend/app/services/tools/registry.py` (Updated registry pre-populated with 10 platform tools)
  - `backend/alembic/versions/7792f4a5525d_create_experiments_table.py` (Alembic migration for `experiments` table)
  - `backend/tests/test_experiments.py` (18 comprehensive unit, integration, lifecycle, and tool tests)
  - `backend/tests/test_tools.py` (Updated registry tool count assertions from 8 to 10)
  - 164 total tests passing across full suite, 0 failures, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
In Milestone 11, the platform gained the ability to synthesize research literature and produce structured research plans containing `ProposedExperiment` entries. However, those proposed experiments existed solely as static, un-tracked JSON objects inside the `plan_output` column of the `research_plans` table.

Researchers could not:
1. Track whether a proposed experiment had been set up, was running, had completed, or was abandoned.
2. Record empirical findings, quantitative metric results, or qualitative conclusions after executing experiments outside the platform.
3. Manually create standalone experiments or investigations that diverged from an automated LLM plan.
4. Support exploratory or qualitative research where standard benchmark datasets and numerical metrics do not apply.
5. Record whether the empirical evidence supported, refuted, or proved inconclusive regarding the original research hypothesis.
6. Trace an empirical result back to the specific paper, hypothesis, and gap that motivated the investigation.
7. Allow the autonomous research agent (from Milestone 13) to discover or inspect planned and completed experiments.

#### The Solution
Milestone 14 establishes a **lightweight, domain-agnostic research experiment planning and tracking system**:
- **First-Class Relational Entity**: A dedicated `experiments` table with foreign key to `projects.id` (`ON DELETE CASCADE`) and nullable foreign key to `research_plans.id` (`ON DELETE SET NULL`).
- **Flexible Specification & Outcome Ledger**: Hybrid relational core for scientific invariants alongside validated JSONB columns for flexible datasets, variables, hyperparameters, metric results, and qualitative findings.
- **Unrestricted Manual Creation**: Researchers can record experiments directly in any status (`draft`, `planned`, `in_progress`, `completed`, `abandoned`), allowing immediate recording of retrospective experiments without forced linear transitions.
- **Strict Completion Outcome Validation**: Uniformly enforces that completing an experiment requires at least one meaningful outcome (non-empty quantitative results OR qualitative findings with a summary, or both) across creation, status updates, and results logging.
- **Scientific Provenance Scoping**: Validates references against actual project documents and plan hypotheses/gaps, preserving scientific lineage without extra join tables.
- **Unified Batch & Selective Plan Promotion**: A single endpoint promotes proposed experiments from a plan into tracked records, backed by a database unique constraint on `(research_plan_id, plan_experiment_id)` for idempotency.
- **Selective Results Replacement**: Logging findings preserves previously stored metric results, and logging metric results preserves qualitative findings.
- **Secondary Read-Only Agent Tools**: Registers `ListExperimentsTool` and `GetExperimentTool` (`ToolSafetyTier.READ_ONLY`), enabling the Milestone 13 agent to inspect experiment status and results without mutation permissions.

---

### 2. What the API Exposes

7 RESTful endpoints are mounted under `/api/projects`:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `POST` | `/api/projects/{p_id}/plans/{plan_id}/experiments` | Unified batch and selective promotion from a research plan | `201 Created` / `200 OK` |
| `POST` | `/api/projects/{p_id}/experiments` | Manually create an experiment across any lifecycle status | `201 Created` |
| `GET` | `/api/projects/{p_id}/experiments` | List experiments with filtering (`status`, `priority`, `plan_id`) and pagination | `200 OK` |
| `GET` | `/api/projects/{p_id}/experiments/{exp_id}` | Retrieve full details, variables, parameters, results, and findings | `200 OK` |
| `PATCH` | `/api/projects/{p_id}/experiments/{exp_id}` | Partially update configuration, priority, or lifecycle status | `200 OK` |
| `POST` | `/api/projects/{p_id}/experiments/{exp_id}/results` | Record empirical results/findings with selective replacement and optional completion | `200 OK` |
| `DELETE` | `/api/projects/{p_id}/experiments/{exp_id}` | Delete an experiment record | `204 No Content` |

---

### 3. Key Architectural Decisions

1. **Dedicated Relational Table with `ON DELETE SET NULL` on Plans**:
   - Rather than embedding experiment updates in JSONB blobs on `research_plans`, a dedicated `experiments` table provides indexed filtering and relational integrity.
   - If a `ResearchPlan` is deleted or re-generated, `research_plan_id` is set to `NULL`, preserving valuable empirical results and researcher-entered findings.

2. **Domain-Agnostic & Flexible Schema**:
   - `datasets`: Flexible JSONB supporting a list of benchmark names, structured references, single descriptors, or `None` when no conventional dataset is used.
   - `variables`: Flexible JSONB dictionary without forcing rigid independent/dependent/control taxonomies.
   - `target_metrics`: Optional list of metric names; exploratory and qualitative research does not require pre-defined target metrics.
   - `results`: Flexible key-value dictionary accepting numeric, categorical, boolean, or nested values.

3. **Lifecycle State Machine & Invariant Enforcement**:
   - Statuses: `draft`, `planned`, `in_progress`, `completed`, `abandoned`.
   - Permitted transitions to `completed`: from `planned` or `in_progress`.
   - Reopening from `completed` to `in_progress` or `planned` automatically clears `completed_at = None`.
   - Abandonment strictly requires an `abandonment_reason`; reopening clears `abandonment_reason = None`.
   - Direct manual creation allows setting any status directly.

4. **Database-Level Promotion Idempotency**:
   - A database `UniqueConstraint("research_plan_id", "plan_experiment_id", name="uq_experiments_plan_experiment")` prevents duplicate rows at the database level.
   - The service catches concurrent `IntegrityError` exceptions, rolling back cleanly and returning existing records.
   - Re-promoting an already fully promoted plan returns `HTTP 200 OK` with `promoted_count=0` and existing records.

5. **Read-Only Secondary Agent Tools**:
   - Added `ListExperimentsTool` and `GetExperimentTool` with `ToolSafetyTier.READ_ONLY`.
   - The autonomous agent can inspect experimental setups and results, but all creation, mutation, and result logging operations remain strictly user-driven via REST API.

---

### 4. Interview Talking Points

- **Why a dedicated table instead of JSONB updates on `research_plans`?**
  Updating experiments inside a plan's JSONB requires locking the entire plan document, makes relational filtering across plans expensive, and prevents standalone experiments not generated by an LLM. A dedicated table provides clean relational foreign keys, B-tree indexed status filtering, and directly enables Milestone 15 (Experiment Comparison).
- **How is data protected if a research plan is deleted?**
  The foreign key to `research_plans` uses `ON DELETE SET NULL`. If a researcher deletes an obsolete research plan, their real-world experimental results, parameters, and findings are safely retained.
- **How is scientific provenance validated without heavy join tables?**
  The service layer validates that referenced `document_ids` exist in the project, and that `hypothesis_id` and `gap_ids` exist in the referenced plan. This provides verifiable scientific lineage without creating high-overhead join tables (`experiment_documents`, `experiment_gaps`).
- **Why are agent tools strictly read-only?**
  Scientific experimentation represents empirical ground truth. Autonomous agents should be able to read and reason over experimental outcomes, but should not unilaterally modify parameters, mark experiments complete, or fabricate results without human researcher oversight.
