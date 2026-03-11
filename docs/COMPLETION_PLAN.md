# Completion Plan — Coincidence Labs Take-Home

## Evaluation Criteria → What Covers It

| Criterion | Status | Where |
|-----------|--------|-------|
| Architecture & context management | ✅ Built + documented | `src/orchestrator.py`, `src/context_manager.py`, README |
| Conflict handling (surfaces + reasons) | ✅ Built | `src/agents/conflict_agent.py` — 5 conflict types |
| System behavior changes on conflict | ✅ Built | CONCEPTUAL → `_expand_context()` → fetches more chunks |
| Code quality | ✅ Built | All src/ files, typed, retries, tests |
| README write-up | ✅ Written | `README.md` |
| 5 test queries with outputs | ❌ Needs API key | Run `py -3 main.py --run-all` |
| Bonus: IND template generation | ❌ Needs API key | Run `py -3 main.py --run-all --ind-template` |
| Frontend | ❌ Not built yet | `frontend/` |

---

## Priority Order

### PHASE 1 — Get credentials & run the system (do first, everything else depends on it)

**Step 1.1 — Email Yannick for the OpenAI key**
```
Email: yannick@coincidencelabs.com
Subject: Ready to start — OpenAI API key
```

**Step 1.2 — Create Supabase project**
1. Go to supabase.com → New project → name it `nvx0228-rag`
2. Copy: Project URL → `SUPABASE_URL`, Service role key → `SUPABASE_SERVICE_KEY`
3. Copy `.env.example` → `.env` and fill both values + `OPENAI_API_KEY`

**Step 1.3 — Run migrations**
```bash
npm install -g supabase
supabase login
supabase link --project-ref your-project-ref
supabase db push
```
Expected: 5 migrations applied. Verify in Supabase dashboard → Table Editor → `chunks` and `paper_summaries` tables exist.

**Step 1.4 — Ingest papers**
```bash
py -3 supabase/seed/seed_papers.py
```
Expected: 5 papers × ~8 chunks = ~40 rows in `chunks` table. 5 rows in `paper_summaries`.

**Step 1.5 — Run all 5 test queries**
```bash
py -3 main.py --run-all
```
This runs the exact 5 assignment queries and saves JSON to `outputs/`. Verify outputs exist:
```bash
ls outputs/
```

**Step 1.6 — Run IND template generation (bonus)**
```bash
py -3 main.py --run-all --ind-template
```
This adds IND sections to each output. Alternatively run one focused query:
```bash
py -3 main.py --query "What is the mechanism of action of NVX-0228?" --ind-template
```

---

### PHASE 2 — Verify outputs hit all evaluation criteria

For each of the 5 output JSONs, manually verify:

**Query 1: IC50**
- [ ] `conflicts` contains an entry with `conflict_type: ASSAY_VARIABILITY`
- [ ] `papers_cited` includes paper1, paper2, paper3, paper5 (paper4 reports Kd not IC50)
- [ ] `answer` mentions 8.5 nM, 12 nM, 15.3 nM, 10.2 nM with paper citations
- [ ] `answer` explains assay format differences (TR-FRET, AlphaScreen)

