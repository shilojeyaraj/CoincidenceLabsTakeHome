import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ResultCard from "@/components/ResultCard";
import { QueryResult } from "@/types";

export const mockQueryResult: QueryResult = {
  query: "What is the IC50 of NVX-0228?",
  answer:
    "NVX-0228 shows an IC50 of 2.3 nM in cell-free assays [Paper1], however a separate study reports 4.7 nM using a different assay format [Paper2]. The discrepancy is attributed to assay variability.",
  conflicts: [
    {
      property: "IC50 value",
      conflict_type: "CONCEPTUAL",
      papers_involved: ["paper_001", "paper_002"],
      claims: [
        {
          paper_id: "paper_001",
          property: "IC50",
          value: "2.3 nM",
          context: "Cell-free kinase assay",
          chunk_id: "chunk_001",
          confidence: 0.92,
        },
        {
          paper_id: "paper_002",
          property: "IC50",
          value: "4.7 nM",
          context: "Alternative assay format",
          chunk_id: "chunk_002",
          confidence: 0.88,
        },
      ],
      reasoning:
        "Two papers report conflicting IC50 values for NVX-0228. Paper 1 reports 2.3 nM while Paper 2 reports 4.7 nM. This conceptual conflict arises from fundamental differences in experimental interpretation rather than methodology alone.",
      resolution: "Further validation recommended using standardized assays.",
      requires_expansion: true,
    },
    {
      property: "Assay method",
      conflict_type: "ASSAY_VARIABILITY",
      papers_involved: ["paper_001", "paper_003"],
      claims: [
        {
          paper_id: "paper_001",
          property: "assay_type",
          value: "cell-free kinase assay",
          context: "Standard biochemical assay",
          chunk_id: "chunk_003",
          confidence: 0.95,
        },
        {
          paper_id: "paper_003",
          property: "assay_type",
          value: "cellular thermal shift assay",
          context: "Cell-based assay",
          chunk_id: "chunk_004",
          confidence: 0.91,
        },
      ],
      reasoning:
        "The difference in IC50 values between papers is explained by different assay methodologies. This is an assay variability conflict, not a conceptual disagreement.",
      requires_expansion: false,
    },
  ],
  papers_cited: ["paper_001", "paper_002", "paper_003"],
  context_expansion_triggered: true,
  trace: [
    {
      step: "RetrievalAgent.VectorSearch",
      agent: "RetrievalAgent",
      input_summary: "Query: What is the IC50 of NVX-0228?",
      output_summary: "Retrieved 8 chunks with similarity > 0.75",
      tokens_used: 512,
      latency_ms: 342,
      timestamp: "2024-01-15T10:00:00Z",
    },
    {
      step: "ConflictAgent.ContextExpansion",
      agent: "ConflictAgent",
      input_summary: "Expanding context for CONCEPTUAL conflict",
      output_summary: "Fetched 4 additional chunks",
      tokens_used: 256,
      latency_ms: 198,
      timestamp: "2024-01-15T10:00:01Z",
    },
  ],
  timestamp: "2024-01-15T10:00:05Z",
};

describe("ResultCard", () => {
  it("renders answer text", () => {
    render(<ResultCard result={mockQueryResult} />);
    const answerEl = screen.getByTestId("answer-text");
    expect(answerEl).toBeInTheDocument();
    // Check for partial text content (citations are split into spans)
    expect(answerEl.textContent).toContain("NVX-0228 shows an IC50");
  });

  it("renders conflict badges for each conflict", () => {
    render(<ResultCard result={mockQueryResult} />);
    const conflictItems = screen.getAllByTestId("conflict-item");
    expect(conflictItems).toHaveLength(2);

    const badges = screen.getAllByTestId("conflict-badge");
    expect(badges).toHaveLength(2);
  });

  it("renders expansion banner when context_expansion_triggered=true", () => {
    render(<ResultCard result={mockQueryResult} />);
    const banner = screen.getByTestId("expansion-banner");
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain("Context expansion triggered");
  });

  it("does NOT render expansion banner when context_expansion_triggered=false", () => {
    const result = { ...mockQueryResult, context_expansion_triggered: false };
    render(<ResultCard result={result} />);
    expect(screen.queryByTestId("expansion-banner")).not.toBeInTheDocument();
  });

  it("renders papers cited list", () => {
    render(<ResultCard result={mockQueryResult} />);
    expect(screen.getByText("paper_001")).toBeInTheDocument();
    expect(screen.getByText("paper_002")).toBeInTheDocument();
    expect(screen.getByText("paper_003")).toBeInTheDocument();
  });

  it("[Paper1] citation in answer renders as badge", () => {
    render(<ResultCard result={mockQueryResult} />);
    // [Paper1] and [Paper2] should be rendered as badge spans inside answer-text
    const answerEl = screen.getByTestId("answer-text");
    // The citation badges are rendered as <span> elements inside the answer
    const citationBadges = Array.from(answerEl.querySelectorAll("span")).filter(
      (el) => /^\[Paper\d+\]$/.test(el.textContent?.trim() ?? "")
    );
    expect(citationBadges.length).toBeGreaterThan(0);
    expect(citationBadges[0].textContent).toBe("[Paper1]");
  });

  it("renders result-card container", () => {
    render(<ResultCard result={mockQueryResult} />);
    expect(screen.getByTestId("result-card")).toBeInTheDocument();
  });

  it("renders CONCEPTUAL conflict badge with correct type", () => {
    render(<ResultCard result={mockQueryResult} />);
    const conceptualBadge = screen
      .getAllByTestId("conflict-badge")
      .find((el) => el.getAttribute("data-conflict-type") === "CONCEPTUAL");
    expect(conceptualBadge).toBeTruthy();
  });

  it("renders ASSAY_VARIABILITY conflict badge with correct type", () => {
    render(<ResultCard result={mockQueryResult} />);
    const assayBadge = screen
      .getAllByTestId("conflict-badge")
      .find(
        (el) => el.getAttribute("data-conflict-type") === "ASSAY_VARIABILITY"
      );
    expect(assayBadge).toBeTruthy();
  });
});
