# Milestone 12: Tool Calling

- **Status**: Completed
- **Version**: `v1.2`
- **Key Files & Test Counts**:
  - `backend/app/schemas/tool.py` (Pydantic schemas for `ToolCall`, `ToolResult`, argument schemas, and API request/response envelopes)
  - `backend/app/services/tools/base.py` (`BaseTool` abstract base class and server-injected `ToolContext`)
  - `backend/app/services/tools/implementations.py` (Concrete implementations for all 8 platform tools)
  - `backend/app/services/tools/registry.py` (`ToolRegistry` catalog and standard OpenAI/Ollama function-schema generator)
  - `backend/app/services/tools/__init__.py` (Core tool exports)
  - `backend/app/services/tool_execution_service.py` (Sandboxed execution service: validation, timing, logging, error containment)
  - `backend/app/services/llm_service.py` (Extended with optional `tools` parameter and `tool_calls` response field)
  - `backend/app/services/ollama_llm_service.py` (Native Ollama tool calling pass-through and tool call parsing)
  - `backend/app/api/endpoints/tools.py` (API endpoints: `GET /tools`, `POST /tools/execute`)
  - `backend/app/api/router.py` (Registered tools router under `/api/projects/{project_id}/tools`)
  - `backend/tests/test_tools.py` (16 integration & unit tests)
  - 126 total tests passing across full suite, 0 regressions

---

### 1. Objective & Problem Solved

#### The Problem
Prior milestones provided robust backend capabilities: hybrid retrieval with reranking (M4–M7), evidence-grounded Q&A (M8), paper extractions (M9), literature comparisons (M10), and research planning (M11). However, these operations remained passive and siloed: they could only be triggered deterministically via explicit HTTP calls from human users.

In **Milestone 13 (Agentic Research Workflow)**, an AI agent must autonomously reason across multiple steps to solve complex research queries. Allowing an LLM to interact with backend services without an abstraction layer presents severe risks:
1. **Hallucinated Arguments & Broken Types**: LLMs invent parameters or out-of-range bounds (`limit=999999`), causing unhandled crashes.
2. **Cross-Project Boundary Leaks**: If an LLM controls the target `project_id`, prompt injection or hallucinations could expose private research papers from other projects.
3. **Context Window Exhaustion**: Returning raw database models or 384-dimensional vector embeddings rapidly exhausts model token limits.
4. **Fragile Reasoners**: Unhandled runtime exceptions crash the execution loop rather than providing structured feedback that enables self-correction.

#### The Solution
Milestone 12 creates a **declarative, sandboxed, and auditable Tool-Calling Layer**. It exposes 8 safe analytical tools conforming to the industry-standard OpenAI/Ollama function-calling specification, backed by strict Pydantic argument validation, server-enforced project isolation, dual-representation outputs (token-efficient summaries for LLM context windows alongside structured data payloads), and comprehensive logging.

---

### 2. What the API Exposes

Two new RESTful endpoints are exposed under the Tools group:

| Method | Endpoint | Description | Success Status |
|:---|:---|:---|:---|
| `GET` | `/api/projects/{p_id}/tools` | List all available tools and their OpenAI-compatible JSON schemas for a project | `200 OK` |
| `POST` | `/api/projects/{p_id}/tools/execute` | Execute a registered platform tool in a sandboxed, validated environment | `200 OK` |

#### Request Schema (`ToolExecutionRequest`)
- `tool_name`: `str` (e.g., `"search_chunks"`)
- `arguments`: `dict[str, Any]` matching the tool's specific Pydantic `args_schema`

#### Response Schema (`ToolExecutionResponse`)
- `success`: `bool` indicating whether the tool executed successfully
- `tool_name`: Name of the executed tool
- `execution_time_ms`: Execution latency in milliseconds
- `result_summary`: Token-optimized, human/LLM-readable text summary
- `data`: Optional structured JSON dictionary with full domain payload
- `error`: Optional error string if validation or execution failed

---

### 3. Architecture & Security Sandbox

```text
POST /api/projects/{p_id}/tools/execute
Body: { "tool_name": "search_chunks", "arguments": { "query": "...", "limit": 5 } }
     │
     ├─ 1. Verify Project:
     │     └─ ProjectRepository.get_by_id(project_id) -> 404 if not found.
     │
     ├─ 2. Tool Lookup:
     │     └─ ToolRegistry.get_tool("search_chunks") -> error response if unknown tool.
     │
     ├─ 3. Strict Argument Validation (Pydantic Sandbox):
     │     └─ tool.args_schema.model_validate(arguments)
     │        * Catches ValidationError and returns clean success=False with field error details.
     │
     ├─ 4. Injected Execution Context (Zero-Trust Scoping):
     │     └─ Create ToolContext(db=db, project_id=project_id)
     │        * project_id is NEVER supplied by the LLM or client body.
     │        * Prevents cross-project data leakage.
     │
     ├─ 5. Sandboxed Handler Execution:
     │     └─ tool.run(context, **validated_args)
     │        * Catches any unhandled exceptions, returns safe error response without crashing server.
     │
     ├─ 6. Dual-Representation Formatting:
     │     └─ Builds ToolResult(result_summary=..., data=...)
     │        * result_summary: token-optimized markdown with exact page and chunk provenance.
     │        * data: complete structured payload for UI rendering or audit.
     │
     └─ 7. Observability & Timing:
           └─ Emits structured log event and returns ToolExecutionResponse.
```

