import { ApiError } from "../api/client";

// Copy for the contract's stable `error` codes. Display copy lives here, not
// in the API: the server's `message` is safe to show but isn't written in
// the product voice (PRODUCT.md, Voice and Copy), so it is never shown as-is.
const CODE_TEXT: Record<string, string> = {
  forbidden:
    "You don't have permission to do that. If you think you should, contact your Prompt Patrol administrator.",
  not_found:
    "We couldn't find that. It may have been removed. Refresh the page and try again.",
  conflict:
    "This changed since the page loaded. Refresh the page and try again.",
  upstream_idp_error:
    "We couldn't set up sign-in for this account. Nothing was saved. Try again.",
  detector_timeout:
    "The detector took too long to answer. Nothing was saved. Try again in a moment.",
  detector_unavailable:
    "The detector is unavailable right now. Nothing was saved. Try again shortly.",
  payload_too_large:
    "That answer is too long to check. Shorten it and check again.",
  question_text_required:
    "The detector needs the question as well as the answer. Add the question and check again.",
};

const UNREACHABLE =
  "We couldn't reach Prompt Patrol. Check your connection and try again.";

export const CHECK_FAILURE = "The check didn't go through. Nothing was saved. Try again.";

export function describeError(
  error: unknown,
  fallback = "Something went wrong. Try again.",
): string {
  if (!(error instanceof ApiError)) return fallback;
  if (error.code && error.code in CODE_TEXT) return CODE_TEXT[error.code];
  // Network failures carry our own client-side copy (api/client.ts).
  if (error.status === 0) return error.message;
  if (error.isUnreachable) return UNREACHABLE;
  return fallback;
}

export function describeCheckFailure(error: unknown): string {
  return describeError(error, CHECK_FAILURE);
}
