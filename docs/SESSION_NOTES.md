# Session Notes — Coincidence Labs Take-Home

## Status: PAUSED

Last session: March 11, 2026
Contact: Yannick Sun — yannick@coincidencelabs.com (awaiting OpenAI API key to run system)

---

## What Was Decided (Architecture)

**Stack:**
- LangGraph StateGraph for agent orchestration (parallel fan-out + conditional edges)
- Multi-agent system: PaperAgents ×5 → ConflictAgent → SynthesisAgent (+ bonus INDTemplateAgent)
- Supabase pgvector as vector store (per-paper filtering via `match_chunks` RPC)
- OpenAI `gpt-4o-mini` (LLM) + `text-embedding-3-small` (embeddings)
- FastAPI backend + Next.js 14 frontend (Next.js not yet built)
- PyTest (backend) + Jest/RTL (frontend)
- Hot/Warm/Cold tiered context management (ContextManager class, compresses every 10 messages)

**Why LangGraph + multi-agent = the same thing:**
LangGraph IS the framework for the multi-agent system. The agents are nodes in the graph. LangGraph handles parallel execution (Send API), state fan-in (Annotated reducers), conditional branching (conflict → expansion), and checkpointing. Using both demonstrates both orchestration framework knowledge and agentic design — not a trade-off.

---

## What Was Built This Session

### ✅ Complete
| File | Description |
|------|-------------|
| `CLAUDE.md` | Full architecture spec, commands, testing strategy, context management rationale |
| `requirements.txt` | All Python dependencies |
| `.env.example` | All required env vars |
| `supabase/config.toml` | Supabase CLI config |
| `supabase/migrations/20240001_enable_pgvector.sql` | pgvector extension |
| `supabase/migrations/20240002_create_chunks_table.sql` | chunks table + indexes |
| `supabase/migrations/20240003_create_match_chunks_fn.sql` | match_chunks RPC |
| `supabase/migrations/20240004_create_paper_summaries.sql` | paper_summaries (WARM tier) |
| `supabase/migrations/20240005_rls_policies.sql` | RLS policies |
| `supabase/seed/seed_papers.py` | Ingests 5 JSONs → embeds → upserts to Supabase |
| `src/__init__.py` | Package init |
| `src/models.py` | All Pydantic models (Chunk, Conflict, QueryResult, etc.) |
| `src/config.py` | Settings + paths |
| `src/db.py` | Supabase singleton + schema verification |
| `src/context_manager.py` | Hot/Warm/Cold tiered context with rolling compression |
| `src/embeddings.py` | Embedding generation + Supabase search |
| `src/agents/__init__.py` | Package init |
| `src/agents/paper_agent.py` | Per-paper retrieval + claim extraction |
| `src/agents/conflict_agent.py` | Conflict detection, classification, context expansion |
| `src/agents/synthesis_agent.py` | Final cited answer generation |
| `src/agents/ind_template_agent.py` | IND Module 2.6.2 section generation (bonus) |
| `src/orchestrator.py` | LangGraph StateGraph — full graph definition |
| `src/api.py` | FastAPI routes (/query, /ind-template, /health, /queries) |
| `main.py` | CLI entrypoint (--query, --run-all, --ind-template, --build) |
| `tests/conftest.py` | Shared fixtures (mock OpenAI, mock Supabase) |
| `tests/test_paper_agent.py` | PaperAgent unit tests |
| `tests/test_conflict_agent.py` | ConflictAgent unit tests (inc. EVOLVING_DATA edge case) |
| `tests/test_synthesis_agent.py` | SynthesisAgent unit tests |
| `tests/test_context_manager.py` | ContextManager compression + tier tests |
| `outputs/.gitkeep` | Tracks outputs directory |

### ✅ Also Confirmed Complete (agent finished after pause)
| File | Description |
|------|-------------|
| `tests/test_api.py` | FastAPI TestClient — 9 test functions |
| `pytest.ini` | Sets `asyncio_mode = auto` for async tests |

### ✅ Frontend Complete
| File | Description |
|------|-------------|
| `frontend/src/components/ConflictBadge.tsx` | 5 types, color-coded with dot + label, data-testid attrs |
| `frontend/src/components/TraceViewer.tsx` | Collapsible, expansion steps orange-highlighted |
| `frontend/src/components/ResultCard.tsx` | [PaperN] as pill badges, conflict list, expansion banner |
| `frontend/src/components/QueryBox.tsx` | 5 exact chips, phase progression (0s/2s/6s), API call |
| `frontend/src/__tests__/*.test.tsx` | 33 total tests (9+7+9+8) |
| `frontend/jest.config.ts` | `setupFilesAfterEnv` — correct key, jsdom, @/ alias |

