"""
PaperAgent: retrieves and extracts structured claims from a single paper.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, date
from typing import Optional

import openai
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import (
    EXPANSION_TOP_K,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    OPENAI_API_KEY,
    TOP_K_PER_PAPER,
)
from src.db import get_client
from src.embeddings import generate_embedding, search_paper
from src.models import (
    Chunk,
    ExtractedClaim,
    PaperResult,
    RetrievedChunk,
    TraceStep,
)

_openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

_CLAIM_EXTRACTION_SYSTEM = """\
You are a pharmaceutical research analyst. Your task is to extract ALL structured
factual claims from the provided paper chunks.

Guidelines:
- Extract every numerical value with its units (IC50, EC50, Kd, Cmax, t½, ORR, etc.)
- Flag chunks that are TABLE type explicitly — table data is high-confidence
- Note if units differ across claims for the same property
- Assign a confidence score (0.0–1.0): 1.0 = direct numerical measurement,
  0.7 = indirect/inferred, 0.4 = qualitative only
- Property names should be snake_case (e.g., "ic50_bd1_nm", "thrombocytopenia_rate_pct")

Return a JSON array of objects with these fields:
  paper_id, property, value, context, chunk_id, confidence

Example:
[
  {
    "paper_id": "paper1_nvx0228_novel_inhibitor",
    "property": "ic50_bd1_nm",
    "value": "12",
    "context": "NVX-0228 demonstrated IC50 of 12 nM in BD1 biochemical assay (AlphaScreen)",
    "chunk_id": "p1-chunk-001-a3f8b2c1",
    "confidence": 0.95
  }
]
"""


class PaperAgent:
    """Agent that retrieves and extracts claims from a single paper."""

    def __init__(self, paper_id: str) -> None:
        self.paper_id = paper_id
        self._client = get_client()

    async def run(
        self,
        query: str,
        expanded: bool = False,
        extra_count: int = 0,
    ) -> tuple[PaperResult, TraceStep]:
        """
        Retrieve chunks for this paper and extract structured claims.

        Args:
            query:       The user's research question.
            expanded:    If True, fetch EXPANSION_TOP_K chunks instead of TOP_K_PER_PAPER.
            extra_count: Override match_count; used when expansion requests a specific count.

        Returns:
            (PaperResult, TraceStep)
        """
        start_time = time.time()

        # --- Fetch WARM summary from paper_summaries ---
        warm_summary: Optional[str] = None
        paper_title: Optional[str] = None
        paper_authors: Optional[list[str]] = None
        publication_date_val: Optional[date] = None
        journal_val: Optional[str] = None
        sample_size_val: Optional[int] = None

        try:
            resp = (
                self._client.table("paper_summaries")
                .select("*")
                .eq("paper_id", self.paper_id)
                .limit(1)
                .execute()
            )
            if resp.data:
                row = resp.data[0]
                warm_summary = row.get("summary")
                paper_title = row.get("title")
                paper_authors = row.get("authors", [])
                pub_date_str = row.get("publication_date")
                if pub_date_str:
                    try:
                        publication_date_val = date.fromisoformat(pub_date_str)
                    except ValueError:
                        pass
                journal_val = row.get("journal")
                sample_size_val = row.get("sample_size")
        except Exception:
            pass  # Graceful degradation if summary not available

        # --- Generate query embedding ---
        query_embedding = generate_embedding(query)

        # --- Determine match_count ---
        if extra_count > 0:
            match_count = extra_count
        elif expanded:
            match_count = EXPANSION_TOP_K
        else:
            match_count = TOP_K_PER_PAPER

        # --- Call match_chunks RPC ---
        raw_chunks = search_paper(query_embedding, self.paper_id, match_count)

        # --- Build RetrievedChunk objects ---
        retrieved: list[RetrievedChunk] = []
        for rc in raw_chunks:
            chunk = Chunk(
                id=rc.get("id", ""),
                paper_id=rc.get("paper_id", self.paper_id),
                chunk_type=rc.get("chunk_type", "text"),
                content=rc.get("content", ""),
                section=rc.get("section"),
                page=rc.get("page"),
                grounding=rc.get("grounding"),
            )
            retrieved.append(
                RetrievedChunk(
                    chunk=chunk,
                    similarity=rc.get("similarity", 0.0),
                    paper_title=paper_title,
                    paper_authors=paper_authors,
                    publication_date=publication_date_val,
                    journal=journal_val,
                    sample_size=sample_size_val,
                )
            )

        # --- Extract claims via LLM ---
        claims = await self._extract_claims(retrieved, query)

        latency_ms = (time.time() - start_time) * 1000

        result = PaperResult(
            paper_id=self.paper_id,
            paper_title=paper_title,
            chunks=retrieved,
            claims=claims,
            warm_summary=warm_summary,
        )

        trace = TraceStep(
            step=f"paper_agent_{self.paper_id}",
            agent="PaperAgent",
            input_summary=f"query='{query[:80]}...', paper_id={self.paper_id}, match_count={match_count}",
            output_summary=(
                f"Retrieved {len(retrieved)} chunks, extracted {len(claims)} claims"
                + (", EXPANDED" if expanded else "")
            ),
            tokens_used=0,  # Updated below if LLM call succeeded
            latency_ms=latency_ms,
            timestamp=datetime.utcnow(),
        )

        return result, trace

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _extract_claims(
        self,
        retrieved: list[RetrievedChunk],
        query: str,
    ) -> list[ExtractedClaim]:
        """Call the LLM to extract structured claims from retrieved chunks."""
        if not retrieved:
            return []

        # Build chunk context for the prompt
        chunk_context_parts = []
        for rc in retrieved:
            chunk_type_tag = "[TABLE]" if rc.chunk.chunk_type == "table" else "[TEXT]"
            chunk_context_parts.append(
                f"{chunk_type_tag} chunk_id={rc.chunk.id} "
                f"section='{rc.chunk.section}' page={rc.chunk.page}\n"
                f"{rc.chunk.content}"
            )
        chunk_context = "\n\n---\n\n".join(chunk_context_parts)

        user_message = (
            f"Paper ID: {self.paper_id}\n"
            f"Research question: {query}\n\n"
            f"Chunks to analyze:\n\n{chunk_context}\n\n"
            "Extract all factual claims relevant to the research question as JSON."
        )

        response = _openai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _CLAIM_EXTRACTION_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=LLM_MAX_TOKENS,
            temperature=0.0,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content or "{}"

        # The model may wrap the array in a key
        try:
            parsed = json.loads(raw_content)
            if isinstance(parsed, list):
                claims_data = parsed
            elif isinstance(parsed, dict):
                # Look for the first list value
                claims_data = next(
                    (v for v in parsed.values() if isinstance(v, list)), []
                )
            else:
                claims_data = []
        except json.JSONDecodeError:
            claims_data = []

        claims: list[ExtractedClaim] = []
        for item in claims_data:
            if not isinstance(item, dict):
                continue
            try:
                claims.append(
                    ExtractedClaim(
                        paper_id=item.get("paper_id", self.paper_id),
                        property=item.get("property", "unknown"),
                        value=str(item.get("value", "")),
                        context=item.get("context", ""),
                        chunk_id=item.get("chunk_id", ""),
                        confidence=float(item.get("confidence", 0.5)),
                    )
                )
            except Exception:
                continue

        return claims
