import Button from "./ui/Button";
import TextButton from "./ui/TextButton";
import { useToast } from "../hooks/useToast";
import StrictnessField from "./StrictnessField";
import { useRunBatch } from "../hooks/useChecks";
import { useEffect, useRef, useState } from "react";
import BatchResultsTable from "./BatchResultsTable";
import { MAX_ROWS, parseAnswersCsv } from "../lib/csv";
import type { BatchRowInput, Strictness } from "../api/types";

interface LoadedFile {
  name: string;
  rows: BatchRowInput[];
}

const ALERT_CLASS =
  "rounded-md bg-danger-soft px-4 py-3 text-[13px] text-danger";

export default function BatchTab() {
  const [file, setFile] = useState<LoadedFile | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [progress, setProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [strictness, setStrictness] = useState<Strictness>("standard");
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const { showToast } = useToast();
  const batch = useRunBatch((done, total) => setProgress({ done, total }));

  useEffect(() => {
    if (batch.isSuccess) {
      resultsRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }
  }, [batch.isSuccess]);

  async function loadFile(f: File) {
    if (batch.isPending) return;
    batch.reset();
    setProgress(null);
    try {
      const text = await f.text();
      const { rows, errors } = parseAnswersCsv(text);
      setErrors(errors);
      setFile(rows.length > 0 ? { name: f.name, rows } : null);
    } catch {
      setErrors([
        "That file could not be read. Try exporting it again as UTF-8 CSV.",
      ]);
      setFile(null);
    }
  }

  function onRun() {
    if (!file || batch.isPending) return;
    setProgress({ done: 0, total: file.rows.length });
    batch.mutate(
      { fileName: file.name, rows: file.rows, strictness },
      { onSuccess: () => showToast("Batch complete. Saved to history.") },
    );
  }

  function onReset() {
    setFile(null);
    setErrors([]);
    setProgress(null);
    batch.reset();
    if (inputRef.current) inputRef.current.value = "";
  }

  const shownErrors = errors.slice(0, 6);

  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-xl border border-border bg-surface p-7">
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
          <input
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

        {shownErrors.length > 0 && (
          <div className={`mt-4 ${ALERT_CLASS}`} role="alert">
            {shownErrors.map((err) => (
              <p key={err} className="leading-relaxed">
                {err}
              </p>
            ))}
            {errors.length > shownErrors.length && (
              <p>…and {errors.length - shownErrors.length} more.</p>
            )}
          </div>
        )}

        {file && (
          <div className="mt-5 max-w-sm">
            <StrictnessField value={strictness} onChange={setStrictness} />
          </div>
        )}

        {file && (
          <div className="mt-4 flex items-center justify-between gap-4">
            <div className="flex items-baseline gap-2 rounded-md border border-border bg-input-bg px-3 py-2">
              <span className="text-sm font-medium text-foreground">
                {file.name}
              </span>
              <span className="text-[13px] text-disabled-foreground">
                · {file.rows.length} rows · parsed
              </span>
              <TextButton
                onClick={onReset}
                tone="muted"
                className="ml-2 text-[13px]"
              >
                Remove
              </TextButton>
            </div>
            <Button
              size="lg"
              onClick={onRun}
              disabled={batch.isPending}
              className="shrink-0"
            >
              {batch.isPending && progress
                ? `Checking ${progress.done} of ${progress.total}…`
                : `Run ${file.rows.length} checks`}
            </Button>
          </div>
        )}

        {batch.isPending && progress && (
          <div
            className="mt-4"
            role="progressbar"
            aria-label="Batch progress"
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.done}
          >
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-primary-soft">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${(progress.done / progress.total) * 100}%` }}
              />
            </div>
          </div>
        )}

        <p role="status" className="sr-only">
          {batch.isPending && progress
            ? `Checked ${Math.floor((progress.done / progress.total) * 10) * 10} percent`
            : batch.isSuccess && batch.data
              ? `Batch complete. ${batch.data.counts.ai_generated} flagged, ${batch.data.counts.uncertain} uncertain, ${batch.data.counts.human_written} likely human.`
              : ""}
        </p>

        {batch.isError && (
          <p className={`mt-4 ${ALERT_CLASS}`} role="alert">
            The batch run failed. Nothing was saved. Try again.
          </p>
        )}
      </section>

      {batch.isSuccess && batch.data && (
        <div ref={resultsRef}>
          <BatchResultsTable run={batch.data} />
        </div>
      )}
    </div>
  );
}
