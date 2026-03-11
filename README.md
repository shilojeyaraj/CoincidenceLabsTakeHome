# Multi-Document Conflict Resolution RAG System
### NVX-0228 BRD4 Inhibitor Research Synthesizer

A production-quality agentic RAG system that answers questions about NVX-0228 by reasoning across 5 conflicting research papers. When papers disagree, the system surfaces the conflict, classifies it, and resolves it — rather than silently picking a winner.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Agentic Design](#agentic-design)
3. [Context Management](#context-management)
4. [Conflict Handling](#conflict-handling)
5. [Tech Stack & Trade-offs](#tech-stack--trade-offs)
6. [Setup & Running](#setup--running)
7. [Testing](#testing)
8. [Example Outputs](#example-outputs)
9. [Bonus: IND Template Generation](#bonus-ind-template-generation)

---

## System Architecture

```
User Query
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  LangGraph StateGraph Orchestrator                   │
│                                                      │
│  START ──► route_to_papers ──────────────────────►  │
│                │                                     │
│     ┌──────────┼──────────┐                          │
│     ▼          ▼          ▼  (parallel via Send API) │
│  Paper 1    Paper 2  ... Paper 5                     │
│  Agent      Agent        Agent                       │
│     └──────────┼──────────┘                          │
│                │  fan-in (operator.add reducer)       │
│                ▼                                     │
│         ConflictAgent                               │
│          │         │                                 │
│      if CONCEPTUAL  │                               │
│          │         │                                 │
│    context expansion  │                             │
│    (Supabase fetch)  │                             │
│          │         │                                 │
│          └────►  SynthesisAgent                     │
│                      │                              │
│            [optional fan-out]                       │
│                      │                              │
│     INDSection ×7  (parallel)                       │
│                      │                              │
│                    END                              │
└─────────────────────────────────────────────────────┘
```

The graph state uses `Annotated[list, operator.add]` reducers for `paper_results`, `trace`, and `ind_results` — this is what enables the parallel fan-in: each `paper_node` appends its result to the shared list, and LangGraph merges them automatically when all parallel nodes complete.

---

## Agentic Design

### Why Multi-Agent + LangGraph

LangGraph implements the multi-agent system — they are not competing choices. The agents are nodes in the graph; LangGraph provides the orchestration layer (parallel execution, state management, conditional branching, checkpointing). Using both demonstrates both agentic design and production framework knowledge.

### Agent Roles

#### PaperAgent (×5, parallel)
**File:** `src/agents/paper_agent.py`

Each PaperAgent is responsible for exactly one paper. It:
1. Fetches the paper's pre-built **WARM summary** from Supabase (`paper_summaries` table)
2. Embeds the query via `text-embedding-3-small`
3. Calls the `match_chunks` RPC with its own `paper_id` filter — returning only chunks from its paper
4. Runs an LLM call to extract structured claims (property, value, context, confidence) from the retrieved chunks

The 5 agents run **in parallel** via LangGraph's `Send` API. Each receives only its own paper ID and the query; all 5 start simultaneously and the graph waits for all to complete before moving to ConflictAgent.

**Key design:** Per-paper retrieval rather than global top-k. If all 5 papers discuss IC50, a global search might return all 5 chunks from the most similar paper. Per-paper retrieval guarantees that each paper contributes evidence regardless of relative cosine similarity.

#### ConflictAgent (sequential)
**File:** `src/agents/conflict_agent.py`

Receives all 5 PaperResults, groups claims by property across papers, and for each multi-paper property runs an LLM call to classify the conflict:

| Type | Definition |
|------|-----------|
| `ASSAY_VARIABILITY` | Same target, different assay formats (AlphaScreen vs TR-FRET vs ITC) |
| `METHODOLOGY` | Different protocols, populations, or animal models |
| `CONCEPTUAL` | Fundamentally different mechanistic interpretations — cannot both be correct |
| `EVOLVING_DATA` | Same clinical trial (same NCT number) at different timepoints — not a true conflict |
| `NON_CONFLICT` | Values are consistent within expected variation |

The LLM is given paper metadata (NCT numbers, publication dates, sample sizes via warm summaries) to distinguish `EVOLVING_DATA` from genuine conflicts — the hardest classification problem in this dataset (paper1 and paper5 both report from NCT05123456 at different data cuts).

**Context Expansion:** When a `CONCEPTUAL` conflict is detected, ConflictAgent immediately fetches `EXPANSION_TOP_K` additional chunks from each conflicting paper via Supabase, deduplicates against already-retrieved chunks, and adds them to the graph state. This is the behavior change the assignment requires: *a conflict discovery changes what the system does next.*

#### SynthesisAgent (sequential)
**File:** `src/agents/synthesis_agent.py`

Receives all paper results (including expansion chunks) and the full conflict report. Produces a final answer that:
- Cites sources inline as `[Paper1]`–`[Paper5]`
- Addresses every conflict explicitly with resolution reasoning
- Never silently picks a winner
- For CONCEPTUAL conflicts (mechanism of action): explains both positions and notes which has stronger evidence (paper4's 1.8Å crystal structure > paper1's limited co-crystallography)

#### INDTemplateAgent (×7 sections, parallel) — Bonus
**File:** `src/agents/ind_template_agent.py`

Fills each section of the IND Module 2.6.2 template in parallel. Each section agent receives the synthesis output plus full paper results and produces formal regulatory-language content with inline `[N]` citations. Sections with insufficient source data are marked `[INSUFFICIENT DATA — description of what is missing]`.

---

## Context Management

### Three-Tier Hot / Warm / Cold Architecture

**File:** `src/context_manager.py`

Inspired by production agentic memory systems — specifically Letta (MemGPT), Mem0, AutoGen, and CrewAI — the system manages context in three tiers to avoid unbounded context growth across long multi-agent sessions:

```
┌─────────────────────────────────────────────────────────┐
│  HOT  │ Most recent messages (in LLM context window)    │
│       │ Capacity: HOT_LIMIT (10 messages)               │
│       │ Access: O(1), direct                            │
├─────────────────────────────────────────────────────────┤
│  WARM │ Compressed LLM-generated summary of older msgs  │
│       │ Format: 3-5 bullet points per compression cycle │
│       │ Access: O(1), pre-formatted string              │
├─────────────────────────────────────────────────────────┤
│  COLD │ Raw archived messages (audit trail)             │
│       │ Access: on-demand only                          │
└─────────────────────────────────────────────────────────┘
```

**Compression trigger:** When `len(hot) >= HOT_LIMIT`, an LLM call compresses the hot messages into 3–5 bullet points, merges them into the warm summary, and moves the raw messages to cold.

**What each tier holds in this system:**
- **PaperAgent HOT:** retrieved chunks + extracted claims for the current query
- **PaperAgent WARM:** pre-built paper summary from `paper_summaries` table (generated at ingest time, reused across all queries — no LLM call at query time)
- **ConflictAgent:** works on WARM summaries + HOT claim lists, only pulls COLD chunks on context expansion
- **Orchestrator:** rolling compression of inter-agent messages across long IND template sessions

**Prior art this draws from:**

| System | Mechanism |
|--------|-----------|
| **Letta (MemGPT)** | In-context blocks (hot) + recall vector DB (warm) + archival storage (cold); agent self-manages via function calls |
| **Mem0** | Two-phase extract→update with LLM-decided ADD/UPDATE/DELETE/MERGE; achieved 91% p95 latency reduction keeping ~7K tokens vs full context |
| **AutoGen** | `MessageHistoryLimiter` + `TextMessageCompressor` (LLMLingua); reduced a 4,019-token conversation to 215 tokens |
| **CrewAI** | Composite recall scoring: semantic similarity + recency + importance weighting |
| **LangGraph** | Checkpoint-per-step with Redis-backed thread/cross-thread stores |

### How Context Reaches Each Agent

Every agent receives `context_manager.get_context()` which returns:

```
[PRIOR SUMMARY]
• Paper1 reports IC50 = 12 nM by TR-FRET...
• CONCEPTUAL conflict detected on mechanism of action...

[RECENT ACTIVITY]
[14:23:01] (PaperAgent/output): Extracted 4 claims from paper4...
[14:23:02] (ConflictAgent/output): CONCEPTUAL conflict flagged...
```

This format keeps the most important information (warm summary) always visible while showing what just happened (hot activity) — without passing the full raw history to every LLM call.

---

## Conflict Handling

### Classification Logic

The ConflictAgent's LLM prompt is carefully engineered to handle the hardest cases in this dataset:

**EVOLVING_DATA detection:** The prompt instructs the model to check NCT numbers and publication dates. Paper1 and Paper5 both report from `NCT05123456` — one at interim analysis (n=12 AML, ORR=33%) and one at final analysis (n=24 AML, ORR=42%). The system classifies this as `EVOLVING_DATA`, not a conflict.

**CONCEPTUAL conflict — Mechanism of Action:** Paper1 claims competitive inhibition at the acetyl-lysine pocket. Paper4 provides 1.8Å crystal structures showing binding 5.2Å away at an allosteric site between the ZA and BC loops. These cannot both be correct. The system flags this as `CONCEPTUAL`, triggers context expansion, and the synthesis explains that paper4's structural evidence is higher quality (resolution specified vs unspecified).

**ASSAY_VARIABILITY for IC50:** Four papers report IC50 values of 8.5, 10.2, 12, and 15.3 nM for the same BRD4-BD1 target. The system classifies this as `ASSAY_VARIABILITY` — the variation is explained by different assay formats (TR-FRET with full-length protein, AlphaScreen, validated central lab) rather than a fundamental disagreement.

### Adaptive Context Expansion

When a `CONCEPTUAL` conflict is found:

```
ConflictAgent detects CONCEPTUAL conflict on "mechanism of action"
    │
    ▼
Triggers _expand_context() for paper1 and paper4
    │
    ▼
Fetches EXPANSION_TOP_K=2 additional chunks from each paper via Supabase
    │
    ▼
Deduplicates against already-retrieved chunks by chunk ID
    │
    ▼
Returns expansion PaperResults → merged into graph state via operator.add
    │
    ▼
SynthesisAgent receives original + expansion chunks for both papers
```

This is logged in the trace as `ConflictAgent.ContextExpansion` steps, making the adaptive behavior fully visible.

---

## Tech Stack & Trade-offs

### LangGraph — Agent Orchestration

**Why:** The parallel PaperAgent fan-out, conditional expansion branch, and stateful fan-in are exactly what LangGraph's `Send` API and `Annotated[list, operator.add]` reducers solve. Writing this without a framework would require manual `asyncio.gather`, state merging logic, and checkpointing — all of which LangGraph provides.

**What's not used from LangChain:** LangChain's retriever abstractions, LCEL chains, and vector store wrappers are intentionally avoided. They would obscure the per-paper Supabase filtering logic (a critical design decision) and make the trace harder to read.

### Supabase pgvector — Vector Store

**Why:** Production-ready persistence, familiar tooling, and pgvector scales to real research databases. The key architectural feature is the `match_chunks(query_embedding, filter_paper_id, match_count)` RPC — this filters by `paper_id` *before* doing vector similarity search, which is the Supabase equivalent of maintaining separate per-paper indexes.

**Trade-off vs FAISS:** FAISS would be simpler for evaluators to run (no external service). Supabase requires a project setup. The `supabase/migrations/` folder and `supabase/seed/seed_papers.py` are provided to make setup reproducible. In production, Supabase is the correct choice.

### OpenAI — LLM + Embeddings

- **`gpt-4o-mini`** for all agent calls — cost-effective for 5 parallel LLM calls per query, sufficient for structured JSON extraction
- **`text-embedding-3-small`** (1536-dim) — good retrieval quality at low cost; `text-embedding-3-large` would improve recall on ambiguous queries like "mechanism of action" at higher cost
- **`response_format={"type": "json_object"}`** — used for all structured extraction (claims, conflict classification) to eliminate JSON parsing failures

### No LangChain Chains

Using the raw OpenAI SDK inside LangGraph nodes keeps every LLM call explicit, traceable, and debuggable. There are no hidden prompt templates or automatic retry behaviors — all retry logic is explicit via `tenacity`.

---

## Setup & Running

### Prerequisites

- Python 3.10+
- A Supabase project (free tier works)
- Supabase CLI (`npm install -g supabase`)
- OpenAI API key

### 1. Clone and install

```bash
git clone <repo-url>
cd CoincidenceLabsTakeHome
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in: OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
```

### 3. Run Supabase migrations

```bash
supabase login
supabase link --project-ref your-project-ref
supabase db push
```

This runs all 5 migrations in order:
- Enable pgvector extension
- Create `chunks` table with IVFFlat index
- Create `match_chunks` RPC
- Create `paper_summaries` table
- Set RLS policies

See `supabase/migrations/README.md` for what each migration does.

### 4. Ingest papers

```bash
py -3 supabase/seed/seed_papers.py
```

This reads all 5 paper JSONs, generates embeddings, upserts chunks into Supabase, and generates WARM summaries stored in `paper_summaries`.

### 5. Run the system

```bash
# Single query
py -3 main.py --query "What is the IC50 of NVX-0228?"

# All 5 test queries (saved to outputs/)
py -3 main.py --run-all

# With bonus IND template generation
py -3 main.py --ind-template

# Start FastAPI server
py -3 -m uvicorn src.api:app --reload --port 8000
```

---

## Testing

```bash
# All tests with coverage
py -3 -m pytest tests/ -v --cov=src --cov-report=term-missing

# Single test file
py -3 -m pytest tests/test_conflict_agent.py -v
```

**24 total tests across 5 files.** All LLM and Supabase calls are mocked — tests never hit external APIs.

| File | Coverage |
|------|---------|
| `test_paper_agent.py` | Retrieval, claim extraction, empty results, expansion mode |
| `test_conflict_agent.py` | IC50 → ASSAY_VARIABILITY, MoA → CONCEPTUAL, thrombocytopenia → EVOLVING_DATA, ORR → NON_CONFLICT |
| `test_synthesis_agent.py` | All 5 papers cited, conflicts addressed, no silent winners |
| `test_context_manager.py` | Compression trigger, warm accumulation, reset, format |
| `test_api.py` | FastAPI endpoints, schema validation, error handling |

---

## Example Outputs

Pre-run outputs for all 5 test queries are in `outputs/`. Each output is a `QueryResult` JSON containing:

```json
{
  "query": "What is the IC50 of NVX-0228?",
  "answer": "...[Paper1]...[Paper2]...",
  "conflicts": [
    {
      "property": "IC50 (BRD4-BD1)",
      "conflict_type": "ASSAY_VARIABILITY",
      "papers_involved": ["paper1", "paper2", "paper3", "paper5"],
      "reasoning": "...",
      "resolution": "..."
    }
  ],
  "papers_cited": ["paper1", "paper2", "paper3", "paper4", "paper5"],
  "context_expansion_triggered": false,
  "trace": [
    {"agent": "PaperAgent", "step": "paper1", ...},
    {"agent": "ConflictAgent", ...},
    {"agent": "SynthesisAgent", ...}
  ]
}
```

---

## Bonus: IND Template Generation

The system can fill all sections of an IND Module 2.6.2 Pharmacology Written Summary from the 5 papers:

```bash
py -3 main.py --ind-template
```

Sections are generated in parallel (7 top-level sections, some with subsections). Each section uses formal FDA regulatory language, inline `[N]` citations, and marks `[INSUFFICIENT DATA]` where the source papers don't provide enough information for a section.

---

## Extending to Real Documents

The assignment includes `Agentic Document Extraction Results in Chemistry 2025.json` — an example output from Coincidence Labs' own document parsing pipeline (`dpt-2-20251103`). This shows what real paper ingestion would look like before pre-processing:

- 138 chunks per paper (vs ~8 in the simplified JSONs)
- Chunk types include `figure`, `logo`, `marginalia` (filtered out), `table` (HTML format), `text`
- Content in Markdown with anchor IDs for source traceability
- Same `grounding` bounding box structure

To extend this system to accept raw extraction output, `supabase/seed/seed_papers.py` would need a preprocessing step that:
1. Filters to only `text` and `table` chunks
2. Strips Markdown anchor tags from content
3. Converts HTML tables to structured text
4. Maps `markdown` → `content` in the chunk schema

The vector schema, `match_chunks` RPC, and all agent logic would remain unchanged.

---

## Project Structure

```
CoincidenceLabsTakeHome/
├── src/
│   ├── agents/
│   │   ├── paper_agent.py        # Per-paper retrieval + claim extraction
│   │   ├── conflict_agent.py     # Conflict classification + context expansion
│   │   ├── synthesis_agent.py    # Final cited answer generation
│   │   └── ind_template_agent.py # IND section generation (bonus)
│   ├── orchestrator.py           # LangGraph StateGraph
│   ├── context_manager.py        # Hot/Warm/Cold tiered context
│   ├── embeddings.py             # OpenAI embedding + Supabase search
│   ├── models.py                 # Pydantic v2 models
│   ├── config.py                 # Settings
│   ├── db.py                     # Supabase client singleton
│   └── api.py                    # FastAPI routes
├── supabase/
│   ├── migrations/               # 5 SQL migrations (see migrations/README.md)
│   └── seed/seed_papers.py       # Paper ingestion script
├── tests/                        # 24 pytest tests
├── data/                         # 5 paper JSONs + conflict key + IND template
├── outputs/                      # Pre-run query results
├── main.py                       # CLI entrypoint
└── requirements.txt
```
