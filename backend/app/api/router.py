from fastapi import APIRouter

from app.api.endpoints import projects, documents, processing, search, embedding, rag, comparison, research_planning, tools

router = APIRouter()

router.include_router(projects.router)
router.include_router(documents.router)
router.include_router(processing.router)
router.include_router(search.router)
router.include_router(embedding.router)
router.include_router(rag.router)
router.include_router(comparison.router)
router.include_router(research_planning.router)
router.include_router(tools.router)
