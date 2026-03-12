"""
SynthesisAgent: synthesizes a final answer from all paper results and conflicts.
"""
from __future__ import annotations

import time
from datetime import datetime

import openai
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import SYNTHESIS_MAX_TOKENS, LLM_MODEL, OPENAI_API_KEY
from src.models import Conflict, ConflictType, PaperResult, TraceStep

_openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)

_SYNTHESIS_SYSTEM = """\
You are a senior pharmaceutical research analyst synthesizing findings from multiple
scientific papers about NVX-0228, a BD1-selective BRD4 inhibitor.

FORMATTING RULES — follow these exactly:
- Use PLAIN TEXT only. Do NOT use markdown syntax of any kind.
- Do NOT use asterisks (**bold**), underscores (_italic_), hashtags (# Header),
  backticks, or any other markdown or LaTeX symbols.
- Section headings must be written in ALL CAPS on their own line, followed by a
  blank line. Example:
      SUMMARY

      Text goes here.

- Use numbered lists (1. 2. 3.) and dashes (-) for bullet points.
- Separate sections with a blank line.

CONTENT RULES:

1. CITATION FORMAT: Cite papers inline using the author-year keys defined in the
   PAPER REGISTRY section of the context (e.g., Chen et al., 2023). Use parenthetical
   format: (Chen et al., 2023). When multiple papers support a claim, list all:
   (Chen et al., 2023; Park et al., 2023).

2. CONFLICT RESOLUTION: Address EVERY identified conflict explicitly. Never silently
   pick one value over another. For each conflict:
   - State both (all) conflicting values with their citation keys
   - Explain the likely reason for the conflict (assay method, timepoint, etc.)
   - Indicate which source is more authoritative when applicable

3. EVIDENCE HIERARCHY: When resolving CONCEPTUAL conflicts, apply this hierarchy:
   - Crystal structure data (high-resolution structural papers) > indirect binding data
   - Later-stage clinical data > early-stage clinical data
   - Multiple orthogonal assays > single assay format
   - Larger patient cohorts > smaller cohorts

4. COMPLEMENTARY vs CONTRADICTORY: Explicitly note when papers are complementary
   (reporting different aspects of the same compound) vs truly contradictory
   (reaching opposite mechanistic conclusions).

5. COMPLETENESS: Include all key numerical values mentioned in the context
   (IC50, ORR, safety rates, PK parameters) with their units.

6. TONE: Formal, scientific, balanced. Do not hedge unnecessarily.

7. REFERENCES: End your answer with a "REFERENCES" section listing every cited
   paper in full bibliographic format:
   Author(s). (Year). Title. Journal.

Structure: SUMMARY / KEY FINDINGS / CONFLICT ANALYSIS / CONCLUSIONS / REFERENCES
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
        answer, tokens_used = await self._call_llm(query, context)

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
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            timestamp=datetime.utcnow(),
        )

        return answer, trace

    @staticmethod
    def _make_citation_key(pr: PaperResult) -> str:
        """
        Build an author-year citation key from paper metadata.
        Falls back to a title-slug if author/date are unavailable.

        Examples:
            "Chen et al., 2023"
            "Park, 2024"
            "NVX-0228 Novel Inhibitor"
        """
        authors: list[str] = []
        year: str = "n.d."

        # Authors and date live on the first RetrievedChunk's metadata
        if pr.chunks:
            rc = pr.chunks[0]
            if rc.paper_authors:
                authors = rc.paper_authors
            if rc.publication_date:
                year = str(rc.publication_date.year)

        if authors:
            # "Chen, W." → "Chen"
            first_last = authors[0].split(",")[0].strip()
            suffix = " et al." if len(authors) > 1 else ""
            return f"{first_last}{suffix}, {year}"

        # Fallback: derive a short slug from the paper title or paper_id
        title = pr.paper_title or pr.paper_id.replace("_", " ")
        words = title.split()
        slug = " ".join(words[:4]) if len(words) > 4 else title
        return f"{slug} ({year})"

    @staticmethod
    def _make_full_reference(pr: PaperResult, key: str) -> str:
        """
        Format a full bibliographic reference string.
        Example: Chen, W., Rodriguez, M., Patel, S., Nakamura, T. (2023).
                 NVX-0228: A Novel BRD4 Inhibitor. Journal of Medicinal Chemistry.
        """
        authors_str = "Unknown authors"
        year = "n.d."
        journal = ""

        if pr.chunks:
            rc = pr.chunks[0]
            if rc.paper_authors:
                authors_str = ", ".join(rc.paper_authors)
            if rc.publication_date:
                year = str(rc.publication_date.year)
            if rc.journal:
                journal = rc.journal

        title = pr.paper_title or pr.paper_id.replace("_", " ")
        parts = [f"{authors_str} ({year}). {title}."]
        if journal:
            parts.append(f" {journal}.")
        return "".join(parts)

    def _build_context(
        self,
        paper_results: list[PaperResult],
        conflicts: list[Conflict],
    ) -> str:
        """Build the full context block for the LLM prompt."""
        context_parts: list[str] = []

        # Build citation keys (unique — deduplicate by paper_id)
        seen_ids: set[str] = set()
        unique_papers: list[PaperResult] = []
        for pr in paper_results:
            if pr.paper_id not in seen_ids:
                seen_ids.add(pr.paper_id)
                unique_papers.append(pr)

        # Map paper_id → citation key
        citation_map: dict[str, str] = {}
        used_keys: set[str] = set()
        for pr in unique_papers:
            key = self._make_citation_key(pr)
            # Disambiguate duplicate keys (e.g., two papers same first author + year)
            if key in used_keys:
                base = key
                suffix_idx = 2
                while key in used_keys:
                    key = f"{base}{chr(96 + suffix_idx)}"  # ...2023b, 2023c
                    suffix_idx += 1
            used_keys.add(key)
            citation_map[pr.paper_id] = key

        # --- Paper registry block (LLM sees this to know how to cite) ---
        registry_lines = ["=== PAPER REGISTRY (use these keys for in-text citations) ==="]
        for pr in unique_papers:
            key = citation_map[pr.paper_id]
            ref = self._make_full_reference(pr, key)
            registry_lines.append(f"[{key}] → {ref}")
        context_parts.append("\n".join(registry_lines))
        context_parts.append("")

        # --- Per-paper context ---
        for pr in unique_papers:
            key = citation_map[pr.paper_id]
            header = (
                f"=== [{key}] paper_id={pr.paper_id} "
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

        # --- Conflict summary (reference papers by citation key, not paper_id) ---
        if conflicts:
            context_parts.append("=== IDENTIFIED CONFLICTS ===")
            for conflict in conflicts:
                involved_keys = [
                    citation_map.get(pid, pid) for pid in conflict.papers_involved
                ]
                context_parts.append(
                    f"Property: {conflict.property}\n"
                    f"Type: {conflict.conflict_type.value}\n"
                    f"Papers: {', '.join(involved_keys)}\n"
                    f"Reasoning: {conflict.reasoning}\n"
                    + (f"Resolution: {conflict.resolution}\n" if conflict.resolution else "")
                )
        else:
            context_parts.append("=== NO CONFLICTS IDENTIFIED ===")

        return "\n".join(context_parts)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _call_llm(self, query: str, context: str) -> tuple[str, int]:
        """Call the LLM to synthesize the final answer.

        Returns:
            (answer, tokens_used)
        """
        # Count per-paper sections by matching the section delimiter "=== ["
        # (excludes the registry header and conflict header which use different prefixes)
        paper_count = context.count("paper_id=")
        user_message = (
            f"Research question: {query}\n\n"
            f"Context from {paper_count}-paper corpus:\n\n"
            f"{context}"
        )

        response = await _openai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYNTHESIS_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=SYNTHESIS_MAX_TOKENS,
            temperature=0.2,
        )

        tokens_used: int = getattr(getattr(response, "usage", None), "total_tokens", 0) or 0
        return response.choices[0].message.content or "", tokens_used
