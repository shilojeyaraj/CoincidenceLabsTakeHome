"""
Pytest fixtures for the Multi-Document Conflict Resolution RAG test suite.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
# Fake data helpers
# ---------------------------------------------------------------------------

def _make_fake_embedding(dim: int = 1536) -> list[float]:
    """Return a zero-filled embedding vector."""
    return [0.0] * dim


def _make_fake_chat_response(content: str, total_tokens: int = 150) -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.total_tokens = total_tokens
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _make_fake_embedding_response(texts: list[str]) -> MagicMock:
    """Build a mock OpenAI embedding response."""
    data = []
    for i, _ in enumerate(texts):
        item = MagicMock()
        item.embedding = _make_fake_embedding()
        item.index = i
        data.append(item)
    response = MagicMock()
    response.data = data
    return response


# ---------------------------------------------------------------------------
# Fake Supabase chunk rows
# ---------------------------------------------------------------------------

FAKE_SUPABASE_CHUNKS = [
    {
        "id": "p1-chunk-001-a3f8b2c1",
        "paper_id": "paper1_nvx0228_novel_inhibitor",
        "chunk_type": "text",
        "content": (
            "NVX-0228 is a novel small-molecule inhibitor of BRD4 with an IC50 of 12 nM "
            "in biochemical assays (BD1 bromodomain, AlphaScreen format)."
        ),
        "section": "Abstract",
        "page": 0,
        "grounding": {"box": {"left": 0.05, "top": 0.08, "right": 0.95, "bottom": 0.28}, "page": 0},
        "similarity": 0.92,
    },
    {
        "id": "p1-chunk-003-b2c8d5e7",
        "paper_id": "paper1_nvx0228_novel_inhibitor",
        "chunk_type": "text",
        "content": (
            "NVX-0228 was designed as a competitive inhibitor that binds directly to the "
            "acetyl-lysine recognition pocket of the BD1 bromodomain."
        ),
        "section": "Results - Compound Design and SAR",
        "page": 3,
        "grounding": {"box": {"left": 0.05, "top": 0.08, "right": 0.95, "bottom": 0.42}, "page": 3},
        "similarity": 0.87,
    },
]

FAKE_PAPER_SUMMARY = {
    "paper_id": "paper1_nvx0228_novel_inhibitor",
    "title": "NVX-0228: A Novel BRD4 Inhibitor with Potent Antitumor Activity",
    "authors": ["Chen, W.", "Rodriguez, M.", "Patel, S.", "Nakamura, T."],
    "publication_date": "2023-06-15",
    "journal": "Journal of Medicinal Chemistry",
    "sample_size": 48,
    "page_count": 14,
    "summary": (
        "NVX-0228 is a BD1-selective BRD4 inhibitor (IC50=12 nM) demonstrating 50-fold "
        "selectivity over BD2. Phase I trial NCT05123456 in 48 AML/DLBCL patients showed "
        "ORR of 33% in AML with mild thrombocytopenia in 15% of subjects."
    ),
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_openai(monkeypatch):
    """
    Patch the OpenAI client used by all agents.
    Returns realistic fake responses for embeddings and chat completions.
    """
    fake_claims_json = (
        '{"claims": ['
        '{"paper_id": "paper1_nvx0228_novel_inhibitor", "property": "ic50_bd1_nm", '
        '"value": "12", "context": "IC50 of 12 nM in BD1 biochemical assay", '
        '"chunk_id": "p1-chunk-001-a3f8b2c1", "confidence": 0.95}'
        ']}'
    )
    fake_conflict_json = (
        '{"conflict_type": "ASSAY_VARIABILITY", '
        '"reasoning": "Values differ due to assay format (AlphaScreen vs TR-FRET).", '
        '"resolution": "Both values within expected assay variability range.", '
        '"requires_expansion": false}'
    )
    fake_synthesis = (
        "NVX-0228 demonstrates potent BRD4 BD1 inhibition (IC50=12 nM [Paper1]; "
        "8 nM [Paper3]) with 50-fold BD1/BD2 selectivity [Paper1][Paper4]. "
        "IC50 values show ASSAY_VARIABILITY between AlphaScreen and TR-FRET formats. "
        "The competitive binding mechanism is confirmed by 1.8 Å crystal structure [Paper4]. "
        "Phase I safety profile [Paper1][Paper5] shows mild thrombocytopenia (15%). "
        "[Paper2] characterizes PK parameters at RP2D."
    )

    mock_client = MagicMock()

    # Embeddings (sync client in embeddings.py — called via asyncio.to_thread)
    mock_client.embeddings.create.side_effect = lambda **kwargs: _make_fake_embedding_response(
        kwargs.get("input", [""])
        if isinstance(kwargs.get("input", ""), list)
        else [kwargs.get("input", "")]
    )

    # Chat completions — AsyncMock because agents now use AsyncOpenAI (await required)
    call_counter = {"n": 0}
    responses = [fake_claims_json, fake_conflict_json, fake_synthesis]

    def _chat_side_effect(**kwargs):
        idx = call_counter["n"] % len(responses)
        call_counter["n"] += 1
        return _make_fake_chat_response(responses[idx])

    mock_client.chat.completions.create = AsyncMock(side_effect=_chat_side_effect)
    mock_client.models.list.return_value = MagicMock()

    with patch("src.agents.paper_agent._openai_client", mock_client), \
         patch("src.agents.conflict_agent._openai_client", mock_client), \
         patch("src.agents.synthesis_agent._openai_client", mock_client), \
         patch("src.agents.ind_template_agent._openai_client", mock_client), \
         patch("src.context_manager._openai_client", mock_client), \
         patch("openai.OpenAI", return_value=mock_client):
        yield mock_client


@pytest.fixture
def mock_supabase(monkeypatch):
    """
    Patch the Supabase client used by all agents.
    Returns fake chunk and paper_summary data.
    """
    mock_client = MagicMock()

    # --- chunks table mock ---
    chunks_response = MagicMock()
    chunks_response.data = FAKE_SUPABASE_CHUNKS

    # --- paper_summaries table mock ---
    summaries_response = MagicMock()
    summaries_response.data = [FAKE_PAPER_SUMMARY]

    # Chain: table(...).select(...).eq(...).limit(...).execute() → response
    def table_side_effect(table_name: str):
        tbl = MagicMock()
        if table_name == "paper_summaries":
            tbl.select.return_value.eq.return_value.limit.return_value.execute.return_value = summaries_response
            tbl.upsert.return_value.execute.return_value = MagicMock()
        elif table_name == "chunks":
            tbl.select.return_value.limit.return_value.execute.return_value = chunks_response
            tbl.upsert.return_value.execute.return_value = MagicMock()
        return tbl

    mock_client.table.side_effect = table_side_effect

    # --- RPC mock for match_chunks ---
    rpc_response = MagicMock()
    rpc_response.data = FAKE_SUPABASE_CHUNKS
    mock_client.rpc.return_value.execute.return_value = rpc_response

    with patch("src.db.get_client", return_value=mock_client), \
         patch("src.agents.paper_agent.get_client", return_value=mock_client), \
         patch("src.embeddings.get_client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def sample_paper_results() -> list[PaperResult]:
    """Two realistic PaperResult fixtures using NVX-0228 data."""
    chunk1 = Chunk(
        id="p1-chunk-001-a3f8b2c1",
        paper_id="paper1_nvx0228_novel_inhibitor",
        chunk_type="text",
        content="NVX-0228 demonstrated IC50 of 12 nM in BD1 biochemical assay (AlphaScreen).",
        section="Abstract",
        page=0,
    )
    chunk2 = Chunk(
        id="p3-chunk-001-x9y2z3",
        paper_id="paper3_brd4_hematologic_comparative",
        chunk_type="text",
        content="NVX-0228 showed IC50 of 8 nM in TR-FRET competitive binding assay for BRD4 BD1.",
        section="Results - In Vitro",
        page=2,
    )
    chunk3 = Chunk(
        id="p4-chunk-002-crystal",
        paper_id="paper4_nvx0228_structural_basis",
        chunk_type="text",
        content=(
            "The 1.8 Å crystal structure confirms competitive binding mechanism: "
            "NVX-0228 occupies the acetyl-lysine pocket forming hydrogen bonds with Asn140."
        ),
        section="Results - Crystal Structure",
        page=4,
    )

    claims1 = [
        ExtractedClaim(
            paper_id="paper1_nvx0228_novel_inhibitor",
            property="ic50_bd1_nm",
            value="12",
            context="AlphaScreen biochemical assay",
            chunk_id="p1-chunk-001-a3f8b2c1",
            confidence=0.95,
        ),
        ExtractedClaim(
            paper_id="paper1_nvx0228_novel_inhibitor",
            property="mechanism_of_action",
            value="competitive inhibitor",
            context="Binds acetyl-lysine pocket of BD1",
            chunk_id="p1-chunk-003-b2c8d5e7",
            confidence=0.85,
        ),
    ]
    claims2 = [
        ExtractedClaim(
            paper_id="paper3_brd4_hematologic_comparative",
            property="ic50_bd1_nm",
            value="8",
            context="TR-FRET competitive binding assay",
            chunk_id="p3-chunk-001-x9y2z3",
            confidence=0.90,
        ),
    ]
    claims3 = [
        ExtractedClaim(
            paper_id="paper4_nvx0228_structural_basis",
            property="mechanism_of_action",
            value="competitive — confirmed by 1.8 Å crystal structure",
            context="Crystal structure shows acetyl-lysine pocket occupancy",
            chunk_id="p4-chunk-002-crystal",
            confidence=0.99,
        ),
    ]

    return [
        PaperResult(
            paper_id="paper1_nvx0228_novel_inhibitor",
            paper_title="NVX-0228: A Novel BRD4 Inhibitor with Potent Antitumor Activity",
            chunks=[RetrievedChunk(chunk=chunk1, similarity=0.92)],
            claims=claims1,
            warm_summary="NVX-0228 BD1-selective BRD4 inhibitor, IC50=12 nM, Phase I NCT05123456, 48 patients.",
        ),
        PaperResult(
            paper_id="paper3_brd4_hematologic_comparative",
            paper_title="BRD4 Inhibitors in Hematologic Malignancies: Comparative Study",
            chunks=[RetrievedChunk(chunk=chunk2, similarity=0.85)],
            claims=claims2,
            warm_summary="Comparative analysis of BRD4 inhibitors including NVX-0228 (IC50=8 nM by TR-FRET).",
        ),
        PaperResult(
            paper_id="paper4_nvx0228_structural_basis",
            paper_title="Structural Basis for BD1 Selectivity of NVX-0228",
            chunks=[RetrievedChunk(chunk=chunk3, similarity=0.91)],
            claims=claims3,
            warm_summary="1.8 Å crystal structure of NVX-0228/BRD4-BD1 complex confirms competitive binding.",
        ),
    ]


@pytest.fixture
def sample_conflicts() -> list[Conflict]:
    """One ASSAY_VARIABILITY conflict and one CONCEPTUAL conflict."""
    assay_conflict = Conflict(
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
                context="AlphaScreen biochemical assay",
                chunk_id="p1-chunk-001-a3f8b2c1",
                confidence=0.95,
            ),
            ExtractedClaim(
                paper_id="paper3_brd4_hematologic_comparative",
                property="ic50_bd1_nm",
                value="8",
                context="TR-FRET competitive binding assay",
                chunk_id="p3-chunk-001-x9y2z3",
                confidence=0.90,
            ),
        ],
        reasoning=(
            "IC50 values of 12 nM (AlphaScreen) vs 8 nM (TR-FRET) differ due to assay format "
            "differences. Both within expected assay variability range."
        ),
        resolution="Values consistent within assay format variability; both indicate low-nM potency.",
        requires_expansion=False,
    )

    conceptual_conflict = Conflict(
        property="mechanism_of_action",
        conflict_type=ConflictType.CONCEPTUAL,
        papers_involved=[
            "paper1_nvx0228_novel_inhibitor",
            "paper4_nvx0228_structural_basis",
        ],
        claims=[
            ExtractedClaim(
                paper_id="paper1_nvx0228_novel_inhibitor",
                property="mechanism_of_action",
                value="competitive inhibitor",
                context="Based on SAR studies",
                chunk_id="p1-chunk-003-b2c8d5e7",
                confidence=0.85,
            ),
            ExtractedClaim(
                paper_id="paper4_nvx0228_structural_basis",
                property="mechanism_of_action",
                value="competitive — confirmed by 1.8 Å crystal structure",
                context="Crystal structure of NVX-0228/BRD4-BD1 complex",
                chunk_id="p4-chunk-002-crystal",
                confidence=0.99,
            ),
        ],
        reasoning=(
            "Paper1 claims competitive mechanism based on SAR. Paper4 provides structural "
            "confirmation at 1.8 Å resolution showing direct acetyl-lysine pocket occupancy. "
            "These are not truly contradictory — Paper4 provides stronger evidence for the "
            "same competitive mechanism."
        ),
        resolution="Paper4 crystal structure provides definitive structural confirmation of competitive binding.",
        requires_expansion=True,
    )

    return [assay_conflict, conceptual_conflict]
