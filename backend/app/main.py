"""FastAPI entrypoint (Developer 2 owns). Run from repo root:
    uvicorn app.main:app --reload --port 8000 --app-dir backend
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "demo"}