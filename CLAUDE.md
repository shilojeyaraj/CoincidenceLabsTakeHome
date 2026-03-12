# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Multi-Document Conflict Resolution RAG system — Coincidence Labs take-home assignment. The system answers questions about NVX-0228 (a fictional BRD4 inhibitor) by orchestrating multiple agents across 5 conflicting research papers. Full requirements: `docs/assignment.md`.

---

## Commands

### Backend (Python / FastAPI)
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables (copy .env.example → .env and fill in)
export OPENAI_API_KEY=your_key_here
export SUPABASE_URL=https://your-project.supabase.co
export SUPABASE_SERVICE_KEY=your_service_role_key

# Run Supabase migrations (must have Supabase CLI installed)
supabase db push
# or apply individually:
supabase migration up

# Ingest papers → generates embeddings and upserts into Supabase pgvector
py -3 -m src.embeddings --ingest

# Start FastAPI server
py -3 -m uvicorn src.api:app --reload --port 8000

# Run a single query (CLI mode)
py -3 main.py --query "What is the IC50 of NVX-0228?"

# Run all 5 test queries, save to outputs/
py -3 main.py --run-all

# Run bonus IND template generation
py -3 main.py --query "What is the mechanism of action of NVX-0228?" --ind-template
py -3 main.py --run-all --ind-template
```

### Frontend (Next.js) — Preview the UI
```bash
cd frontend
npm install        # first time only — installs node_modules
npm run dev        # starts dev server → open http://localhost:3000
npm run build      # production build
npm run test       # Jest unit + component tests
npm run test:watch # watch mode
```

### Testing
```bash
# Backend unit tests
py -3 -m pytest tests/ -v

# Backend with coverage
py -3 -m pytest tests/ --cov=src --cov-report=term-missing

# Run a single test file
py -3 -m pytest tests/test_conflict_agent.py -v

# Frontend tests
cd frontend && npm test -- --watchAll=false
```

> On Windows use `py -3` instead of `python3`. Use `pathlib.Path` in all file I/O — never hardcode slashes.

---

## Architecture

### System Overview

```
User Query
    │
    ▼
Orchestrator (src/orchestrator.py)
    │
    ├── [PARALLEL] PaperAgent × 5  ──── each searches its own FAISS index
    │         returns: RetrievedChunk list + extracted claims per paper
    │
    ▼
ConflictAgent (sequential — needs all 5 PaperAgent outputs)
    │   classifies: ASSAY_VARIABILITY | METHODOLOGY | CONCEPTUAL | EVOLVING_DATA | NON_CONFLICT
    │   if CONCEPTUAL conflict → triggers context expansion:
    │       └── re-queries relevant PaperAgents for 2 more chunks each
    │
    ▼
SynthesisAgent (sequential — needs conflict report)
    │   produces: cited answer + conflict resolutions + trace log
    │
    ▼  [BONUS]
INDTemplateSectionAgent × 7 sections  ──── run in parallel
    │   fills generation_template.json, marks [INSUFFICIENT DATA] where needed
    │
    ▼
Output saved to outputs/{query_slug}.json
```

### Backend File Structure
```
src/
  orchestrator.py          # Top-level coordinator; owns ThreadPoolExecutor for parallel PaperAgents
  agents/
    paper_agent.py         # One instance per paper; Supabase vector search + claim extraction
    conflict_agent.py      # Conflict detection, classification, context expansion trigger
    synthesis_agent.py     # Final cited answer with conflict resolution reasoning
    ind_template_agent.py  # Bonus: fills one IND section per invocation
  context_manager.py       # Hot/warm/cold tiered context (see below)
  embeddings.py            # Generate embeddings + upsert to Supabase; query via match_chunks RPC
  models.py                # Pydantic schemas: Chunk, RetrievedChunk, Conflict, QueryResult
  config.py                # Model names, top-k, compression thresholds, Supabase settings
  api.py                   # FastAPI routes: POST /query, POST /ind-template, GET /health
  db.py                    # Supabase client singleton (uses SUPABASE_URL + SUPABASE_SERVICE_KEY)