**Query 2: Toxicity**
- [ ] `conflicts` contains `conflict_type: EVOLVING_DATA` for thrombocytopenia
- [ ] `answer` notes 15% (paper1, early Phase I) vs 22% (paper5, updated) vs 41% (paper3, Phase II)
- [ ] `answer` explains these are different trial stages/timepoints, not a true contradiction
- [ ] `context_expansion_triggered: false` (EVOLVING_DATA doesn't trigger expansion)

**Query 3: Mechanism of Action** ← Most important
- [ ] `conflicts` contains `conflict_type: CONCEPTUAL`
- [ ] `context_expansion_triggered: true` ← this is the required "conflict changes behavior" case
- [ ] `trace` shows `ConflictAgent.ContextExpansion` steps for paper1 and paper4
- [ ] `answer` explains competitive (paper1) vs allosteric (paper4) and why paper4's 1.8Å crystal structure is more authoritative

**Query 4: Clinical Trials**
- [ ] `answer` mentions NCT05123456 (paper1, paper5) and NCT05234567 (paper3)
- [ ] ORR evolution noted: 33% (paper1, n=12) → 42% (paper5, n=24) classified as EVOLVING_DATA
- [ ] Multiple indications covered: AML, DLBCL, r/r hematologic malignancies

**Query 5: Resistance Mechanisms**
- [ ] BRD4 phosphorylation at S492/S498 mentioned (paper3)
- [ ] CK2 as responsible kinase noted (paper5)
- [ ] Papers treated as complementary (converging evidence), not conflicting
- [ ] Classified as NON_CONFLICT or ASSAY_VARIABILITY (prevalence difference: 64% vs 37.5%)

---

### PHASE 3 — Run tests

```bash
py -3 -m pytest tests/ -v --cov=src --cov-report=term-missing
```

**Target: all 24 tests passing.** Key tests to verify manually:

| Test | What to check |
|------|--------------|
| `test_conflict_agent.py::test_conceptual_conflict_triggers_expansion` | `requires_expansion=True` and expansion results returned |
| `test_conflict_agent.py::test_evolving_data_not_classified_as_conceptual` | Paper1 vs Paper5 thrombocytopenia → `EVOLVING_DATA` |
| `test_synthesis_agent.py::test_synthesis_cites_all_papers` | All [Paper1]-[Paper5] in output |
| `test_context_manager.py::test_compression_triggers_at_hot_limit` | Warm non-empty after HOT_LIMIT messages |
| `test_api.py::test_query_endpoint_returns_result` | 200 response with QueryResult schema |

If tests fail, debug before proceeding.

---

### PHASE 4 — Build Frontend

```bash
cd frontend
npx create-next-app@latest . --typescript --tailwind --app --no-git --yes
npm install @testing-library/react @testing-library/jest-dom jest jest-environment-jsdom msw
```

**Components to build (in order):**

#### `src/components/ConflictBadge.tsx`
Simplest component, build first to establish the type system.
```
Props: { conflictType: "ASSAY_VARIABILITY" | "METHODOLOGY" | "CONCEPTUAL" | "EVOLVING_DATA" | "NON_CONFLICT" }
Colors: CONCEPTUAL=red-600, METHODOLOGY=orange-500, ASSAY_VARIABILITY=yellow-500, EVOLVING_DATA=blue-500, NON_CONFLICT=green-500
```

#### `src/components/TraceViewer.tsx`
```
Props: { trace: TraceStep[] }
UI: Collapsible accordion. Each step shows agent name, latency, input/output summary.
Default: all collapsed. Context expansion steps highlighted in orange.
```

#### `src/components/ResultCard.tsx`
```
Props: { result: QueryResult }
Sections:
  - Answer (with [PaperN] citations rendered as highlighted spans)
  - Conflicts list (ConflictBadge + reasoning text)
  - Papers cited (list)
  - Context expansion badge (if triggered)
  - TraceViewer (collapsed by default)
```

#### `src/components/QueryBox.tsx`
```
Props: none (manages own state)
UI:
  - Text input for query
  - Submit button (disabled while loading)
  - Quick-select chips for the 5 test queries (one-click to populate + submit)
  - Phase progress indicator: "Retrieving..." → "Detecting conflicts..." → "Synthesizing..."
  - Error display on failure
```

#### `src/app/page.tsx`
Compose QueryBox + ResultCard. Handle API call to `NEXT_PUBLIC_API_URL/query`.

**Frontend tests (after components built):**
```bash
cd frontend && npm test -- --watchAll=false
```

Tests needed:
- `ConflictBadge.test.tsx` — each type renders correct color class
- `TraceViewer.test.tsx` — steps collapsed by default, expand on click
- `ResultCard.test.tsx` — conflicts render badges, citations render as spans
- `QueryBox.test.tsx` — quick-select chip populates input, submit triggers API call

---

### PHASE 5 — Final checks before submission

**Checklist:**
- [ ] `outputs/` has 5+ JSON files (one per test query, at minimum)
- [ ] At least one output has `context_expansion_triggered: true` (query 3 — MoA)
- [ ] All 5 outputs show conflicts detected
- [ ] All 5 outputs cite multiple papers
- [ ] IND template output exists (run with `--ind-template`)
- [ ] `py -3 -m pytest tests/ -v` — all 24 passing
- [ ] `cd frontend && npm test -- --watchAll=false` — all passing
- [ ] `py -3 -m uvicorn src.api:app --port 8000` starts without error
- [ ] `cd frontend && npm run build` — no TypeScript errors
- [ ] `.env` is in `.gitignore` — never commit credentials
- [ ] `RAG-home assement copy 4/` folder removed from repo (it's a duplicate)
- [ ] README.md is complete and accurate

**Final `git status` should show:**
```
README.md
CLAUDE.md
main.py
requirements.txt
.env.example
src/ (all files)
supabase/ (migrations + seed)
tests/ (all files)
frontend/ (all files)
outputs/ (5+ JSON files)
data/ (original JSONs)
```

---

### PHASE 6 — Submission

Per Yannick's email:
1. Push to a **public** GitHub repo
2. Email Yannick the repo URL
3. **Attach Claude Code session logs** — Yannick specifically asked for these

**Claude Code session export:**
The conversation history is saved automatically. When submitting, include this conversation as a log file or share the Claude Code session trace. This demonstrates how the tooling was used, which Yannick explicitly requested.

---

## Bug to Watch For

**Issue:** `QueryResult.timestamp` is `datetime` in models.py but `run_query()` sets `timestamp=datetime.utcnow()` — Pydantic v2 serializes this correctly, but if you see a serialization error, change to `timestamp: str` with `Field(default_factory=lambda: datetime.utcnow().isoformat())`.

**Issue:** LangGraph's `add_conditional_edges` with `route_after_synthesis` returning `list[Send]` — if you get a graph compilation error, ensure LangGraph version is `>=0.2.28` which added stable `Send` support in conditional edge functions.

**Issue:** Supabase `match_chunks` RPC — the `filter_paper_id` parameter must exactly match the `paper_id` column values. If retrieval returns 0 results, check that `seed_papers.py` set `paper_id` to the same strings as `PAPER_IDS` in `config.py`.

---

## Time Estimate for Remaining Work

| Task | Est. Time |
|------|-----------|
| Supabase setup + migrations | 15 min |
| Seed papers + verify | 10 min |
| Run 5 test queries + verify outputs | 20 min |
| Run IND template + verify | 10 min |
| Debug any test failures | 20 min |
| Build frontend (4 components + tests) | 60 min |
| Final checks + push | 15 min |
| **Total** | **~2.5 hours** |
