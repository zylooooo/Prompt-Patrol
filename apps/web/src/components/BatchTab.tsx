import { FileText, Trash2 } from "lucide-react";
import Button from "./ui/Button";
import TextButton from "./ui/TextButton";
import { useToast } from "../hooks/useToast";
import StrictnessField from "./StrictnessField";
import CancelBatchDialog from "./CancelBatchDialog";
import { useDetectorCapabilities, useHistory } from "../hooks/useChecks";
import {
  useActiveBatch,
  useCancelBatch,
  useCreateBatch,
  useBatchProgress,
} from "../hooks/useBatches";
import { useEffect, useRef, useState } from "react";
import BatchResultsTable from "./BatchResultsTable";
import { MAX_ROWS, parseAnswersCsv, parseHeaderAndPreview } from "../lib/csv";
import type { BatchRun, ColumnMapping, Strictness } from "../types";

const CANONICAL_FIELDS = ["external_ref", "answer_text", "question_text"] as const;
type CanonicalField = (typeof CANONICAL_FIELDS)[number];
const CANONICAL_SET: Set<string> = new Set(CANONICAL_FIELDS);

const FIELD_LABEL: Record<CanonicalField, string> = {
  external_ref: "Student reference",
  answer_text: "Answer",
  question_text: "Question",
};

const ALERT_CLASS =
  "rounded-md bg-danger-soft px-4 py-3 text-[13px] text-danger";

