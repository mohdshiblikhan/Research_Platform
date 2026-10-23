from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.project_repository import ProjectRepository
from app.schemas.tool import (
    ToolDefinitionResponse,
    ToolExecutionRequest,
    ToolExecutionResponse,
)
from app.services.tool_execution_service import ToolExecutionService
from app.services.tools.registry import get_default_tool_registry

router = APIRouter(prefix="/projects", tags=["Tools"])


@router.get("/{project_id}/tools", response_model=list[ToolDefinitionResponse])
def list_available_tools(project_id: int, db: Session = Depends(get_db)):
    """List all available tools and their OpenAI-compatible JSON schemas for a project."""
    project_repo = ProjectRepository(db)
    project = project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    registry = get_default_tool_registry()
    tools = registry.get_all_tools()
    return [
        ToolDefinitionResponse(
            name=t.name,
            description=t.description,
            parameters=t.args_schema.model_json_schema(),
            safety_tier=t.safety_tier,
        )
        for t in tools
    ]


@router.post("/{project_id}/tools/execute", response_model=ToolExecutionResponse)
def execute_tool(
    project_id: int,
    request: ToolExecutionRequest,
    db: Session = Depends(get_db),
):
    """Execute a registered platform tool in a sandboxed, validated environment."""
    project_repo = ProjectRepository(db)
    project = project_repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    service = ToolExecutionService()
    return service.execute(
        db=db,
        project_id=project_id,
        tool_name=request.tool_name,
        arguments=request.arguments,
    )