---

### 4. The 8 Platform Tools

| Tool Name | Safety Tier | Args Schema | Reused Backend Component | Provenance & Output |
|:---|:---|:---|:---|:---|
| `search_chunks` | `read_only` | `SearchChunksArgs` | `SearchService.search()` (M4–M7) | Top matching text passages with `[Chunk ID \| Doc ID \| Page X-Y \| Score]` |
| `get_chunk` | `read_only` | `GetChunkArgs` | `ChunkRepository.get_by_id()` (M3) | Verbatim chunk text, character offsets, and page boundaries |
| `list_documents` | `read_only` | `ListDocumentsArgs` | `DocumentRepository.list_by_project()` (M2) | Document list with upload dates, page counts, chunk counts, and status |
| `get_document_metadata` | `read_only` | `GetDocumentMetadataArgs` | `DocumentRepository` + `ExtractionRepository` | Detailed file stats and flag indicating if structured extraction exists |
| `get_paper_extraction` | `read_only` | `GetPaperExtractionArgs` | `ExtractionRepository.get_by_document_id()` (M9) | Pre-extracted 8-field research metadata (problem, method, metrics, results, etc.) |
| `compare_papers` | `analytical` | `ComparePapersArgs` | `ComparisonService.compare()` (M10) | Cross-document matrix and optional LLM analytical synthesis |
| `get_research_plan` | `read_only` | `GetResearchPlanArgs` | `ResearchPlanRepository.get_by_id()` (M11) | Literature gaps, hypotheses, and proposed experiments |
| `list_research_plans` | `read_only` | `ListResearchPlansArgs` | `ResearchPlanRepository.list_by_project()` (M11) | Catalog of all historical research roadmaps for the project |

---

### 5. Key Architectural Decisions

- **Class-Based `BaseTool` with Pydantic Schemas**: Avoided bloated third-party agent frameworks (LangChain, LlamaIndex, CrewAI). Keeps the modular monolith clean, maintainable, dependency-light, and completely explainable during technical interviews.
- **OpenAI-Compatible Function Calling Specification**: Tools export JSON Schema definitions using Pydantic's `model_json_schema()`. This format is supported natively by Ollama (`llama3.1`, `mistral`, `qwen2.5`) and cloud LLMs without prompt-parsing hacks.
- **Server-Injected `ToolContext` for Scoping**: `project_id` is never exposed in the LLM's parameter schema. Instead, the runtime server injects `ToolContext(db, project_id)`. Even if an LLM hallucinates an arbitrary document or chunk ID, tool handlers explicitly verify ownership within the injected `project_id` scope, preventing cross-project data leakage.
- **Dual-Representation Adapter Pattern (`ToolResult`)**: Resolves the conflict between LLM context efficiency and API consumer detail. The LLM receives a token-optimized, human-readable text summary formatted in markdown with clear provenance tags `[Chunk ID, Doc ID, Page X]`, while the application receives the full structured dictionary for rendering rich UI widgets or tracking citations.
- **Safe Read-Only & Analytical Tiers**: The agent is restricted to non-destructive tools (retrieval, extraction inspection, cross-paper comparison, and plan reading). Destructive operations (document deletion, file uploads) remain strictly user-driven.
- **Deferred Database Persistence**: Tool call metrics are logged via Python `logging` and returned in API responses. Creating a persistent `tool_executions` table is deferred to Milestone 13 when complete agent trajectories and multi-step reasoning sessions are designed.

---

### 6. Testing & Verification

16 new integration and unit tests were implemented in `backend/tests/test_tools.py`:
- `test_tool_registry_initialization`: Verifies registry initializes with all 8 tools and supports lookups.
- `test_tool_registry_duplicate_registration`: Verifies duplicate registration raises `ValueError`.
- `test_tool_to_openai_schema`: Verifies exported schemas match the OpenAI/Ollama function calling standard.
- `test_search_chunks_tool_execution`: Verifies retrieval with score and provenance formatting.
- `test_get_chunk_tool_success`: Verifies verbatim passage retrieval and character offsets.
- `test_get_chunk_cross_project_isolation`: Verifies that attempting to read another project's chunk fails securely.
- `test_list_documents_tool`: Verifies document listing and status filtering.
- `test_get_document_metadata_tool`: Verifies metadata inspection and cross-project checks.
- `test_get_paper_extraction_tool`: Verifies extraction field retrieval and missing extraction handling.
- `test_compare_papers_tool`: Verifies matrix generation and mocked synthesis.
- `test_research_plan_tools`: Verifies listing and inspecting persisted research plans.
- `test_tool_execution_service_validation_error`: Verifies Pydantic validation failures return structured error envelopes.
- `test_tool_execution_service_unknown_tool`: Verifies calling an unregistered tool fails safely.
- `test_api_list_tools`: Verifies `GET /api/projects/{p_id}/tools` returns 200 with all 8 tool definitions.
- `test_api_execute_tool_endpoint`: Verifies `POST /api/projects/{p_id}/tools/execute` executes tools via REST API.
- `test_mock_llm_tool_calling_flow`: Verifies end-to-end agent pattern with parsed `ToolCall` objects.

**Test Suite Status**: 126 tests passing, 0 regressions across all previous milestones.
