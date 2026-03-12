# Multi-Document Conflict Resolution RAG System
### NVX-0228 BRD4 Inhibitor Research Synthesizer

A production-quality agentic RAG system that answers questions about NVX-0228 by reasoning across 5 conflicting research papers. When papers disagree, the system surfaces the conflict, classifies it, and resolves it — rather than silently picking a winner.

---

## Table of Contents

1. [Design Q&A](#design-qa)
2. [System Architecture](#system-architecture)
3. [Agentic Design](#agentic-design)
4. [Context Management](#context-management)
5. [Conflict Handling](#conflict-handling)
6. [Tech Stack & Trade-offs](#tech-stack--trade-offs)
7. [Setup & Running](#setup--running)
8. [Testing](#testing)
9. [Example Outputs](#example-outputs)
10. [Bonus: IND Template Generation](#bonus-ind-template-generation)

---

## Design Q&A

These are the four core design questions, answered in my own words with reasoning from how the system actually behaves in practice.

---

### Q1: How do you manage context? The papers total ~40 chunks — too much to pass everything into a single LLM call.

The 40-chunk problem was the first design constraint I worked through. My answer was a three-tier architecture — **Hot / Warm / Cold** — rather than either passing everything or truncating arbitrarily.

**The core insight:** not all context is equal, and context has a natural lifecycle.

- **COLD** is what lives in Supabase. Every chunk from every paper is stored as a pgvector embedding. Nothing is thrown away — it's just not in the LLM's context window yet.
- **WARM** is a pre-built LLM summary for each paper, generated at ingest time and stored in the `paper_summaries` table. Each PaperAgent gets this for free at query time with no additional LLM call. It tells the agent "here is what this paper is broadly about" before it even fetches any chunks.
- **HOT** is what actually goes into a given LLM call: `TOP_K_PER_PAPER = 3` chunks (retrieved by cosine similarity) plus the warm summary. For a 5-paper system that's a maximum of 15 chunks + 5 summaries visible at any one time — well within token limits.

What's clever about this structure is that the warm tier is what enables the ConflictAgent to reason across papers without ever receiving all 40 chunks. It gets 5 warm summaries + the extracted claim lists from each PaperAgent. The full chunks stay cold unless a CONCEPTUAL conflict triggers expansion.

This maps directly to how production memory systems work. Letta (MemGPT) has in-context blocks (hot), recall vector store (warm), and archival storage (cold). Mem0 keeps ~7K tokens active by constantly deciding what to ADD/UPDATE/DELETE. AutoGen's `TextMessageCompressor` reduced a 4,019-token conversation to 215 tokens using similar principles. I built a domain-specific version of the same idea.

```
                  Per LLM call budget
                  ┌────────────────────────────────────────┐
PaperAgent call:  │  warm_summary (1 paper) + 3 chunks     │  ~800–1200 tokens
                  └────────────────────────────────────────┘

ConflictAgent:    │  5 claim lists (no raw chunks)          │  ~400–600 tokens
                  └────────────────────────────────────────┘

SynthesisAgent:   │  5 warm summaries + 15 chunks + claims  │  ~3000–4000 tokens
                  └────────────────────────────────────────┘
```

The synthesis call is the largest but still bounded — chunks are truncated to `CHUNK_CONTENT_MAX_CHARS = 1200` and I set `SYNTHESIS_MAX_TOKENS = 2500` to control TTFT without cutting off the references section.

---

### Q2: How do you ensure evidence is pulled from multiple papers, not just the most similar one?

This was the most important architectural decision. The naive approach — embed the query, run a single global similarity search returning the top 15 chunks — would fail completely. If Paper 2 is semantically closest to "What is the IC50?", a global search might return 12 of its chunks and 1 each from two others. You'd miss the 15.3 nM value from Paper 3 entirely.

**My fix: per-paper retrieval with mandatory participation.**

Each of the 5 PaperAgents calls the `match_chunks` Supabase RPC with its own `paper_id` as a filter:

```sql
SELECT id, content, section, page,
       1 - (embedding <=> query_embedding) AS similarity
FROM chunks
WHERE paper_id = $paper_id          -- ← mandatory filter before similarity
ORDER BY similarity DESC
LIMIT $match_count
```

This guarantees every paper contributes exactly `TOP_K_PER_PAPER = 3` chunks, regardless of whether it's the most similar paper overall. The 5 agents run in parallel via LangGraph's `Send` API so there's no latency penalty.

The effect is visible in every trace — all 5 papers are always cited:

```
--- Papers Cited ---
  paper1_nvx0228_novel_inhibitor
  paper2_nvx0228_pharmacokinetics
  paper3_brd4_hematologic_comparative
  paper4_nvx0228_structural_basis
  paper5_nvx0228_updated_phase1
```

This is also the reason CONCEPTUAL conflicts get detected reliably. The mechanism-of-action conflict between Paper 1 (competitive inhibitor) and Paper 4 (allosteric modulator) only surfaces because both papers are forced to contribute. A global search for "mechanism of action" might return mostly Paper 1 chunks — Paper 4's structural data would never appear.

**One more layer: claim extraction is query-aware.** Each PaperAgent passes the user's original question to the extraction LLM alongside the retrieved chunks. The model is told to extract claims *relevant to the research question*. So for an IC50 question, it extracts IC50 values. For a toxicity question, it extracts adverse event rates. The same chunk corpus produces different structured claim outputs depending on what you asked.

---

### Q3: When the system discovers a conflict, how does it respond?

Conflicts are not all the same, and the response depends on the type. I defined five types in `ConflictType`:

| Type | What it means | System response |
|------|--------------|-----------------|
| `ASSAY_VARIABILITY` | Same target, different measurement methods (TR-FRET vs AlphaScreen vs ITC) | Classify and explain in synthesis |
| `METHODOLOGY` | Different protocols, patient populations, animal models | Classify and explain in synthesis |
| `CONCEPTUAL` | Fundamentally different mechanistic interpretations — both cannot be correct | **Trigger context expansion** |
| `EVOLVING_DATA` | Same trial at different data cuts (same NCT number, different timepoints) | Classify as non-conflict, explain timeline |
| `NON_CONFLICT` | Values agree within expected variation | Pass through silently |

**The CONCEPTUAL path is where the system's behavior actually changes:**

```
ConflictAgent detects CONCEPTUAL: mechanism_of_action
    │
    ▼  immediately, before synthesis runs
_expand_context() fetches EXPANSION_TOP_K=5 chunks per paper
(instead of the original TOP_K_PER_PAPER=3)
    │
    ▼
Deduplicate by chunk ID against already-retrieved set
    │
    ▼
New chunks merged into graph state via operator.add
    │
    ▼
SynthesisAgent now receives 5 chunks/paper instead of 3
— the structural data from Paper 4 (1.8Å crystal structure,
  5.2Å displacement from acetyl-lysine pocket) is now visible
```

This shows up in the trace as additional `ConflictAgent.ContextExpansion` steps and sets `context_expansion_triggered: true` in the output:

```
[ConflictAgent] conflict_agent: 3 conflicts classified:
  [ic50_bd1_nm:ASSAY_VARIABILITY, mechanism_of_action:CONCEPTUAL,
   thrombocytopenia_rate_pct:METHODOLOGY];
  context_expansion_triggered=True (1 CONCEPTUAL) (5713ms)

[ConflictAgent.ContextExpansion] context_expansion_paper1: Fetched 5 chunks, 2 new (127ms)
[ConflictAgent.ContextExpansion] context_expansion_paper4: Fetched 5 chunks, 2 new (93ms)
[ConflictAgent.ContextExpansion] context_expansion_paper2: Fetched 5 chunks, 2 new (80ms)
[ConflictAgent.ContextExpansion] context_expansion_paper3: Fetched 5 chunks, 2 new (79ms)
[ConflictAgent.ContextExpansion] context_expansion_paper5: Fetched 5 chunks, 2 new (80ms)
```

The total trace goes from 7 steps (no expansion) to 12 steps (with expansion). The SynthesisAgent then explicitly addresses the conflict in its output rather than picking a winner:

```
CONFLICT ANALYSIS

The mechanism of action of NVX-0228 is a subject of debate. Chen et al. (2023)
describe it as a competitive inhibitor, while Kim et al. (2023) present evidence
for an allosteric modulation mechanism. This conceptual conflict suggests that
further studies are necessary to clarify the binding mode and functional
implications of NVX-0228.
```

For the hardest case in the dataset — Paper 1 and Paper 5 both reporting from the same trial NCT05123456 at different data cuts — the ConflictAgent is prompted to check NCT numbers and publication dates before classifying. It correctly identifies this as `EVOLVING_DATA`, not a genuine conflict.

---

### Q4: How is the work decomposed? What are the boundaries between components?

I decomposed into agents based on a simple rule: **each agent owns exactly one paper or exactly one cross-paper concern, and agents cannot call each other directly.** All communication goes through LangGraph's shared graph state.

```
Component               Owns                          Input               Output
─────────────────────────────────────────────────────────────────────────────────
PaperAgent (×5)         One paper each                query + paper_id    PaperResult
                        Supabase fetch + claim LLM                        (chunks + claims)

ConflictAgent (×1)      Cross-paper conflict          all PaperResults    conflicts[]
                        detection + expansion         + query             + expansion chunks

SynthesisAgent (×1)     Final answer generation       all PaperResults    answer string
                                                      + conflicts[]

INDTemplateAgent (×7)   One IND section each          PaperResults        INDSectionResult
                        (bonus)                       + conflicts[]
```

**Why these exact boundaries?**

PaperAgents are isolated so they can run in parallel without coordination. They don't know about each other. They don't know about conflicts. They just find the most relevant evidence from their one paper and extract structured claims from it.

ConflictAgent is sequential by necessity — it needs all 5 PaperResults before it can group claims by property across papers. But within ConflictAgent, the per-property classification calls run in parallel via `asyncio.gather`. The expansion fetches also run in parallel. Sequential at the graph level, parallel internally.

SynthesisAgent is sequential by necessity — it needs the conflict report. But it's the only agent that sees the full picture: all chunks, all summaries, all conflicts. It's the only one with `SYNTHESIS_MAX_TOKENS = 2500` because it produces the longest output.

**Why LangGraph specifically?**

The parallel fan-out to 5 PaperAgents, the fan-in back into a single ConflictAgent, and the conditional expansion branch (only runs when CONCEPTUAL fires) are exactly the patterns LangGraph's `Send` API and `Annotated[list, operator.add]` reducers were built for. Writing this without the framework would require manual `asyncio.gather` with state merging, checkpointing per step for fault tolerance, and conditional edge logic — all of which LangGraph handles declaratively.

What I deliberately did NOT use from LangChain: retriever abstractions, LCEL chains, vector store wrappers. These would hide the per-paper Supabase filtering logic (the single most important retrieval decision in the system) and make the trace harder to read. The raw OpenAI SDK inside each agent node keeps every LLM call explicit and inspectable.

**Agent communication example — how ConflictAgent output changes SynthesisAgent behavior:**

```python
# ConflictAgent sets context_expansion_triggered in state
return {
    "conflicts": conflicts,
    "context_expansion_triggered": len(expansion_traces) > 0,
    "paper_results": expansion_results,   # operator.add merges expansion chunks in
    "trace": all_trace,
}

# SynthesisAgent receives the expanded paper_results automatically
# — it doesn't know whether expansion ran, it just uses whatever is in state
async def synthesis_node(state: GraphState) -> dict:
    answer, trace = await SynthesisAgent().run(
        query=state["query"],
        paper_results=state["paper_results"],  # may contain 3 or 5 chunks/paper
        conflicts=state["conflicts"],
    )
```

The SynthesisAgent doesn't have a conditional branch for "did expansion run?" — it just consumes whatever context is in the state. ConflictAgent shapes what state looks like, and SynthesisAgent benefits from it automatically.

---

## System Architecture

### Query Pipeline

```
User Query (any NVX-0228 question)
    │
    ▼  text-embedding-3-small (1536-dim)
Query Embedding  ──────────────────────────────────────────────────────────────┐
    │                                                                           │
    ▼                                                                           │
┌─────────────────────────────────────────────────────────────────────────────┐│
│  LangGraph StateGraph Orchestrator                                           ││
│                                                                              ││
│  START ──► route_to_papers ──────────────────────────────────────────────►  ││
│                │                                                             ││
│     ┌──────────┼──────────┬──────────┬──────────┐  parallel via Send API   ││
│     ▼          ▼          ▼          ▼          ▼                           ││
│  Paper 1    Paper 2    Paper 3    Paper 4    Paper 5   ◄────────────────────┘│
│  Agent      Agent      Agent      Agent      Agent                           │
│  [pgvector  [pgvector  [pgvector  [pgvector  [pgvector                       │
│   RPC +      RPC +      RPC +      RPC +      RPC +                         │
│   LLM]       LLM]       LLM]       LLM]       LLM]                          │
│     └──────────┴──────────┴──────────┴──────────┘                           │
│                │  fan-in: operator.add reducer merges all 5 results          │
│                ▼                                                             │
│          ConflictAgent                                                       │
│           │         │                                                        │
│       if CONCEPTUAL │                                                        │
│           │         │                                                        │
│     context expansion                                                        │
│     (fetch more chunks                                                       │
│      via Supabase)   │                                                       │
│           │         │                                                        │
│           └────►  SynthesisAgent                                             │
│                       │                                                      │
│             [optional fan-out]                                               │
│                       │                                                      │
│      INDSection ×7  (parallel)                                               │
│                       │                                                      │
│                     END                                                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

The graph state uses `Annotated[list, operator.add]` reducers for `paper_results`, `trace`, and `ind_results` — this is what enables the parallel fan-in: each `paper_node` appends its result to the shared list, and LangGraph merges them automatically when all parallel nodes complete.

### Vector Storage & Retrieval

```
INGEST TIME (once, via seed_papers.py)
────────────────────────────────────────────────────────────────
  Paper JSON  ──► chunk splitter  ──► text-embedding-3-small
                                            │
                                            ▼
                                  Supabase pgvector
                                  chunks table
                                  ┌────────────────────────────┐
                                  │ id │ paper_id │ content │   │
                                  │    │          │ section │   │
                                  │    │          │ embedding◄──┘
                                  │    │          │ (vector  │
                                  │    │          │  1536-d) │
                                  └────────────────────────────┘
                                  ivfflat index on embedding col

  Also stored:  paper_summaries table  (one row per paper)
                ┌──────────────────────────────────────────────┐
                │ paper_id │ title │ authors │ date │ journal   │
                │          │ summary (LLM-generated warm cache) │
                └──────────────────────────────────────────────┘

QUERY TIME (per query, per paper — runs in parallel for all 5)
────────────────────────────────────────────────────────────────
  User Query
      │
      ▼  text-embedding-3-small (lru_cache — 5 agents share 1 API call)
  Query Embedding
      │
      ▼
  match_chunks(query_embedding, paper_id, match_count) RPC
  ┌──────────────────────────────────────────────────────┐
  │  SELECT ... FROM chunks                               │
  │  WHERE paper_id = $paper_id                           │  ← per-paper filter
  │  ORDER BY embedding <=> $query_embedding              │  ← cosine similarity
  │  LIMIT $match_count                                   │
  └──────────────────────────────────────────────────────┘
      │
      ▼  TOP_K_PER_PAPER=3 chunks  (EXPANSION_TOP_K=5 if CONCEPTUAL conflict)
  Retrieved chunks + warm summary
      │
      ▼  gpt-4o-mini
  Structured claims: [{property, value, context, confidence}, ...]
```

**Why per-paper retrieval instead of global top-k:** A global similarity search would return all top chunks from whichever single paper happens to be most similar to the query — the system would miss evidence from the other 4 papers entirely. Per-paper retrieval guarantees every paper contributes regardless of relative cosine similarity. This is critical for conflict detection: you need all 4 IC50 values across all 4 papers, not just the 3 chunks from the most similar one.

**The system handles any question** — not just the 5 test queries. Vector similarity search retrieves the most relevant chunks from each paper for whatever you ask. Try `py -3 main.py --query "What is the BD1/BD2 selectivity ratio?"` or `py -3 main.py --query "What dose was used in Phase II?"` — the retrieval and conflict detection adapt automatically.

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
- Cites sources inline in author-year format: `(Chen et al., 2023)` — built from paper metadata stored in Supabase at ingest time
- Ends with a full REFERENCES section listing every cited paper with authors, year, title, and journal
- Addresses every conflict explicitly with resolution reasoning; never silently picks a winner
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
Triggers _expand_context() for every paper in conflict.papers_involved
    │
    ▼
Fetches EXPANSION_TOP_K=5 chunks/paper via Supabase (up from TOP_K_PER_PAPER=3)
    │
    ▼
Deduplicates against already-retrieved chunk IDs — keeps only new chunks
(typically 2 new per paper: 5 fetched − 3 already seen = 2 net new)
    │
    ▼
Returns expansion PaperResults → merged into graph state via operator.add
    │
    ▼
SynthesisAgent receives up to 5 chunks/paper instead of 3
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

# With bonus IND template generation (must be combined with --query or --run-all)
py -3 main.py --query "What is the mechanism of action of NVX-0228?" --ind-template
py -3 main.py --run-all --ind-template

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

**54 backend tests + 34 frontend tests.** All LLM and Supabase calls are mocked — tests never hit external APIs.

| Backend file | Tests | Coverage |
|-------------|-------|---------|
| `test_paper_agent.py` | 8 | Retrieval, claim extraction, empty results, expansion, token counting, malformed JSON, Supabase failure |
| `test_conflict_agent.py` | 5 | IC50 → ASSAY_VARIABILITY, MoA → CONCEPTUAL, thrombocytopenia → EVOLVING_DATA, ORR → NON_CONFLICT |
| `test_synthesis_agent.py` | 4 | All 5 papers cited, conflicts addressed, no silent winners |
| `test_context_manager.py` | 18 | Compression trigger, warm accumulation, reset, format, tiered access |
| `test_api.py` | 12 | FastAPI endpoints, schema validation, 422 on bad input, max length enforcement |
| `test_orchestrator.py` | 7 | Full graph integration: fan-out, fan-in, graceful paper failure, output file saved |

| Frontend file | Tests | Coverage |
|--------------|-------|---------|
| `QueryBox.test.tsx` | — | Submit fires API call, loading state |
| `ResultCard.test.tsx` | — | Conflict badges, expansion banner, citation rendering |
| `ConflictBadge.test.tsx` | — | Color/label maps to conflict type enum |
| `TraceViewer.test.tsx` | — | Steps expand/collapse |

---

## Example Outputs

> **All 6 pre-run output files are in [`outputs/`](outputs/).** Each is a complete `QueryResult` JSON — answer, conflicts, trace, and papers cited.
> See [`outputs/README.md`](outputs/README.md) for a guided breakdown of what to look at in each file.
> **Want to read an actual answer?** [`docs/SAMPLE_OUTPUTS.md`](docs/SAMPLE_OUTPUTS.md) shows the IC50 query rendered as human-readable text — full answer, conflict table, and agent trace with latencies.

| Query | File | Key conflicts | Context expansion |
|-------|------|--------------|------------------|
| What is the IC50 of NVX-0228? | [`outputs/20260312_145936_What_is_the_IC50_of_NVX-0228_.json`](outputs/20260312_145936_What_is_the_IC50_of_NVX-0228_.json) | ASSAY_VARIABILITY (8.5–15.3 nM across 4 assay formats) | No |
| What toxicity was observed? | [`outputs/20260312_150039_What_toxicity_was_observed_with_NVX-0228.json`](outputs/20260312_150039_What_toxicity_was_observed_with_NVX-0228.json) | METHODOLOGY × 4 (thrombocytopenia 15% → 22% → 41%) | No |
| What is the mechanism of action? | [`outputs/20260312_150137_What_is_the_mechanism_of_action_of_NVX-0.json`](outputs/20260312_150137_What_is_the_mechanism_of_action_of_NVX-0.json) | **CONCEPTUAL** (competitive vs allosteric) | **Yes — 12-step trace** |
| What clinical trials were conducted? | [`outputs/20260312_150241_What_clinical_trials_have_been_conducted.json`](outputs/20260312_150241_What_clinical_trials_have_been_conducted.json) | CONCEPTUAL + METHODOLOGY × 3 + NON_CONFLICT | **Yes** |
| What resistance mechanisms exist? | [`outputs/20260312_150340_What_resistance_mechanisms_have_been_ide.json`](outputs/20260312_150340_What_resistance_mechanisms_have_been_ide.json) | CONCEPTUAL + ASSAY_VARIABILITY | **Yes** |
| *(bonus)* Oral bioavailability & half-life? | [`outputs/20260312_151144_What_is_the_oral_bioavailability_and_hal.json`](outputs/20260312_151144_What_is_the_oral_bioavailability_and_hal.json) | METHODOLOGY × 3 (preclinical vs clinical PK) | No |

The mechanism-of-action query is the most interesting to inspect — open that file and look at the `trace` array. It has **12 steps** instead of the usual 7: the system detected a CONCEPTUAL conflict, automatically fetched additional chunks from all 5 papers (`ConflictAgent.ContextExpansion` steps), then synthesised with the expanded evidence set.

---

## Bonus: IND Template Generation

### IND Module 2.6.2 — Pharmacology Written Summary

The system extends its agent architecture to fill every section of an IND Module 2.6.2 submission using the same evidence it already retrieved for the research query. The template structure follows ICH M4S(R2) / 21 CFR 312.23(a)(8) and is defined in `data/generation_template.json`.

```bash
# Run with any research query — IND generation happens after synthesis
py -3 main.py --query "What is the mechanism of action of NVX-0228?" --ind-template

# Or run on all 5 test queries
py -3 main.py --run-all --ind-template
```

### Section Structure

| Section | Heading | Subsections |
|---------|---------|-------------|
| 2.6.2.1 | Brief Summary | — |
| 2.6.2.2 | Primary Pharmacodynamics | 2.6.2.2.1 Mechanism of Action, 2.6.2.2.2 In Vitro Pharmacology, 2.6.2.2.3 Structure-Activity Relationships |
| 2.6.2.3 | Secondary Pharmacodynamics | — |
| 2.6.2.4 | Safety Pharmacology | — |
| 2.6.2.5 | Pharmacodynamic Drug Interactions | 2.6.2.5.1 Resistance Mechanisms, 2.6.2.5.2 Strategies to Overcome Resistance |
| 2.6.2.6 | Clinical Trial Summary | 2.6.2.6.1 Completed Studies, 2.6.2.6.2 Ongoing Studies, 2.6.2.6.3 Terminated Studies |
| 2.6.2.7 | Discussion and Conclusions | — |

### How it integrates with the agent system

```
SynthesisAgent completes
        │
        ▼  route_after_synthesis() reads generation_template.json
        │  fans out one Send per top-level section
        │
   ┌────┴────┬────────┬────────┬────────┬────────┬────────┐
   ▼         ▼        ▼        ▼        ▼        ▼        ▼
 2.6.2.1  2.6.2.2  2.6.2.3  2.6.2.4  2.6.2.5  2.6.2.6  2.6.2.7
 (parallel — all 7 INDTemplateAgent instances run simultaneously)
   └────┬────┴────────┴────────┴────────┴────────┴────────┘
        │  operator.add fan-in
        ▼
  ind_results[] in QueryResult — sorted by section_id, saved to outputs/ JSON
```

Each `INDTemplateAgent` receives:
- **All 5 PaperResults** (chunks + extracted claims + warm summaries) — same evidence used by SynthesisAgent
- **All identified conflicts** from ConflictAgent — so each section knows where papers disagree
- **Section-specific regulatory guidance** from the template (ICH S7A references, 21 CFR citations, what quantitative data to include)

### Conflict-awareness in IND sections

The agent prompt explicitly handles conflicts: when conflicting values exist across papers, the section presents all values and notes the discrepancy in FDA regulatory language rather than picking one:

```
IC50 values reported across studies for NVX-0228 against BRD4-BD1 range from
8.5 nM [2] to 15.3 nM [3], with variation attributable to differences in assay
format (AlphaScreen, TR-FRET, validated central laboratory assay). A single
authoritative value cannot be determined from available data without assay
standardization.
```

### Insufficient data handling

Sections that require information not present in the 5 source papers are marked rather than fabricated:

```
[INSUFFICIENT DATA — no in vivo pharmacodynamic data (xenograft or PDX models)
 available in source documents; preclinical PD studies would be required to
 complete this section per ICH S7A]
```

The `INDSectionResult` model tracks `insufficient_data: bool` and `missing_info: str` per section, making gaps machine-readable for downstream review workflows.

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
├── tests/                        # 54 backend pytest tests
├── data/                         # 5 paper JSONs + conflict key + IND template
├── outputs/                      # Pre-run query results
├── main.py                       # CLI entrypoint
└── requirements.txt
```