supabase/
  migrations/
    20240001_create_chunks_table.sql     # chunks table with paper_id, section, content, metadata
    20240002_enable_pgvector.sql         # CREATE EXTENSION vector; ivfflat index on embedding col
    20240003_create_match_chunks_fn.sql  # match_chunks(query_embedding, paper_id, match_count) RPC
    20240004_create_paper_summaries.sql  # paper_summaries table for WARM context tier
    20240005_rls_policies.sql            # Row Level Security policies for service role access
  seed/
    seed_papers.py                       # Reads data/paper*.json, embeds, upserts into Supabase
  config.toml                            # Supabase CLI project config
tests/
  test_paper_agent.py
  test_conflict_agent.py
  test_synthesis_agent.py
  test_context_manager.py
  test_embeddings.py       # Supabase upsert + match_chunks RPC (uses test schema or mocks)
  test_api.py              # FastAPI TestClient integration tests
  conftest.py              # Shared fixtures: mock Supabase client, mock OpenAI
frontend/
  src/
    components/
      QueryBox.tsx
      ResultCard.tsx
      ConflictBadge.tsx
      TraceViewer.tsx
    __tests__/
      QueryBox.test.tsx
      ResultCard.test.tsx
      ConflictBadge.test.tsx
  jest.config.ts
  tsconfig.json
main.py                    # CLI entrypoint
outputs/                   # Saved example outputs (JSON) for submission
.env.example               # Template: OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
```

---

## Context Management — Hot / Warm / Cold Tiers

This is the core architectural decision. Inspired by production agentic systems:

| Tier | Content | Storage | Analogy |
|------|---------|---------|---------|
| **HOT** | Active chunks + current agent messages | In LLM context window | CPU cache |
| **WARM** | Rolling summary (compressed every 10 messages) | In-memory string | RAM |
| **COLD** | Full message history, all chunks | Disk (`data/indexes/`, `outputs/`) | Disk |

### How It Works

```python
class ContextManager:
    HOT_LIMIT = 10  # messages before compression

    def add(self, message):
        self.hot.append(message)
        if len(self.hot) >= self.HOT_LIMIT:
            self._compress()  # LLM call → 3-5 bullet summary → merge into warm

    def get_context(self) -> str:
        return f"[SUMMARY]\n{self.warm}\n\n[RECENT]\n{format(self.hot)}"
