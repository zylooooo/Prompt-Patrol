import {
  ANSWER_MAX_CHARS,
  ANSWER_MIN_CHARS,
  EXTERNAL_REF_MAX_CHARS,
  QUESTION_MAX_CHARS,
  type BatchRun,
} from "../../types";
import { describe, expect, it } from "vitest";
import { MAX_ROWS, parseAnswersCsv, serializeResultsCsv } from "../csv";

/**
 * This file is deliberately weighted towards malformed input. `parseAnswersCsv`
 * consumes files produced by whatever spreadsheet an instructor happens to use,
 * so the interesting cases are the broken ones; the two "well-formed" tests
 * exist only as positive controls.
 *
 * Every length check is asserted at the boundary and one past it, because an
 * off-by-one there either rejects valid work or lets oversized input through.
 */

const A = (n: number) => "a".repeat(n);
const answer = () => A(ANSWER_MIN_CHARS + 10);
const HEADER = "external_ref,answer_text,question_text";

describe("parseAnswersCsv — structure", () => {
  it("parses a well-formed file (positive control)", () => {
    const { rows, errors } = parseAnswersCsv(
      `${HEADER}\nA1,${answer()},What is X?`,
    );
    expect(errors).toEqual([]);
    expect(rows).toEqual([
      { externalRef: "A1", answerText: answer(), questionText: "What is X?" },
    ]);
  });

  it("omits question_text rather than storing an empty string", () => {
    const { rows } = parseAnswersCsv(
      `external_ref,answer_text\nA1,${answer()}`,
    );
    expect(rows[0].questionText).toBeUndefined();
  });

  it("survives a UTF-8 BOM, which Excel prepends by default", () => {
    // The BOM below is a real U+FEFF. It is stripped by `.trim()` on the header
    // cells; a refactor away from `trim()` would silently break every Excel
    // export with "Missing required column: external_ref".
    const BOM = "\uFEFF";
    const { rows, errors } = parseAnswersCsv(
      `${BOM}${HEADER}\nA1,${answer()},Q`,
    );
    expect(errors).toEqual([]);
    expect(rows).toHaveLength(1);
  });

  it("accepts CRLF and lone-CR line endings", () => {
    for (const eol of ["\r\n", "\r"]) {
      const { rows, errors } = parseAnswersCsv(
        `external_ref,answer_text${eol}A1,${answer()}${eol}A2,${answer()}`,
      );
      expect(errors).toEqual([]);
      expect(rows).toHaveLength(2);
    }
  });

  it("does not invent a phantom row from a trailing newline", () => {
    const { rows, errors } = parseAnswersCsv(
      `external_ref,answer_text\nA1,${answer()}\n`,
    );
    expect(rows).toHaveLength(1);
    expect(errors).toEqual([]);
  });

  it("honours quoted fields containing commas and newlines", () => {
    const { rows, errors } = parseAnswersCsv(
      `${HEADER}\nA1,"one, two\nthree ${answer()}",Q`,
    );
    expect(errors).toEqual([]);
    expect(rows[0].answerText).toBe(`one, two\nthree ${answer()}`);
  });

  it("unescapes doubled quotes inside a quoted field", () => {
    const { rows } = parseAnswersCsv(
      `${HEADER}\nA1,"he said ""hi"" ${answer()}",Q`,
    );
    expect(rows[0].answerText).toBe(`he said "hi" ${answer()}`);
  });

  it("matches header columns case-insensitively and in any order", () => {
    const { rows, errors } = parseAnswersCsv(
      `Answer_Text,External_Ref\n${answer()},A1`,
    );
    expect(errors).toEqual([]);
    expect(rows[0].externalRef).toBe("A1");
  });

  it("takes the first of duplicate columns rather than the last", () => {
    const { rows } = parseAnswersCsv(
      `external_ref,answer_text,answer_text\nA1,${answer()},ignored`,
    );
    expect(rows[0].answerText).toBe(answer());
  });
});

