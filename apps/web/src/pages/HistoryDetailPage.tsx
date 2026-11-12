import { fmtDateTime } from "../lib/format";
import { useParams } from "react-router-dom";
import { useEntry } from "../hooks/useChecks";
import ResultPanel from "../components/ResultPanel";
import { TextLink } from "../components/ui/TextButton";
import ErrorState from "../components/ui/ErrorState";
import LoadingState from "../components/ui/LoadingState";
import Page, { PageScroll } from "../components/ui/Page";
import BatchResultsTable from "../components/BatchResultsTable";

import { usePageTitle } from "../hooks/usePageTitle";
import { SECTION_LABEL } from "../components/ui/section-label";

export default function HistoryDetailPage() {
  usePageTitle("Check details");
  const { id } = useParams<{ id: string }>();
  const { data: entry, isPending, isError, refetch } = useEntry(id);

  return (
    <Page>
      <div className="shrink-0">
        <TextLink to="/history" className="text-sm">
          ← History
        </TextLink>
      </div>

      <PageScroll>
        {isPending && <LoadingState size="card" label="Loading entry…" />}

        {isError && (
          <ErrorState
            className="mt-6"
            title="We couldn't load this check"
            description="It's still saved. Try again in a moment."
            onRetry={() => void refetch()}
          />
        )}

        {!isPending && !isError && !entry && (
          <section className="mt-6 rounded-xl bg-surface p-12 text-center shadow-md">
            <p className="text-lg font-medium text-foreground">
              We couldn't find that check
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              It may have been removed, or the link may be wrong.
            </p>
          </section>
        )}

        {entry?.kind === "single" && (
          <div className="mt-6 grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <section className="rounded-xl bg-surface p-7 shadow-md">
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
            <ResultPanel
              status="success"
              result={entry}
              showSavedLink={false}
            />
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
      </PageScroll>
    </Page>
  );
}
