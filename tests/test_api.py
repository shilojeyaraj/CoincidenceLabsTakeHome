"""
Tests for the FastAPI application.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.models import Conflict, ConflictType, PaperResult, QueryResult, TraceStep


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_query_result(query: str = "test query") -> QueryResult:
    """Build a minimal but valid QueryResult for mocking."""
    return QueryResult(
        query=query,
        answer=(
            "NVX-0228 demonstrates potent BD1-selective BRD4 inhibition with IC50=12 nM [Paper1]. "
            "No major conflicts identified across the 5 papers."
        ),
        conflicts=[],
        papers_cited=["paper1_nvx0228_novel_inhibitor", "paper4_nvx0228_structural_basis"],
        context_expansion_triggered=False,
        trace=[
            TraceStep(
                step="paper_agent_paper1",
                agent="PaperAgent",
                input_summary="query='test'",
                output_summary="2 chunks, 1 claim",
                latency_ms=120.5,
            )
        ],
        timestamp=datetime.utcnow(),
    )


@pytest.fixture
def app_client():
    """
    Create a TestClient with mocked Supabase schema verification and orchestrator.
    This prevents real I/O during API tests.
    """
    # Patch verify_schema to be a no-op
    with patch("src.api.verify_schema", return_value=None), \
         patch("src.db.verify_schema", return_value=None):
        from src.api import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:

    def test_health_endpoint_returns_200(self, app_client):
        """GET /health should return HTTP 200."""
        with patch("src.api.verify_schema", return_value=None), \
             patch("openai.OpenAI") as mock_openai_cls:
            mock_openai_instance = MagicMock()
            mock_openai_instance.models.list.return_value = MagicMock()
            mock_openai_cls.return_value = mock_openai_instance

            response = app_client.get("/health")

        assert response.status_code == 200

    def test_health_endpoint_returns_status_ok(self, app_client):
        """GET /health should return {status: 'ok'}."""
        with patch("src.api.verify_schema", return_value=None), \
             patch("openai.OpenAI") as mock_openai_cls:
            mock_openai_instance = MagicMock()
            mock_openai_instance.models.list.return_value = MagicMock()
            mock_openai_cls.return_value = mock_openai_instance

            response = app_client.get("/health")

        data = response.json()
        assert data["status"] == "ok"
        assert "supabase" in data
        assert "openai" in data


class TestQueryEndpoint:

    def test_query_endpoint_returns_result(self, app_client):
        """POST /query should return a valid QueryResult when orchestrator succeeds."""
        fake_result = _make_query_result("What is the IC50 of NVX-0228?")

        with patch("src.api.run_query", new=AsyncMock(return_value=fake_result)):
            response = app_client.post(
                "/query",
                json={"query": "What is the IC50 of NVX-0228?"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "conflicts" in data
        assert "papers_cited" in data
        assert "trace" in data
        assert data["query"] == "What is the IC50 of NVX-0228?"

    def test_query_endpoint_validates_empty_string(self, app_client):
        """POST /query with empty query string should return 422 Unprocessable Entity."""
        response = app_client.post(
            "/query",
            json={"query": ""},
        )
        assert response.status_code == 422

    def test_query_endpoint_validates_missing_query(self, app_client):
        """POST /query with missing query field should return 422."""
        response = app_client.post(
            "/query",
            json={},
        )
        assert response.status_code == 422

    def test_query_endpoint_returns_answer_field(self, app_client):
        """POST /query response should include a non-empty answer field."""
        fake_result = _make_query_result("Test query")
        with patch("src.api.run_query", new=AsyncMock(return_value=fake_result)):
            response = app_client.post(
                "/query",
                json={"query": "Test query"},
            )

        data = response.json()
        assert len(data["answer"]) > 0

    def test_query_endpoint_propagates_orchestrator_errors(self, app_client):
        """POST /query should return 500 when orchestrator raises an exception."""
        with patch("src.api.run_query", new=AsyncMock(side_effect=RuntimeError("Supabase error"))):
            response = app_client.post(
                "/query",
                json={"query": "What is the IC50?"},
            )

        assert response.status_code == 500


class TestINDTemplateEndpoint:

    def test_ind_template_endpoint_returns_result(self, app_client):
        """POST /ind-template should return a valid QueryResult."""
        fake_result = _make_query_result("IND template query")
        with patch("src.api.run_query", new=AsyncMock(return_value=fake_result)):
            response = app_client.post(
                "/ind-template",
                json={"query": "Generate IND section for NVX-0228"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "answer" in data

    def test_ind_template_validates_empty_query(self, app_client):
        """POST /ind-template with empty query should return 422."""
        response = app_client.post(
            "/ind-template",
            json={"query": ""},
        )
        assert response.status_code == 422


class TestInputValidation:

    def test_query_too_long_returns_422(self, app_client):
        """POST /query with query > 500 chars should return 422 Unprocessable Entity."""
        long_query = "a" * 501
        response = app_client.post("/query", json={"query": long_query})
        assert response.status_code == 422

    def test_query_at_max_length_is_accepted(self, app_client):
        """POST /query with exactly 500-char query should pass validation (not 422)."""
        max_query = "a" * 500
        fake_result = _make_query_result(max_query[:40])
        with patch("src.api.run_query", new=AsyncMock(return_value=fake_result)):
            response = app_client.post("/query", json={"query": max_query})
        assert response.status_code == 200

    def test_ind_template_too_long_returns_422(self, app_client):
        """POST /ind-template with query > 500 chars should return 422."""
        long_query = "x" * 501
        response = app_client.post("/ind-template", json={"query": long_query})
        assert response.status_code == 422


class TestQueriesEndpoint:

    def test_queries_endpoint_returns_list(self, app_client, tmp_path, monkeypatch):
        """GET /queries should return a list of saved output filenames."""
        # Create fake output files in tmp_path
        (tmp_path / "20240101_120000_test_query.json").write_text("{}")
        (tmp_path / "20240102_130000_another_query.json").write_text("{}")

        # Monkeypatch OUTPUTS_DIR to tmp_path
        import src.api as api_module
        import src.config as config_module

        monkeypatch.setattr(api_module, "OUTPUTS_DIR", tmp_path)
        monkeypatch.setattr(config_module, "OUTPUTS_DIR", tmp_path)

        response = app_client.get("/queries")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert "20240101_120000_test_query.json" in data
        assert "20240102_130000_another_query.json" in data

    def test_queries_endpoint_returns_empty_list_when_no_outputs(self, app_client, tmp_path, monkeypatch):
        """GET /queries should return an empty list when no outputs exist."""
        import src.api as api_module

        monkeypatch.setattr(api_module, "OUTPUTS_DIR", tmp_path)

        response = app_client.get("/queries")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert data == []
