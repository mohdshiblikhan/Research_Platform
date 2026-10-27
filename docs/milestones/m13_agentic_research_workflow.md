# Milestone 13: Agentic Research Workflow

- **Status**: Completed
- **Version**: `v1.3`
- **Key Files & Test Counts**:
  - `backend/app/schemas/agent.py` (Pydantic schemas for research request, session response, step trajectory records, and citations)
  - `backend/app/models/agent_session.py` (`AgentSession` SQLAlchemy model with JSONB trajectory, status, and execution counters)
  - `backend/app/repositories/agent_session_repository.py` (CRUD, intermediate checkpointing, and session finalization)
  - `backend/app/prompts/agent_prompts.py` (System prompts with heuristic strategy guidance, evidence grounding, and forced synthesis templates)
  - `backend/app/services/agent_service.py` (Autonomous ReAct loop orchestrator, safety boundaries, context trimming, and forced synthesis)
  - `backend/app/services/llm_service.py` (Extended `LLMService` ABC with `generate_chat()` and native message tracking)
  - `backend/app/services/ollama_llm_service.py` (Refactored Ollama provider with shared chat kwargs and response parsers)
  - `backend/app/core/config.py` (Centralized agent runtime boundaries: max iterations, max tool calls, timeouts, budget tokens)
  - `backend/app/api/endpoints/agent.py` (REST endpoints: `POST /agent/research`, `GET /agent/sessions`, `GET /agent/sessions/{id}`)
  - `backend/app/api/router.py` (Mounted agent router under `/api/projects`)
  - `backend/alembic/versions/d47427ab4920_create_agent_sessions_table.py` (Database migration creating `agent_sessions`)
  - `backend/tests/test_llm_service.py` (5 unit tests for multi-turn LLM chat)
  - `backend/tests/test_agent.py` (15 integration, safety boundary, and API tests)
  - 146 total tests passing across full suite, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
In earlier milestones, the platform provided strong isolated capabilities: hybrid retrieval with reranking (M4–M7), question-answering (M8), paper extractions (M9), comparative matrices (M10), research planning (M11), and a sandboxed tool catalog (M12). However, executing an investigation required a human in the loop at every turn: deciding which paper to inspect, crafting keyword or semantic queries, reviewing chunk text, comparing extracted methodologies, and drafting conclusions.

Real research questions (e.g. *"What are the primary causes of hallucination in RAG systems, and how do self-reflective retrieval strategies mitigate them?"*) cannot be answered by a single static RAG query or a single predefined workflow graph. Different questions require vastly different exploration paths:
1. Some need immediate targeted chunk search.
2. Some require discovering all documents in a project first, then inspecting specific extractions.
3. Some require comparing two specific methodologies before retrieving supporting excerpts.
4. Rigid, hard-coded stage graphs (e.g. Stage 1 -> Stage 2 -> Stage 3) force unnecessary latency and tool calls on simple questions, yet fail to adapt when search queries yield zero results.
5. Unbounded agent loops risk infinite recursion, token context overflows, runaway local GPU/CPU consumption, and crashes due to consecutive errors.

#### The Solution
Milestone 13 introduces an **Autonomous Agentic Research Workflow** governed by an adaptive ReAct (Reasoning + Acting) loop:
- **Autonomous Tool Dispatching**: The agent dynamically selects and chains calls across all 8 platform tools based on emergent findings.
- **Multi-Dimensional Safety Boundaries**: Hard-enforced ceilings on iterations (10), tool calls (25), wall-clock execution time (300s), and consecutive errors (3).
- **Observable Trajectory Persistence**: Every tool invocation, argument set, execution time, result summary, and intermediate thought is persisted to PostgreSQL inside `agent_sessions`.
- **Intermediate Checkpointing**: The trajectory is flushed to the database every 3 iterations, guaranteeing observability and preventing data loss during long-running sessions.
- **Context Budget Protection**: Token estimation (~3.5 chars/token) with selective pruning of older tool observations ensures local 8K context windows (e.g. `llama3.1:8b`) are never exhausted.
- **Forced Synthesis Fallback**: When stopping conditions trigger before natural convergence, the agent performs a guaranteed final evidence-synthesis pass (`json_mode=True`) over collected observations, preventing hanging or answerless research sessions.

---

### 2. What the API Exposes

Three new RESTful endpoints are exposed under `/api/projects`:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `POST` | `/api/projects/{p_id}/agent/research` | Launch an autonomous research session for a given question | `200 OK` |
| `GET` | `/api/projects/{p_id}/agent/sessions` | List all research sessions and summary metrics for a project | `200 OK` |
| `GET` | `/api/projects/{p_id}/agent/sessions/{s_id}` | Retrieve full details, citations, and observable step trajectory of a session | `200 OK` |

