export const NETWORK_ERROR_STATUS = 0;

const GATEWAY_FAILURE_STATUSES = new Set([502, 503, 504]);

const DEFAULT_TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }

  get isUnreachable(): boolean {
    return (
      this.status === NETWORK_ERROR_STATUS ||
      GATEWAY_FAILURE_STATUSES.has(this.status)
    );
  }
}

export interface RequestOptions {
  signal?: AbortSignal;
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  timeoutMs?: number;
}

interface ErrorBody {
  detail?: string | { code?: string; message?: string };
  code?: string;
  message?: string;
}

async function describeFailure(
  response: Response,
): Promise<{ code: string | null; message: string }> {
  const fallback = `Request failed with status ${response.status}`;
  let body: ErrorBody;
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    return { code: null, message: fallback };
  }

  const detail = body.detail;
  if (detail && typeof detail === "object") {
    return { code: detail.code ?? null, message: detail.message ?? fallback };
  }
  if (typeof detail === "string") return { code: null, message: detail };
  return { code: body.code ?? null, message: body.message ?? fallback };
}

function withTimeout(
  signal: AbortSignal | undefined,
  timeoutMs: number,
): { signal: AbortSignal; done: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const forward = () => controller.abort(signal?.reason);

  if (signal?.aborted) forward();
  else signal?.addEventListener("abort", forward, { once: true });

  return {
    signal: controller.signal,
    done: () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", forward);
    },
  };
}

export async function apiRequest<T>(
  path: string,
  {
    signal,
    method = "GET",
    body,
    timeoutMs = DEFAULT_TIMEOUT_MS,
  }: RequestOptions = {},
): Promise<T> {
  const deadline = withTimeout(signal, timeoutMs);
  let response: Response;

  try {
    response = await fetch(path, {
      method,
      signal: deadline.signal,
      credentials: "include",
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(
      NETWORK_ERROR_STATUS,
      deadline.signal.aborted
        ? "The server took too long to respond."
        : "Could not reach the server.",
    );
  } finally {
    deadline.done();
  }

  if (!response.ok) {
    const { code, message } = await describeFailure(response);
    throw new ApiError(response.status, message, code);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