export default function BatchTab() {
  const [rawText, setRawText] = useState<string | null>(null);
  const [originalFile, setOriginalFile] = useState<File | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [needsMapping, setNeedsMapping] = useState(false);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<string[]>([]);
  const [parsedCount, setParsedCount] = useState<number | null>(null);
  const activeBatch = useActiveBatch();
  const [batchId, setBatchId] = useState<string | null>(
    () => activeBatch.active?.batchId ?? null,
  );
  const [dragging, setDragging] = useState(false);
  const [strictness, setStrictness] = useState<Strictness>("standard");
  const [errorsExpanded, setErrorsExpanded] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const scrolledForBatchRef = useRef<string | null>(null);
  const { showToast } = useToast();

  const capabilities = useDetectorCapabilities();
  const requiresQuestionText = capabilities.data?.requiresQuestionText ?? false;

  const createBatch = useCreateBatch();
  const progress = useBatchProgress(batchId);
  const cancelBatch = useCancelBatch(batchId);
  const history = useHistory();

  const cancelled = progress.data?.cancelled ?? false;
  const done = progress.data
    ? cancelled ||
      progress.data.completed + progress.data.failed >= progress.data.rowTotal
    : false;

  const resultEntry = batchId
    ? (history.data?.find(
        (entry) => entry.kind === "batch" && entry.id === batchId,
      ) as BatchRun | undefined)
    : undefined;

  // Scroll to the results once they first appear for this batch, not on
  // every live-progress refetch - otherwise every poll yanks the page back
  // down, fighting anyone who scrolled or expanded a row to look at it.
  useEffect(() => {
    if (resultEntry && scrolledForBatchRef.current !== batchId) {
      scrolledForBatchRef.current = batchId;
      resultsRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  }, [resultEntry, batchId]);

  useEffect(() => {
    if (batchId && (done || progress.isError)) activeBatch.clear();
  }, [batchId, done, progress.isError, activeBatch]);

  function resetFileState() {
    setRawText(null);
    setOriginalFile(null);
    setFileName(null);
    setHeaders([]);
    setNeedsMapping(false);
    setMapping({});
    setErrors([]);
    setParsedCount(null);
    setErrorsExpanded(false);
  }

  async function loadFile(f: File) {
    if (createBatch.isPending) return;
    createBatch.reset();
    setBatchId(null);
    resetFileState();
    try {
      const text = await f.text();
      const { headers: parsedHeaders } = parseHeaderAndPreview(text);
      const allCanonical =
        parsedHeaders.length > 0 &&
        parsedHeaders.every((h) => CANONICAL_SET.has(h.trim().toLowerCase()));

      setRawText(text);
      setOriginalFile(f);
      setFileName(f.name);
      setHeaders(parsedHeaders);

      if (allCanonical) {
        setNeedsMapping(false);
        const { rows, errors: parseErrors } = parseAnswersCsv(
          text,
          null,
          requiresQuestionText,
        );
        setErrors(parseErrors);
        setParsedCount(rows.length);
      } else {
        setNeedsMapping(true);
        const initial: Record<string, string> = {};
        for (const h of parsedHeaders) {
          const lower = h.trim().toLowerCase();
          initial[h] = CANONICAL_SET.has(lower) ? lower : "";
        }
        setMapping(initial);
      }
    } catch {
      setErrors([
        "That file could not be read. Try exporting it again as UTF-8 CSV.",
      ]);
      resetFileState();
    }
  }

  function buildColumnMapping(): ColumnMapping | null {
    if (!needsMapping) return null;
    const entries = Object.entries(mapping).filter(([, v]) => v !== "");
    return Object.fromEntries(entries) as ColumnMapping;
  }

  function onRun() {
    if (!rawText || !originalFile || !fileName || createBatch.isPending) return;

    const columnMapping = buildColumnMapping();
    const { rows, errors: parseErrors } = parseAnswersCsv(
      rawText,
      columnMapping,
      requiresQuestionText,
    );
    setErrors(parseErrors);
    setParsedCount(rows.length);
    if (rows.length === 0) return;

    createBatch.mutate(
      {
        file: originalFile,
        input: {
          fileName,
          strictness,
          retainAnswer: true,
          columnMapping,
        },
      },
      {
        onSuccess: (info) => {
          setBatchId(info.batchId);
          activeBatch.save({
            batchId: info.batchId,
            fileName: info.fileName,
            rowTotal: info.rowTotal,
          });
          showToast("Batch submitted. Watching progress…");
        },
      },
    );
  }

  function onReset() {
    resetFileState();
    setBatchId(null);
    createBatch.reset();
    if (inputRef.current) inputRef.current.value = "";
  }

  const shownErrors = errorsExpanded ? errors : errors.slice(0, 6);

  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-xl bg-surface p-7 shadow-md">
        {!rawText && (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const f = e.dataTransfer.files[0];
              if (f) void loadFile(f);
            }}
            className={`flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed px-6 py-9 text-center transition-colors ${
              dragging
                ? "border-accent bg-accent-soft"
                : "border-border bg-input-bg"
            }`}
          >
            <p className="text-sm text-foreground">
              Drop a CSV here, or{" "}
              <TextButton
                onClick={() => inputRef.current?.click()}
                className="font-medium"
              >
                browse
              </TextButton>
            </p>
            <p className="font-mono text-xs text-disabled-foreground">
              external_ref, answer_text, question_text (optional) · up to{" "}
              {MAX_ROWS} rows · UTF-8
            </p>
            <label htmlFor="batch-csv-input" className="sr-only">
              Upload CSV
            </label>
            <input
              id="batch-csv-input"
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void loadFile(f);
              }}
            />
          </div>
        )}

        {rawText && !batchId && (
          <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-input-bg px-4 py-3">
            <div className="flex min-w-0 items-center gap-3">
              <FileText
                className="h-8 w-8 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">
                  {fileName}
                </p>
                <p className="text-[13px] text-disabled-foreground">
                  {parsedCount !== null
                    ? `${parsedCount} rows parsed`
                    : "Parsing…"}
                </p>
              </div>
            </div>
            <Button
              variant="destructiveOutline"
              size="xs"
              onClick={onReset}
              className="shrink-0"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
              Remove
            </Button>
          </div>
        )}

        {shownErrors.length > 0 && (
          <div className={`mt-4 ${ALERT_CLASS}`} role="alert">
            {shownErrors.map((err) => (
              <p key={err} className="leading-relaxed">
                {err}
              </p>
            ))}
            {errors.length > 6 && (
              <TextButton
                onClick={() => setErrorsExpanded((v) => !v)}
                className="mt-1 text-[13px]"
              >
                {errorsExpanded
                  ? "Show fewer"
                  : `…and ${errors.length - 6} more. Show all`}
              </TextButton>
            )}
          </div>
        )}

        {needsMapping && rawText && !batchId && (
          <div className="mt-5">
            <p className="text-sm font-medium text-foreground">
              Map your columns to our fields
            </p>
            <p className="mt-1 text-xs text-disabled-foreground">
              This file's headers don't match our field names. Tell us which
              column is which — "Not used" skips a column entirely.
            </p>
            <div className="mt-4 flex items-center gap-3">
              <span className="w-40 shrink-0 text-xs font-medium tracking-wide text-disabled-foreground uppercase">
                Your CSV column
              </span>
              <span className="text-xs font-medium tracking-wide text-disabled-foreground uppercase">
                Maps to
              </span>
            </div>
            <div className="mt-2 flex flex-col gap-2.5">
              {headers.map((header) => {
                const id = `batch-map-${header}`;
                return (
                  <div key={header} className="flex items-center gap-3">
                    <label
                      htmlFor={id}
                      className="w-40 shrink-0 truncate rounded-md border border-border bg-input-bg px-2.5 py-1.5 font-mono text-sm text-foreground"
                    >
                      {header || "(blank header)"}
                    </label>
                    <select
                      id={id}
                      value={mapping[header] ?? ""}
                      onChange={(e) =>
                        setMapping((m) => ({ ...m, [header]: e.target.value }))
                      }
                      className="rounded-md border border-border bg-input-bg px-2.5 py-1.5 text-sm text-foreground"
                    >
                      <option value="">Not used</option>
                      {CANONICAL_FIELDS.map((field) => (
                        <option key={field} value={field}>
                          {FIELD_LABEL[field]}
                        </option>
                      ))}
                    </select>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {rawText && !batchId && (
          <div className="mt-5 max-w-sm">
            <StrictnessField value={strictness} onChange={setStrictness} />
          </div>
        )}

        {rawText && !batchId && (
          <div className="mt-5 flex items-center justify-end">
            <Button
              onClick={onRun}
              disabled={createBatch.isPending}
              className="shrink-0"
            >
              {createBatch.isPending
                ? "Uploading…"
                : parsedCount !== null
                  ? `Run ${parsedCount} checks`
                  : "Run"}
            </Button>
          </div>
        )}

        {batchId && !done && (
          <div className="mt-5">
            {(() => {
              const scored = progress.data
                ? progress.data.completed + progress.data.failed
                : 0;
              const total = progress.data?.rowTotal ?? 0;
              const pct = total > 0 ? Math.round((scored / total) * 100) : 0;
              const label =
                fileName ??
                progress.data?.batch.fileName ??
                activeBatch.active?.fileName;
              return (
                <>
                  <div className="flex items-center justify-between gap-4 text-[13px] text-muted-foreground">
                    <span>
                      Screening in progress…{" "}
                      {label && (
                        <span className="text-foreground">{label}</span>
                      )}
                    </span>
                    <div className="flex shrink-0 items-center gap-3">
                      <span className="font-mono text-foreground">
                        {scored} / {total} · {pct}%
                      </span>
                      <Button
                        variant="destructiveOutline"
                        size="xs"
                        onClick={() => setShowCancelConfirm(true)}
                      >
                        Stop batch
                      </Button>
                    </div>
                  </div>
                  <div
                    role="progressbar"
                    aria-label="Batch progress"
                    aria-valuemin={0}
                    aria-valuemax={total}
                    aria-valuenow={scored}
                    className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-primary-soft"
                  >
                    <div
                      className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </>
              );
            })()}
          </div>
        )}

        {cancelled && (
          <p className="mt-4 rounded-md bg-warning-soft px-3.5 py-2.5 text-[13px] text-foreground">
            This batch was stopped before every row was checked. Rows already
            scored are below; the rest were skipped.
          </p>
        )}

        <p role="status" className="sr-only">
          {batchId && !done && progress.data
            ? `Checked ${Math.floor(((progress.data.completed + progress.data.failed) / progress.data.rowTotal) * 10) * 10} percent`
            : resultEntry
              ? `Batch complete. ${resultEntry.counts.ai_generated} flagged, ${resultEntry.counts.uncertain} uncertain, ${resultEntry.counts.human_written} likely human.` +
                (resultEntry.failures?.length
                  ? ` ${resultEntry.failures.length} rows could not be checked.`
                  : "")
              : ""}
        </p>

        {createBatch.isError && (
          <p className={`mt-4 ${ALERT_CLASS}`} role="alert">
            The batch could not be submitted. Nothing was saved. Try again.
          </p>
        )}
      </section>

      {resultEntry && (
        <div ref={resultsRef}>
          <BatchResultsTable run={resultEntry} liveOrder={!done} />
        </div>
      )}

      <CancelBatchDialog
        open={showCancelConfirm}
        fileName={
          fileName ??
          progress.data?.batch.fileName ??
          activeBatch.active?.fileName ??
          null
        }
        busy={cancelBatch.isPending}
        onClose={() => setShowCancelConfirm(false)}
        onConfirm={() =>
          cancelBatch.mutate(undefined, {
            onSuccess: () => {
              setShowCancelConfirm(false);
              showToast("Batch stopped.");
            },
          })
        }
      />
    </div>
  );
}
