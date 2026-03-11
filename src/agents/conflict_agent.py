"""
ConflictAgent: identifies and classifies conflicts across paper results,
triggering context expansion for CONCEPTUAL conflicts.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

import openai
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import (
    EXPANSION_TOP_K,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    OPENAI_API_KEY,
)
from src.embeddings import generate_embedding_cached, search_paper
from src.models import (
    Chunk,
    Conflict,
    ConflictType,
    ExtractedClaim,
    PaperResult,
    RetrievedChunk,
    TraceStep,
)

_openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

_CONFLICT_CLASSIFICATION_SYSTEM = """\
You are a pharmaceutical research conflict analyst. You will receive claims for a
single property extracted from multiple papers about NVX-0228, a BRD4 inhibitor.

Classify the conflict type using these definitions:

- ASSAY_VARIABILITY: Same property measured by different assay formats (AlphaScreen,
  TR-FRET, ITC, cell-based) yielding different numerical results. Expected scientific
  variation, not a fundamental disagreement.

- METHODOLOGY: Different experimental protocols, cell lines, animal models, or patient
  populations that explain different outcomes.

- CONCEPTUAL: Fundamentally different mechanistic interpretations (e.g., competitive vs
  allosteric inhibition, BD1-selective vs pan-BET) that cannot both be correct.
  IMPORTANT: Only classify as CONCEPTUAL if the papers truly disagree on mechanism or
  interpretation, not just on numerical values.

- EVOLVING_DATA: Papers reporting on the same clinical trial (same NCT number) at
  different timepoints (interim vs final analysis). This is NOT a true conflict —
  it is updated data from the same study. Check NCT numbers and publication dates.

- NON_CONFLICT: Values are consistent within expected variation, or claims are
  complementary rather than contradictory.

