import { render, screen } from "@testing-library/react";
import ConflictBadge from "@/components/ConflictBadge";
import { ConflictType } from "@/types";

describe("ConflictBadge", () => {
  it("renders correct label for CONCEPTUAL conflict type", () => {
    render(<ConflictBadge conflictType="CONCEPTUAL" />);
    expect(screen.getByText("Conceptual Conflict")).toBeInTheDocument();
  });

  it("renders correct label for METHODOLOGY conflict type", () => {
    render(<ConflictBadge conflictType="METHODOLOGY" />);
    expect(screen.getByText("Methodology")).toBeInTheDocument();
  });

  it("renders correct label for ASSAY_VARIABILITY conflict type", () => {
    render(<ConflictBadge conflictType="ASSAY_VARIABILITY" />);
    expect(screen.getByText("Assay Variability")).toBeInTheDocument();
  });

  it("renders correct label for EVOLVING_DATA conflict type", () => {
    render(<ConflictBadge conflictType="EVOLVING_DATA" />);
    expect(screen.getByText("Evolving Data")).toBeInTheDocument();
  });

  it("renders correct label for NON_CONFLICT conflict type", () => {
    render(<ConflictBadge conflictType="NON_CONFLICT" />);
    expect(screen.getByText("Non-Conflict")).toBeInTheDocument();
  });

  it("applies correct color class for CONCEPTUAL (red)", () => {
    render(<ConflictBadge conflictType="CONCEPTUAL" />);
    const badge = screen.getByTestId("conflict-badge");
    expect(badge.className).toMatch(/red/);
  });

  it("applies correct color class for EVOLVING_DATA (blue)", () => {
    render(<ConflictBadge conflictType="EVOLVING_DATA" />);
    const badge = screen.getByTestId("conflict-badge");
    expect(badge.className).toMatch(/blue/);
  });

  it("renders sm size correctly", () => {
    render(<ConflictBadge conflictType="NON_CONFLICT" size="sm" />);
    const badge = screen.getByTestId("conflict-badge");
    // sm size uses px-2 py-0.5 text-xs gap-1
    expect(badge.className).toMatch(/px-2/);
    expect(screen.getByText("Non-Conflict")).toBeInTheDocument();
  });

  it("sets data-conflict-type attribute correctly", () => {
    const conflictType: ConflictType = "ASSAY_VARIABILITY";
    render(<ConflictBadge conflictType={conflictType} />);
    const badge = screen.getByTestId("conflict-badge");
    expect(badge).toHaveAttribute("data-conflict-type", conflictType);
  });
});
