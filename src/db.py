"""
Supabase client singleton and schema verification utilities.
"""
from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from src.config import SUPABASE_SERVICE_KEY, SUPABASE_URL


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Return a cached Supabase service-role client."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in your environment. "
            "Copy .env.example to .env and fill in your credentials."
        )
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def verify_schema() -> None:
    """
    Confirm that both required tables exist and are accessible.

    Raises RuntimeError with a descriptive message if either table is missing
    or the connection fails.
    """
    client = get_client()

    required_tables = ["chunks", "paper_summaries"]
    for table in required_tables:
        try:
            # A lightweight query — we only care that the table exists
            response = client.table(table).select("*").limit(1).execute()
            # supabase-py raises an exception on HTTP errors; if we get here the
            # table exists.
        except Exception as exc:
            raise RuntimeError(
                f"Schema verification failed: table '{table}' is inaccessible. "
                f"Have you run the Supabase migrations? Error: {exc}\n\n"
                "Run: supabase db push  (or apply migrations manually)"
            ) from exc
