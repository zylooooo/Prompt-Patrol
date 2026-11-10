import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import BatchTab from "../BatchTab";
import * as batchesApi from "../../api/batches";
import * as checksApi from "../../api/checks";
import { ToastProvider } from "../ToastProvider";
import { installDomStubs } from "../../test/dom-stubs";
import { clearPreviousUserData } from "../../api/auth";
import { clearBatchDraft, readBatchDraft } from "../../lib/checkDraft";

/** A picked-but-not-started CSV survives leaving the page via the sidebar. */

vi.mock("../../hooks/useAuth", () => ({
  useAuth: () => ({
    user: { id: "u1", email: "i@smu.edu.sg", role: "instructor" },
  }),
}));

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <BatchTab />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

const CSV = new File(
  [
    "Student ID,Response\nstu-1,This answer is long enough to pass every rule.\n",
  ],
  "answers.csv",
  { type: "text/csv" },
);

async function pickAndMap() {
  fireEvent.change(screen.getByLabelText(/upload/i, { selector: "input" }), {
    target: { files: [CSV] },
  });
  fireEvent.change(await screen.findByLabelText("Student ID"), {
    target: { value: "external_ref" },
  });
}

beforeEach(() => {
  installDomStubs();
  clearBatchDraft();
  vi.spyOn(checksApi, "hasScreeningAccess").mockReturnValue(true);
});
afterEach(() => cleanup());

describe("BatchTab draft", () => {
  it("keeps the picked CSV and its column mapping when the page remounts", async () => {
    renderTab();
    await pickAndMap();
    cleanup(); // leaving via the sidebar unmounts the page

    renderTab();
    expect(screen.getByText("answers.csv")).toBeTruthy();
    expect(screen.getByLabelText<HTMLSelectElement>("Student ID").value).toBe(
      "external_ref",
    );
  });

  it("drops the draft once the batch starts", async () => {
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
    vi.spyOn(batchesApi, "getBatchProgress").mockReturnValue(
      new Promise(() => {}),
    );
    renderTab();
    await pickAndMap();
    fireEvent.change(screen.getByLabelText("Response"), {
      target: { value: "answer_text" },
    });
    expect(readBatchDraft("u1")).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /run/i }));
    await waitFor(() => expect(readBatchDraft("u1")).toBeNull());
  });

  it("drops the draft on sign-out or a change of user", async () => {
    renderTab();
    await pickAndMap();
    clearPreviousUserData();
    expect(readBatchDraft("u1")).toBeNull();
  });
});
