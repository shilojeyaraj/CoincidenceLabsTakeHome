# Testing Session Notes

_Session date: 2026-03-11. Full end-to-end testing run with live OpenAI API key._

---

## Summary

| Layer | Status | Tests |
|-------|--------|-------|
| Backend unit/integration (pytest) | ✅ All pass | 45 / 45 |
| Frontend unit (Jest) | ✅ All pass (after fix) | 34 / 34 |
| Backend live end-to-end (main.py) | ⛔ Blocked | Supabase schema not applied |
| Seeder (seed_papers.py) | ⛔ Blocked | Depends on schema |

---

## Phase 1 — Environment Check

### OpenAI API Key
- **Status: ✅ Working**
- Embedding API (`text-embedding-3-small`): responds correctly, 1536 dims
- Chat API (`gpt-4o-mini`): responds correctly, token counting verified
- `tokens_used` now correctly read from `response.usage.total_tokens` in all agents

### `.env` Issues Found and Fixed
1. **Line 6 malformed text** — the string `api openai` (no `=` sign) was present as a bare comment on line 6. This caused python-dotenv to emit a parse warning on every startup. **Fixed:** removed the line.
2. **`SUPABASE_SERVICE_KEY` appears to be the publishable key** — the key has the prefix `sb_publishable_` (46 chars). The correct key for seeding (bypassing RLS) is the `sb_secret_` key from the Supabase dashboard under **Project Settings → API → Secret key**. The publishable key may work for anon-read but will be rejected for write operations used by the seeder.

---

## Phase 2 — Backend Unit Tests (pytest)

**Result: 45 / 45 PASSED**

```
tests/test_api.py              14 passed
tests/test_conflict_agent.py    5 passed
tests/test_context_manager.py   7 passed  (includes new tests from last session)
tests/test_orchestrator.py      7 passed  (new — full LangGraph integration)
tests/test_paper_agent.py       8 passed  (includes 3 new edge case tests)
tests/test_synthesis_agent.py   4 passed
```

No regressions from the optimization work in the previous session.

---

## Phase 3 — Frontend Unit Tests (Jest)

**Result: 34 / 34 PASSED (after 1 fix)**

### Issue Found: `jest.config.ts` requires `ts-node`

**Error:**
```
Jest: 'ts-node' is required for the TypeScript configuration files.
Error: Cannot find package 'ts-node'
```

**Root cause:** Same pattern as `next.config.ts` from the previous session — Jest's bundled config loader can't run `.ts` config files without `ts-node` installed as a dev dependency.

**Fix:** Converted `jest.config.ts` → `jest.config.js` using CommonJS `module.exports`:
```js
const nextJest = require("next/jest.js");
const createJestConfig = nextJest({ dir: "./" });
const config = { testEnvironment: "jsdom", setupFilesAfterEnv: [...], ... };
module.exports = createJestConfig(config);
```

### Issue Found: `getByText` fails on duplicate text in `ResultCard.test.tsx`

**Error:**
```
TestingLibraryElementError: Found multiple elements with the text: paper_001
```

**Root cause:** `ResultCard` renders `paper_001` in multiple places simultaneously:
1. The "Papers Cited" pill badge list at the bottom
2. Inside the answer text (the mock answer text includes `[paper_001]` references)
3. Potentially in conflict claim metadata

The test used `screen.getByText(...)` which throws if >1 element matches.

**Fix:** Changed to `screen.getAllByText("paper_001").length` and asserted `>0`.

---

## Phase 4 — Supabase Schema Setup (BLOCKED)

### Status: ⛔ Schema not applied

**Error from `verify_schema()`:**
```
Schema verification failed: table 'chunks' is inaccessible.
Error: Could not find the table 'public.chunks' in the schema cache
Code: PGRST205
```

**Root cause:** The 5 migration SQL files have never been applied to the Supabase project. The Supabase Python client cannot run DDL SQL directly — it requires either:
- The Supabase CLI (`supabase db push`)
- Manual paste into the SQL Editor

### Action Required (Manual)

1. Go to your Supabase project dashboard
2. Navigate to **SQL Editor → New Query**
3. Paste and run the entire contents of: `supabase/APPLY_IN_SQL_EDITOR.sql`
4. Verify by checking **Table Editor** — you should see `chunks` and `paper_summaries` tables

### Also Required: Get the Secret Key

The current `SUPABASE_SERVICE_KEY` in `.env` starts with `sb_publishable_` — this is the **anon/public** key.

The seeder needs the **service role** (secret) key to bypass Row Level Security when writing chunks:

1. Go to **Supabase Dashboard → Project Settings → API**
2. Copy the **Service Role Secret** key (starts with `sb_secret_` or the old `eyJ...` JWT format)
3. Update `.env`:
   ```
   SUPABASE_SERVICE_KEY=<paste secret key here>
   ```

---

## Phase 5 — Live End-to-End Run (PENDING)

Once schema is applied and secret key is updated, run in this order:

### Step 1 — Seed the database
```bash
py -3 supabase/seed/seed_papers.py
```

Expected output:
```
=== Processing paper1_nvx0228_novel_inhibitor (8 chunks) ===
  Embedding batches: 100%|████| 1/1
  Upserting 8 chunks...
  Generating WARM summary...
  Done with paper1_nvx0228_novel_inhibitor
... (repeat for all 5 papers)
Seeding complete!
```

### Step 2 — Verify schema
```bash
py -3 -c "from dotenv import load_dotenv; load_dotenv(); from src.db import verify_schema; verify_schema(); print('OK')"
```

### Step 3 — Run all 5 assignment queries
```bash
py -3 main.py --run-all
```

### Step 4 — Run IND template generation
```bash
py -3 main.py --run-all --ind-template
```

### Step 5 — Start backend API
```bash
uvicorn src.api:app --reload --port 8000
```

### Step 6 — Start frontend
```bash
cd frontend && npm run dev
```

---

## Bugs Fixed This Session

| # | Bug | File | Fix |
|---|-----|------|-----|
| 1 | `.env` line 6 malformed text causing dotenv parse warning | `.env` | Removed bare `api openai` line |
| 2 | `jest.config.ts` requires `ts-node` not installed | `frontend/jest.config.ts` | Converted to `jest.config.js` (CommonJS) |
| 3 | `getByText("paper_001")` fails — multiple elements match | `frontend/src/__tests__/ResultCard.test.tsx` | Changed to `getAllByText(...).length > 0` |

---

## Remaining Before Final Submission

- [ ] Apply `supabase/APPLY_IN_SQL_EDITOR.sql` in Supabase dashboard
- [ ] Update `SUPABASE_SERVICE_KEY` with the `sb_secret_` service role key
- [ ] Run `py -3 supabase/seed/seed_papers.py` to embed and load all 5 papers
- [ ] Run `py -3 main.py --run-all` and verify outputs are saved to `outputs/`
- [ ] Run `py -3 main.py --run-all --ind-template` for IND generation
- [ ] Commit the `outputs/` folder (sample results for submission)
- [ ] Delete `frontend/jest.config.ts.bak` (backup file from the config migration)
