# Project Memory — CoincidenceLabsTakeHome

## What This Is
Take-home for Coincidence Labs (ML/AI developer role, contact: Yannick Sun yannick@coincidencelabs.com).
Multi-Document Conflict Resolution RAG system for 5 papers about NVX-0228 (fictional BRD4 inhibitor).
OpenAI API key to be provided by Yannick when ready to start.

## Architecture Decisions (Final)
- Multi-agent: PaperAgents × 5 (parallel) → ConflictAgent → SynthesisAgent (sequential)
- ConflictAgent triggers context expansion on CONCEPTUAL conflicts → re-queries PaperAgents
- Bonus: INDTemplateSectionAgent × 7 sections (parallel)
- Vector store: Supabase pgvector — user is very familiar with Supabase. Per-paper filtering via match_chunks(query_embedding, paper_id, match_count) RPC (equivalent to per-paper FAISS indexes)
- LLM: gpt-4o-mini, Embeddings: text-embedding-3-small
- Context: Hot/Warm/Cold tiers with rolling compression every 10 messages (ContextManager class)
- Backend: FastAPI, Frontend: Next.js 14 + TypeScript
- Tests: PyTest (backend) + Jest + React Testing Library (frontend)

## Key Design Rationale
- Supabase match_chunks RPC filters by paper_id before vector similarity — guarantees multi-paper coverage (prevents cosine dominance by one paper)
- ALWAYS create supabase/migrations/ folder with all necessary SQL migration files when building
- Conflict types: ASSAY_VARIABILITY | METHODOLOGY | CONCEPTUAL | EVOLVING_DATA | NON_CONFLICT
- Only CONCEPTUAL conflicts trigger adaptive context expansion (showing conflict changes system behavior)
- Hot/Warm/Cold inspired by: Letta (MemGPT), Mem0, AutoGen, CrewAI, LangGraph

## Critical Conflicts to Detect
- IC50: 8.5–15.3 nM (assay variability, easy)
- Mechanism: competitive vs allosteric (CONCEPTUAL, hard — must detect)
- Binding pose: acetyl-lysine pocket vs 5.2Å away (CONCEPTUAL, hard)
- Thrombocytopenia: 15%→22%→41% (evolving data across trial timepoints)
- MW: 489.1 in paper3 vs 487.3 elsewhere (paper3's salt form math is wrong — subtle)

## Windows Environment
- Use `py -3` not `python3`
- Use `pathlib.Path` for all file I/O
- FAISS indexes stored in `data/indexes/`
- Outputs saved to `outputs/`

## Files
- `takehome_agentic_document_rag.md` — full assignment spec
- `data/paper1-5_*.json` — 5 papers, ~8 chunks each
- `data/conflict_key.json` — ground truth conflicts (evaluator reference, used in tests)
- `data/generation_template.json` — IND Module 2.6.2 (bonus task)
- `CLAUDE.md` — full architecture spec with commands and testing strategy
