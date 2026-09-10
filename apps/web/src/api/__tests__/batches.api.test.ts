import { describe, expect, it, vi, beforeEach } from "vitest";
import * as client from "../client";
import {
  cancelBatch,
  createBatch,
  getBatchProgress,
  requestUploadUrl,
} from "../batches";

describe("batches api", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("requestUploadUrl posts the file name and returns the presigned url/key", async () => {
    const spy = vi.spyOn(client, "apiRequest").mockResolvedValue({
      upload_url: "https://example.com/put",
      upload_key: "batches/key.csv",
    });

    const result = await requestUploadUrl("answers.csv");

    expect(spy).toHaveBeenCalledWith(
      "/api/batches/upload-url",
      expect.objectContaining({
        method: "POST",
        body: { file_name: "answers.csv" },
      }),
    );
    expect(result).toEqual({
      uploadUrl: "https://example.com/put",
      uploadKey: "batches/key.csv",
    });
  });

  it("createBatch posts upload_key/file_name/strictness/mapping", async () => {
    const spy = vi.spyOn(client, "apiRequest").mockResolvedValue({
      batch_id: "b1",
      actor_id: "a1",
      batch_file_name: "answers.csv",
      strictness: "standard",
      created_at: "2026-09-09T00:00:00Z",
      row_total: 2,
    });

    const result = await createBatch("batches/key.csv", {
      fileName: "answers.csv",
      strictness: "standard",
      retainAnswer: true,
      columnMapping: { "Student ID": "external_ref" },
    });

    expect(spy).toHaveBeenCalledWith(
      "/api/batches",
      expect.objectContaining({
        method: "POST",
        body: {
          upload_key: "batches/key.csv",
          file_name: "answers.csv",
          strictness: "standard",
          retain_answer: true,
          column_mapping: { "Student ID": "external_ref" },
        },
      }),
    );
    expect(result.rowTotal).toBe(2);
  });

  it("getBatchProgress maps the response into camelCase", async () => {
    vi.spyOn(client, "apiRequest").mockResolvedValue({
      batch: {
        batch_id: "b1",
        actor_id: "a1",
        batch_file_name: "answers.csv",
        strictness: "standard",
        created_at: "2026-09-09T00:00:00Z",
        row_total: 2,
      },
      completed: 1,
      failed: 0,
      pending: 1,
      row_total: 2,
      cancelled: false,
    });

    const result = await getBatchProgress("b1");
    expect(result.completed).toBe(1);
    expect(result.batch.fileName).toBe("answers.csv");
    expect(result.cancelled).toBe(false);
  });

  it("cancelBatch posts to the cancel endpoint and maps the response", async () => {
    const spy = vi.spyOn(client, "apiRequest").mockResolvedValue({
      batch: {
        batch_id: "b1",
        actor_id: "a1",
        batch_file_name: "answers.csv",
        strictness: "standard",
        created_at: "2026-09-09T00:00:00Z",
        row_total: 2,
        cancelled_at: "2026-09-09T00:05:00Z",
      },
      completed: 1,
      failed: 1,
      pending: 0,
      row_total: 2,
      cancelled: true,
    });

    const result = await cancelBatch("b1");

    expect(spy).toHaveBeenCalledWith(
      "/api/batches/b1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
    expect(result.cancelled).toBe(true);
  });
});
