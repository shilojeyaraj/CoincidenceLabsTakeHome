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

# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY", "")

# ---------------------------------------------------------------------------
# Retrieval / context management
# ---------------------------------------------------------------------------
TOP_K_PER_PAPER: int = 2
EXPANSION_TOP_K: int = 2
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
