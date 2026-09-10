import DataTable, {
  TABLE_ACTION_COLUMN_WIDTH,
  type DataTableColumn,
} from "./ui/DataTable";
import Button from "./ui/Button";
import RowAction from "./ui/RowAction";
import VerdictChip from "./VerdictChip";
import ResultPanel from "./ResultPanel";
import Pagination from "./ui/Pagination";
import { SECTION_LABEL } from "./ui/section-label";
import { truncate } from "../lib/format";
import { useMemo, useState, type ReactNode } from "react";
import type { BatchRow, BatchRun } from "../types";
import { downloadCsv, serializeResultsCsv } from "../lib/csv";
import { isUncalibrated, UNCALIBRATED_NOTICE } from "../lib/detectorNotice";

const PAGE_SIZE = 10;

function CountChip({
  dotClass,
  children,
}: {
  dotClass: string;
  children: ReactNode;
}) {
  return (
    <span className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
      <span
        aria-hidden
        className={`h-[7px] w-[7px] rounded-full ${dotClass}`}
      />
      {children}
    </span>
  );
}

interface BatchResultsTableProps {
  run: BatchRun;
  // While a batch is still running, newly-scored rows are appended by
  // createdAt instead of the usual flagged-first order - resorting by
  // verdict/score every poll would reshuffle rows the instructor is already
  // looking at out from under them. Once the batch is done, the run's own
  // (flagged-first) order is used as-is.
  liveOrder?: boolean;
}

export default function BatchResultsTable({
  run,
  liveOrder = false,
}: BatchResultsTableProps) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  // A new batch (or a switch between live/final ordering) starts back on
  // page 1 - staying on page 4 of the previous run's rows would show stale
  // or out-of-range data. Reset during render (React's documented pattern
  // for "adjust state when a prop changes") rather than in a useEffect, so
  // it doesn't cost an extra commit-then-rerun-effect render pass.
  const [pageResetKey, setPageResetKey] = useState(`${run.id}:${liveOrder}`);
  const currentResetKey = `${run.id}:${liveOrder}`;
  if (currentResetKey !== pageResetKey) {
    setPageResetKey(currentResetKey);
    setPage(0);
  }

  const rows = useMemo(
    () =>
      liveOrder
        ? [...run.rows].sort((a, b) => a.createdAt.localeCompare(b.createdAt))
        : run.rows,
    [run.rows, liveOrder],
  );

  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visibleRows = rows.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );

  function onDownload() {
    const base = run.fileName.replace(/\.csv$/i, "");
    downloadCsv(`${base}-results.csv`, serializeResultsCsv(run));
  }

  const toggle = (checkId: string) =>
    setExpanded((current) => (current === checkId ? null : checkId));

  const columns: DataTableColumn<BatchRow>[] = [
    {
      id: "externalRef",
      header: "Reference",
      width: "minmax(0,0.9fr)",
      cell: (row) => (
        <span className="truncate font-mono text-[13px] text-foreground">
          {row.externalRef}
        </span>
      ),
    },
    {
      id: "answer",
      header: "Answer",
      width: "minmax(0,2.4fr)",
      cell: (row) => (
        <span className="truncate text-sm text-muted-foreground">
          {truncate(row.answerText ?? "")}
        </span>
      ),
    },
    {
      id: "score",
      header: "Score",
      width: "minmax(0,0.5fr)",
      hideWhenCompact: true,
      cell: (row) => (
        <span className="font-mono text-[13px] text-foreground">
          {row.rawScore.toFixed(2)}
        </span>
      ),
    },
    {
      id: "verdict",
      header: "Verdict",
      width: "minmax(0,0.8fr)",
      cell: (row) => <VerdictChip verdict={row.verdict} />,
    },
    {
      id: "actions",
      header: "",
      width: TABLE_ACTION_COLUMN_WIDTH,
      align: "right",
      cell: (row) => (
        <span onClick={(e) => e.stopPropagation()}>
          <RowAction onClick={() => toggle(row.checkId)}>
            {expanded === row.checkId ? "Hide" : "View"}
          </RowAction>
        </span>
      ),
    },
  ];

  const expandedRow = rows.find((row) => row.checkId === expanded);
  const failures = run.failures ?? [];
  const shownFailures = failures.slice(0, 6);

  return (
    <section className="rounded-xl bg-surface p-7 shadow-md">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-base font-medium text-foreground">{run.fileName}</p>
        <div className="flex items-center gap-5">
          <CountChip dotClass="bg-flag">
            {run.counts.ai_generated} flagged
          </CountChip>
          <CountChip dotClass="bg-unsure">
            {run.counts.uncertain} uncertain
          </CountChip>
          <CountChip dotClass="bg-human">
            {run.counts.human_written} likely human
          </CountChip>
        </div>
      </div>

      {failures.length > 0 && (
        <div
          className="mt-4 rounded-md bg-warning-soft px-3.5 py-2.5 text-[13px] text-foreground"
          role="status"
        >
          <p className="font-medium">
            {failures.length} of {run.rows.length + failures.length} rows could
            not be checked. The rest were scored.
          </p>
          <ul className="mt-1.5 space-y-0.5 text-muted-foreground">
            {shownFailures.map((failure) => (
              <li key={failure.externalRef}>
                <span className="font-mono">{failure.externalRef}</span> —{" "}
                {failure.reason}
              </li>
            ))}
            {failures.length > shownFailures.length && (
              <li>…and {failures.length - shownFailures.length} more.</li>
            )}
          </ul>
        </div>
      )}

      {rows.length > 0 && isUncalibrated(rows[0].detector) && (
        <p className="mt-3 text-xs text-disabled-foreground">
          {UNCALIBRATED_NOTICE}
        </p>
      )}

      <div className="mt-5">
        <DataTable<BatchRow>
          columns={columns}
          rows={visibleRows}
          getRowId={(row) => row.checkId}
          selectedId={expanded}
          onSelect={toggle}
          footer={
            failures.length > 0
              ? `${rows.length} scored${liveOrder ? "" : " · flagged first"}`
              : `${rows.length} total${liveOrder ? "" : " · flagged first"}`
          }
        />
        <div className="mt-3">
          <Pagination
            page={currentPage + 1}
            totalPages={pageCount}
            total={rows.length}
            pageSize={PAGE_SIZE}
            itemNoun="answers"
            onPageChange={(next) => setPage(next - 1)}
          />
        </div>
      </div>

      {expandedRow && (
        <div className="mt-4 grid grid-cols-1 items-start gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <section className="rounded-xl bg-surface p-7 shadow-md">
            <p className={SECTION_LABEL}>Student answer</p>
            <p className="mt-3 text-sm leading-relaxed text-foreground">
              {expandedRow.answerText ??
                "The answer was not retained for this check."}
            </p>
            {expandedRow.questionText && (
              <>
                <p className={`mt-6 ${SECTION_LABEL}`}>Question context</p>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  {expandedRow.questionText}
                </p>
              </>
            )}
          </section>
          <ResultPanel
            status="success"
            result={expandedRow}
            showSavedLink={false}
          />
        </div>
      )}

      <div className="mt-5 flex items-center justify-end">
        <Button variant="secondary" onClick={onDownload}>
          Download results (CSV)
        </Button>
      </div>
    </section>
  );
}
