"""
Configuration module: loads environment variables and exports constants.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Resolve repo root regardless of CWD
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")

# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
EMBEDDING_MODEL: str = "text-embedding-3-small"
EMBEDDING_DIM: int = 1536
LLM_MODEL: str = "gpt-4o-mini"
LLM_MAX_TOKENS: int = 4096
CLAIM_EXTRACTION_MAX_TOKENS: int = 1500   # Claims JSON is small; cap to reduce TTFT
SYNTHESIS_MAX_TOKENS: int = 2048          # Synthesis answer; longer but bounded
CONFLICT_CLASSIFICATION_MAX_TOKENS: int = 512  # Short JSON classification response
CHUNK_CONTENT_MAX_CHARS: int = 1200       # Truncate chunk content to reduce input tokens

# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY", "")  # anon/publishable key
SUPABASE_SECRET_KEY: str = os.environ.get("SUPABASE_SECRET_KEY", "")    # service_role secret (bypasses RLS)

# ---------------------------------------------------------------------------
# Retrieval / context management
# ---------------------------------------------------------------------------
TOP_K_PER_PAPER: int = 3   # increased from 2 → 3 to improve claim extraction on structural papers
EXPANSION_TOP_K: int = 5   # must exceed TOP_K_PER_PAPER so expansion fetches genuinely new chunks
HOT_LIMIT: int = 10

# ---------------------------------------------------------------------------
# Paper IDs (must match filenames in data/ without .json extension)
# ---------------------------------------------------------------------------
PAPER_IDS: list[str] = [
    "paper1_nvx0228_novel_inhibitor",
    "paper2_nvx0228_pharmacokinetics",
    "paper3_brd4_hematologic_comparative",
    "paper4_nvx0228_structural_basis",
    "paper5_nvx0228_updated_phase1",
]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR: Path = _ROOT / "data"
OUTPUTS_DIR: Path = _ROOT / "outputs"
GENERATION_TEMPLATE_PATH: Path = DATA_DIR / "generation_template.json"

# Ensure outputs directory exists at import time
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
