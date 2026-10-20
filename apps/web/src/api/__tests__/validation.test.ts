import {
  ANSWER_MAX_CHARS,
  ANSWER_MIN_CHARS,
  EXTERNAL_REF_MAX_CHARS,
  QUESTION_MAX_CHARS,
} from "../../types";
import { validateCheckInput } from "../validation";
import { describe, expect, it } from "vitest";

const A = (n: number) => "a".repeat(n);
const answerText = A(ANSWER_MIN_CHARS);

describe("validateCheckInput", () => {
  it("accepts input at every limit", () => {
    expect(() =>
      validateCheckInput({
        answerText: A(ANSWER_MAX_CHARS),
        questionText: A(QUESTION_MAX_CHARS),
        externalRef: A(EXTERNAL_REF_MAX_CHARS),
      }),
    ).not.toThrow();
  });

  it("counts the answer after trimming", () => {
    expect(() =>
      validateCheckInput({ answerText: `  ${A(ANSWER_MIN_CHARS - 1)}  ` }),
    ).toThrow(`Enter at least ${ANSWER_MIN_CHARS} characters.`);
  });

  it.each([
    ["answer", { answerText: A(ANSWER_MAX_CHARS + 1) }, "Answers are limited"],
    ["question", { answerText, questionText: A(QUESTION_MAX_CHARS + 1) }, "Questions are limited"],
    ["reference", { answerText, externalRef: A(EXTERNAL_REF_MAX_CHARS + 1) }, "Reference is limited"],
  ])("refuses a %s over its limit as a 400", (_, input, message) => {
    expect(() => validateCheckInput(input)).toThrow(message);
    expect(() => validateCheckInput(input)).toThrow(
      expect.objectContaining({ status: 400 }),
    );
  });
});
