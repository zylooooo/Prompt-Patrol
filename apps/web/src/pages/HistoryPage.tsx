import { useMemo, useState } from "react";
import { useHistory } from "../hooks/useChecks";
import PageHeader from "../components/PageHeader";
import VerdictChip from "../components/VerdictChip";
import { usePageTitle } from "../hooks/usePageTitle";
import { fmtDateShort, truncate } from "../lib/format";
import { RowActionLink } from "../components/RowAction";
import { entryId, type HistoryEntry, type Verdict } from "../api/types";

type Filter = "all" | Verdict;
const PAGE_SIZE = 8;

const FILTER_TABS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "ai_generated", label: "Flagged" },
  { id: "uncertain", label: "Uncertain" },
  { id: "human_written", label: "Human" },
];

const HEAD_CELL =
  "py-3 pr-4 text-[11px] font-semibold tracking-[0.09em] text-muted-foreground uppercase";

const CONTROL =
  "h-9 rounded-md border border-input-border bg-surface text-sm transition focus:outline-hidden focus:ring-2 focus:ring-focus-ring/30";

const PAGER_BUTTON =
  "h-9 rounded-md border border-border px-4 text-sm text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40 focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30";

function matchesFilter(entry: HistoryEntry, filter: Filter): boolean {
  if (filter === "all") return true;
  return entry.kind === "single"
    ? entry.verdict === filter
    : entry.counts[filter] > 0;
}

function matchesQuery(entry: HistoryEntry, q: string): boolean {
  if (!q) return true;
  const needle = q.toLowerCase();
  return entry.kind === "single"
    ? (entry.answerText ?? "").toLowerCase().includes(needle)
    : entry.fileName.toLowerCase().includes(needle);
}

function matchesDays(entry: HistoryEntry, days: number): boolean {
  if (days === 0) return true;
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return new Date(entry.createdAt).getTime() >= cutoff;
}

export default function HistoryPage() {
  usePageTitle("History");
  const { data, isPending } = useHistory();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [days, setDays] = useState(0);
  const [page, setPage] = useState(0);

  const entries = useMemo(() => {
    return (data ?? []).filter(
      (e) =>
        matchesFilter(e, filter) &&
        matchesQuery(e, query) &&
        matchesDays(e, days),
    );
  }, [data, filter, query, days]);

  const pageCount = Math.max(1, Math.ceil(entries.length / PAGE_SIZE));
  const current = Math.min(page, pageCount - 1);
  const visible = entries.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);

  function setAndResetPage<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setPage(0);
    };
  }

  const hasAny = (data ?? []).length > 0;

  return (
    <>
      <PageHeader
        title="History"
        subtitle="Every check is stored with its score, verdict, and model version."
      />

      {isPending ? (
        <section
          className="mt-8 flex flex-col gap-3 rounded-xl border border-border bg-surface p-7"
          aria-busy="true"
          aria-label="Loading history"
        >
          {[0, 1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="h-10 animate-pulse rounded-md bg-surface-muted"
            />
          ))}
        </section>
      ) : !hasAny ? (
        <section className="mt-8 rounded-xl border border-border bg-surface p-12 text-center">
          <p className="text-lg font-medium text-foreground">No checks yet</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
            Checked answers will appear here. Run your first check from the
            Check answers page.
          </p>
        </section>
      ) : (
        <>
          <div className="mt-7 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={query}
                onChange={(e) => setAndResetPage(setQuery)(e.target.value)}
                placeholder="Search answers…"
                aria-label="Search answers"
                className={`w-64 px-3.5 text-foreground placeholder:text-input-placeholder ${CONTROL}`}
              />
              {FILTER_TABS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setAndResetPage(setFilter)(option.id)}
                  aria-pressed={filter === option.id}
                  className={`h-9 rounded-md border px-3.5 text-sm transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30 ${
                    filter === option.id
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-surface text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <select
              value={days}
              onChange={(e) => setAndResetPage(setDays)(Number(e.target.value))}
              aria-label="Time range"
              className={`px-3 text-muted-foreground ${CONTROL}`}
            >
              <option value={0}>All time</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
            </select>
          </div>

          <section className="mt-5 rounded-xl border border-border bg-surface px-7 py-2">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-border">
                    <th className={HEAD_CELL}>Checked at</th>
                    <th className={HEAD_CELL}>Type</th>
                    <th className={HEAD_CELL}>Answer</th>
                    <th className={HEAD_CELL}>Score</th>
                    <th className={HEAD_CELL}>Verdict</th>
                    <th className="py-3" />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((entry) => (
                    <tr
                      key={entryId(entry)}
                      className="border-b border-border last:border-b-0"
                    >
                      <td className="py-4 pr-4 text-sm whitespace-nowrap text-foreground">
                        {fmtDateShort(entry.createdAt)}
                      </td>
                      <td className="py-4 pr-4 text-sm text-muted-foreground">
                        {entry.kind === "single" ? "Single" : "Batch"}
                      </td>
                      <td className="max-w-[380px] py-4 pr-4 text-sm text-muted-foreground">
                        {entry.kind === "single"
                          ? truncate(
                              entry.answerText ?? "Answer not retained",
                              60,
                            )
                          : `${entry.fileName} · ${entry.rows.length} answers`}
                      </td>
                      <td className="py-4 pr-4 font-mono text-[13px] text-foreground">
                        {entry.kind === "single"
                          ? entry.rawScore.toFixed(2)
                          : "·"}
                      </td>
                      <td className="py-4 pr-4">
                        {entry.kind === "single" ? (
                          <VerdictChip verdict={entry.verdict} />
                        ) : (
                          <span className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
                            <span
                              aria-hidden
                              className="h-[7px] w-[7px] rounded-full bg-flag"
                            />
                            {entry.counts.ai_generated} flagged
                          </span>
                        )}
                      </td>
                      <td className="py-4 text-right">
                        <RowActionLink to={`/history/${entryId(entry)}`}>
                          {entry.kind === "single" ? "View" : "Open"}
                        </RowActionLink>
                      </td>
                    </tr>
                  ))}
                  {visible.length === 0 && (
                    <tr>
                      <td
                        colSpan={6}
                        className="py-10 text-center text-sm text-disabled-foreground"
                      >
                        No checks match the current filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between border-t border-border py-3.5">
              <p className="text-[13px] text-disabled-foreground">
                Page {current + 1} of {pageCount} · {entries.length} checks
                stored
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setPage(current - 1)}
                  disabled={current === 0}
                  className={PAGER_BUTTON}
                >
                  Previous
                </button>
                <button
                  type="button"
                  onClick={() => setPage(current + 1)}
                  disabled={current >= pageCount - 1}
                  className={PAGER_BUTTON}
                >
                  Next
                </button>
              </div>
            </div>
          </section>
        </>
      )}
    </>
  );
}
