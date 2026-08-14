import Button from "./ui/Button";
import RowAction from "./RowAction";
import VerdictChip from "./VerdictChip";
import SignalsList from "./SignalsList";
import { truncate } from "../lib/format";
import type { BatchRun } from "../api/types";
import { Fragment, useState, type ReactNode } from "react";
import { downloadCsv, serializeResultsCsv } from "../lib/csv";

const HEAD_CELL =
  "py-2.5 pr-4 text-[11px] font-semibold tracking-[0.09em] text-muted-foreground uppercase";

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

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[880px] border-collapse text-left">
          <thead>
            <tr className="border-b border-border">
              <th className={HEAD_CELL}>Reference</th>
              <th className={HEAD_CELL}>Answer</th>
              <th className={HEAD_CELL}>Score</th>
              <th className={HEAD_CELL}>Verdict</th>
              <th className="py-2.5" />
            </tr>
          </thead>
          <tbody>
            {run.rows.map((row) => (
              <Fragment key={row.checkId}>
                <tr className="border-b border-border last:border-b-0">
                  <td className="py-3.5 pr-4 font-mono text-[13px] whitespace-nowrap text-foreground">
                    {row.externalRef}
                  </td>
                  <td className="max-w-[420px] py-3.5 pr-4 text-sm text-muted-foreground">
                    {truncate(row.answerText ?? "")}
                  </td>
                  <td className="py-3.5 pr-4 font-mono text-[13px] text-foreground">
                    {row.rawScore.toFixed(2)}
                  </td>
                  <td className="py-3.5 pr-4">
                    <VerdictChip verdict={row.verdict} />
                  </td>
                  <td className="py-3.5 text-right">
                    <RowAction
                      onClick={() =>
                        setExpanded(
                          expanded === row.checkId ? null : row.checkId,
                        )
                      }
                    >
                      {expanded === row.checkId ? "Hide" : "View"}
                    </RowAction>
                  </td>
                </tr>
                {expanded === row.checkId && (
                  <tr className="border-b border-border last:border-b-0">
                    <td colSpan={5} className="bg-surface-muted px-4 py-4">
                      <p className="text-sm leading-relaxed text-foreground">
                        {row.answerText}
                      </p>
                      {row.questionText && (
                        <p className="mt-2 text-xs text-disabled-foreground">
                          question: {row.questionText}
                        </p>
                      )}
                      <div className="mt-4">
                        <SignalsList
                          abstainReason={row.abstainReason}
                          explanation={row.explanation}
                        />
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-5 flex items-center justify-between border-t border-border pt-4">
        <p className="text-[13px] text-disabled-foreground">
          Showing all {run.rows.length} · flagged first
        </p>
        <Button variant="secondary" size="lg" onClick={onDownload}>
          Download results (CSV)
        </Button>
      </div>
    </section>
  );
}