describe("parseAnswersCsv — whole-file rejections", () => {
  it("reports an empty file", () => {
    expect(parseAnswersCsv("")).toEqual({
      rows: [],
      errors: ["The file is empty."],
    });
  });

  it("reports a header with no data rows instead of failing silently", () => {
    // Regression: this used to return `{ rows: [], errors: [] }`, which the
    // batch tab rendered as nothing whatsoever — no chip, no alert.
    const { rows, errors } = parseAnswersCsv("external_ref,answer_text");
    expect(rows).toEqual([]);
    expect(errors).toEqual(["The file has a header row but no answers."]);
  });

  it("treats a file of only blank lines after the header the same way", () => {
    const { errors } = parseAnswersCsv("external_ref,answer_text\n\n\n");
    expect(errors).toEqual(["The file has a header row but no answers."]);
  });

  it("reports an unterminated quote with the line it opened on", () => {
    const { rows, errors } = parseAnswersCsv(`${HEADER}\nA1,"never closed,Q`);
    expect(rows).toEqual([]);
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("line 2");
  });

  it("names every missing required column, not just the first", () => {
    const { rows, errors } = parseAnswersCsv("question_text\nQ");
    expect(rows).toEqual([]);
    expect(errors).toEqual([
      "Missing required column: external_ref",
      "Missing required column: answer_text",
    ]);
  });

  it(`accepts exactly ${MAX_ROWS} rows and rejects ${MAX_ROWS + 1}`, () => {
    const file = (n: number) =>
      `external_ref,answer_text\n${Array.from(
        { length: n },
        (_, i) => `A${i},${answer()}`,
      ).join("\n")}`;

    expect(parseAnswersCsv(file(MAX_ROWS)).rows).toHaveLength(MAX_ROWS);

    const over = parseAnswersCsv(file(MAX_ROWS + 1));
    expect(over.rows).toEqual([]);
    expect(over.errors[0]).toContain(`${MAX_ROWS + 1} rows`);
  });

  it("rejects an oversized file wholesale rather than truncating it", () => {
    // Truncating would silently screen a subset and report success, which is
    // worse than refusing the file.
    const over = parseAnswersCsv(
      `external_ref,answer_text\n${Array.from(
        { length: MAX_ROWS + 50 },
        (_, i) => `A${i},${answer()}`,
      ).join("\n")}`,
    );
    expect(over.rows).toHaveLength(0);
  });
});

describe("parseAnswersCsv — per-row validation", () => {
  it("skips a bad row, keeps the good ones, and cites the source line", () => {
    const { rows, errors } = parseAnswersCsv(
      [
        "external_ref,answer_text",
        `A1,${answer()}`,
        `,${answer()}`,
        `A3,${answer()}`,
      ].join("\n"),
    );
    expect(rows.map((r) => r.externalRef)).toEqual(["A1", "A3"]);
    expect(errors).toEqual(["Line 3: external_ref is empty."]);
  });

  it("keeps line numbers accurate across a multi-line quoted field", () => {
    // The first record spans lines 2-4, so the offending record starts at 5.
    const { errors } = parseAnswersCsv(
      [
        "external_ref,answer_text",
        `A1,"line one`,
        `line two`,
        `line three ${answer()}"`,
        `,${answer()}`,
      ].join("\n"),
    );
    expect(errors).toEqual(["Line 5: external_ref is empty."]);
  });

  it("keeps line numbers accurate across CRLF and blank lines", () => {
    expect(
      parseAnswersCsv(
        `external_ref,answer_text\r\nA1,${answer()}\r\n,${answer()}`,
      ).errors,
    ).toEqual(["Line 3: external_ref is empty."]);

    expect(
      parseAnswersCsv(
        `external_ref,answer_text\nA1,${answer()}\n\n,${answer()}`,
      ).errors,
    ).toEqual(["Line 4: external_ref is empty."]);
  });

  it("rejects a row with fewer fields than the header", () => {
    const { rows, errors } = parseAnswersCsv("external_ref,answer_text\nA1");
    expect(rows).toEqual([]);
    expect(errors).toEqual(["Line 2: answer_text is empty."]);
  });

  it("treats a whitespace-only field as empty", () => {
    const { rows, errors } = parseAnswersCsv(
      `external_ref,answer_text\nA1,"   "`,
    );
    expect(rows).toEqual([]);
    expect(errors[0]).toContain("answer_text is empty");
  });

  it("trims before validating, so padding cannot smuggle a value past a limit", () => {
    const { rows, errors } = parseAnswersCsv(
      `external_ref,answer_text\n  A1  ,  ${answer()}  `,
    );
    expect(errors).toEqual([]);
    expect(rows[0].externalRef).toBe("A1");
  });

  it("reports one error per bad row and drops all of them", () => {
    const { rows, errors } = parseAnswersCsv(
      ["external_ref,answer_text", `,${answer()}`, "A2,", `,${answer()}`].join(
        "\n",
      ),
    );
    expect(rows).toEqual([]);
    expect(errors).toHaveLength(3);
  });
});

