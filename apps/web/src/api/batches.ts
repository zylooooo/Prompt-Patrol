import type {
  BatchFailure,
  BatchInfo,
  BatchProgress,
  ColumnMapping,
  Strictness,
} from "../types";
import { apiRequest } from "./client";

const BATCHES_PATH = "/api/batches";

interface UploadUrlResponse {
  upload_url: string;
  upload_key: string;
}

export async function requestUploadUrl(
  fileName: string,
): Promise<{ uploadUrl: string; uploadKey: string }> {
  const body = await apiRequest<UploadUrlResponse>(`${BATCHES_PATH}/upload-url`, {
    method: "POST",
    body: { file_name: fileName },
  });
  return { uploadUrl: body.upload_url, uploadKey: body.upload_key };
}

export async function uploadFileToS3(uploadUrl: string, file: File): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": "text/csv" },
    body: file,
  });
  if (!response.ok) {
    throw new Error(`Upload failed with status ${response.status}`);
  }
}

interface BatchInfoResponse {
  batch_id: string;
  actor_id: string;
  batch_file_name: string;
  strictness: Strictness;
  created_at: string;
  row_total: number;
}

function toBatchInfo(row: BatchInfoResponse): BatchInfo {
  return {
    batchId: row.batch_id,
    actorId: row.actor_id,
    fileName: row.batch_file_name,
    strictness: row.strictness,
    createdAt: row.created_at,
    rowTotal: row.row_total,
  };
}

// uploadKey isn't known by the caller until requestUploadUrl() resolves (see
// useCreateBatch in hooks/useBatches.ts), so it's not part of the input a
// caller assembles up front - createBatch takes it as a separate argument
// instead of folding it into CreateBatchInput.
export interface CreateBatchInput {
  fileName: string;
  strictness: Strictness;
  retainAnswer: boolean;
  columnMapping: ColumnMapping | null;
}

export async function createBatch(
  uploadKey: string,
  input: CreateBatchInput,
): Promise<BatchInfo> {
  const body = await apiRequest<BatchInfoResponse>(BATCHES_PATH, {
    method: "POST",
    body: {
      upload_key: uploadKey,
      file_name: input.fileName,
      strictness: input.strictness,
      retain_answer: input.retainAnswer,
      column_mapping: input.columnMapping,
    },
  });
  return toBatchInfo(body);
}

interface BatchFailureResponse {
  row_number: number;
  external_ref: string | null;
  reason: string;
}

function toBatchFailure(row: BatchFailureResponse): BatchFailure {
  return { rowNumber: row.row_number, externalRef: row.external_ref, reason: row.reason };
}

interface BatchProgressResponse {
  batch: BatchInfoResponse;
  completed: number;
  failed: number;
  pending: number;
  row_total: number;
  cancelled: boolean;
  failures: BatchFailureResponse[];
}

function toBatchProgress(body: BatchProgressResponse): BatchProgress {
  return {
    batch: toBatchInfo(body.batch),
    completed: body.completed,
    failed: body.failed,
    pending: body.pending,
    rowTotal: body.row_total,
    cancelled: body.cancelled,
    failures: body.failures.map(toBatchFailure),
  };
}

export async function getBatchProgress(
  batchId: string,
  signal?: AbortSignal,
): Promise<BatchProgress> {
  const body = await apiRequest<BatchProgressResponse>(`${BATCHES_PATH}/${batchId}`, {
    signal,
  });
  return toBatchProgress(body);
}

export async function cancelBatch(batchId: string): Promise<BatchProgress> {
  const body = await apiRequest<BatchProgressResponse>(
    `${BATCHES_PATH}/${batchId}/cancel`,
    { method: "POST" },
  );
  return toBatchProgress(body);
}