#### Request Schema (`AgentResearchRequest`)
- `research_question`: `str` (min 1, max 2000 chars)
- `max_iterations`: `Optional[int]` (override loop iteration cap, 1–20)
- `max_tool_calls`: `Optional[int]` (override total tool calls budget, 1–50)
- `max_time_seconds`: `Optional[int]` (override wall-clock timeout, 10–600s)
- `temperature`: `Optional[float]` (override LLM temperature, 0.0–1.0)

#### Response Schema (`AgentResearchResponse`)
- `session_id`: Unique integer session ID
- `project_id`: Project scope identifier
- `research_question`: The investigated research question
- `status`: `"completed"`, `"max_iterations"`, `"max_tool_calls"`, `"timeout"`, or `"failed"`
- `final_answer`: Evidence-grounded synthesized answer
- `citations`: List of grounded citations (`chunk_id`, `document_id`, `filename`, `page_number`, `claim`)
- `trajectory`: Step-by-step observable trajectory (`iteration`, `action_type`, `tool_calls`, `iteration_time_ms`, `tokens_used`)
- `total_iterations`: Total ReAct iterations executed
- `total_tool_calls`: Total tool calls executed
- `total_tokens_used`: Cumulative LLM tokens consumed
- `total_time_ms`: End-to-end elapsed time in milliseconds
- `model_used`: LLM model identifier
- `stop_reason`: Human-readable reason for termination
- `created_at` / `completed_at`: Timestamps

---

### 3. Architecture & The ReAct Engine

```text
POST /api/projects/{project_id}/agent/research
                      │
                      ▼
            1. Verify Project Existence
                      │
                      ▼
     2. Initialize AgentSession (status="running")
                      │
                      ▼
     3. Assemble Initial Context Messages
        [System Prompt with Strategy Heuristics] + [User Question]
                      │
         ┌────────────┴─────────────┐
         │                          │
         ▼                          ▼
   Iteration Loop              Safety Limits Check
   (1 .. max_iterations)       - Elapsed time >= 300s?
         │                     - Tool calls >= 25?
         │                     - Consecutive errors >= 3?
         ▼                          │
   LLM generate_chat()              ▼ (if triggered)
         │                     Break to Forced Synthesis
         ├───────────────────────────────────────────┐
         │                                           │
  (No tool calls)                             (Tool calls requested)
         │                                           │
         ▼                                           ▼
  Parse JSON Answer                           Duplicate Detection
  - Extract answer & citations                (Canonical Signature Hashing)
  - Status = "completed"                             │
  - Break loop                                       ▼
         │                                    ToolExecutionService
         │                                    - Execute in sandbox
         │                                    - Truncate observation (1500 chars)
         │                                    - Record AgentToolCallRecord
         │                                           │
         │                                           ▼
         │                                    Context Budget Management
         │                                    (Trim oldest observations if > 6000 tokens)
         │                                           │
         │                                           ▼
         │                                    Checkpoint Trajectory
         │                                    (Every 3 iterations to DB)
         │                                           │
         │                                    Next Iteration...
         │                                           │
         └─────────────────┬─────────────────────────┘
                           │
                           ▼
          4. Loop Ended Without Final Answer?
                           │
                 Yes ──────┴────── No
                  │                 │
                  ▼                 ▼
          Forced Synthesis     Persist Completed
          (json_mode=True)     Session to DB
                  │                 │
                  └────────┬────────┘
                           │
                           ▼
          5. Finalize Session in Database
             - status: "completed" / "max_iterations" / etc.
             - total_iterations, total_tool_calls, total_time_ms
             - completed_at timestamp
                           │
                           ▼
          6. Return AgentResearchResponse
```

---

### 4. Safety Guardrails & Resource Controls

1. **Multi-Dimensional Stopping Boundaries**:
   - `max_iterations = 10`
   - `max_tool_calls = 25`
   - `max_time_seconds = 300` (5 minutes)
   - `max_consecutive_errors = 3` (prevents doom loops on malformed calls)

2. **In-Flight Duplicate Tool Call Detection**:
   - Computes canonical signature: `{tool_name}:{json.dumps(args, sort_keys=True)}`.
   - If identical call was executed earlier in the session, the agent skips redundant execution, logs a notice, and informs the model via tool observation. Conserves GPU compute and latency.

3. **Context Budget Management**:
   - Local models (e.g. `llama3.1:8b`) operate within finite context windows (8K).
   - Tracks estimated tokens using 3.5 chars/token.
   - If estimated tokens exceed 6,000, older tool observation contents are truncated to concise notices (`[earlier observation trimmed to conserve context budget]`), preserving the system prompt, original question, and recent reasoning steps.