describe("parseAnswersCsv — length boundaries", () => {
  const cases: [string, number, (n: number) => string][] = [
    [
      "answer_text minimum",
      ANSWER_MIN_CHARS,
      (n) => `external_ref,answer_text\nA1,${A(n)}`,
    ],
    [
      "answer_text maximum",
      ANSWER_MAX_CHARS,
      (n) => `external_ref,answer_text\nA1,${A(n)}`,
    ],
    [
      "external_ref maximum",
      EXTERNAL_REF_MAX_CHARS,
      (n) => `external_ref,answer_text\n${"x".repeat(n)},${answer()}`,
    ],
    [
      "question_text maximum",
      QUESTION_MAX_CHARS,
      (n) => `${HEADER}\nA1,${answer()},${A(n)}`,
    ],
  ];

  it("accepts input exactly at each limit", () => {
    for (const [name, limit, build] of cases) {
      expect(parseAnswersCsv(build(limit)).errors, name).toEqual([]);
    }
  });

  it("rejects input one character past each maximum", () => {
    for (const [name, limit, build] of cases.slice(1)) {
      expect(parseAnswersCsv(build(limit + 1)).errors, name).toHaveLength(1);
    }
  });

  it("rejects an answer one character under the minimum", () => {
    const { errors } = parseAnswersCsv(
      `external_ref,answer_text\nA1,${A(ANSWER_MIN_CHARS - 1)}`,
    );
    expect(errors).toHaveLength(1);
    expect(errors[0]).toContain("under");
  });
});

const run = (rows: unknown[]): BatchRun => ({ rows }) as unknown as BatchRun;

const row = (over: Record<string, unknown> = {}) => ({
  externalRef: "A1",
  answerText: "text",
  questionText: "q",
  rawScore: 0.5,
  verdict: "uncertain",
  ...over,
});

describe("serializeResultsCsv", () => {
  it("emits a header and CRLF-separated rows (positive control)", () => {
    const lines = serializeResultsCsv(run([row()])).split("\r\n");
    expect(lines[0]).toBe(
      "external_ref,question_text,answer_text,raw_score,verdict,verdict_text,note",
    );
    expect(lines).toHaveLength(2);
  });

  it("lists rows the detector could not score, rather than omitting them", () => {
    // A downloaded file holding fewer rows than the uploaded one is the same
    // failure as a table showing fewer — it just travels further.
    const csv = serializeResultsCsv({
      ...run([row({ externalRef: "OK-1" })]),
      failures: [
        { externalRef: "BAD-1", reason: "The detector took too long." },
      ],
    });
    const lines = csv.split("\r\n");

    expect(lines).toHaveLength(3);
    expect(lines[2]).toBe("BAD-1,,,,,,The detector took too long.");
  });

  it("quotes fields containing commas, quotes or newlines", () => {
    expect(
      serializeResultsCsv(run([row({ answerText: 'a, b "c"\nd' })])),
    ).toContain('"a, b ""c""\nd"');
  });

  it("neutralises every spreadsheet formula lead", () => {
    // A cell starting =, +, -, @, tab or CR is evaluated by Excel and Sheets.
    // Answers are untrusted input, so each lead must be rendered inert.
    for (const lead of ["=", "+", "-", "@", "\t", "\r"]) {
      const csv = serializeResultsCsv(
        run([row({ externalRef: `${lead}cmd|'/c calc'!A0` })]),
      );
      expect(csv, `lead ${JSON.stringify(lead)}`).toContain(`'${lead}cmd`);
    }
  });

  it("does not prefix a value that merely contains a formula character", () => {
    expect(serializeResultsCsv(run([row({ answerText: "2+2=4" })]))).toContain(
      "2+2=4",
    );
  });

  it("rounds the score to two decimals", () => {
    expect(serializeResultsCsv(run([row({ rawScore: 0.126 })]))).toContain(
      "0.13",
    );
  });

  it("tolerates missing text fields", () => {
    const csv = serializeResultsCsv(
      run([
        row({ externalRef: null, answerText: undefined, questionText: null }),
      ]),
    );
    expect(csv.split("\r\n")).toHaveLength(2);
  });

  it("emits only a header for an empty run", () => {
    expect(serializeResultsCsv(run([])).split("\r\n")).toHaveLength(1);
  });

  it("produces a file its own parser accepts", () => {
    // Round-trip: export must not emit something the import path rejects.
    const original = `has "quotes", a comma and\na newline ${answer()}`;
    const reparsed = parseAnswersCsv(
      serializeResultsCsv(
        run([row({ externalRef: "A1", answerText: original })]),
      ),
    );
    expect(reparsed.errors).toEqual([]);
    expect(reparsed.rows[0].answerText).toBe(original);
  });
});
