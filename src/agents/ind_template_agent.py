"""
INDTemplateAgent: generates IND submission sections from paper results and conflicts.
"""
from __future__ import annotations

import time
import re
from datetime import datetime
from typing import Any

import openai
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import IND_SECTION_MAX_TOKENS, LLM_MODEL, OPENAI_API_KEY
from src.models import Conflict, INDSectionResult, PaperResult, TraceStep

_openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

_IND_SYSTEM = """\
You are an expert regulatory writer preparing an IND (Investigational New Drug)
application for submission to the FDA.

Requirements:
1. REGULATORY LANGUAGE: Use formal FDA submission language (21 CFR 312 style).
   Write in third person, passive voice where appropriate. Be precise and thorough.

2. CITATIONS: Every factual claim MUST include an inline citation in the format [N]
   where N is the paper number (1-5). Example: "NVX-0228 demonstrated an IC50 of
   12 nM in BD1 biochemical assays [1]."

3. INSUFFICIENT DATA: If the source documents do not contain sufficient information
   for a section or subsection, insert:
   [INSUFFICIENT DATA — <description of what specific information is missing>]
   Do NOT fabricate data.

4. CONFLICT HANDLING: When conflicting data exists across sources, present all values
   and note the discrepancy. Example: "IC50 values reported across studies range from
   8 nM [3] to 12 nM [1], with variation attributable to assay format differences."

5. STRUCTURE: Follow the exact CTD section numbering and heading provided.

6. COMPLETENESS: Include all quantitative data (IC50, Kd, Cmax, t½, ORR, AE rates)
   from the provided context with proper units.
"""


class INDTemplateAgent:
    """Agent that generates a single IND template section."""

    async def run(
        self,
        section: dict[str, Any],
        paper_results: list[PaperResult],
        conflicts: list[Conflict],
    ) -> tuple[INDSectionResult, TraceStep]:
        """
        Generate content for a single IND section.

        Args:
            section:       Dict with 'id', 'heading', 'guidance', and optionally
                           'subsections' from generation_template.json
            paper_results: All paper results from the orchestration run
            conflicts:     All identified conflicts

        Returns:
            (INDSectionResult, TraceStep)
        """
        start_time = time.time()

        section_id = section.get("id", "unknown")
        heading = section.get("heading", "Unknown Section")
        guidance = section.get("guidance", "")
        subsections = section.get("subsections", [])

        context = self._build_context(paper_results, conflicts)
        content, tokens_used = await self._call_llm(section_id, heading, guidance, subsections, context)

        # Parse citations from the content
        citations = list(set(re.findall(r'\[(\d+)\]', content)))
        citations.sort(key=lambda x: int(x))

        # Check for insufficient data markers
        insufficient_data = "[INSUFFICIENT DATA" in content
        missing_info: str | None = None
        if insufficient_data:
            # Extract the first missing info description
            match = re.search(r'\[INSUFFICIENT DATA[—\-–]\s*([^\]]+)\]', content)
            if match:
                missing_info = match.group(1).strip()

        latency_ms = (time.time() - start_time) * 1000

        result = INDSectionResult(
            section_id=section_id,
            heading=heading,
            content=content,
            citations=citations,
            insufficient_data=insufficient_data,
            missing_info=missing_info,
        )

        trace = TraceStep(
            step=f"ind_section_{section_id}",
            agent="INDTemplateAgent",
            input_summary=(
                f"section={section_id} '{heading}', "
                f"{len(paper_results)} papers, {len(conflicts)} conflicts"
            ),
            output_summary=(
                f"Generated {len(content)} chars, "
                f"{len(citations)} citations, "
                f"insufficient_data={insufficient_data}"
            ),
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            timestamp=datetime.utcnow(),
        )

        return result, trace

    def _build_context(
        self,
        paper_results: list[PaperResult],
        conflicts: list[Conflict],
    ) -> str:
        """Build context block for the LLM prompt."""
        parts: list[str] = []

        for i, pr in enumerate(paper_results, start=1):
            parts.append(f"--- Source [{i}]: {pr.paper_id} | {pr.paper_title or 'Unknown'} ---")

            if pr.warm_summary:
                parts.append(f"Summary: {pr.warm_summary[:500]}")

            for rc in pr.chunks:
                ctype = "[TABLE]" if rc.chunk.chunk_type == "table" else "[TEXT]"
                parts.append(
                    f"{ctype} {rc.chunk.section} (p.{rc.chunk.page}): "
                    f"{rc.chunk.content[:500]}"
                )

            if pr.claims:
                for c in pr.claims:
                    parts.append(f"  Claim: {c.property} = {c.value}")

            parts.append("")

        if conflicts:
            parts.append("--- Identified Conflicts ---")
            for conf in conflicts:
                parts.append(
                    f"[{conf.conflict_type.value}] {conf.property}: "
                    f"{conf.reasoning[:300]}"
                )

        return "\n".join(parts)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _call_llm(
        self,
        section_id: str,
        heading: str,
        guidance: str,
        subsections: list[dict],
        context: str,
    ) -> tuple[str, int]:
        """Call the LLM to generate IND section content.

        Returns:
            (content, tokens_used)
        """
        subsections_text = ""
        if subsections:
            sub_parts = []
            for sub in subsections:
                sub_parts.append(
                    f"  {sub.get('id')} {sub.get('heading')}: {sub.get('guidance', '')}"
                )
            subsections_text = "\nSubsections to include:\n" + "\n".join(sub_parts)

        user_message = (
            f"Generate content for IND section {section_id}: {heading}\n\n"
            f"Regulatory guidance: {guidance}{subsections_text}\n\n"
            f"Source data:\n{context}"
        )

        response = await _openai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _IND_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=IND_SECTION_MAX_TOKENS,
            temperature=0.1,
        )

        tokens_used: int = getattr(getattr(response, "usage", None), "total_tokens", 0) or 0
        return response.choices[0].message.content or "", tokens_used
