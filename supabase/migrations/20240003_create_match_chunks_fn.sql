-- Create the match_chunks function for vector similarity search
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
