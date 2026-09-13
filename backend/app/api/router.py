from fastapi import APIRouter

from app.api.endpoints import projects, documents

router = APIRouter()

router.include_router(projects.router)
router.include_router(documents.router)
