import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QueryBox from "@/components/QueryBox";
import { QueryResult } from "@/types";

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockQueryResult: QueryResult = {
  query: "What is the IC50 of NVX-0228?",
  answer: "The IC50 is approximately 2.3 nM [Paper1].",
  conflicts: [],
  papers_cited: ["paper_001"],
  context_expansion_triggered: false,
  trace: [],
  timestamp: "2024-01-15T10:00:00Z",
};

const noop = () => {};

describe("QueryBox", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders query input", () => {
    render(
      <QueryBox onResult={noop} onLoading={noop} onError={noop} />
    );
    expect(screen.getByTestId("query-input")).toBeInTheDocument();
  });

  it("renders all 5 quick-select chips", () => {
    render(
      <QueryBox onResult={noop} onLoading={noop} onError={noop} />
    );
    const chips = screen.getAllByTestId("query-chip");
    expect(chips).toHaveLength(5);
  });

  it("submit button disabled when input is empty", () => {
    render(
      <QueryBox onResult={noop} onLoading={noop} onError={noop} />
    );
    const submitBtn = screen.getByTestId("submit-button");
    expect(submitBtn).toBeDisabled();
  });

  it("submit button enabled when input has text", async () => {
    const user = userEvent.setup();
    render(
      <QueryBox onResult={noop} onLoading={noop} onError={noop} />
    );
    const input = screen.getByTestId("query-input");
    await user.type(input, "What is the IC50?");
    const submitBtn = screen.getByTestId("submit-button");
    expect(submitBtn).not.toBeDisabled();
  });

  it("clicking chip populates input", async () => {
    const user = userEvent.setup();
    // Mock fetch to prevent actual network call when chip is clicked
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockQueryResult,
    });

    render(
      <QueryBox onResult={noop} onLoading={noop} onError={noop} />
    );
    const chips = screen.getAllByTestId("query-chip");
    await user.click(chips[0]);

    // Input should be populated with first chip's query text
    const input = screen.getByTestId("query-input") as HTMLTextAreaElement;
    expect(input.value).toBe("What is the IC50 of NVX-0228?");
  });

  it("calls onLoading when form submitted (mock fetch)", async () => {
    const user = userEvent.setup();
    const onLoading = jest.fn();
    const onResult = jest.fn();
    const onError = jest.fn();

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockQueryResult,
    });

    render(
      <QueryBox onResult={onResult} onLoading={onLoading} onError={onError} />
    );

    const input = screen.getByTestId("query-input");
    await user.type(input, "What is the IC50?");
    await user.click(screen.getByTestId("submit-button"));

    expect(onLoading).toHaveBeenCalledWith(true, expect.any(String));

    await waitFor(() => {
      expect(onResult).toHaveBeenCalledWith(mockQueryResult);
    });

    expect(onLoading).toHaveBeenCalledWith(false, "");
  });

  it("calls onError on fetch failure", async () => {
    const user = userEvent.setup();
    const onError = jest.fn();
    const onLoading = jest.fn();

    mockFetch.mockRejectedValueOnce(new Error("Network failure"));

    render(
      <QueryBox onResult={noop} onLoading={onLoading} onError={onError} />
    );

    const input = screen.getByTestId("query-input");
    await user.type(input, "What is the IC50?");
    await user.click(screen.getByTestId("submit-button"));

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith(expect.any(String));
    });
  });

  it("calls onError on non-ok HTTP response", async () => {
    const user = userEvent.setup();
    const onError = jest.fn();

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ detail: "Internal server error" }),
    });

    render(
      <QueryBox onResult={noop} onLoading={jest.fn()} onError={onError} />
    );

    const input = screen.getByTestId("query-input");
    await user.type(input, "What is the IC50?");
    await user.click(screen.getByTestId("submit-button"));

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith("Internal server error");
    });
  });

  it("renders submit button with correct initial text", () => {
    render(
      <QueryBox onResult={noop} onLoading={noop} onError={noop} />
    );
    expect(screen.getByTestId("submit-button")).toHaveTextContent("Analyze");
  });
});
