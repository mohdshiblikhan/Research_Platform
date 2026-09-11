from fastapi import FastAPI

from app.api.router import router as api_router

app = FastAPI(title="Research Platform")

app.include_router(api_router, prefix="/api")

@app.get("/health")
def health():
    return {"status": "ok"}