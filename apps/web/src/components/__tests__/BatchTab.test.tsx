import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import BatchTab from "../BatchTab";
import * as batchesApi from "../../api/batches";
import * as checksApi from "../../api/checks";
import { ToastProvider } from "../ToastProvider";
import { installDomStubs } from "../../test/dom-stubs";

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

const CSV_NEEDS_MAPPING = new File(
  ["Student ID,Response\nstu-1,This answer is long enough to pass every rule.\n"],
  "answers.csv",
  { type: "text/csv" },
);

describe("BatchTab", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    installDomStubs();
    vi.spyOn(checksApi, "hasScreeningAccess").mockReturnValue(true);
    vi.spyOn(batchesApi, "requestUploadUrl").mockResolvedValue({
      uploadUrl: "https://example.com/put",
      uploadKey: "batches/key.csv",
    });
    vi.spyOn(batchesApi, "uploadFileToS3").mockResolvedValue(undefined);
    vi.spyOn(batchesApi, "createBatch").mockResolvedValue({
      batchId: "b1",
      actorId: "a1",
      fileName: "answers.csv",
      strictness: "standard",
      createdAt: "2026-09-09T00:00:00Z",
      rowTotal: 1,
    });
    vi.spyOn(batchesApi, "getBatchProgress").mockResolvedValue({
      batch: {
        batchId: "b1",
        actorId: "a1",
        fileName: "answers.csv",
        strictness: "standard",
        createdAt: "2026-09-09T00:00:00Z",
        rowTotal: 1,
      },
      completed: 1,
      failed: 0,
      pending: 0,
      rowTotal: 1,
      cancelled: false,
    });
  });

  it("shows a column-mapping step when the CSV headers don't match our field names", async () => {
    renderWithClient(<BatchTab />);
    const input = screen.getByLabelText(/upload/i, { selector: "input" });
    fireEvent.change(input, { target: { files: [CSV_NEEDS_MAPPING] } });

    expect(await screen.findByText(/map your columns/i)).toBeTruthy();
    expect(screen.getByText("Student ID")).toBeTruthy();
    expect(screen.getByText("Response")).toBeTruthy();
  });

  it("submits the batch via upload-url + S3 PUT + createBatch, then polls progress", async () => {
    renderWithClient(<BatchTab />);
    const input = screen.getByLabelText(/upload/i, { selector: "input" });
    fireEvent.change(input, { target: { files: [CSV_NEEDS_MAPPING] } });

    fireEvent.change(await screen.findByLabelText("Student ID"), {
      target: { value: "external_ref" },
    });
    fireEvent.change(screen.getByLabelText("Response"), {
      target: { value: "answer_text" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    await waitFor(() => expect(batchesApi.requestUploadUrl).toHaveBeenCalledWith("answers.csv"));
    expect(batchesApi.uploadFileToS3).toHaveBeenCalledWith(
      "https://example.com/put",
      CSV_NEEDS_MAPPING,
    );
    expect(batchesApi.createBatch).toHaveBeenCalledWith(
      "batches/key.csv",
      expect.objectContaining({
        fileName: "answers.csv",
        columnMapping: { "Student ID": "external_ref", Response: "answer_text" },
      }),
    );
    await waitFor(() => expect(batchesApi.getBatchProgress).toHaveBeenCalledWith("b1", expect.anything()));
  });
});
