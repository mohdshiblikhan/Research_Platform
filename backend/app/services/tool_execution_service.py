import logging
import time
from typing import Any, Optional
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.schemas.tool import ToolExecutionResponse
from app.services.tools.base import ToolContext
from app.services.tools.registry import ToolRegistry, get_default_tool_registry

logger = logging.getLogger(__name__)


class ToolExecutionService:
    """Orchestrates safe, validated execution of platform tools."""

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or get_default_tool_registry()

    def execute(
        self,
        db: Session,
        project_id: int,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolExecutionResponse:
        start_time = time.perf_counter()
        tool = self.registry.get_tool(tool_name)
        if not tool:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning(f"Tool execution failed: tool '{tool_name}' not found.")
            return ToolExecutionResponse(
                success=False,
                tool_name=tool_name,
                execution_time_ms=round(elapsed_ms, 2),
                result_summary=f"Error: Tool '{tool_name}' does not exist in registry.",
                error=f"Tool '{tool_name}' not found.",
            )

        # Step 1: Validate arguments against tool's Pydantic schema
        try:
            validated_args = tool.args_schema.model_validate(arguments or {})
        except ValidationError as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            error_msg = f"Argument validation failed: {e.errors()}"
            logger.warning(f"Tool '{tool_name}' validation error: {error_msg}")
            return ToolExecutionResponse(
                success=False,
                tool_name=tool_name,
                execution_time_ms=round(elapsed_ms, 2),
                result_summary=f"Invalid arguments provided for tool '{tool_name}'.",
                error=str(e),
            )

        # Step 2: Prepare server-injected execution context
        context = ToolContext(db=db, project_id=project_id)

        # Step 3: Execute tool in sandbox
        try:
            result = tool.run(context, **validated_args.model_dump())
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.info(
                f"Executed tool '{tool_name}' for project {project_id} in {elapsed_ms:.1f}ms (Success: {result.success})"
            )
            return ToolExecutionResponse(
                success=result.success,
                tool_name=tool_name,
                execution_time_ms=round(elapsed_ms, 2),
                result_summary=result.result_summary,
                data=result.data,
                error=result.error,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.exception(f"Unhandled exception executing tool '{tool_name}': {e}")
            return ToolExecutionResponse(
                success=False,
                tool_name=tool_name,
                execution_time_ms=round(elapsed_ms, 2),
                result_summary=f"Internal error executing tool '{tool_name}'.",
                error=str(e),
            )