Return a JSON object with:
{
  "conflict_type": "ASSAY_VARIABILITY|METHODOLOGY|CONCEPTUAL|EVOLVING_DATA|NON_CONFLICT",
  "reasoning": "Detailed explanation of why this classification was chosen, including
    specific evidence from the papers",
  "resolution": "Suggested resolution or explanation (optional, especially for
    NON_CONFLICT and EVOLVING_DATA)",
  "requires_expansion": true|false  // true only for CONCEPTUAL conflicts
}
"""

_EXPANSION_SYSTEM = """\
You are analyzing context expansion for a CONCEPTUAL conflict. The additional chunks
have been retrieved from the papers to provide deeper mechanistic context.
"""


class ConflictAgent:
    """Agent that identifies, classifies, and resolves conflicts across papers."""

    async def run(
        self,
        query: str,
        paper_results: list[PaperResult],
    ) -> tuple[list[Conflict], TraceStep, list[PaperResult], list[TraceStep]]:
        """
        Classify conflicts across paper results.

        For CONCEPTUAL conflicts, fetches EXPANSION_TOP_K more chunks from each
        involved paper and logs the expansion in additional trace steps.

        Returns:
            (conflicts, main_trace_step, expansion_paper_results, expansion_trace_steps)
        """
        start_time = time.time()

        # --- Group claims by property across papers ---
        property_claims: dict[str, list[ExtractedClaim]] = defaultdict(list)
        for pr in paper_results:
            for claim in pr.claims:
                property_claims[claim.property].append(claim)

        # Only analyze properties that appear in ≥2 papers (potential conflicts)
        multi_paper_properties = {
            prop: claims
            for prop, claims in property_claims.items()
            if len({c.paper_id for c in claims}) >= 2
        }

        conflicts: list[Conflict] = []
        expansion_paper_results: list[PaperResult] = []
        expansion_trace_steps: list[TraceStep] = []
        context_expansion_count = 0

        for prop, claims in multi_paper_properties.items():
            conflict = await self._classify_conflict(prop, claims, paper_results)
            conflicts.append(conflict)

            # --- Context expansion for CONCEPTUAL conflicts ---
            if conflict.conflict_type == ConflictType.CONCEPTUAL and conflict.requires_expansion:
                context_expansion_count += 1
                exp_results, exp_traces = await self._expand_context(
                    query, conflict, paper_results
                )
                expansion_paper_results.extend(exp_results)
                expansion_trace_steps.extend(exp_traces)

        latency_ms = (time.time() - start_time) * 1000
        conflict_summary = ", ".join(
            f"{c.property}:{c.conflict_type.value}" for c in conflicts
        ) or "none"

        main_trace = TraceStep(
            step="conflict_agent",
            agent="ConflictAgent",
            input_summary=(
                f"query='{query[:80]}', "
                f"{len(paper_results)} papers, "
                f"{sum(len(pr.claims) for pr in paper_results)} total claims, "
                f"{len(multi_paper_properties)} multi-paper properties"
            ),
            output_summary=(
                f"{len(conflicts)} conflicts classified: [{conflict_summary}]; "
                f"context_expansion_triggered={context_expansion_count > 0} "
                f"({context_expansion_count} CONCEPTUAL)"
            ),
            latency_ms=latency_ms,
            timestamp=datetime.utcnow(),
        )

        return conflicts, main_trace, expansion_paper_results, expansion_trace_steps

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _classify_conflict(
        self,
        property_name: str,
        claims: list[ExtractedClaim],
        paper_results: list[PaperResult],
    ) -> Conflict:
        """Call the LLM to classify a conflict for a single property."""

        # Build a rich claims summary including paper metadata
        paper_meta: dict[str, Any] = {}
        for pr in paper_results:
            paper_meta[pr.paper_id] = {
                "title": pr.paper_title,
                "warm_summary_snippet": (pr.warm_summary or "")[:300],
            }

        claims_text_parts = []
        for c in claims:
            meta = paper_meta.get(c.paper_id, {})
            claims_text_parts.append(
                f"Paper: {c.paper_id} | Title: {meta.get('title', 'unknown')}\n"
                f"  value={c.value}, context={c.context}\n"
                f"  chunk_id={c.chunk_id}, confidence={c.confidence}"
            )
        claims_text = "\n\n".join(claims_text_parts)

        # Include paper warm summaries (first 400 chars) for NCT/date context
        summaries_text = "\n".join(
            f"{pid}: {info['warm_summary_snippet']}"
            for pid, info in paper_meta.items()
            if info.get("warm_summary_snippet")
        )

        user_message = (
            f"Property being analyzed: {property_name}\n\n"
            f"Claims from different papers:\n{claims_text}\n\n"
            f"Paper context (for NCT number / timeline detection):\n{summaries_text}\n\n"
            "Classify the conflict type and provide reasoning."
        )

        response = _openai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _CONFLICT_CLASSIFICATION_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=1024,
            temperature=0.0,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}

        conflict_type_str = data.get("conflict_type", "NON_CONFLICT")
        try:
            conflict_type = ConflictType(conflict_type_str)
        except ValueError:
            conflict_type = ConflictType.NON_CONFLICT

        papers_involved = list({c.paper_id for c in claims})

        return Conflict(
            property=property_name,
            conflict_type=conflict_type,
            papers_involved=papers_involved,
            claims=claims,
            reasoning=data.get("reasoning", ""),
            resolution=data.get("resolution"),
            requires_expansion=bool(data.get("requires_expansion", False)),
        )

    async def _expand_context(
        self,
        query: str,
        conflict: Conflict,
        paper_results: list[PaperResult],
    ) -> tuple[list[PaperResult], list[TraceStep]]:
        """
        Fetch EXPANSION_TOP_K additional chunks from each paper involved in a
        CONCEPTUAL conflict and return augmented PaperResult objects.
        """
        start_time = time.time()
        query_embedding = list(
            await asyncio.to_thread(generate_embedding_cached, query)
        )

        expansion_results: list[PaperResult] = []
        trace_steps: list[TraceStep] = []

        # Build lookup for existing paper results
        paper_result_map = {pr.paper_id: pr for pr in paper_results}

        for paper_id in conflict.papers_involved:
            exp_start = time.time()
            raw_chunks = await asyncio.to_thread(
                search_paper, query_embedding, paper_id, EXPANSION_TOP_K
            )

            # Get existing retrieved chunk IDs to avoid duplicates
            existing_pr = paper_result_map.get(paper_id)
            existing_ids = set()
            if existing_pr:
                existing_ids = {rc.chunk.id for rc in existing_pr.chunks}

            new_retrieved: list[RetrievedChunk] = []
            for rc in raw_chunks:
                if rc.get("id") in existing_ids:
                    continue  # Skip already-retrieved chunks
                chunk = Chunk(
                    id=rc.get("id", ""),
                    paper_id=rc.get("paper_id", paper_id),
                    chunk_type=rc.get("chunk_type", "text"),
                    content=rc.get("content", ""),
                    section=rc.get("section"),
                    page=rc.get("page"),
                    grounding=rc.get("grounding"),
                )
                new_retrieved.append(
                    RetrievedChunk(
                        chunk=chunk,
                        similarity=rc.get("similarity", 0.0),
                        paper_title=existing_pr.paper_title if existing_pr else None,
                    )
                )

            if new_retrieved:
                # Create an expansion PaperResult with only new chunks
                expansion_pr = PaperResult(
                    paper_id=paper_id,
                    paper_title=existing_pr.paper_title if existing_pr else None,
                    chunks=new_retrieved,
                    claims=[],  # Claims are not re-extracted for expansion chunks
                    warm_summary=None,
                )
                expansion_results.append(expansion_pr)

            exp_latency_ms = (time.time() - exp_start) * 1000
            trace_steps.append(
                TraceStep(
                    step=f"context_expansion_{paper_id}",
                    agent="ConflictAgent.ContextExpansion",
                    input_summary=(
                        f"CONCEPTUAL conflict on property='{conflict.property}', "
                        f"paper={paper_id}, fetching {EXPANSION_TOP_K} extra chunks"
                    ),
                    output_summary=(
                        f"Fetched {len(raw_chunks)} chunks, "
                        f"{len(new_retrieved)} new (non-duplicate)"
                    ),
                    latency_ms=exp_latency_ms,
                    timestamp=datetime.utcnow(),
                )
            )

        return expansion_results, trace_steps
