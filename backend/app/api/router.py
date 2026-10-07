from fastapi import APIRouter

from app.api.endpoints import projects, documents, processing, search, embedding, rag

router = APIRouter()

router.include_router(projects.router)
router.include_router(documents.router)
router.include_router(processing.router)
router.include_router(search.router)
router.include_router(embedding.router)
router.include_router(rag.router)
