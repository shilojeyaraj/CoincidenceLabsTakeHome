# Engineering Workflow — Multi-Document Conflict Resolution RAG

This document captures how this system was designed and built: the reasoning behind each decision, the problems that were hit, and how they were resolved. It reflects a real development process — not a polished post-mortem, but the actual back-and-forth of building something production-quality under time pressure.

---

## Starting Point: Reading the Problem

The assignment brief has four questions buried in it:

> - How do you manage context?
> - How do you ensure evidence is pulled from multiple papers, not just the most similar one?
> - When the system discovers a conflict, how does it respond?
> - How is the work decomposed?

Before writing a single line of code, I sat with these questions. The naive approach — embed everything, global top-k, pass to a single LLM call — fails all four. You'd get context from one paper, no conflict detection, no adaptive behavior, and no clear component separation.

The answer to all four questions pointed to the same architecture: **one agent per paper, a dedicated conflict classifier, and a synthesis layer that sees everything.**

---

## Architecture Decision: Why Multi-Agent + LangGraph

The key insight was that per-paper isolation is not optional — it's the whole point. If you run a global similarity search, the most-similar paper dominates and you miss the others entirely. You can only reliably detect that Paper 1 says "competitive inhibitor" and Paper 4 says "allosteric modulator" if both papers are *forced* to contribute evidence regardless of their relative similarity score.

That means 5 parallel agents, each owning exactly one paper. LangGraph's `Send` API and `Annotated[list, operator.add]` reducers are exactly what this pattern requires — parallel fan-out, automatic fan-in, and stateful checkpointing without writing the plumbing by hand.

```
User Query
    │
    ▼
LangGraph StateGraph
    │
    ├── PaperAgent(paper1) ─┐
    ├── PaperAgent(paper2)  │ parallel via Send API
    ├── PaperAgent(paper3)  │ each retrieves from its own
    ├── PaperAgent(paper4)  │ Supabase vector index
    └── PaperAgent(paper5) ─┘
                │
                ▼ fan-in via operator.add
         ConflictAgent
                │
                ▼
         SynthesisAgent
```

LangChain's retriever abstractions were deliberately avoided. They'd hide the per-paper `paper_id` filter in the Supabase RPC — the single most important retrieval decision in the system.

---

## The Context Management Problem

The papers total ~40 chunks. Passing all 40 into every LLM call is wasteful, slow, and blows past sensible token budgets for cheap models like `gpt-4o-mini`.

The solution: **Hot / Warm / Cold tiers**, modeled after how production memory systems like Letta (MemGPT) and Mem0 work.

| Tier | What it holds | Where it lives |
|------|--------------|----------------|
| Cold | All chunks, all papers | Supabase pgvector |
| Warm | Pre-built paper summary (generated at ingest, reused on every query) | `paper_summaries` table |
| Hot | TOP_K=3 retrieved chunks + warm summary for the current query | LLM context window |

Each PaperAgent LLM call sees at most ~800–1200 tokens of context. The ConflictAgent only sees extracted claim lists (not raw chunks). The SynthesisAgent sees the most — 15 chunks + 5 summaries — but that's still bounded and manageable at `SYNTHESIS_MAX_TOKENS = 2500`.

The warm tier was a particularly high-leverage decision. Because summaries are generated once at ingest time and cached in Supabase, every query gets rich paper-level context at zero LLM cost.

---

## The Conflict Detection Problem

Getting conflict detection to work reliably required solving two separate sub-problems:

**Sub-problem 1: Property name normalization.**
PaperAgents extract claims as JSON like `{"property": "mechanism_of_action", "value": "competitive inhibitor"}`. If Paper 1's agent writes `binding_mode` and Paper 4's writes `allosteric_binding`, the ConflictAgent never groups them together — it sees two different properties with one paper each, not a conflict.

The fix was two-pronged:
1. The extraction prompt explicitly instructs: *"ALWAYS use property name `mechanism_of_action` for binding mechanism claims"*
2. A `_PROPERTY_SYNONYMS` dictionary in ConflictAgent normalizes 15+ variant names (`inhibitor_type`, `binding_pose`, `allosteric_binding`, etc.) to canonical forms before grouping

