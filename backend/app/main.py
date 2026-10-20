"""FastAPI entrypoint (Developer 2 owns). Run from repo root:
    uvicorn app.main:app --reload --port 8000 --app-dir backend
"""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Resolve .env from the repository root regardless of Uvicorn's working directory.
root_env = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=root_env)

from app.api.routes.analysis import router as analysis_router

app = FastAPI(title="Kubernetes FinOps Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(analysis_router, prefix="/api")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "demo"}
