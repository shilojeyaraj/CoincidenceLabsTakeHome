"""
FastAPI application for the Multi-Document Conflict Resolution RAG system.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.config import OUTPUTS_DIR
from src.db import verify_schema
from src.models import QueryResult
from src.orchestrator import run_query

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Multi-Document Conflict Resolution RAG",
    description="RAG system for resolving conflicts across NVX-0228 research papers.",
    version="1.0.0",
)

# CORS: allow local frontend and env-configured URL
_frontend_url = os.environ.get("NEXT_PUBLIC_API_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", _frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event() -> None:
    """Verify database schema on startup."""
    verify_schema()


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Research question to answer")


class INDTemplateRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Research question for IND generation")


class HealthResponse(BaseModel):
    status: str
    supabase: bool
    openai: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check system health: API, Supabase, and OpenAI connectivity."""
    supabase_ok = False
    openai_ok = False

    try:
        verify_schema()
        supabase_ok = True
    except Exception:
        pass

    try:
        import openai
        from src.config import OPENAI_API_KEY

        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        client.models.list()
        openai_ok = True
    except Exception:
        pass

    return HealthResponse(status="ok", supabase=supabase_ok, openai=openai_ok)


@app.post("/query", response_model=QueryResult)
async def query_endpoint(request: QueryRequest) -> QueryResult:
    """
    Run a research query across all 5 papers and return a synthesized answer
    with conflict analysis.
    """
    try:
        result = await run_query(query=request.query, run_ind_template=False)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/ind-template", response_model=QueryResult)
async def ind_template_endpoint(request: INDTemplateRequest) -> QueryResult:
    """
    Run a query AND generate IND submission template sections.
    """
    try:
        result = await run_query(query=request.query, run_ind_template=True)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/queries", response_model=list[str])
async def list_queries() -> list[str]:
    """Return a list of saved output filenames from the outputs directory."""
    try:
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(
            p.name for p in OUTPUTS_DIR.iterdir() if p.suffix == ".json"
        )
        return files
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
