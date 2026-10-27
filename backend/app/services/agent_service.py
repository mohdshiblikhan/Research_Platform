import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_session import AgentSession
from app.prompts.agent_prompts import (
    FORCED_SYNTHESIS_SYSTEM_PROMPT,
    build_agent_system_prompt,
    build_forced_synthesis_user_message,
)
from app.repositories.agent_session_repository import AgentSessionRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.agent import (
    AgentCitation,
    AgentResearchRequest,
    AgentResearchResponse,
    AgentStepRecord,
    AgentToolCallRecord,
)
from app.services.llm_service import LLMService
from app.services.llm_service_factory import get_llm_service
from app.services.tool_execution_service import ToolExecutionService
from app.services.tools.registry import ToolRegistry, get_default_tool_registry

logger = logging.getLogger(__name__)


def _parse_final_answer(content: str) -> tuple[Optional[str], list[AgentCitation]]:
    """Attempt to parse final answer and citations from LLM JSON output."""
    if not content:
        return None, []

    cleaned = content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and "answer" in data:
            raw_citations = data.get("citations", [])
            citations = []
            if isinstance(raw_citations, list):
                for c in raw_citations:
                    if isinstance(c, dict):
                        citations.append(
                            AgentCitation(
                                chunk_id=c.get("chunk_id"),
                                document_id=c.get("document_id"),
                                filename=c.get("filename"),
                                page_number=c.get("page_number"),
                                claim=c.get("claim"),
                            )
                        )
            return str(data["answer"]), citations
    except Exception:
        pass

    return None, []


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Conservative token estimation using 3.5 chars per token."""
    total_chars = sum(
        len(str(m.get("content", ""))) + len(str(m.get("tool_calls", "")))
        for m in messages
    )
    return int(total_chars / 3.5)


def _trim_messages_if_needed(messages: list[dict[str, Any]], max_tokens: int) -> None:
    """Trim older tool observations in-place if message list exceeds token budget."""
    if _estimate_tokens(messages) <= max_tokens:
        return

    # Trim oldest tool messages first, keeping system and initial user question intact
    for i in range(2, len(messages) - 2):
        msg = messages[i]
        if msg.get("role") == "tool":
            content = str(msg.get("content", ""))
            if len(content) > 200:
                msg["content"] = content[:200] + "... [earlier observation trimmed to conserve context budget]"
                if _estimate_tokens(messages) <= max_tokens:
                    return


class AgentService:
    """Autonomous ReAct research agent orchestrating iterative literature exploration."""

    def __init__(
        self,
        db: Session,
        llm_service: Optional[LLMService] = None,
        tool_service: Optional[ToolExecutionService] = None,
        session_repo: Optional[AgentSessionRepository] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        self.db = db
        self.llm_service = llm_service or get_llm_service()
        self.tool_service = tool_service or ToolExecutionService(tool_registry)
        self.session_repo = session_repo or AgentSessionRepository(db)
        self.tool_registry = tool_registry or get_default_tool_registry()
        self.tools_schema = self.tool_registry.get_openai_tools()

    def run_research_session(
        self,
        project_id: int,
        request: AgentResearchRequest,
    ) -> AgentResearchResponse:
        """Execute an autonomous research session with safety boundaries and persistence."""
        project = ProjectRepository(self.db).get_by_id(project_id)
        if not project:
            raise ValueError(f"Project with ID {project_id} not found.")

        # Configuration resolution
        max_iterations = request.max_iterations or settings.agent_max_iterations
        max_tool_calls = request.max_tool_calls or settings.agent_max_tool_calls
        max_time_seconds = request.max_time_seconds or settings.agent_max_time_seconds
        temperature = (
            request.temperature
            if request.temperature is not None
            else settings.llm_temperature
        )
        checkpoint_interval = settings.agent_checkpoint_interval
        max_obs_chars = settings.agent_max_observation_chars
        context_budget = settings.agent_context_budget_tokens

        # Persist session in 'running' state
        model_name = self.llm_service.get_model_name()
        session = self.session_repo.create(
            project_id=project_id,
            research_question=request.research_question,
            model_used=model_name,
        )

        start_time = time.perf_counter()
        status = "running"
        stop_reason = ""
        trajectory: list[AgentStepRecord] = []
        final_answer: Optional[str] = None
        citations: list[AgentCitation] = []

        total_tool_calls = 0
        total_tokens_used = 0
        consecutive_errors = 0
        executed_tool_sigs: set[str] = set()
        gathered_observations: list[str] = []

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_agent_system_prompt()},
            {"role": "user", "content": request.research_question},
        ]

        logger.info(
            f"Starting agent session {session.id} for project {project_id}: '{request.research_question[:80]}...'"
        )

        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            iter_start = time.perf_counter()

            # Check timeout limit
            elapsed_sec = time.perf_counter() - start_time
            if elapsed_sec >= max_time_seconds:
                status = "timeout"
                stop_reason = f"Execution exceeded {max_time_seconds}s time limit"
                logger.warning(f"Session {session.id} timed out after {elapsed_sec:.1f}s")
                break

            # Check tool call limit
            if total_tool_calls >= max_tool_calls:
                status = "max_tool_calls"
                stop_reason = f"Reached maximum limit of {max_tool_calls} tool calls"
                logger.warning(f"Session {session.id} hit max tool calls: {total_tool_calls}")
                break

            # Check consecutive errors limit
            if consecutive_errors >= settings.agent_max_consecutive_errors:
                status = "failed"
                stop_reason = f"Encountered {consecutive_errors} consecutive tool/call errors"
                logger.error(f"Session {session.id} failed due to consecutive errors")
                break

            # Trim messages if approaching context budget
            _trim_messages_if_needed(messages, context_budget)

            # Invoke LLM via multi-turn chat
            try:
                llm_response = self.llm_service.generate_chat(
                    messages=messages,
                    temperature=temperature,
                    tools=self.tools_schema,
                )
            except Exception as e:
                logger.error(f"LLM call failed at iteration {iteration}: {e}")
                consecutive_errors += 1
                if consecutive_errors >= settings.agent_max_consecutive_errors:
                    status = "failed"
                    stop_reason = f"LLM generation failed: {e}"
                    break
                continue

            if llm_response.total_tokens:
                total_tokens_used += llm_response.total_tokens

            # Case A: LLM produced no tool calls -> converged on final answer
            if not llm_response.tool_calls:
                parsed_ans, parsed_cites = _parse_final_answer(llm_response.content)
                if parsed_ans:
                    final_answer = parsed_ans
                    citations = parsed_cites
                else:
                    final_answer = llm_response.content
                    citations = []

                status = "completed"
                stop_reason = "Agent converged on final answer"

                iter_time_ms = round((time.perf_counter() - iter_start) * 1000, 2)
                trajectory.append(
                    AgentStepRecord(
                        iteration=iteration,
                        action_type="final_answer",
                        tool_calls=[],
                        observation_summary=(final_answer[:300] if final_answer else ""),
                        tokens_used=llm_response.total_tokens,
                        iteration_time_ms=iter_time_ms,
                    )
                )
                logger.info(f"Session {session.id} converged naturally at iteration {iteration}")
                break

            # Case B: LLM invoked one or more tools
            # Append assistant message with tool calls to context history
            if llm_response.raw_message:
                messages.append(llm_response.raw_message)
            else:
                formatted_calls = [
                    {
                        "id": tc.id or f"call_{i}",
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for i, tc in enumerate(llm_response.tool_calls)
                ]
                messages.append(
                    {
                        "role": "assistant",
                        "content": llm_response.content or "",
                        "tool_calls": formatted_calls,
                    }
                )

            step_tool_records: list[AgentToolCallRecord] = []
            turn_had_success = False

            for tc in llm_response.tool_calls:
                if total_tool_calls >= max_tool_calls:
                    status = "max_tool_calls"
                    stop_reason = f"Reached maximum limit of {max_tool_calls} tool calls"
                    break

                # Duplicate detection
                sig = f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True)}"
                if sig in executed_tool_sigs:
                    dup_summary = f"[Duplicate tool call to '{tc.name}' skipped]"
                    step_tool_records.append(
                        AgentToolCallRecord(
                            tool_name=tc.name,
                            arguments=tc.arguments,
                            success=True,
                            result_summary=dup_summary,
                            execution_time_ms=0.0,
                        )
                    )
                    messages.append(
                        {"role": "tool", "content": dup_summary, "tool_name": tc.name}
                    )
                    continue

                executed_tool_sigs.add(sig)
                total_tool_calls += 1

                t_exec_start = time.perf_counter()
                exec_result = self.tool_service.execute(
                    db=self.db,
                    project_id=project_id,
                    tool_name=tc.name,
                    arguments=tc.arguments,
                )
                t_exec_ms = round((time.perf_counter() - t_exec_start) * 1000, 2)

                if exec_result.success:
                    turn_had_success = True
                else:
                    logger.warning(f"Tool {tc.name} execution failed: {exec_result.error}")

                # Format and truncate observation
                raw_obs = (
                    json.dumps(exec_result.data)
                    if exec_result.data is not None
                    else (exec_result.result_summary or exec_result.error or "")
                )
                if len(raw_obs) > max_obs_chars:
                    obs_content = (
                        raw_obs[:max_obs_chars]
                        + f"... [truncated {len(raw_obs) - max_obs_chars} chars]"
                    )
                else:
                    obs_content = raw_obs

                gathered_observations.append(f"Tool `{tc.name}`: {obs_content}")

                step_tool_records.append(
                    AgentToolCallRecord(
                        tool_name=tc.name,
                        arguments=tc.arguments,
                        success=exec_result.success,
                        result_summary=obs_content[:300],
                        execution_time_ms=t_exec_ms,
                        error=exec_result.error,
                    )
                )

                messages.append(
                    {"role": "tool", "content": obs_content, "tool_name": tc.name}
                )

            if turn_had_success:
                consecutive_errors = 0
            else:
                consecutive_errors += 1

            iter_time_ms = round((time.perf_counter() - iter_start) * 1000, 2)
            trajectory.append(
                AgentStepRecord(
                    iteration=iteration,
                    action_type="tool_call",
                    tool_calls=step_tool_records,
                    observation_summary=f"Executed {len(step_tool_records)} tool call(s)",
                    tokens_used=llm_response.total_tokens,
                    iteration_time_ms=iter_time_ms,
                )
            )

            # Periodic trajectory checkpointing
            if iteration % checkpoint_interval == 0:
                self.session_repo.checkpoint_trajectory(
                    session_id=session.id,
                    trajectory=[s.model_dump() for s in trajectory],
                    total_iterations=iteration,
                    total_tool_calls=total_tool_calls,
                    total_tokens_used=total_tokens_used,
                    total_time_ms=round((time.perf_counter() - start_time) * 1000, 2),
                )

        # Loop ended without natural convergence -> forced synthesis
        if status == "running":
            status = "max_iterations"
            stop_reason = f"Reached maximum {max_iterations} iterations without natural convergence"

        if final_answer is None and settings.agent_force_final_after_max:
            synth_start = time.perf_counter()
            logger.info(f"Executing forced synthesis for session {session.id} (status: {status})")
            recent_observations = "\n\n".join(gathered_observations[-10:])
            synth_user_msg = build_forced_synthesis_user_message(
                question=request.research_question,
                evidence_summary=recent_observations or "No observations gathered.",
            )
            forced_messages = [
                {"role": "system", "content": FORCED_SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": synth_user_msg},
            ]

            try:
                synth_response = self.llm_service.generate_chat(
                    messages=forced_messages,
                    temperature=0.1,
                    json_mode=True,
                )
                if synth_response.total_tokens:
                    total_tokens_used += synth_response.total_tokens

                parsed_ans, parsed_cites = _parse_final_answer(synth_response.content)
                if parsed_ans:
                    final_answer = parsed_ans
                    citations = parsed_cites
                else:
                    final_answer = synth_response.content
                    citations = []

                synth_time_ms = round((time.perf_counter() - synth_start) * 1000, 2)
                trajectory.append(
                    AgentStepRecord(
                        iteration=iteration + 1,
                        action_type="forced_synthesis",
                        tool_calls=[],
                        observation_summary=(final_answer[:300] if final_answer else ""),
                        tokens_used=synth_response.total_tokens,
                        iteration_time_ms=synth_time_ms,
                    )
                )
            except Exception as e:
                logger.error(f"Forced synthesis failed for session {session.id}: {e}")
                final_answer = f"Research terminated with reason: {stop_reason}. Unable to synthesize final answer: {e}"

        total_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Finalize and persist completed/stopped session
        persisted_session = self.session_repo.finalize_session(
            session_id=session.id,
            status=status,
            final_answer=final_answer,
            citations=[c.model_dump() for c in citations],
            trajectory=[s.model_dump() for s in trajectory],
            total_iterations=len(trajectory),
            total_tool_calls=total_tool_calls,
            total_tokens_used=total_tokens_used,
            total_time_ms=total_time_ms,
            stop_reason=stop_reason,
        )

        return AgentResearchResponse(
            session_id=session.id,
            project_id=project_id,
            research_question=request.research_question,
            status=status,
            final_answer=final_answer,
            citations=citations,
            trajectory=trajectory,
            total_iterations=len(trajectory),
            total_tool_calls=total_tool_calls,
            total_tokens_used=total_tokens_used,
            total_time_ms=total_time_ms,
            model_used=model_name,
            stop_reason=stop_reason,
            created_at=persisted_session.created_at if (persisted_session and persisted_session.created_at) else datetime.now(timezone.utc),
            completed_at=persisted_session.completed_at if (persisted_session and persisted_session.completed_at) else datetime.now(timezone.utc),
        )
