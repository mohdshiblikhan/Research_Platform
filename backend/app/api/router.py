from fastapi import APIRouter

from app.api.endpoints import projects

router = APIRouter()

router.include_router(projects.router)
