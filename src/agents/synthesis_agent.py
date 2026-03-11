"""
SynthesisAgent: synthesizes a final answer from all paper results and conflicts.
"""
from __future__ import annotations

import time
from datetime import datetime

import openai
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import LLM_MAX_TOKENS, LLM_MODEL, OPENAI_API_KEY
from src.models import Conflict, ConflictType, PaperResult, TraceStep

_openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

_SYNTHESIS_SYSTEM = """\
You are a senior pharmaceutical research analyst synthesizing findings from multiple
scientific papers about NVX-0228, a BD1-selective BRD4 inhibitor.

Your synthesis MUST:

1. CITATION FORMAT: Cite papers inline as [Paper1], [Paper2], [Paper3], [Paper4],
   [Paper5] corresponding to the papers provided in the context.

2. CONFLICT RESOLUTION: Address EVERY identified conflict explicitly. Never silently
   pick one value over another. For each conflict:
   - State both (all) conflicting values
   - Explain the likely reason for the conflict (assay method, timepoint, etc.)
   - Indicate which source is more authoritative when applicable

3. EVIDENCE HIERARCHY: When resolving CONCEPTUAL conflicts, apply this hierarchy:
   - Crystal structure data (1.8 Å resolution from Paper4) > indirect binding data
   - Later-stage clinical data > early-stage clinical data
   - Multiple orthogonal assays > single assay format
   - Larger patient cohorts > smaller cohorts

4. COMPLEMENTARY vs CONTRADICTORY: Explicitly note when papers are complementary
   (reporting different aspects of the same compound) vs truly contradictory
   (reaching opposite mechanistic conclusions).

5. COMPLETENESS: Include all key numerical values mentioned in the context
   (IC50, ORR, safety rates, PK parameters) with their units.

6. TONE: Formal, scientific, balanced. Do not hedge unnecessarily.

Structure your answer with: Summary → Key Findings → Conflict Analysis → Conclusions
"""


class SynthesisAgent:
    """Agent that synthesizes a final answer across all paper results and conflicts."""

    async def run(
        self,
        query: str,
        paper_results: list[PaperResult],
        conflicts: list[Conflict],
    ) -> tuple[str, TraceStep]:
        """
        Synthesize a final answer.

        Returns:
            (answer_string, TraceStep)
        """
        start_time = time.time()

        context = self._build_context(paper_results, conflicts)
        answer = await self._call_llm(query, context)

        latency_ms = (time.time() - start_time) * 1000

        conflict_types_str = ", ".join(
            f"{c.property}={c.conflict_type.value}" for c in conflicts
        ) or "none"

        trace = TraceStep(
            step="synthesis_agent",
            agent="SynthesisAgent",
            input_summary=(
                f"query='{query[:80]}', "
                f"{len(paper_results)} papers, "
                f"{len(conflicts)} conflicts [{conflict_types_str}]"
            ),
            output_summary=f"Synthesized answer ({len(answer)} chars)",
            latency_ms=latency_ms,
            timestamp=datetime.utcnow(),
        )

        return answer, trace

    def _build_context(
        self,
        paper_results: list[PaperResult],
        conflicts: list[Conflict],
    ) -> str:
        """Build the full context block for the LLM prompt."""
        context_parts: list[str] = []

        # --- Per-paper context ---
        for i, pr in enumerate(paper_results, start=1):
            paper_label = f"Paper{i}"
            header = (
                f"=== [{paper_label}] paper_id={pr.paper_id} "
                f"title='{pr.paper_title or 'Unknown'}' ==="
            )
            context_parts.append(header)

            if pr.warm_summary:
                context_parts.append(f"WARM SUMMARY:\n{pr.warm_summary}\n")

            if pr.chunks:
                chunks_text_parts = []
                for rc in pr.chunks:
                    ctype = "[TABLE]" if rc.chunk.chunk_type == "table" else "[TEXT]"
                    chunks_text_parts.append(
                        f"  {ctype} section='{rc.chunk.section}' "
                        f"page={rc.chunk.page} similarity={rc.similarity:.3f}\n"
                        f"  {rc.chunk.content[:600]}"
                    )
                context_parts.append("RETRIEVED CHUNKS:\n" + "\n\n".join(chunks_text_parts))

            if pr.claims:
                claims_text = "\n".join(
                    f"  - {c.property}: {c.value} (conf={c.confidence:.2f})"
                    for c in pr.claims
                )
                context_parts.append(f"EXTRACTED CLAIMS:\n{claims_text}")

            context_parts.append("")

        # --- Conflict summary ---
        if conflicts:
            context_parts.append("=== IDENTIFIED CONFLICTS ===")
            for conflict in conflicts:
                context_parts.append(
                    f"Property: {conflict.property}\n"
                    f"Type: {conflict.conflict_type.value}\n"
                    f"Papers: {', '.join(conflict.papers_involved)}\n"
                    f"Reasoning: {conflict.reasoning}\n"
                    + (f"Resolution: {conflict.resolution}\n" if conflict.resolution else "")
                )
        else:
            context_parts.append("=== NO CONFLICTS IDENTIFIED ===")

        return "\n".join(context_parts)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _call_llm(self, query: str, context: str) -> str:
        """Call the LLM to synthesize the final answer."""
        user_message = (
            f"Research question: {query}\n\n"
            f"Context from {context.count('=== [Paper')}-paper corpus:\n\n"
            f"{context}"
        )

        response = _openai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYNTHESIS_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=LLM_MAX_TOKENS,
            temperature=0.2,
        )

        return response.choices[0].message.content or ""
