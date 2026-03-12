"""
Pydantic v2 models for the Multi-Document Conflict Resolution RAG system.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ConflictType(str, Enum):
    """Classification of conflicts found across papers."""
    ASSAY_VARIABILITY = "ASSAY_VARIABILITY"
    METHODOLOGY = "METHODOLOGY"
    CONCEPTUAL = "CONCEPTUAL"
    EVOLVING_DATA = "EVOLVING_DATA"
    NON_CONFLICT = "NON_CONFLICT"


class Chunk(BaseModel):
    """A single text or table chunk from a paper."""
    id: str
    paper_id: str
    chunk_type: str  # 'text' | 'table'
    content: str
    section: Optional[str] = None
    page: Optional[int] = None
    grounding: Optional[dict[str, Any]] = None


class RetrievedChunk(BaseModel):
    """A chunk retrieved from the vector store with metadata."""
    chunk: Chunk
    similarity: float
    paper_title: Optional[str] = None
    paper_authors: Optional[list[str]] = None
    publication_date: Optional[date] = None
    journal: Optional[str] = None
    sample_size: Optional[int] = None


class ExtractedClaim(BaseModel):
    """A factual claim extracted from a chunk by the PaperAgent."""
    paper_id: str
    property: str  # e.g., "IC50_BD1", "thrombocytopenia_rate", "mechanism_of_action"
    value: str     # The extracted value or description
    context: str   # Brief context sentence
    chunk_id: str
    confidence: float = Field(ge=0.0, le=1.0)


class Conflict(BaseModel):
    """A conflict (or agreement) found across papers for a given property."""
    property: str
    conflict_type: ConflictType
    papers_involved: list[str]
    claims: list[ExtractedClaim]
    reasoning: str
    resolution: Optional[str] = None
    requires_expansion: bool = False


class TraceStep(BaseModel):
    """A single step in the orchestration trace."""
    step: str
    agent: str
    input_summary: str
    output_summary: str
    tokens_used: int = 0
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaperResult(BaseModel):
    """Result from a PaperAgent run."""
    paper_id: str
    paper_title: Optional[str] = None
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    warm_summary: Optional[str] = None


class QueryResult(BaseModel):
    """Final result for a user query."""
    query: str
    answer: str
    conflicts: list[Conflict] = Field(default_factory=list)
    papers_cited: list[str] = Field(default_factory=list)
    context_expansion_triggered: bool = False
    trace: list[TraceStep] = Field(default_factory=list)
    ind_results: list["INDSectionResult"] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class INDSectionResult(BaseModel):
    """Result for a single IND template section."""
    section_id: str
    heading: str
    content: str
    citations: list[str] = Field(default_factory=list)
    insufficient_data: bool = False
    missing_info: Optional[str] = None
