import DataTable, {
  TABLE_ICON_COLUMN_WIDTH,
  type DataTableColumn,
} from "./ui/DataTable";
import Button from "./ui/Button";
import RowAction from "./RowAction";
import VerdictChip from "./VerdictChip";
import SignalsList from "./SignalsList";
import { truncate } from "../lib/format";
import { useState, type ReactNode } from "react";
import type { BatchRow, BatchRun } from "../api/types";
import { downloadCsv, serializeResultsCsv } from "../lib/csv";

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

export default function BatchResultsTable({ run }: { run: BatchRun }) {
  const [expanded, setExpanded] = useState<string | null>(null);

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
      width: TABLE_ICON_COLUMN_WIDTH,
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

  const expandedRow = run.rows.find((row) => row.checkId === expanded);

  return (
    <section className="rounded-xl border border-border bg-surface p-7">
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

      <div className="mt-5">
        <DataTable<BatchRow>
          columns={columns}
          rows={run.rows}
          getRowId={(row) => row.checkId}
          selectedId={expanded}
          onSelect={toggle}
          bodyMaxHeightClass="max-h-[28rem]"
          footer={`Showing all ${run.rows.length} · flagged first`}
        />
      </div>

      {expandedRow && (
        <div className="mt-4 rounded-xl bg-surface-muted px-5 py-4">
          <p className="text-sm leading-relaxed text-foreground">
            {expandedRow.answerText}
          </p>
          {expandedRow.questionText && (
            <p className="mt-2 text-xs text-disabled-foreground">
              question: {expandedRow.questionText}
            </p>
          )}
          <div className="mt-4">
            <SignalsList
              abstainReason={expandedRow.abstainReason}
              explanation={expandedRow.explanation}
            />
          </div>
        </div>
      )}

      <div className="mt-5 flex items-center justify-end">
        <Button variant="secondary" size="lg" onClick={onDownload}>
          Download results (CSV)
        </Button>
      </div>
    </section>
  );
}