4. **Observation Truncation**:
   - Individual tool observations are capped at 1,500 characters. Large extraction payloads or multi-chunk searches cannot flood the LLM context.

5. **Intermediate Trajectory Checkpointing**:
   - Sessions checkpoint trajectory records to PostgreSQL every 3 iterations (`agent_checkpoint_interval = 3`). Even if a container restarts or network disconnects, partial investigation history is safely preserved.

6. **Guaranteed Forced Synthesis**:
   - If an agent reaches the iteration limit or times out before converging, it does not crash or return an empty response.
   - The collected observations are passed to `FORCED_SYNTHESIS_SYSTEM_PROMPT` with `json_mode=True` to synthesize the best possible evidence-backed answer and citations from the acquired data.

---

### 5. Key Architectural Decisions

- **Single Adaptive ReAct Loop over Rigid Multi-Stage Graphs**: Rather than forcing a static graph (Stage 1: Discovery -> Stage 2: Extraction -> Stage 3: Comparison -> Stage 4: Synthesis), a single adaptive ReAct loop is used with strategy heuristics in the system prompt. Simple queries resolve in 1–2 tool calls without artificial graph overhead, while complex queries can loop through 10 iterations freely.
- **Non-Breaking `generate_chat()` on `LLMService`**: Extended the provider ABC with `generate_chat(messages, temperature, max_tokens, json_mode, tools)` while refactoring `generate()` into a clean pass-through. Single-turn callers across earlier milestones continue working without breaking changes.
- **Single `agent_sessions` Table with JSONB Trajectory**: Avoided creating a separate high-churn `agent_steps` relational table. A single row per session with JSONB `trajectory` and `citations` keeps the database schema clean, allows atomic checkpointing, and provides fast serialization for API consumers.
- **Server-Injected Project Isolation Preserved**: Maintained the M12 security invariant: `project_id` is never accepted from the LLM or client tool calls; it is strictly injected by `ToolContext(db=db, project_id=project_id)`.
- **Structured Evidence Citations**: Final answers strictly decouple the freeform natural language response from verifiable evidence claims. Each citation links a specific claim to a `chunk_id`, `document_id`, `filename`, and `page_number`.

---

### 6. Testing & Verification

20 new unit and integration tests were implemented:

1. **LLM Chat Service Tests** (`backend/tests/test_llm_service.py`):
   - `test_generate_chat_basic`: Verifies multi-turn message handling and token counting.
   - `test_generate_chat_with_single_tool_call`: Verifies parsed `ToolCall` objects.
   - `test_generate_chat_with_multiple_tool_calls`: Verifies multiple tool calls in a single response turn.
   - `test_generate_backward_compatibility`: Verifies `generate()` delegates seamlessly to `generate_chat()`.
   - `test_generate_chat_error_handling`: Verifies failure containment and runtime error wrapping.

2. **Agent Service & API Integration Tests** (`backend/tests/test_agent.py`):
   - `test_agent_converges_naturally`: Verifies turn 1 tool call -> turn 2 final JSON answer convergence.
   - `test_agent_max_iterations_forced_synthesis`: Verifies forced synthesis on loop exhaustion.
   - `test_agent_max_tool_calls_reached`: Verifies execution halts cleanly when tool budget is exhausted.
   - `test_agent_timeout`: Verifies wall-clock timeout boundary triggers gracefully.
   - `test_agent_consecutive_errors`: Verifies termination after 3 consecutive failures.
   - `test_agent_duplicate_tool_call_skipped`: Verifies identical tool calls are skipped.
   - `test_agent_trajectory_observable_structure`: Verifies step records contain timestamps, action types, and summaries.
   - `test_agent_session_persistence_lifecycle`: Verifies DB row transitions from `running` to `completed`.
   - `test_agent_checkpointing`: Verifies periodic trajectory flushes every 3 iterations.
   - `test_agent_endpoint_success`: Verifies `POST /api/projects/{p_id}/agent/research` returns 200 with full response.
   - `test_agent_endpoint_not_found`: Verifies nonexistent project returns 404.
   - `test_agent_list_sessions_endpoint`: Verifies `GET /api/projects/{p_id}/agent/sessions` returns session summaries.
   - `test_agent_get_session_endpoint`: Verifies `GET /api/projects/{p_id}/agent/sessions/{s_id}` returns detailed trajectory.
   - `test_agent_get_session_cross_project_isolation`: Verifies accessing another project's session returns 404.
   - `test_agent_context_budget_trimming`: Verifies older tool observations are trimmed when exceeding token budgets.

**Full Test Suite Status**: **146 tests passed in 12.33s**, 0 failures, 0 regressions.
