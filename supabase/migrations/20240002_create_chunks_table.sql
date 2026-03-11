-- Create the chunks table for storing paper chunks with embeddings
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

-- Index for efficient paper_id lookups
CREATE INDEX IF NOT EXISTS paper_id_idx ON chunks (paper_id);

-- IVFFlat index for approximate nearest-neighbor search using cosine distance
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
