"""
Tests for the three-tier ContextManager.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.config import HOT_LIMIT
from src.context_manager import ContextManager, Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(agent: str = "PaperAgent", content: str = "test content") -> Message:
    return Message(agent=agent, role="assistant", content=content)


def _mock_llm_compress(summary: str = "• Bullet 1\n• Bullet 2\n• Bullet 3") -> MagicMock:
    mock_client = MagicMock()
    choice = MagicMock()
    choice.message.content = summary
    resp = MagicMock()
    resp.choices = [choice]
    mock_client.chat.completions.create.return_value = resp
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestContextManager:

    def test_compression_triggers_at_hot_limit(self):
        """Adding HOT_LIMIT messages should trigger compression: warm non-empty, hot empty."""
        mock_llm = _mock_llm_compress("• Bullet 1\n• Bullet 2\n• Bullet 3")

        with patch("src.context_manager._openai_client", mock_llm):
            cm = ContextManager()
            for i in range(HOT_LIMIT):
                cm.add(_make_message(content=f"Message {i}"))

        # After compression: warm should have content, hot should be cleared
        assert cm.warm != "", "Warm tier should have a summary after compression"
        assert len(cm.hot) == 0, "Hot tier should be empty after compression"
        assert len(cm.cold) == HOT_LIMIT, "Cold tier should contain the archived messages"

    def test_warm_summary_accumulates_across_cycles(self):
        """Two compression cycles should accumulate content in warm tier."""
        summaries = [
            "• Cycle 1 bullet 1\n• Cycle 1 bullet 2",
            "• Cycle 2 bullet 1\n• Cycle 2 bullet 2",
        ]
        call_count = {"n": 0}

        def side_effect(**kwargs):
            idx = call_count["n"] % len(summaries)
            call_count["n"] += 1
            choice = MagicMock()
            choice.message.content = summaries[idx]
            resp = MagicMock()
            resp.choices = [choice]
            return resp

        mock_llm = MagicMock()
        mock_llm.chat.completions.create.side_effect = side_effect

        with patch("src.context_manager._openai_client", mock_llm):
            cm = ContextManager()

            # First cycle
            for i in range(HOT_LIMIT):
                cm.add(_make_message(content=f"Cycle1 Message {i}"))

            warm_after_first = cm.warm

            # Second cycle
            for i in range(HOT_LIMIT):
                cm.add(_make_message(content=f"Cycle2 Message {i}"))

            warm_after_second = cm.warm

        # Both cycle summaries should appear in warm
        assert "Cycle 1" in warm_after_second or summaries[0] in warm_after_second, (
            "First cycle summary should be retained in warm tier"
        )
        assert "Cycle 2" in warm_after_second or summaries[1] in warm_after_second, (
            "Second cycle summary should be present in warm tier"
        )
        # Warm should grow (or at least not shrink) across cycles
        assert len(warm_after_second) >= len(warm_after_first)

    def test_get_context_format(self):
        """get_context() should include [PRIOR SUMMARY] and [RECENT ACTIVITY] sections."""
        mock_llm = _mock_llm_compress("• Summary bullet")

        with patch("src.context_manager._openai_client", mock_llm):
            cm = ContextManager()

            # Add some messages to hot (below compression threshold)
            for i in range(3):
                cm.add(_make_message(content=f"Recent message {i}"))

            context = cm.get_context()

        assert "[PRIOR SUMMARY]" in context, "Context must contain [PRIOR SUMMARY] section"
        assert "[RECENT ACTIVITY]" in context, "Context must contain [RECENT ACTIVITY] section"

    def test_get_context_format_after_compression(self):
        """After compression, get_context should have both prior summary and recent activity."""
        mock_llm = _mock_llm_compress("• Prior summary bullet")

        with patch("src.context_manager._openai_client", mock_llm):
            cm = ContextManager()

            # Trigger compression
            for i in range(HOT_LIMIT):
                cm.add(_make_message(content=f"Old message {i}"))

            # Add new hot messages
            cm.add(_make_message(content="New message 1"))
            cm.add(_make_message(content="New message 2"))

            context = cm.get_context()

        assert "[PRIOR SUMMARY]" in context
        assert "[RECENT ACTIVITY]" in context
        # Prior summary should appear
        assert "Prior summary bullet" in context or "•" in context
        # Recent messages should appear
        assert "New message" in context

    def test_reset_clears_all_tiers(self):
        """After reset(), all three tiers should be empty."""
        mock_llm = _mock_llm_compress("• Summary")

        with patch("src.context_manager._openai_client", mock_llm):
            cm = ContextManager()

            # Populate all tiers
            for i in range(HOT_LIMIT):
                cm.add(_make_message(content=f"Message {i}"))

            # Add more hot messages
            cm.add(_make_message(content="Post-compression message"))

            # Verify tiers are populated
            assert len(cm.cold) > 0
            assert cm.warm != ""

            # Reset
            cm.reset()

        assert cm.hot == [], "Hot tier should be empty after reset"
        assert cm.warm == "", "Warm tier should be empty after reset"
        assert cm.cold == [], "Cold tier should be empty after reset"

    def test_add_message_under_limit_does_not_compress(self):
        """Adding fewer than HOT_LIMIT messages should NOT trigger compression."""
        mock_llm = MagicMock()

        with patch("src.context_manager._openai_client", mock_llm):
            cm = ContextManager()
            for i in range(HOT_LIMIT - 1):
                cm.add(_make_message(content=f"Message {i}"))

        # LLM should NOT have been called for compression
        mock_llm.chat.completions.create.assert_not_called()
        assert len(cm.hot) == HOT_LIMIT - 1
        assert cm.warm == ""
        assert cm.cold == []

    def test_get_context_shows_last_5_hot_messages(self):
        """get_context() should show at most the last 5 hot messages."""
        mock_llm = MagicMock()

        with patch("src.context_manager._openai_client", mock_llm):
            cm = ContextManager()
            # Add 7 messages (below HOT_LIMIT to avoid compression)
            # HOT_LIMIT is 10, so 7 is safe
            n_messages = min(7, HOT_LIMIT - 1)
            for i in range(n_messages):
                cm.add(_make_message(content=f"Message number {i}"))

            context = cm.get_context()

        # Only last 5 should appear in [RECENT ACTIVITY]
        recent_section = context.split("[RECENT ACTIVITY]")[-1]
        # Messages 2-6 (last 5 of 7) should appear
        if n_messages > 5:
            assert "Message number 2" in recent_section or f"Message number {n_messages - 5}" in recent_section
            # First message should NOT appear
            assert "Message number 0" not in recent_section
