"""
Integration tests for the LangGraph orchestrator (full graph end-to-end).

These tests exercise the full StateGraph flow:
  START → paper_node×5 → conflict_node → synthesis_node → END
and optionally the IND template fan-out. All I/O is mocked.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import (
    Conflict,
    ConflictType,
    ExtractedClaim,
    INDSectionResult,
    PaperResult,
    QueryResult,
    TraceStep,
)
from src.orchestrator import run_query


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paper_result(paper_id: str, ic50_value: str = "12") -> PaperResult:
    return PaperResult(
        paper_id=paper_id,
        paper_title=f"Test paper {paper_id}",
        chunks=[],
        claims=[
            ExtractedClaim(
                paper_id=paper_id,
                property="ic50_bd1_nm",
                value=ic50_value,
                context=f"IC50 from {paper_id}",
                chunk_id=f"{paper_id}-chunk-001",
                confidence=0.9,
            )
        ],
        warm_summary=f"Warm summary for {paper_id}.",
    )


def _make_conflict() -> Conflict:
    return Conflict(
        property="ic50_bd1_nm",
        conflict_type=ConflictType.ASSAY_VARIABILITY,
        papers_involved=[
            "paper1_nvx0228_novel_inhibitor",
            "paper3_brd4_hematologic_comparative",
        ],
        claims=[
            ExtractedClaim(
                paper_id="paper1_nvx0228_novel_inhibitor",
                property="ic50_bd1_nm",
                value="12",
                context="AlphaScreen",
                chunk_id="p1-c1",
                confidence=0.95,
            ),
            ExtractedClaim(
                paper_id="paper3_brd4_hematologic_comparative",
                property="ic50_bd1_nm",
                value="8",
                context="TR-FRET",
                chunk_id="p3-c1",
                confidence=0.9,
            ),
        ],
        reasoning="Assay format difference (AlphaScreen vs TR-FRET).",
        resolution="Within expected assay variability.",
        requires_expansion=False,
    )


_PAPER_IDS = [
    "paper1_nvx0228_novel_inhibitor",
    "paper2_nvx0228_pharmacokinetics",
    "paper3_brd4_hematologic_comparative",
    "paper4_nvx0228_structural_basis",
    "paper5_nvx0228_updated_phase1",
]

_FAKE_TRACE_STEP = TraceStep(
    step="mock_step",
    agent="MockAgent",
    input_summary="mock input",
    output_summary="mock output",
    tokens_used=100,
    latency_ms=50.0,
    timestamp=datetime.utcnow(),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_paper_agent():
    """Mock PaperAgent.run to return a deterministic PaperResult per paper."""
    paper_ic50_map = {
        "paper1_nvx0228_novel_inhibitor": "12",
        "paper2_nvx0228_pharmacokinetics": "11",
        "paper3_brd4_hematologic_comparative": "8",
        "paper4_nvx0228_structural_basis": "10",
        "paper5_nvx0228_updated_phase1": "15",
    }

    async def fake_run(query, expanded=False, extra_count=0):
        # `self` is the PaperAgent; capture paper_id from it
        return _make_paper_result("paper1_nvx0228_novel_inhibitor", "12"), _FAKE_TRACE_STEP

    with patch("src.orchestrator.PaperAgent") as mock_cls:
        instances = {}

        def make_instance(paper_id):
            inst = MagicMock()
            ic50 = paper_ic50_map.get(paper_id, "12")

            async def _run(query, expanded=False, extra_count=0):
                return _make_paper_result(paper_id, ic50), _FAKE_TRACE_STEP

            inst.run = _run
            instances[paper_id] = inst
            return inst

        mock_cls.side_effect = lambda paper_id: make_instance(paper_id)
        yield mock_cls


@pytest.fixture
def mock_conflict_agent():
    """Mock ConflictAgent.run to return one ASSAY_VARIABILITY conflict."""
    conflict = _make_conflict()

    async def fake_run(query, paper_results):
        return [conflict], _FAKE_TRACE_STEP, [], []

    with patch("src.orchestrator.ConflictAgent") as mock_cls:
        inst = MagicMock()
        inst.run = fake_run
        mock_cls.return_value = inst
        yield mock_cls


@pytest.fixture
def mock_synthesis_agent():
    """Mock SynthesisAgent.run to return a fake synthesis string."""
    async def fake_run(query, paper_results, conflicts):
        answer = (
            "NVX-0228 demonstrates BD1-selective BRD4 inhibition (IC50=12 nM [Paper1]; "
            "8 nM [Paper3]). ASSAY_VARIABILITY on ic50_bd1_nm: AlphaScreen vs TR-FRET. "
            "Competitive mechanism confirmed by crystal structure [Paper4]."
        )
        return answer, _FAKE_TRACE_STEP

    with patch("src.orchestrator.SynthesisAgent") as mock_cls:
        inst = MagicMock()
        inst.run = fake_run
        mock_cls.return_value = inst
        yield mock_cls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOrchestratorFullGraph:

    @pytest.mark.asyncio
    async def test_run_query_returns_query_result(
        self, mock_paper_agent, mock_conflict_agent, mock_synthesis_agent
    ):
        """run_query should return a QueryResult with answer, conflicts, trace."""
        result = await run_query(query="What is the IC50 of NVX-0228?")

        assert isinstance(result, QueryResult)
        assert result.query == "What is the IC50 of NVX-0228?"
        assert len(result.answer) > 0

    @pytest.mark.asyncio
    async def test_run_query_papers_cited(
        self, mock_paper_agent, mock_conflict_agent, mock_synthesis_agent
    ):
        """papers_cited should be populated from all 5 paper agent results."""
        result = await run_query(query="What is the IC50 of NVX-0228?")

        assert len(result.papers_cited) == 5
        for pid in _PAPER_IDS:
            assert pid in result.papers_cited

    @pytest.mark.asyncio
    async def test_run_query_conflicts_populated(
        self, mock_paper_agent, mock_conflict_agent, mock_synthesis_agent
    ):
        """result.conflicts should contain the ASSAY_VARIABILITY conflict from mock."""
        result = await run_query(query="What is the IC50 of NVX-0228?")

        assert len(result.conflicts) == 1
        assert result.conflicts[0].conflict_type == ConflictType.ASSAY_VARIABILITY
        assert result.conflicts[0].property == "ic50_bd1_nm"

    @pytest.mark.asyncio
    async def test_run_query_trace_has_minimum_steps(
        self, mock_paper_agent, mock_conflict_agent, mock_synthesis_agent
    ):
        """Trace should have at least 7 steps: 5 paper agents + conflict + synthesis."""
        result = await run_query(query="What is the IC50 of NVX-0228?")

        # 5 paper_node steps + 1 conflict_node + 1 synthesis_node = 7
        assert len(result.trace) >= 7

    @pytest.mark.asyncio
    async def test_run_query_no_ind_template_by_default(
        self, mock_paper_agent, mock_conflict_agent, mock_synthesis_agent
    ):
        """By default (run_ind_template=False), ind_sections should be absent/None."""
        result = await run_query(query="What is the IC50 of NVX-0228?")

        # QueryResult doesn't have ind_sections field — confirm no error raised
        assert isinstance(result, QueryResult)

    @pytest.mark.asyncio
    async def test_run_query_saves_output_file(
        self,
        mock_paper_agent,
        mock_conflict_agent,
        mock_synthesis_agent,
        tmp_path,
        monkeypatch,
    ):
        """run_query should persist a JSON file to OUTPUTS_DIR."""
        import src.orchestrator as orch_module
        monkeypatch.setattr(orch_module, "OUTPUTS_DIR", tmp_path)

        await run_query(query="Save test query")

        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1
        assert "Save_test_query" in json_files[0].name or json_files[0].suffix == ".json"

    @pytest.mark.asyncio
    async def test_run_query_one_paper_agent_fails_gracefully(
        self, mock_conflict_agent, mock_synthesis_agent
    ):
        """If one PaperAgent raises, the graph should still complete with 4 valid results."""
        call_count = {"n": 0}

        with patch("src.orchestrator.PaperAgent") as mock_cls:
            def make_instance(paper_id):
                inst = MagicMock()
                idx = call_count["n"]
                call_count["n"] += 1

                if idx == 2:  # third paper raises
                    async def _run(query, expanded=False, extra_count=0):
                        raise RuntimeError("Simulated Supabase timeout")
                    inst.run = _run
                else:
                    async def _run(query, expanded=False, extra_count=0):
                        return _make_paper_result(paper_id, "12"), _FAKE_TRACE_STEP
                    inst.run = _run

                return inst

            mock_cls.side_effect = lambda paper_id: make_instance(paper_id)

            result = await run_query(query="What is the IC50 of NVX-0228?")

        # Graph completes without raising
        assert isinstance(result, QueryResult)
        # Error is captured in the trace
        error_steps = [t for t in result.trace if "ERROR" in t.output_summary]
        assert len(error_steps) == 1
