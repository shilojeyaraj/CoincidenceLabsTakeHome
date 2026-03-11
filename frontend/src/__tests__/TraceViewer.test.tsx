import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TraceViewer from "@/components/TraceViewer";
import { TraceStep } from "@/types";

const mockTrace: TraceStep[] = [
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
    input_summary: "Expanding context for CONCEPTUAL conflict on IC50 property",
    output_summary: "Fetched 4 additional chunks from papers 2 and 3",
    tokens_used: 256,
    latency_ms: 198,
    timestamp: "2024-01-15T10:00:01Z",
  },
  {
    step: "SynthesisAgent.AnswerGeneration",
    agent: "SynthesisAgent",
    input_summary: "Synthesizing answer from 12 chunks",
    output_summary: "Generated comprehensive answer with citations",
    tokens_used: 1024,
    latency_ms: 2100,
    timestamp: "2024-01-15T10:00:03Z",
  },
];

describe("TraceViewer", () => {
  it("renders 'Show Trace' button", () => {
    render(<TraceViewer trace={mockTrace} />);
    expect(screen.getByTestId("trace-toggle")).toBeInTheDocument();
    expect(screen.getByTestId("trace-toggle")).toHaveTextContent("Show Trace");
  });

  it("trace steps are hidden by default", () => {
    render(<TraceViewer trace={mockTrace} />);
    const steps = screen.queryAllByTestId("trace-step");
    expect(steps).toHaveLength(0);
  });

  it("clicking toggle shows trace steps", async () => {
    const user = userEvent.setup();
    render(<TraceViewer trace={mockTrace} />);

    const toggleBtn = screen.getByTestId("trace-toggle");
    await user.click(toggleBtn);

    const steps = screen.getAllByTestId("trace-step");
    expect(steps).toHaveLength(mockTrace.length);
  });

  it("context expansion step has orange styling", async () => {
    const user = userEvent.setup();
    render(<TraceViewer trace={mockTrace} />);

    await user.click(screen.getByTestId("trace-toggle"));

    const steps = screen.getAllByTestId("trace-step");
    // Second step is the context expansion step (index 1)
    const expansionStep = steps[1];
    expect(expansionStep.className).toMatch(/orange/);
  });

  it("renders correct agent names", async () => {
    const user = userEvent.setup();
    render(<TraceViewer trace={mockTrace} />);

    await user.click(screen.getByTestId("trace-toggle"));

    expect(screen.getByText("RetrievalAgent")).toBeInTheDocument();
    expect(screen.getByText("ConflictAgent")).toBeInTheDocument();
    expect(screen.getByText("SynthesisAgent")).toBeInTheDocument();
  });

  it("renders latency for each step", async () => {
    const user = userEvent.setup();
    render(<TraceViewer trace={mockTrace} />);

    await user.click(screen.getByTestId("trace-toggle"));

    expect(screen.getByText("342ms")).toBeInTheDocument();
    expect(screen.getByText("198ms")).toBeInTheDocument();
    expect(screen.getByText("2100ms")).toBeInTheDocument();
  });

  it("clicking toggle again hides trace steps", async () => {
    const user = userEvent.setup();
    render(<TraceViewer trace={mockTrace} />);

    const toggleBtn = screen.getByTestId("trace-toggle");
    await user.click(toggleBtn);
    expect(screen.getAllByTestId("trace-step")).toHaveLength(mockTrace.length);

    await user.click(toggleBtn);
    expect(screen.queryAllByTestId("trace-step")).toHaveLength(0);
  });
});
