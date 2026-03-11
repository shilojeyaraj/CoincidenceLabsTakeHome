"""
Three-tier context manager for the RAG orchestration pipeline.

Tiers:
  hot  — most recent messages (in-memory list)
  warm — compressed LLM-generated summary of older messages
  cold — raw archive of compressed messages (kept for auditability)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import openai
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import HOT_LIMIT, LLM_MODEL, OPENAI_API_KEY

_openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)


@dataclass
class Message:
    """A single message in the context manager."""
    agent: str
    role: str   # 'system' | 'user' | 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_text(self) -> str:
        ts = self.timestamp.strftime("%H:%M:%S")
        return f"[{ts}] ({self.agent}/{self.role}): {self.content}"


class ContextManager:
    """
    Manages three-tier context: hot (recent), warm (compressed), cold (archive).

    When len(hot) >= HOT_LIMIT, the hot messages are compressed into the warm
    summary via an LLM call, and the raw messages are moved to cold.
    """

    def __init__(self) -> None:
        self.hot: list[Message] = []
        self.warm: str = ""
        self.cold: list[Message] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, message: Message) -> None:
        """Add a message to the hot tier, compressing if needed."""
        self.hot.append(message)
        if len(self.hot) >= HOT_LIMIT:
            self._compress()

    def get_context(self) -> str:
        """
        Return a formatted context string with prior summary and recent activity.

        Format:
            [PRIOR SUMMARY]
            <warm summary or empty>

            [RECENT ACTIVITY]
            <last 5 hot messages>
        """
        recent = self.hot[-5:] if len(self.hot) > 5 else self.hot
        recent_text = "\n".join(m.to_text() for m in recent) if recent else "(none)"

        prior = self.warm if self.warm else "(none)"

        return (
            "[PRIOR SUMMARY]\n"
            f"{prior}\n\n"
            "[RECENT ACTIVITY]\n"
            f"{recent_text}"
        )

    def reset(self) -> None:
        """Clear all context tiers (e.g., between independent queries)."""
        self.hot = []
        self.warm = ""
        self.cold = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compress(self) -> None:
        """
        Summarize hot messages into 3-5 bullets, merge into warm, archive to cold.
        """
        if not self.hot:
            return

        # Build text of all hot messages to compress
        messages_text = "\n".join(m.to_text() for m in self.hot)

        prior_context = f"Previous summary:\n{self.warm}\n\n" if self.warm else ""

        summary = self._call_llm_summarize(prior_context + messages_text)

        # Merge new summary into warm
        if self.warm:
            self.warm = f"{self.warm}\n\n{summary}"
        else:
            self.warm = summary

        # Archive hot to cold
        self.cold.extend(self.hot)
        self.hot = []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _call_llm_summarize(self, messages_text: str) -> str:
        """Call the LLM to compress a block of messages into 3-5 bullet points."""
        response = _openai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a context compression assistant. "
                        "Summarize the following agent conversation messages into "
                        "3-5 concise bullet points that capture key findings, "
                        "decisions, and unresolved issues. Be factual and brief."
                    ),
                },
                {
                    "role": "user",
                    "content": messages_text,
                },
            ],
            max_tokens=512,
            temperature=0.1,
        )
        return response.choices[0].message.content.strip()