**Sub-problem 2: Context expansion was silently not triggering.**
Even after fixing property names, the `context_expansion_triggered` flag was coming back `False` on mechanism-of-action queries. The root cause: `EXPANSION_TOP_K` was set to 3 (same as `TOP_K_PER_PAPER`), so expansion fetched 3 chunks, they were all duplicates of the already-retrieved 3, the dedup returned an empty list, and the flag used `len(expansion_results) > 0` — which was False.

Fix: raised `EXPANSION_TOP_K` to 5 (guaranteeing 2 genuinely new chunks after dedup against 3 already-seen) and changed the flag to use `len(expansion_traces) > 0` instead, since traces emit whenever CONCEPTUAL fires regardless of whether new content was found.

The trace now looks like this on mechanism questions:

```
[ConflictAgent] 3 conflicts: [ic50_bd1_nm:ASSAY_VARIABILITY,
  mechanism_of_action:CONCEPTUAL, thrombocytopenia_rate_pct:METHODOLOGY]
  context_expansion_triggered=True (1 CONCEPTUAL) (5713ms)

[ConflictAgent.ContextExpansion] paper1: Fetched 5 chunks, 2 new (127ms)
[ConflictAgent.ContextExpansion] paper4: Fetched 5 chunks, 2 new (93ms)
[ConflictAgent.ContextExpansion] paper2: Fetched 5 chunks, 2 new (80ms)
[ConflictAgent.ContextExpansion] paper3: Fetched 5 chunks, 2 new (79ms)
[ConflictAgent.ContextExpansion] paper5: Fetched 5 chunks, 2 new (80ms)
```

Total trace goes from 7 steps (no expansion) to 12 steps with expansion.

---

## The Performance Problem

Initial end-to-end query time: **79–84 seconds**. Target: under 45 seconds.

Three optimizations were made in sequence:

**1. Sync → Async OpenAI client (~2× speedup)**

All 4 agents used `openai.OpenAI` (sync) wrapped in `asyncio.to_thread`. Every LLM call was blocking a thread in a pool. Switched to `openai.AsyncOpenAI` with native `await` — LLM calls now genuinely overlap instead of sharing thread slots.

Result: Q3 (mechanism query, the heaviest) dropped from 79–84s to ~41s average.

**2. Parallel conflict classification (~3× for the conflict phase)**

ConflictAgent was classifying each multi-paper property in a sequential for-loop. 4–5 properties = 4–5 sequential LLM calls. Changed to `asyncio.gather(*classification_tasks)` — all classifications run simultaneously.

Result: ConflictAgent phase dropped from 15–17s to 4–7s.

**3. Semaphore scope refactoring**

The orchestrator had a `Semaphore(3)` wrapping the entire `paper_node` execution — Supabase fetch AND LLM extraction. This meant while paper1 was waiting 30s for OpenAI, papers 4 and 5 were blocked from starting. Moved the semaphore into `PaperAgent._get_supabase_sem()` where it only wraps the ~200ms Supabase calls. LLM extraction for all 5 papers now runs fully concurrently.

Result: Paper phase runs in `max(slowest paper)` instead of batched groups.

**Token budget tuning**

Added per-agent `max_tokens` constants instead of using a global 4096 for every call:

| Agent | Constant | Value | Rationale |
|-------|----------|-------|-----------|
| Claim extraction | `CLAIM_EXTRACTION_MAX_TOKENS` | 1500 | Claims JSON is small; 4096 was wasteful |
| Conflict classification | `CONFLICT_CLASSIFICATION_MAX_TOKENS` | 512 | Single JSON object, ~100 tokens actual |
| Synthesis | `SYNTHESIS_MAX_TOKENS` | 2500 | Full answer + references section |
| IND sections | `IND_SECTION_MAX_TOKENS` | 4096 | Regulatory sections can be long |

---

## The Output Quality Problem

After performance was solved, the output format needed work. Three issues were raised and fixed:

**Problem 1: `[Paper1]`, `[Paper2]` citations were unprofessional.**

The synthesis system prompt was telling the LLM to use paper number labels. These are meaningless to a reader who doesn't have the paper list in front of them.