```

- **PaperAgents**: HOT = 2–3 Supabase `match_chunks` RPC results; WARM = pre-built paper summary stored in `paper_summaries` table (generated at ingest time, reused across queries); COLD = full chunk rows in Supabase, fetched on demand
- **Orchestrator**: Rolling compression every 10 agent messages across the session
- **IND Template**: Each section agent receives WARM (global synthesis summary) not the full HOT history

### Prior Art This Pattern Draws From

- **Letta (MemGPT)**: In-context blocks (hot) + recall storage (warm/vector) + archival storage (cold). Agent self-manages via explicit function calls — source: [MemGPT paper](https://arxiv.org/pdf/2310.08560)
- **Mem0**: Two-phase extract → update pipeline with LLM-decided ADD/UPDATE/DELETE/MERGE operations. Achieved 91% p95 latency reduction by keeping only ~7K tokens vs competitors' full context
- **AutoGen**: `MessageHistoryLimiter` + `TextMessageCompressor` (LLMLingua). Triggers at token threshold — reduced 4,019 tokens to 215 in practice
- **CrewAI**: Composite scoring on recall (semantic similarity + recency + importance weighting); non-blocking saves; adaptive depth (shallow vs deep recall)
- **LangGraph**: Checkpoint-per-step for fault tolerance with Redis-backed short-term (thread) and long-term (cross-thread vector) stores — sub-millisecond read/write
- **Cognition (Devin)**: "Context Engineering" — dynamically manages exactly what the agent sees at every step; includes machine snapshots and playbooks for conventions

---

## Testing Strategy

### Backend (PyTest)

| Test File | What It Covers |
|-----------|---------------|
| `test_paper_agent.py` | Supabase `match_chunks` RPC returns chunks from correct paper, top-k behavior |
| `test_conflict_agent.py` | Known conflicts in `conflict_key.json` are detected and correctly classified |
| `test_synthesis_agent.py` | Output cites multiple papers, flags conflicts, never silent-winner |
| `test_context_manager.py` | Compression triggers at HOT_LIMIT, warm summary accumulates correctly |
| `test_api.py` | FastAPI TestClient: POST /query returns expected schema, 422 on bad input |

Tests use `pytest-mock` for LLM calls — never hit the real API in unit tests.

### Frontend (Jest + React Testing Library)

| Test File | What It Covers |
|-----------|---------------|
| `QueryBox.test.tsx` | Submit fires correct API call, loading state shown |
| `ResultCard.test.tsx` | Conflicts render `ConflictBadge`, citations render inline |
| `ConflictBadge.test.tsx` | Color/label maps correctly to conflict type enum |
| `TraceViewer.test.tsx` | Trace steps expand/collapse correctly |

---

## Data

- `data/paper1-5_*.json` — Pre-parsed papers. Schema: `metadata` (title, authors, date, journal, sample_size) + `chunks` (id, type, content, section, page, grounding box)
- `data/conflict_key.json` — Ground truth conflicts for evaluators. **Not used at runtime.** Used in `test_conflict_agent.py` to validate detection accuracy.
- `data/generation_template.json` — IND Module 2.6.2 template (bonus task). 7 sections, some with subsections.
- `supabase/migrations/` — SQL migrations for pgvector setup, chunks table, match_chunks RPC, paper_summaries, and RLS policies. Run via `supabase db push` or `supabase migration up`.

## Key Conflicts in the Data (from conflict_key.json)

| Property | Difficulty | Type |
|----------|------------|------|
| IC50 (8.5–15.3 nM across 4 papers) | Easy | ASSAY_VARIABILITY |
| Mechanism of action (competitive vs allosteric) | Hard | CONCEPTUAL |
| Binding pose (acetyl-lysine pocket vs allosteric site 5.2Å away) | Hard | CONCEPTUAL |
| Thrombocytopenia rate (15%→22%→41%) | Medium | EVOLVING_DATA |
| BD1/BD2 selectivity ratio (50x vs 85x) | Easy | METHODOLOGY |
| Molecular weight (487.3 free base vs 489.1 — paper3's salt form math is wrong) | Medium | METHODOLOGY |
| Resistance mechanism prevalence (64% vs 37.5%) | Medium | ASSAY_VARIABILITY |

The CONCEPTUAL conflicts (mechanism + binding pose) are the critical ones — the system must treat these differently from numerical variation.

---

## Models and Tooling

- **Embeddings**: OpenAI `text-embedding-3-small` (1536-dim)
- **LLM**: `gpt-4o-mini` for all agent calls
- **Vector store**: Supabase pgvector — `chunks` table with `embedding vector(1536)`, ivfflat index, per-paper filtering via `match_chunks(query_embedding, paper_id, match_count)` RPC
- **Supabase client**: `supabase-py` — singleton in `src/db.py`, initialized from env vars
- **API**: FastAPI + uvicorn
- **Frontend**: Next.js 14 (App Router) + TypeScript + Tailwind
- **Backend tests**: pytest + pytest-mock + pytest-cov
- **Frontend tests**: Jest + React Testing Library

### Supabase Schema Notes

The `match_chunks` RPC filters by `paper_id` before doing vector similarity search — this is the Supabase equivalent of the per-paper index strategy. Each paper's chunks are tagged with their `paper_id` so retrieval can be scoped per paper, guaranteeing all 5 papers are represented regardless of which paper has the highest cosine similarity globally.

The `paper_summaries` table holds the WARM context tier — one row per paper with a pre-generated LLM summary, populated at ingest time by `supabase/seed/seed_papers.py`.
