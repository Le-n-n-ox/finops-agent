"""FastAPI entrypoint (Developer 2 owns). Run from repo root:
    uvicorn app.main:app --reload --port 8000 --app-dir backend
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import sample_mode

# Updated import to 'analysis'
from app.api.routes import analysis, data, reports

# 1. Define the app first
app = FastAPI(title="Kubernetes FinOps Agent API", version="0.1.0")

# 2. Then loop through and include the routers (must be indented)
for r in (analysis.router, reports.router, data.router):
    app.include_router(r)

# 3. Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)

# A saved review is a ~1.5 MB JSON document and compresses about 8.6x. The middleware skips
# text/event-stream, so the analysis stream is unaffected.
app.add_middleware(GZipMiddleware, minimum_size=1024)

@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness, plus which external services this process is actually using.

    `sample_mode` is reported because it changes what a run means: no Zetaris query and no model
    call. A reviewer checking whether the external services are reachable can tell from here
    whether they are being asked at all.
    """
    return {
        "status": "ok",
        "mode": "demo",
        "sample_mode": "true" if sample_mode() else "false",
        "data_source": os.getenv("DATA_SOURCE", "local").lower(),
        "llm_backend": os.getenv("LLM_BACKEND", "auto").lower(),
    }