Fix: Added `_make_citation_key()` and `_make_full_reference()` methods to `SynthesisAgent`. At context-build time, paper metadata (authors, year, journal) from the `paper_summaries` table is assembled into a `PAPER REGISTRY` block at the top of the synthesis prompt:

```
=== PAPER REGISTRY (use these keys for in-text citations) ===
[Chen et al., 2023] → Chen, W., Rodriguez, M., Patel, S., Nakamura, T. (2023).
                       NVX-0228: A Novel BRD4 Inhibitor. Journal of Medicinal Chemistry.
```

Output now uses `(Chen et al., 2023)` inline and ends with a full REFERENCES section.

**Problem 2: Markdown in the output.**

The LLM kept defaulting to `**bold**` and `## headers` even when not asked to. Added an explicit `FORMATTING RULES` block to the synthesis system prompt banning all markdown syntax.

**Problem 3: Citations after every single number.**

The output had citations like `"the IC50 was 12 nM (Chen et al., 2023) at 48 hours (Chen et al., 2023) with 95% confidence (Chen et al., 2023)"`. Added a citation frequency rule: cite once per finding at the end of the sentence, not after every data value.

**Fix 4: Dense unreadable list output.**

No spacing between numbered items. Added: "Place a blank line between every numbered item and between every bullet group."

**Frontend rendering (ResultCard.tsx)**

Even with well-formatted plain text, the frontend was rendering it as a single `<p>` block — a dense wall of text. Replaced the `AnswerText` component with a structured parser:

- ALL CAPS headers → `<h3>` with ruled separator
- Numbered items → blue circle pill number + text
- REFERENCES → left-border indented muted text

All 34 frontend tests still pass after the rewrite.

---

## Bugs Found During Audit

Three bugs were found that had nothing to do with the main development work:

**Bug 1: IND sections silently discarded.**
`QueryResult` had no `ind_results` field. The graph computed 7 IND sections via `INDTemplateAgent` and stored them in `GraphState["ind_results"]`, but the assembly step in `run_query()` never read that field. Sections were computed, then dropped. Fixed by adding `ind_results: list[INDSectionResult]` to `QueryResult` and wiring it through.

**Bug 2: Frontend types out of sync with API.**
`INDSectionResult` interface didn't exist in `frontend/src/types/index.ts` at all, and `QueryResult` had no `ind_results` field. The TypeScript compiler would error if anyone tried to use the IND results in a component. Fixed.

**Bug 3: Deprecated FastAPI startup event.**
`api.py` used `@app.on_event("startup")` which FastAPI deprecated in favor of lifespan context managers. Generated deprecation warnings on every test run. Migrated to `@asynccontextmanager async def lifespan(app)`.

---

## Final State

| Metric | Value |
|--------|-------|
| Backend tests | 45 passing |
| Frontend tests | 34 passing |
| Average query time (no expansion) | ~30–35s |
| Average query time (with CONCEPTUAL expansion) | ~38–42s |
| Conflict types detected | All 5 (ASSAY_VARIABILITY, METHODOLOGY, CONCEPTUAL, EVOLVING_DATA, NON_CONFLICT) |
| Context expansion | Fires reliably on all mechanism-of-action queries |
| IND sections generated | 7 (sections 2.6.2.1–2.6.2.7) in parallel |
| Citation format | Author-year with full bibliographic REFERENCES section |
| Output format | Structured plain text, no markdown |

---

## What Would Come Next

Things deliberately left out of scope for this submission:

- **Async Supabase client** — `supabase-py`'s `acreate_client` would require restructuring all of `db.py`. `asyncio.to_thread` achieves the same non-blocking result with less risk.
- **Query-level result caching** — same query string → cached `QueryResult` would break the live `timestamp` and trace fields. Skipped for correctness.
- **MemorySaver TTL** — LangGraph accumulates per-thread checkpoints in memory indefinitely. Fine for a demo. Production would use `PostgresSaver` with a TTL cleanup job.
- **Real paper ingestion pipeline** — the reference extraction output (`Agentic Document Extraction Results in Chemistry 2025.json`) shows what real ingestion looks like: 138 chunks/paper vs ~8, HTML tables, figure filtering. The `seed_papers.py` preprocessing step would need updating; all agent logic stays the same.
