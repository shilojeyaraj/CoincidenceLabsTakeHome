"""
Embedding generation and vector search utilities.
"""
from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from pathlib import Path

import openai
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import (
    EMBEDDING_MODEL,
    OPENAI_API_KEY,
    TOP_K_PER_PAPER,
)
from src.db import get_client

_openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_embedding(text: str) -> list[float]:
    """Generate a single embedding via OpenAI text-embedding-3-small."""
    response = _openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding


@lru_cache(maxsize=256)
def generate_embedding_cached(text: str) -> tuple[float, ...]:
    """
    Cached variant of generate_embedding.

    Returns a tuple (hashable) so lru_cache can key on it. All 5 PaperAgent
    nodes embed the same query; this collapses 5 API calls into 1 per unique
    query string. Callers should cast back to list[float] if needed.
    """
    return tuple(generate_embedding(text))


def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of texts, processing up to 100 per API call.
    """
    results: list[list[float]] = []
    batch_size = 100

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_embeddings = _embed_batch(batch)
        results.extend(batch_embeddings)

    return results


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Retry-wrapped single API call for a batch of texts."""
    response = _openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    # Sort by index to maintain order (OpenAI may reorder internally)
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


# ---------------------------------------------------------------------------
# Vector search via Supabase RPC
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
def search_paper(
    query_embedding: list[float],
    paper_id: str,
    match_count: int = TOP_K_PER_PAPER,
) -> list[dict]:
    """
    Search for similar chunks in a specific paper using the match_chunks RPC.

    Returns a list of dicts with keys:
        id, paper_id, chunk_type, content, section, page, grounding, similarity

    Retry-wrapped to handle transient Supabase connection resets under concurrent load.
    """
    client = get_client()
    response = client.rpc(
        "match_chunks",
        {
            "query_embedding": query_embedding,
            "filter_paper_id": paper_id,
            "match_count": match_count,
        },
    ).execute()
    return response.data or []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embedding utilities for the RAG system."
    )
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Run the full paper ingestion / seeding pipeline.",
    )
    args = parser.parse_args()

    if args.ingest:
        # Import seed script dynamically so this module stays lightweight
        seed_path = Path(__file__).parent.parent / "supabase" / "seed" / "seed_papers.py"
        import importlib.util

        spec = importlib.util.spec_from_file_location("seed_papers", seed_path)
        if spec is None or spec.loader is None:
            print(f"Could not load seed script from {seed_path}", file=sys.stderr)
            sys.exit(1)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        module.main()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
