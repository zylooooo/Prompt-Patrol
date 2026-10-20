import {
  ANSWER_MAX_CHARS,
  ANSWER_MIN_CHARS,
  EXTERNAL_REF_MAX_CHARS,
  QUESTION_MAX_CHARS,
  type CheckInput,
} from "../types";
import { ApiError } from "./client";

// Client-side only: friendlier wording than the server's 400, and the
// question/reference limits the server does not enforce. Not a security
// boundary; the API validates the answer on its own.
export function validateCheckInput(input: CheckInput) {
  const answer = input.answerText.trim();
  if (answer.length < ANSWER_MIN_CHARS) {
    throw new ApiError(400, `Enter at least ${ANSWER_MIN_CHARS} characters.`);
  }
  if (answer.length > ANSWER_MAX_CHARS) {
    throw new ApiError(
      400,
      `Answers are limited to ${ANSWER_MAX_CHARS.toLocaleString()} characters.`,
    );
  }
  if (input.questionText && input.questionText.length > QUESTION_MAX_CHARS) {
    throw new ApiError(
      400,
      `Questions are limited to ${QUESTION_MAX_CHARS.toLocaleString()} characters.`,
    );
  }
  if (input.externalRef && input.externalRef.length > EXTERNAL_REF_MAX_CHARS) {
    throw new ApiError(
      400,
      `Reference is limited to ${EXTERNAL_REF_MAX_CHARS} characters.`,
    );
  }
}
