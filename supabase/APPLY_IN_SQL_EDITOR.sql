-- =============================================================
-- FULL SCHEMA SETUP — paste this entire file into
-- Supabase Dashboard → SQL Editor → New Query → Run
-- =============================================================

-- 1. Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. chunks table
CREATE TABLE IF NOT EXISTS chunks (
    id          text PRIMARY KEY,
    paper_id    text NOT NULL,
    chunk_type  text CHECK (chunk_type IN ('text', 'table')),
    content     text,
    section     text,
    page        integer,
    grounding   jsonb,
    embedding   vector(1536),
    created_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS paper_id_idx ON chunks (paper_id);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);

-- 3. match_chunks RPC function
CREATE OR REPLACE FUNCTION match_chunks(
    query_embedding  vector(1536),
    filter_paper_id  text,
    match_count      int DEFAULT 2
)
RETURNS TABLE (
    id          text,
    paper_id    text,
    chunk_type  text,
    content     text,
    section     text,
    page        integer,
    grounding   jsonb,
    similarity  float
)
LANGUAGE sql STABLE
AS $$
    SELECT
        c.id,
        c.paper_id,
        c.chunk_type,
        c.content,
        c.section,
        c.page,
        c.grounding,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM chunks c
    WHERE c.paper_id = filter_paper_id
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- 4. paper_summaries table
CREATE TABLE IF NOT EXISTS paper_summaries (
    paper_id          text PRIMARY KEY,
    title             text,
    authors           text[],
    publication_date  date,
    journal           text,
    sample_size       integer,
    page_count        integer,
    summary           text,
    created_at        timestamptz DEFAULT now()
);

-- 5. RLS policies
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_summaries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_full_access_chunks"
    ON chunks FOR ALL TO service_role
    USING (true) WITH CHECK (true);

CREATE POLICY "service_role_full_access_paper_summaries"
    ON paper_summaries FOR ALL TO service_role
    USING (true) WITH CHECK (true);

-- anon read access (needed if you want the frontend to query directly)
CREATE POLICY "anon_read_chunks"
    ON chunks FOR SELECT TO anon
    USING (true);

CREATE POLICY "anon_read_summaries"
    ON paper_summaries FOR SELECT TO anon
    USING (true);
