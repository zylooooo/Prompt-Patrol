import {
  ANSWER_MAX_CHARS,
  ANSWER_MIN_CHARS,
  EXTERNAL_REF_MAX_CHARS,
  QUESTION_MAX_CHARS,
  VERDICT_TEXT,
  type BatchRowInput,
  type BatchRun,
} from "../types";

export const MAX_ROWS = 500;

type CanonicalField = "external_ref" | "answer_text" | "question_text";
const REQUIRED_FIELDS: CanonicalField[] = ["external_ref", "answer_text"];

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

export function parseHeaderAndPreview(
  text: string,
  previewRows = 5,
): { headers: string[]; preview: string[][] } {
  const { records } = parseRecords(text);
  if (records.length === 0) return { headers: [], preview: [] };
  return {
    headers: records[0].fields,
    preview: records.slice(1, 1 + previewRows).map((r) => r.fields),
  };
}

export function parseAnswersCsv(
  text: string,
  columnMapping: Partial<Record<string, CanonicalField>> | null = null,
  requiresQuestionText = false,
): ParsedCsv {
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
  // Without a mapping, headers are assumed to already be our canonical names
  // (existing behavior, unchanged). With one, it maps the instructor's
  // literal header text (case-sensitive, as typed) to a canonical field -
  // built against the raw (non-lowercased) header row.
  const rawHeader = records[0].fields;
  const fieldToIndex: Partial<Record<CanonicalField, number>> = {};
  if (columnMapping) {
    for (let i = 0; i < rawHeader.length; i++) {
      const mapped = columnMapping[rawHeader[i]];
      if (mapped) fieldToIndex[mapped] = i;
    }
  } else {
    for (const field of [...REQUIRED_FIELDS, "question_text"] as CanonicalField[]) {
      const idx = header.indexOf(field);
      if (idx !== -1) fieldToIndex[field] = idx;
    }
  }
  for (const field of REQUIRED_FIELDS) {
    if (fieldToIndex[field] === undefined) errors.push(`Missing required column: ${field}`);
  }
  if (requiresQuestionText && fieldToIndex.question_text === undefined) {
    errors.push("Missing required column: question_text");
  }
  const indices = fieldToIndex;
  if (errors.length > 0) {
    return { rows: [], errors };
  }

  const body = records.slice(1);

  if (body.length === 0) {
    return { rows: [], errors: ["The file has a header row but no answers."] };
  }
  if (body.length > MAX_ROWS) {
    return {
      rows: [],
      errors: [`The file has ${body.length} rows; the limit is ${MAX_ROWS}.`],
    };
  }

  const rows: BatchRowInput[] = [];
  for (const rec of body) {
    const externalRef = rec.fields[indices.external_ref!]?.trim() ?? "";
    const answerText = rec.fields[indices.answer_text!]?.trim() ?? "";
    const questionText =
      indices.question_text !== undefined
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
    "external_ref,question_text,answer_text,raw_score,verdict,verdict_text,model_version,calibration,note",
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
        csvEscape(row.detector.modelVersion),
        row.detector.calibrationVersion ?? "uncalibrated",
        "",
      ].join(","),
    );
  }

  for (const failure of run.failures ?? []) {
    lines.push(
      [
        csvEscape(failure.externalRef ?? `row ${failure.rowNumber}`),
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        csvEscape(failure.reason),
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
