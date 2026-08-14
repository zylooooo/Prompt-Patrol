import {
  ANSWER_MAX_CHARS,
  ANSWER_MIN_CHARS,
  EXTERNAL_REF_MAX_CHARS,
  QUESTION_MAX_CHARS,
  VERDICT_TEXT,
  type BatchRowInput,
  type BatchRun,
} from "../api/types";

export const MAX_ROWS = 500;

const REQUIRED_COLUMNS = ["external_ref", "answer_text"] as const;

const OPTIONAL_COLUMNS = ["question_text"] as const;

export interface ParsedCsv {
  rows: BatchRowInput[];
  errors: string[];
}

interface RawRecord {
  fields: string[];
  line: number;
}

interface ParseResult {
  records: RawRecord[];
  unterminatedAtLine: number | null;
}

function parseRecords(text: string): ParseResult {
  const records: RawRecord[] = [];
  let field = "";
  let record: string[] = [];
  let inQuotes = false;
  let line = 1;
  let recordLine = 1;
  let sawStructure = false;
  let quoteOpenLine = 0;

  const pushRecord = () => {
    record.push(field);
    field = "";
    const blankLine =
      !sawStructure && record.every((cell) => cell.trim() === "");
    if (!blankLine) records.push({ fields: record, line: recordLine });
    record = [];
    sawStructure = false;
  };

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        if (ch === "\n") line++;
        field += ch;
      }
    } else if (ch === '"' && field === "") {
      inQuotes = true;
      sawStructure = true;
      quoteOpenLine = line;
    } else if (ch === '"') {
      field += '"';
    } else if (ch === ",") {
      record.push(field);
      field = "";
      sawStructure = true;
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      pushRecord();
      line++;
      recordLine = line;
    } else {
      field += ch;
    }
  }
  if (inQuotes) {
    return { records, unterminatedAtLine: quoteOpenLine };
  }
  if (field !== "" || record.length > 0) pushRecord();
  return { records, unterminatedAtLine: null };
}

export function parseAnswersCsv(text: string): ParsedCsv {
  const errors: string[] = [];
  const { records, unterminatedAtLine } = parseRecords(text);

  if (unterminatedAtLine !== null) {
    return {
      rows: [],
      errors: [
        `Unterminated quoted field starting on line ${unterminatedAtLine}. Check for a stray double quote.`,
      ],
    };
  }
  if (records.length === 0) {
    return { rows: [], errors: ["The file is empty."] };
  }

  const header = records[0].fields.map((heading) =>
    heading.trim().toLowerCase(),
  );
  const indices: Record<string, number> = {};
  for (const col of REQUIRED_COLUMNS) {
    const idx = header.indexOf(col);
    if (idx === -1) errors.push(`Missing required column: ${col}`);
    indices[col] = idx;
  }
  for (const col of OPTIONAL_COLUMNS) {
    indices[col] = header.indexOf(col);
  }
  if (errors.length > 0) {
    return { rows: [], errors };
  }

  const body = records.slice(1);
  if (body.length > MAX_ROWS) {
    return {
      rows: [],
      errors: [`The file has ${body.length} rows; the limit is ${MAX_ROWS}.`],
    };
  }

  const rows: BatchRowInput[] = [];
  for (const rec of body) {
    const externalRef = rec.fields[indices.external_ref]?.trim() ?? "";
    const answerText = rec.fields[indices.answer_text]?.trim() ?? "";
    const questionText =
      indices.question_text >= 0
        ? (rec.fields[indices.question_text]?.trim() ?? "")
        : "";

    if (!externalRef || !answerText) {
      errors.push(
        `Line ${rec.line}: ${!externalRef ? "external_ref" : "answer_text"} is empty.`,
      );
      continue;
    }
    if (externalRef.length > EXTERNAL_REF_MAX_CHARS) {
      errors.push(
        `Line ${rec.line}: external_ref is over ${EXTERNAL_REF_MAX_CHARS} characters.`,
      );
      continue;
    }
    if (answerText.length < ANSWER_MIN_CHARS) {
      errors.push(
        `Line ${rec.line}: answer_text is under ${ANSWER_MIN_CHARS} characters.`,
      );
      continue;
    }
    if (answerText.length > ANSWER_MAX_CHARS) {
      errors.push(
        `Line ${rec.line}: answer_text is over ${ANSWER_MAX_CHARS} characters.`,
      );
      continue;
    }
    if (questionText.length > QUESTION_MAX_CHARS) {
      errors.push(
        `Line ${rec.line}: question_text is over ${QUESTION_MAX_CHARS} characters.`,
      );
      continue;
    }
    rows.push({
      externalRef,
      answerText,
      questionText: questionText || undefined,
    });
  }

  return { rows, errors };
}

const FORMULA_LEAD = /^[=+\-@\t\r]/;

function csvEscape(value: string): string {
  const safe = FORMULA_LEAD.test(value) ? `'${value}` : value;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function serializeResultsCsv(run: BatchRun): string {
  const lines = [
    "external_ref,question_text,answer_text,raw_score,verdict,verdict_text",
  ];
  for (const row of run.rows) {
    lines.push(
      [
        csvEscape(row.externalRef ?? ""),
        csvEscape(row.questionText ?? ""),
        csvEscape(row.answerText ?? ""),
        row.rawScore.toFixed(2),
        row.verdict,
        csvEscape(VERDICT_TEXT[row.verdict]),
      ].join(","),
    );
  }
  return lines.join("\r\n");
}

export function downloadCsv(fileName: string, content: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
