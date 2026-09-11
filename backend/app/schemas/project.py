from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    """Data the client sends when creating a project."""
    title: str
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    """Data the client sends when updating a project. All fields optional."""
    title: Optional[str] = None
    description: Optional[str] = None


class ProjectRead(BaseModel):
    """Data returned to the client. Includes database-generated fields."""
    id: int
    title: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