### ❌ One Thing Remaining
| Item | Priority | Notes |
|------|----------|-------|
| `outputs/` (populated) | **CRITICAL** | Run `py -3 main.py --run-all` + `--ind-template` once API key arrives |

---

## Resume Checklist (Next Session)

### Step 1 — Get OpenAI API key from Yannick
Email yannick@coincidencelabs.com if not received yet.

### Step 2 — Review existing agent code
Before writing new code, read and verify:
- `src/orchestrator.py` — confirm LangGraph graph is wired correctly
- `src/agents/conflict_agent.py` — confirm CONCEPTUAL conflict triggers context expansion
- `src/agents/paper_agent.py` — confirm Supabase RPC call format is correct

### Step 3 — Build frontend
```bash
cd frontend
npx create-next-app@latest . --typescript --tailwind --app --no-git
npm install @testing-library/react @testing-library/jest-dom jest jest-environment-jsdom
```
Then build:
- `QueryBox.tsx` — query input, quick-select chips for 5 test queries, loading states per agent phase
- `ResultCard.tsx` — synthesis answer with inline citations
- `ConflictBadge.tsx` — color-coded: CONCEPTUAL=red, METHODOLOGY=orange, ASSAY_VARIABILITY=yellow, EVOLVING_DATA=blue, NON_CONFLICT=green
- `TraceViewer.tsx` — collapsible accordion per agent step

### Step 4 — Write test_api.py
```bash
py -3 -m pytest tests/test_api.py -v
```
Use FastAPI's `TestClient` from `httpx`.

### Step 5 — Set up Supabase + run migrations
```bash
supabase login
supabase link --project-ref your-project-ref
supabase db push
```

### Step 6 — Ingest papers
```bash
export OPENAI_API_KEY=...
export SUPABASE_URL=...
export SUPABASE_SERVICE_KEY=...
py -3 supabase/seed/seed_papers.py
```

### Step 7 — Run all tests
```bash
py -3 -m pytest tests/ -v --cov=src --cov-report=term-missing
```

### Step 8 — Run all 5 test queries, save outputs
```bash
py -3 main.py --run-all
py -3 main.py --ind-template
```
Check `outputs/` — all 5 JSONs must be present for submission.

### Step 9 — Write README.md
Sections needed:
- Overview + demo screenshot
- Architecture diagram + decisions (why LangGraph, why Supabase, why per-paper retrieval, why no LangChain chains)
- Setup steps (Supabase project → migrations → seed → env → run)
- Example outputs summary
- Trade-offs section
- Context management section (Hot/Warm/Cold + prior art references)

### Step 10 — Final submission
- GitHub repo must be public (or shared with Yannick)
- Include: README, all code, outputs/ folder with pre-run results
- Attach Claude Code session traces/logs (as requested in the email)

---

## Key Conflicts the System Must Detect (from data/conflict_key.json)

| Property | Type | Papers | Difficulty |
|----------|------|--------|------------|
| IC50 (8.5–15.3 nM) | ASSAY_VARIABILITY | 1,2,3,5 | Easy |
| Mechanism of action (competitive vs allosteric) | CONCEPTUAL | 1,4 | Hard ⚠️ |
| Binding pose (acetyl-lysine vs allosteric site 5.2Å away) | CONCEPTUAL | 1,4 | Hard ⚠️ |
| Thrombocytopenia rate (15%→22%→41%) | EVOLVING_DATA | 1,3,5 | Medium |
| BD1/BD2 selectivity (50x vs 85x) | METHODOLOGY | 1,2,4 | Easy |
| Molecular weight (487.3 vs 489.1 — paper3 salt form math wrong) | METHODOLOGY | 3 vs all | Medium |
| Resistance prevalence (64% vs 37.5%) | ASSAY_VARIABILITY | 3,5 | Medium |

The CONCEPTUAL conflicts (mechanism + binding pose) are the critical ones — the system must trigger context expansion on these and the synthesis must explain both positions citing paper4's 1.8Å crystal structure as stronger evidence than paper1's.

---

## About the RAG-Home Assessment Copy Folder

The `RAG-home assement copy 4/` folder in the repo root is the original zip contents from Yannick. Key files:
- `Agentic Document Extraction Results in Chemistry 2025.json` — Coincidence Labs' own pipeline output (dpt-2-20251103). Shows raw extraction format: 138 chunks, markdown content, figure/logo/marginalia types. This is what real paper ingestion looks like before pre-processing. Referenced in README under "Extending to Real Documents."
- `Chemistry 2025.pdf` — Source PDF for above. Real BET inhibitor clinical trials paper (Juan Li et al.). Reference material only, not a 6th paper.
- All other files in the folder are duplicates of existing root files. Can be deleted.

## Agent ID for Background Task (Already Completed)
Background agent `a96151f7d3f56ad90` finished implementing all backend files. No need to resume it.
