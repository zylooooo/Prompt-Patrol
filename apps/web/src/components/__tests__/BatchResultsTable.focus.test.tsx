import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import BatchResultsTable from "../BatchResultsTable";
import * as batchesApi from "../../api/batches";
import { installDomStubs } from "../../test/dom-stubs";
import type { BatchRow, BatchRun } from "../../types";

function row(i: number): BatchRow {
  return {
    checkId: `c${i}`,
    actorId: "a1",
    batchId: "b1",
    externalRef: `stu-${i}`,
    verdict: "human_written",
    rawScore: 0.1,
    confidence: null,
    abstainReason: null,
    truncated: null,
    detector: {
      modelVersion: "m1",
      calibrationVersion: null,
      strictnessApplied: "standard",
      thresholdApplied: null,
      targetFpr: null,
      usedQuestionText: false,
    },
    answerText: `Answer ${i}`,
    questionText: null,
    explanation: null,
    createdAt: `2026-09-09T00:00:${String(i).padStart(2, "0")}Z`,
    latencyMs: null,
  };
}

const run: BatchRun = {
  id: "b1",
  kind: "batch",
  fileName: "answers.csv",
  createdAt: "2026-09-09T00:00:00Z",
  strictness: "standard",
  rows: Array.from({ length: 12 }, (_, i) => row(i + 1)),
  counts: { ai_generated: 0, uncertain: 0, human_written: 12 },
  failures: [],
};

function renderTable() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BatchResultsTable run={run} />
    </QueryClientProvider>,
  );
}

describe("BatchResultsTable detail focus", () => {
  const scrollIntoView = vi.fn();

  beforeEach(() => {
    installDomStubs();
    Element.prototype.scrollIntoView = scrollIntoView;
    vi.spyOn(batchesApi, "getBatchProgress").mockReturnValue(
      new Promise(() => {}),
    );
  });

  afterEach(() => {
    cleanup();
    scrollIntoView.mockClear();
  });

  it("moves focus and scroll to the detail heading when View is clicked", () => {
    renderTable();
    fireEvent.click(screen.getAllByRole("button", { name: "View" })[1]);

    const heading = screen.getByRole("heading", { name: "Details for stu-2" });
    expect(document.activeElement).toBe(heading);
    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: "smooth",
      block: "start",
    });
  });

  it("moves focus to the new detail when another row is opened", () => {
    renderTable();
    fireEvent.click(screen.getAllByRole("button", { name: "View" })[0]);
    // stu-1's button now reads "Hide", so index 1 of the "View"s is stu-3.
    fireEvent.click(screen.getAllByRole("button", { name: "View" })[1]);
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "Details for stu-3" }),
    );
  });

  it("returns focus to the row's View button on Back to results", () => {
    renderTable();
    fireEvent.click(screen.getAllByRole("button", { name: "View" })[1]);
    fireEvent.click(screen.getByRole("button", { name: "Back to results" }));

    expect(screen.queryByRole("heading", { name: /Details for/ })).toBeNull();
    expect(document.activeElement).toBe(
      screen.getAllByRole("button", { name: "View" })[1],
    );
  });

  it("Escape closes the detail and returns to the row's page", () => {
    renderTable();
    fireEvent.click(screen.getAllByRole("button", { name: "View" })[0]);
    // Page away while the detail stays open, then close it.
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    fireEvent.keyDown(
      screen.getByRole("heading", { name: "Details for stu-1" }),
      { key: "Escape" },
    );

    const focused = document.activeElement as HTMLElement;
    expect(focused.textContent).toBe("View");
    expect(screen.getByText("stu-1")).toBeTruthy();
  });
});
