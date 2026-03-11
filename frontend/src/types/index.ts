export type ConflictType =
  | "ASSAY_VARIABILITY"
  | "METHODOLOGY"
  | "CONCEPTUAL"
  | "EVOLVING_DATA"
  | "NON_CONFLICT";

export interface Chunk {
  id: string;
  paper_id: string;
  chunk_type: string;
  content: string;
  section?: string;
  page?: number;
  grounding?: Record<string, unknown>;
}

export interface RetrievedChunk {
  chunk: Chunk;
  similarity: number;
  paper_title?: string;
  paper_authors?: string[];
  publication_date?: string;
  journal?: string;
  sample_size?: number;
}

export interface ExtractedClaim {
  paper_id: string;
  property: string;
  value: string;
  context: string;
  chunk_id: string;
  confidence: number;
}

export interface Conflict {
  property: string;
  conflict_type: ConflictType;
  papers_involved: string[];
  claims: ExtractedClaim[];
  reasoning: string;
  resolution?: string;
  requires_expansion: boolean;
}

export interface TraceStep {
  step: string;
  agent: string;
  input_summary: string;
  output_summary: string;
  tokens_used: number;
  latency_ms: number;
  timestamp: string;
}

export interface QueryResult {
  query: string;
  answer: string;
  conflicts: Conflict[];
  papers_cited: string[];
  context_expansion_triggered: boolean;
  trace: TraceStep[];
  timestamp: string;
}
