"""
Seed script: reads all 5 paper JSONs from data/, generates embeddings,
upserts chunks and paper summaries into Supabase.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm
from tenacity import retry, stop_after_attempt, wait_exponential

# Allow running from repo root or from this directory
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

import openai
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
# Use service_role secret key to bypass RLS for writes
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SECRET_KEY") or os.environ["SUPABASE_SERVICE_KEY"]

EMBEDDING_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4o-mini"
DATA_DIR = ROOT / "data"
PAPER_IDS = [
    "paper1_nvx0228_novel_inhibitor",
    "paper2_nvx0228_pharmacokinetics",
    "paper3_brd4_hematologic_comparative",
    "paper4_nvx0228_structural_basis",
    "paper5_nvx0228_updated_phase1",
]

openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)


# ---------------------------------------------------------------------------
# Retry-wrapped OpenAI helpers
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts (up to 100) via OpenAI."""
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_warm_summary(paper_json: dict) -> str:
    """Generate a WARM context summary for a paper using GPT-4o-mini."""
    metadata = paper_json.get("metadata", {})
    chunks = paper_json.get("chunks", [])

    # Build a condensed view of key chunks (first 6) for the prompt
    chunk_texts = "\n\n---\n\n".join(
        f"[{c.get('section', 'Unknown')}] {c.get('content', '')[:500]}"
        for c in chunks[:6]
    )

    system_msg = (
        "You are a pharmaceutical research summarizer. "
        "Produce a concise 3-5 paragraph WARM context summary of this paper "
        "suitable for retrieval-augmented generation. "
        "Emphasize: key claims, IC50/EC50 values, toxicity profile, mechanism of action, "
        "clinical trial phase and NCT number (if any), sample size, and primary conclusions. "
        "Be factual and quantitative."
    )
    user_msg = (
        f"Paper title: {metadata.get('title', 'Unknown')}\n"
        f"Authors: {', '.join(metadata.get('authors', []))}\n"
        f"Journal: {metadata.get('journal', 'Unknown')}\n"
        f"Publication date: {metadata.get('publication_date', 'Unknown')}\n"
        f"Sample size: {metadata.get('sample_size', 'Unknown')}\n\n"
        f"Selected content:\n{chunk_texts}"
    )

    response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=1024,
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Seeding logic
# ---------------------------------------------------------------------------

def seed_paper(paper_id: str, supabase: Client) -> None:
    """Ingest one paper: embed chunks, upsert chunks, generate and upsert summary."""
    json_path = DATA_DIR / f"{paper_id}.json"
    if not json_path.exists():
        print(f"  [SKIP] {json_path} not found")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        paper_json = json.load(f)

    metadata = paper_json.get("metadata", {})
    chunks = paper_json.get("chunks", [])

    print(f"\n=== Processing {paper_id} ({len(chunks)} chunks) ===")

    # --- Step 1: Generate embeddings in batches of 100 ---
    texts = [c.get("content", "") for c in chunks]
    embeddings: list[list[float]] = []

    batch_size = 100
    for i in tqdm(range(0, len(texts), batch_size), desc="  Embedding batches"):
        batch = texts[i : i + batch_size]
        batch_embeddings = embed_texts(batch)
        embeddings.extend(batch_embeddings)

    # --- Step 2: Upsert chunks ---
    rows = []
    for chunk, embedding in zip(chunks, embeddings):
        rows.append(
            {
                "id": chunk["id"],
                "paper_id": paper_id,
                "chunk_type": chunk.get("type", "text"),
                "content": chunk.get("content", ""),
                "section": chunk.get("section"),
                "page": chunk.get("page"),
                "grounding": chunk.get("grounding"),
                "embedding": embedding,
            }
        )

    print(f"  Upserting {len(rows)} chunks...")
    for i in tqdm(range(0, len(rows), 50), desc="  Upserting chunks"):
        batch = rows[i : i + 50]
        supabase.table("chunks").upsert(batch).execute()

    # --- Step 3: Generate WARM summary ---
    print("  Generating WARM summary...")
    summary = generate_warm_summary(paper_json)

    # --- Step 4: Upsert paper_summary ---
    summary_row = {
        "paper_id": paper_id,
        "title": metadata.get("title"),
        "authors": metadata.get("authors", []),
        "publication_date": metadata.get("publication_date"),
        "journal": metadata.get("journal"),
        "sample_size": metadata.get("sample_size"),
        "page_count": metadata.get("page_count"),
        "summary": summary,
    }
    supabase.table("paper_summaries").upsert(summary_row).execute()
    print(f"  Done with {paper_id}")


def main() -> None:
    print("Connecting to Supabase...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    for paper_id in tqdm(PAPER_IDS, desc="Papers"):
        seed_paper(paper_id, supabase)

    print("\nSeeding complete!")


if __name__ == "__main__":
    main()
