-- Create the paper_summaries table for storing WARM context summaries
CREATE TABLE IF NOT EXISTS paper_summaries (
    paper_id          text PRIMARY KEY,
    title             text,
    authors           text[],
    publication_date  date,
    journal           text,
    sample_size       integer,
    page_count        integer,
    summary           text,   -- LLM-generated WARM context summary
    created_at        timestamptz DEFAULT now()
);
