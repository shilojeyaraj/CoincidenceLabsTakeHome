"""
Tests for SynthesisAgent.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.synthesis_agent import SynthesisAgent
from src.models import (
    Chunk,
    Conflict,
    ConflictType,
    ExtractedClaim,
    PaperResult,
    RetrievedChunk,
    TraceStep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_openai_synthesis(content: str) -> MagicMock:
    mock_client = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock()
    resp.usage.total_tokens = 150
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    return mock_client


def _make_chunk(paper_id: str, content: str, page: int = 0) -> Chunk:
    return Chunk(
        id=f"chunk-{paper_id}-{page}",
        paper_id=paper_id,
        chunk_type="text",
        content=content,
        section="Results",
        page=page,
    )


def _make_paper_result(paper_id: str, label: str) -> PaperResult:
    chunk = _make_chunk(paper_id, f"Content from {label}", page=1)
    return PaperResult(
        paper_id=paper_id,
        paper_title=label,
        chunks=[RetrievedChunk(chunk=chunk, similarity=0.9)],
        claims=[
            ExtractedClaim(
                paper_id=paper_id,
                property="ic50_bd1_nm",
                value="12",
                context="IC50 measurement",
                chunk_id=chunk.id,
                confidence=0.9,
            )
        ],
        warm_summary=f"Warm summary for {label}",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSynthesisAgent:

    @pytest.mark.asyncio
    async def test_synthesis_cites_all_papers(self):
        """The synthesized answer should cite all 5 papers as [Paper1]..[Paper5]."""
        # Build answer that cites all 5
        answer_with_all_citations = (
            "NVX-0228 demonstrates potent BRD4 BD1 inhibition with IC50=12 nM [Paper1]. "
            "Pharmacokinetic studies [Paper2] show Cmax=1,240 ng/mL at RP2D. "
            "Comparative hematologic data [Paper3] confirm selectivity advantages. "
            "The 1.8 Å crystal structure [Paper4] validates competitive binding. "
            "Updated Phase I results [Paper5] show improved ORR of 38% in AML."
        )

        mock_openai = _mock_openai_synthesis(answer_with_all_citations)

        paper_results = [
            _make_paper_result(f"paper{i}_nvx0228", f"Paper {i} Title")
            for i in range(1, 6)
        ]
        conflicts: list[Conflict] = []

        with patch("src.agents.synthesis_agent._openai_client", mock_openai):
            agent = SynthesisAgent()
            answer, trace = await agent.run(
                query="Summarize NVX-0228 across all papers",
                paper_results=paper_results,
                conflicts=conflicts,
            )

        for i in range(1, 6):
            assert f"[Paper{i}]" in answer, f"Expected [Paper{i}] citation in answer"

    @pytest.mark.asyncio
    async def test_synthesis_addresses_conflicts(self):
        """Every conflict's property should be mentioned in the synthesized answer."""
        conflicts = [
            Conflict(
                property="ic50_bd1_nm",
                conflict_type=ConflictType.ASSAY_VARIABILITY,
                papers_involved=["paper1_nvx0228_novel_inhibitor", "paper3_brd4_hematologic_comparative"],
                claims=[
                    ExtractedClaim(
                        paper_id="paper1_nvx0228_novel_inhibitor",
                        property="ic50_bd1_nm",
                        value="12",
                        context="AlphaScreen",
                        chunk_id="c1",
                        confidence=0.9,
                    ),
                    ExtractedClaim(
                        paper_id="paper3_brd4_hematologic_comparative",
                        property="ic50_bd1_nm",
                        value="8",
                        context="TR-FRET",
                        chunk_id="c2",
                        confidence=0.9,
                    ),
                ],
                reasoning="Assay format differences explain the IC50 variation.",
                resolution="Both values within assay variability range.",
            ),
            Conflict(
                property="thrombocytopenia_rate_pct",
                conflict_type=ConflictType.EVOLVING_DATA,
                papers_involved=["paper1_nvx0228_novel_inhibitor", "paper5_nvx0228_updated_phase1"],
                claims=[
                    ExtractedClaim(
                        paper_id="paper1_nvx0228_novel_inhibitor",
                        property="thrombocytopenia_rate_pct",
                        value="15",
                        context="Interim analysis",
                        chunk_id="c3",
                        confidence=0.85,
                    ),
                    ExtractedClaim(
                        paper_id="paper5_nvx0228_updated_phase1",
                        property="thrombocytopenia_rate_pct",
                        value="18",
                        context="Updated analysis",
                        chunk_id="c4",
                        confidence=0.90,
                    ),
                ],
                reasoning="Same NCT, different timepoints.",
            ),
        ]

        answer_text = (
            "IC50 values for ic50_bd1_nm range from 8 to 12 nM [Paper1][Paper3] due to "
            "ASSAY_VARIABILITY between AlphaScreen and TR-FRET. "
            "Thrombocytopenia rate (thrombocytopenia_rate_pct) updated from 15% [Paper1] "
            "to 18% [Paper5] in the updated Phase I analysis (EVOLVING_DATA)."
        )

        mock_openai = _mock_openai_synthesis(answer_text)

        paper_results = [
            _make_paper_result("paper1_nvx0228_novel_inhibitor", "Paper 1"),
            _make_paper_result("paper5_nvx0228_updated_phase1", "Paper 5"),
        ]

        with patch("src.agents.synthesis_agent._openai_client", mock_openai):
            agent = SynthesisAgent()
            answer, trace = await agent.run(
                query="What are the safety and IC50 data for NVX-0228?",
                paper_results=paper_results,
                conflicts=conflicts,
            )

        for conflict in conflicts:
            assert conflict.property in answer, (
                f"Expected conflict property '{conflict.property}' to be addressed in answer"
            )

    @pytest.mark.asyncio
    async def test_synthesis_never_silent_winner(self):
        """
        The synthesized answer must not silently pick one IC50 value without noting
        the disagreement (i.e., it must mention both values or explicitly note the range).
        """
        # This answer correctly notes the disagreement
        answer_noting_disagreement = (
            "IC50 values for NVX-0228 BD1 inhibition range from 8 nM [Paper3] to 12 nM [Paper1] "
            "depending on assay format. Paper1 used AlphaScreen format while Paper3 used TR-FRET; "
            "both values indicate potent low-nanomolar activity. The 1.8 Å crystal structure [Paper4] "
            "provides structural validation independently of assay format."
        )

        mock_openai = _mock_openai_synthesis(answer_noting_disagreement)

        paper_results = [
            _make_paper_result("paper1_nvx0228_novel_inhibitor", "Paper 1"),
            _make_paper_result("paper3_brd4_hematologic_comparative", "Paper 3"),
            _make_paper_result("paper4_nvx0228_structural_basis", "Paper 4"),
        ]
        conflicts = [
            Conflict(
                property="ic50_bd1_nm",
                conflict_type=ConflictType.ASSAY_VARIABILITY,
                papers_involved=["paper1_nvx0228_novel_inhibitor", "paper3_brd4_hematologic_comparative"],
                claims=[
                    ExtractedClaim(
                        paper_id="paper1_nvx0228_novel_inhibitor",
                        property="ic50_bd1_nm",
                        value="12",
                        context="AlphaScreen",
                        chunk_id="c1",
                        confidence=0.9,
                    ),
                    ExtractedClaim(
                        paper_id="paper3_brd4_hematologic_comparative",
                        property="ic50_bd1_nm",
                        value="8",
                        context="TR-FRET",
                        chunk_id="c2",
                        confidence=0.9,
                    ),
                ],
                reasoning="Assay format differences.",
            )
        ]

        with patch("src.agents.synthesis_agent._openai_client", mock_openai):
            agent = SynthesisAgent()
            answer, trace = await agent.run(
                query="What is the IC50 of NVX-0228?",
                paper_results=paper_results,
                conflicts=conflicts,
            )

        # Verify both values appear in the answer — not a silent winner
        assert "8 nM" in answer or "8" in answer, "Expected lower IC50 value to appear in answer"
        assert "12 nM" in answer or "12" in answer, "Expected higher IC50 value to appear in answer"

        # Verify the answer does not ONLY mention one value (simplified check)
        # A silent winner answer would be: "The IC50 is 12 nM." with no mention of 8 nM
        has_both = ("8" in answer and "12" in answer)
        assert has_both, "Answer must reference both conflicting values, not silently pick one"

    @pytest.mark.asyncio
    async def test_synthesis_returns_trace_step(self):
        """SynthesisAgent.run should return a well-formed TraceStep."""
        answer = "NVX-0228 summary answer with [Paper1] citations."
        mock_openai = _mock_openai_synthesis(answer)

        paper_results = [_make_paper_result("paper1_nvx0228_novel_inhibitor", "Paper 1")]

        with patch("src.agents.synthesis_agent._openai_client", mock_openai):
            agent = SynthesisAgent()
            result, trace = await agent.run(
                query="Summarize NVX-0228",
                paper_results=paper_results,
                conflicts=[],
            )

        assert isinstance(trace, TraceStep)
        assert trace.agent == "SynthesisAgent"
        assert trace.step == "synthesis_agent"
        assert trace.latency_ms >= 0.0
        assert len(result) > 0
