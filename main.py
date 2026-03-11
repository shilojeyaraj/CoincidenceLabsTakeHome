"""
CLI entry point for the Multi-Document Conflict Resolution RAG system.

Usage:
    python main.py --query "What is the IC50 of NVX-0228?"
    python main.py --run-all
    python main.py --ind-template
    python main.py --build
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Test queries representative of the NVX-0228 research domain
# ---------------------------------------------------------------------------
# Exact queries from the assignment specification
TEST_QUERIES = [
    "What is the IC50 of NVX-0228?",
    "What toxicity was observed with NVX-0228?",
    "What is the mechanism of action of NVX-0228?",
    "What clinical trials have been conducted with NVX-0228?",
    "What resistance mechanisms have been identified?",
]


def print_result(result: object) -> None:
    """Pretty-print a QueryResult to stdout."""
    # Use model_dump_json if available (Pydantic v2), else fallback
    if hasattr(result, "model_dump_json"):
        print(result.model_dump_json(indent=2))
    else:
        print(json.dumps(result.__dict__, indent=2, default=str))


async def run_single(query: str, ind_template: bool = False) -> None:
    """Run a single query and print the result."""
    from src.orchestrator import run_query

    print(f"\n{'='*70}")
    print(f"Query: {query}")
    print(f"{'='*70}\n")

    result = await run_query(query=query, run_ind_template=ind_template)

    print(f"\n--- Answer ---\n{result.answer}\n")
    print(f"--- Conflicts ({len(result.conflicts)}) ---")
    for conflict in result.conflicts:
        print(
            f"  [{conflict.conflict_type.value}] {conflict.property}: "
            f"{conflict.reasoning[:120]}..."
        )

    print(f"\n--- Papers Cited ---")
    for paper_id in result.papers_cited:
        print(f"  {paper_id}")

    print(f"\n--- Context Expansion Triggered: {result.context_expansion_triggered} ---")
    print(f"--- Trace ({len(result.trace)} steps) ---")
    for step in result.trace:
        print(
            f"  [{step.agent}] {step.step}: {step.output_summary} "
            f"({step.latency_ms:.0f}ms)"
        )


async def run_all(ind_template: bool = False) -> None:
    """Run all 5 test queries."""
    for query in TEST_QUERIES:
        await run_single(query, ind_template=ind_template)


def run_build() -> None:
    """Run the paper ingestion pipeline."""
    seed_path = (
        Path(__file__).parent / "supabase" / "seed" / "seed_papers.py"
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location("seed_papers", seed_path)
    if spec is None or spec.loader is None:
        print(f"Could not load seed script from {seed_path}", file=sys.stderr)
        sys.exit(1)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    module.main()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-Document Conflict Resolution RAG — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--query",
        type=str,
        help="Run a single research query.",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Run all 5 predefined test queries.",
    )
    parser.add_argument(
        "--ind-template",
        action="store_true",
        help="Include IND template generation (use with --query or --run-all).",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Run the paper ingestion / seeding pipeline.",
    )

    args = parser.parse_args()

    if args.build:
        run_build()
    elif args.query:
        asyncio.run(run_single(args.query, ind_template=args.ind_template))
    elif args.run_all:
        asyncio.run(run_all(ind_template=args.ind_template))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
