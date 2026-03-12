"""
Tests for ConflictAgent.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.conflict_agent import ConflictAgent
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

def _make_paper_result(
    paper_id: str,
    claims: list[ExtractedClaim],
    warm_summary: str = "",
) -> PaperResult:
    return PaperResult(
        paper_id=paper_id,
        paper_title=f"Title for {paper_id}",
        chunks=[],
        claims=claims,
        warm_summary=warm_summary,
    )


def _make_claim(paper_id: str, prop: str, value: str, confidence: float = 0.9) -> ExtractedClaim:
    return ExtractedClaim(
        paper_id=paper_id,
        property=prop,
        value=value,
        context=f"Context for {prop} in {paper_id}",
        chunk_id=f"chunk-{paper_id}-{prop}",
        confidence=confidence,
    )


def _mock_openai_for_conflict(conflict_json: str) -> MagicMock:
    """Create a mock OpenAI client returning specified JSON for conflict classification."""
    mock_client = MagicMock()
    choice = MagicMock()
    choice.message.content = conflict_json
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock()
    resp.usage.total_tokens = 100
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    return mock_client


def _mock_supabase_expansion() -> MagicMock:
    """Supabase mock returning expansion chunks."""
    mock_client = MagicMock()
    rpc_response = MagicMock()
    rpc_response.data = [
        {
            "id": "p4-expansion-chunk-001",
            "paper_id": "paper4_nvx0228_structural_basis",
            "chunk_type": "text",
            "content": "1.8 Å crystal structure confirms competitive binding at acetyl-lysine pocket.",
            "section": "Results",
            "page": 4,
            "grounding": {},
            "similarity": 0.88,
        }
    ]
    mock_client.rpc.return_value.execute.return_value = rpc_response
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConflictAgent:

    @pytest.mark.asyncio
    async def test_ic50_conflict_classified_as_assay_variability(self):
        """Different IC50 values from different assay formats → ASSAY_VARIABILITY."""
        conflict_json = json.dumps({
            "conflict_type": "ASSAY_VARIABILITY",
            "reasoning": "Values differ due to assay format: AlphaScreen (12 nM) vs TR-FRET (8 nM).",
            "resolution": "Both within assay variability range.",
            "requires_expansion": False,
        })

        paper_results = [
            _make_paper_result(
                "paper1_nvx0228_novel_inhibitor",
                [_make_claim("paper1_nvx0228_novel_inhibitor", "ic50_bd1_nm", "12")],
                warm_summary="NCT05123456 Phase I, IC50=12 nM AlphaScreen",
            ),
            _make_paper_result(
                "paper3_brd4_hematologic_comparative",
                [_make_claim("paper3_brd4_hematologic_comparative", "ic50_bd1_nm", "8")],
                warm_summary="IC50=8 nM TR-FRET format",
            ),
        ]

        mock_openai = _mock_openai_for_conflict(conflict_json)
        mock_supa = _mock_supabase_expansion()

        with patch("src.agents.conflict_agent._openai_client", mock_openai), \
             patch("src.embeddings._openai_client", mock_openai), \
             patch("src.embeddings.get_client", return_value=mock_supa):

            agent = ConflictAgent()
            conflicts, trace, exp_results, exp_traces = await agent.run(
                query="What is the IC50 of NVX-0228?",
                paper_results=paper_results,
            )

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.property == "ic50_bd1_nm"
        assert conflict.conflict_type == ConflictType.ASSAY_VARIABILITY
        assert not conflict.requires_expansion

    @pytest.mark.asyncio
    async def test_mechanism_conflict_classified_as_conceptual(self):
        """Competitive vs allosteric mechanism claims → CONCEPTUAL conflict."""
        conflict_json = json.dumps({
            "conflict_type": "CONCEPTUAL",
            "reasoning": (
                "Paper1 claims competitive inhibition; Paper2 suggests allosteric mechanism. "
                "These are fundamentally different mechanistic interpretations."
            ),
            "resolution": "Requires further structural data to resolve.",
            "requires_expansion": True,
        })

        paper_results = [
            _make_paper_result(
                "paper1_nvx0228_novel_inhibitor",
                [_make_claim("paper1_nvx0228_novel_inhibitor", "mechanism_of_action", "competitive inhibitor")],
            ),
            _make_paper_result(
                "paper2_nvx0228_pharmacokinetics",
                [_make_claim("paper2_nvx0228_pharmacokinetics", "mechanism_of_action", "allosteric modulator")],
            ),
        ]

        mock_openai = _mock_openai_for_conflict(conflict_json)
        mock_supa = _mock_supabase_expansion()
        emb_item = MagicMock()
        emb_item.embedding = [0.0] * 1536
        emb_item.index = 0
        emb_resp = MagicMock()
        emb_resp.data = [emb_item]
        mock_openai.embeddings.create.return_value = emb_resp

        with patch("src.agents.conflict_agent._openai_client", mock_openai), \
             patch("src.embeddings._openai_client", mock_openai), \
             patch("src.embeddings.get_client", return_value=mock_supa):

            agent = ConflictAgent()
            conflicts, trace, exp_results, exp_traces = await agent.run(
                query="What is the mechanism of NVX-0228?",
                paper_results=paper_results,
            )

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.conflict_type == ConflictType.CONCEPTUAL
        assert conflict.requires_expansion is True

    @pytest.mark.asyncio
    async def test_conceptual_conflict_triggers_expansion(self):
        """CONCEPTUAL conflict with requires_expansion=True should trigger context expansion."""
        conflict_json = json.dumps({
            "conflict_type": "CONCEPTUAL",
            "reasoning": "Mechanistic disagreement requiring structural clarification.",
            "resolution": None,
            "requires_expansion": True,
        })

        paper_results = [
            _make_paper_result(
                "paper1_nvx0228_novel_inhibitor",
                [_make_claim("paper1_nvx0228_novel_inhibitor", "binding_mode", "direct pocket binding")],
            ),
            _make_paper_result(
                "paper4_nvx0228_structural_basis",
                [_make_claim("paper4_nvx0228_structural_basis", "binding_mode", "WPF shelf interaction")],
            ),
        ]

        mock_openai = _mock_openai_for_conflict(conflict_json)
        mock_supa = _mock_supabase_expansion()
        emb_item = MagicMock()
        emb_item.embedding = [0.0] * 1536
        emb_item.index = 0
        emb_resp = MagicMock()
        emb_resp.data = [emb_item]
        mock_openai.embeddings.create.return_value = emb_resp

        with patch("src.agents.conflict_agent._openai_client", mock_openai), \
             patch("src.embeddings._openai_client", mock_openai), \
             patch("src.embeddings.get_client", return_value=mock_supa):

            agent = ConflictAgent()
            conflicts, trace, exp_results, exp_traces = await agent.run(
                query="What is the binding mode?",
                paper_results=paper_results,
            )

        # Expansion should have been triggered
        assert len(exp_results) > 0 or len(exp_traces) > 0
        assert "context_expansion" in trace.output_summary or "CONCEPTUAL" in trace.output_summary

    @pytest.mark.asyncio
    async def test_evolving_data_not_classified_as_conceptual(self):
        """Same trial (same NCT), different timepoints → EVOLVING_DATA, not CONCEPTUAL."""
        conflict_json = json.dumps({
            "conflict_type": "EVOLVING_DATA",
            "reasoning": (
                "Both papers report on NCT05123456 — Paper1 is interim (4.2 months) and "
                "Paper5 is the updated analysis (12 months). This is the same trial at "
                "different timepoints, not a true conflict."
            ),
            "resolution": "Paper5 provides updated data from the same trial; use Paper5 as primary.",
            "requires_expansion": False,
        })

        paper_results = [
            _make_paper_result(
                "paper1_nvx0228_novel_inhibitor",
                [_make_claim("paper1_nvx0228_novel_inhibitor", "orr_aml_pct", "33")],
                warm_summary="NCT05123456 Phase I interim, 4.2 months follow-up, ORR=33%",
            ),
            _make_paper_result(
                "paper5_nvx0228_updated_phase1",
                [_make_claim("paper5_nvx0228_updated_phase1", "orr_aml_pct", "38")],
                warm_summary="NCT05123456 Phase I updated analysis, 12 months follow-up, ORR=38%",
            ),
        ]

        mock_openai = _mock_openai_for_conflict(conflict_json)

        with patch("src.agents.conflict_agent._openai_client", mock_openai), \
             patch("src.embeddings._openai_client", mock_openai):

            agent = ConflictAgent()
            conflicts, trace, exp_results, exp_traces = await agent.run(
                query="What is the ORR in AML?",
                paper_results=paper_results,
            )

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.conflict_type == ConflictType.EVOLVING_DATA
        assert conflict.conflict_type != ConflictType.CONCEPTUAL

    @pytest.mark.asyncio
    async def test_non_conflict_not_flagged(self):
        """Consistent values from different trials → NON_CONFLICT."""
        conflict_json = json.dumps({
            "conflict_type": "NON_CONFLICT",
            "reasoning": (
                "Both papers report BD1/BD2 selectivity ratio of ~50-fold "
                "(50-fold and 48-fold respectively). Values are consistent within "
                "measurement uncertainty."
            ),
            "resolution": "Values are in agreement; no conflict present.",
            "requires_expansion": False,
        })

        paper_results = [
            _make_paper_result(
                "paper1_nvx0228_novel_inhibitor",
                [_make_claim("paper1_nvx0228_novel_inhibitor", "bd1_bd2_selectivity_fold", "50")],
            ),
            _make_paper_result(
                "paper4_nvx0228_structural_basis",
                [_make_claim("paper4_nvx0228_structural_basis", "bd1_bd2_selectivity_fold", "48")],
            ),
        ]

        mock_openai = _mock_openai_for_conflict(conflict_json)

        with patch("src.agents.conflict_agent._openai_client", mock_openai), \
             patch("src.embeddings._openai_client", mock_openai):

            agent = ConflictAgent()
            conflicts, trace, exp_results, exp_traces = await agent.run(
                query="What is the BD1/BD2 selectivity?",
                paper_results=paper_results,
            )

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.conflict_type == ConflictType.NON_CONFLICT
        assert not conflict.requires_expansion
        assert exp_results == []
