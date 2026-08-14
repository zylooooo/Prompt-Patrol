import { fmtDateTime } from "../lib/format";
import { useEntry } from "../hooks/useChecks";
import { Link, useParams } from "react-router-dom";
import ResultPanel from "../components/ResultPanel";
import BatchResultsTable from "../components/BatchResultsTable";

import { usePageTitle } from "../hooks/usePageTitle";

const SECTION_LABEL =
  "text-[11px] font-semibold tracking-[0.09em] text-muted-foreground uppercase";

export default function HistoryDetailPage() {
  usePageTitle("History entry");
  const { id } = useParams<{ id: string }>();
  const { data: entry, isPending } = useEntry(id);

  return (
    <>
      <Link
        to="/history"
        className="rounded-sm text-sm text-primary underline-offset-2 hover:underline focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30"
      >
        ← History
      </Link>

      {isPending && (
        <p className="mt-6 text-sm text-disabled-foreground">Loading entry…</p>
      )}

      {!isPending && !entry && (
        <section className="mt-6 rounded-xl border border-border bg-surface p-12 text-center">
          <p className="text-lg font-medium text-foreground">Entry not found</p>
          <p className="mt-2 text-sm text-muted-foreground">
            This check may have been removed from the stored history.
          </p>
        </section>
      )}

      {entry?.kind === "single" && (
        <div className="mt-6 grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <section className="rounded-xl border border-border bg-surface p-7">
            <p className={SECTION_LABEL}>Student answer</p>
            <p className="mt-3 text-sm leading-relaxed text-foreground">
              {entry.answerText ??
                "The answer was not retained for this check."}
            </p>
            {entry.questionText && (
              <>
                <p className={`mt-6 ${SECTION_LABEL}`}>Question context</p>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  {entry.questionText}
                </p>
              </>
            )}
          </section>
          <ResultPanel status="success" result={entry} showSavedLink={false} />
        </div>
      )}

      {entry?.kind === "batch" && (
        <div className="mt-6 flex flex-col gap-5">
          <div>
            <h1 className="text-[22px] font-bold text-foreground">
              {entry.fileName}
            </h1>
            <p className="mt-1 font-mono text-xs text-disabled-foreground">
              {fmtDateTime(entry.createdAt)} ·{" "}
              {entry.rows[0]?.detector.modelVersion ?? "no rows"}
            </p>
          </div>
          <BatchResultsTable run={entry} />
        </div>
      )}
    </>
  );
}
