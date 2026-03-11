-- Enable Row Level Security on both tables
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE paper_summaries ENABLE ROW LEVEL SECURITY;

-- Policy: service_role has full access to chunks
CREATE POLICY "service_role_full_access_chunks"
    ON chunks
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Policy: service_role has full access to paper_summaries
CREATE POLICY "service_role_full_access_paper_summaries"
    ON paper_summaries
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
