# Supabase Migrations

Run all migrations in order with:
```bash
supabase db push
```

Or individually:
```bash
supabase migration up
```

---

## Migration Files

### `20240001_enable_pgvector.sql`
**What it does:** Enables the `pgvector` PostgreSQL extension in the `extensions` schema.

This is always the first migration — every other migration depends on the `vector` type that pgvector provides. Without this, the `chunks` table cannot store embedding columns and `match_chunks` cannot use cosine similarity operators.

---

### `20240002_create_chunks_table.sql`
**What it does:** Creates the `chunks` table — the primary storage for all paper content and embeddings.

**Schema:**
| Column | Type | Purpose |
|--------|------|---------|
| `id` | `text PK` | Chunk UUID from the source paper JSON |
| `paper_id` | `text` | Which of the 5 papers this chunk belongs to (e.g. `paper1_nvx0228_novel_inhibitor`) |
| `chunk_type` | `text` | `'text'` or `'table'` — table chunks get higher weight in conflict detection |
| `content` | `text` | The actual chunk text, pre-cleaned (no HTML, no noise) |
| `section` | `text` | Paper section (e.g. `Results - Clinical Safety`) |
| `page` | `integer` | Page number in the source PDF |
| `grounding` | `jsonb` | Bounding box `{left, top, right, bottom}` for source traceability |
| `embedding` | `vector(1536)` | OpenAI `text-embedding-3-small` embedding |
| `created_at` | `timestamptz` | Ingestion timestamp |

**Indexes:**
- `chunks_paper_id_idx` — B-tree index on `paper_id` so the `match_chunks` RPC can filter by paper efficiently before doing ANN search
- `chunks_embedding_idx` — IVFFlat index with `lists=10`, `vector_cosine_ops` — enables fast approximate nearest-neighbor search using cosine similarity

---

### `20240003_create_match_chunks_fn.sql`
**What it does:** Creates the `match_chunks` Postgres function — the core retrieval primitive for all 5 PaperAgents.

**Signature:**
```sql
match_chunks(
  query_embedding vector(1536),
  filter_paper_id text,
  match_count     int default 2
)
```

**What it returns:** The top-`match_count` chunks from `filter_paper_id` ordered by cosine similarity to `query_embedding`, with a computed `similarity` column (`1 - cosine_distance`).

**Why this function exists instead of a raw query:** The per-paper filtering (`WHERE paper_id = filter_paper_id`) happens *before* the vector ANN search. This is the critical architectural decision: rather than running a global similarity search and hoping all 5 papers appear in the top-10 results, each PaperAgent calls this function with its own `paper_id` — guaranteeing retrieval from every paper regardless of which paper happens to be most similar to the query overall.

**Called from:** `src/embeddings.py → search_paper()` → used by `src/agents/paper_agent.py`

---

### `20240004_create_paper_summaries.sql`
**What it does:** Creates the `paper_summaries` table — the **WARM context tier** storage.

**Schema:**
| Column | Type | Purpose |
|--------|------|---------|
| `paper_id` | `text PK` | Matches the paper IDs used in `chunks` |
| `title` | `text` | Full paper title |
| `authors` | `text[]` | Author list |
| `publication_date` | `date` | Used by ConflictAgent to detect EVOLVING_DATA |
| `journal` | `text` | Journal name |
| `sample_size` | `integer` | Trial/study sample size |
| `page_count` | `integer` | PDF page count |
| `summary` | `text` | LLM-generated summary of the paper's key claims |
| `created_at` | `timestamptz` | Generation timestamp |

**What the `summary` column contains:** At ingest time (`supabase/seed/seed_papers.py`), a GPT-4o-mini call generates a structured summary of each paper covering: key IC50 values, toxicity findings, mechanism of action claims, clinical trial NCT numbers, and sample sizes. This becomes the **WARM tier** of the context manager — pre-computed once, reused on every query without additional LLM calls.

**Why this matters for context management:** Instead of passing all 8 chunks from each paper to every agent (40 chunks × ~500 tokens = 20K tokens per call), each PaperAgent passes its 2 HOT retrieved chunks + the pre-built WARM summary. The summary provides background context without the full token cost.

---

### `20240005_rls_policies.sql`
**What it does:** Enables Row Level Security (RLS) on both tables and grants full access to the `service_role`.

**Policies created:**
- `service_role_all_chunks` — `service_role` can SELECT/INSERT/UPDATE/DELETE on `chunks`
- `service_role_all_summaries` — `service_role` can SELECT/INSERT/UPDATE/DELETE on `paper_summaries`

**Why RLS is enabled:** Supabase best practice — even for a backend-only service, enabling RLS means the `anon` key (used by frontend clients) cannot access the data directly. Only the `SUPABASE_SERVICE_KEY` (backend only, never exposed to the browser) can read and write. This means the FastAPI backend is the only path to the data.

**Env var used:** `SUPABASE_SERVICE_KEY` in `.env` — always use the service role key server-side, never the anon key.
