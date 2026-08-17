import { ApiError } from "../api/client";

export const GENERIC_FAILURE =
  "The check failed. Nothing was saved. Try again.";

const FAILURE_TEXT: Record<string, string> = {
  detector_timeout:
    "The detector took too long to answer. Nothing was saved — try again in a moment.",
  detector_unavailable:
    "The detector is temporarily unavailable. Nothing was saved — try again shortly.",
  payload_too_large:
    "That answer is too long to screen. Shorten it and check again.",
};

export function describeCheckFailure(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC_FAILURE;
  if (error.code && error.code in FAILURE_TEXT) {
    return FAILURE_TEXT[error.code];
  }

  if (error.status >= 400 && error.status < 500 && error.message) {
    return error.message;
  }
  return GENERIC_FAILURE;
}
