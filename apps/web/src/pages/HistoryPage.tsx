import DataTable, {
  TABLE_ICON_COLUMN_WIDTH,
  type DataTableColumn,
} from "../components/ui/DataTable";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useHistory } from "../hooks/useChecks";
import PageHeader from "../components/PageHeader";
import VerdictChip from "../components/VerdictChip";
import { usePageTitle } from "../hooks/usePageTitle";
import Pagination from "../components/ui/Pagination";
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

const CONTROL =
  "h-9 rounded-md border border-input-border bg-surface text-sm transition focus:outline-hidden focus:ring-2 focus:ring-focus-ring/30";

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
  const navigate = useNavigate();
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

  const columns: DataTableColumn<HistoryEntry>[] = [
    {
      id: "createdAt",
      header: "Checked at",
      width: "minmax(0,1fr)",
      cell: (entry) => (
        <span className="truncate text-sm text-foreground">
          {fmtDateShort(entry.createdAt)}
        </span>
      ),
    },
    {
      id: "kind",
      header: "Type",
      width: "minmax(0,0.5fr)",
      hideWhenCompact: true,
      cell: (entry) => (
        <span className="truncate text-sm text-muted-foreground">
          {entry.kind === "single" ? "Single" : "Batch"}
        </span>
      ),
    },
    {
      id: "answer",
      header: "Answer",
      width: "minmax(0,2fr)",
      cell: (entry) => (
        <span className="truncate text-sm text-muted-foreground">
          {entry.kind === "single"
            ? truncate(entry.answerText ?? "Answer not retained", 60)
            : `${entry.fileName} · ${entry.rows.length} answers`}
        </span>
      ),
    },
    {
      id: "score",
      header: "Score",
      width: "minmax(0,0.5fr)",
      hideWhenCompact: true,
      cell: (entry) => (
        <span className="font-mono text-[13px] text-foreground">
          {entry.kind === "single" ? entry.rawScore.toFixed(2) : "·"}
        </span>
      ),
    },
    {
      id: "verdict",
      header: "Verdict",
      width: "minmax(0,0.8fr)",
      cell: (entry) =>
        entry.kind === "single" ? (
          <VerdictChip verdict={entry.verdict} />
        ) : (
          <span className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
            <span
              aria-hidden
              className="h-[7px] w-[7px] rounded-full bg-flag"
            />
            {entry.counts.ai_generated} flagged
          </span>
        ),
    },
    {
      id: "actions",
      header: "",
      width: TABLE_ICON_COLUMN_WIDTH,
      align: "right",
      cell: (entry) => (
        <span onClick={(e) => e.stopPropagation()}>
          <RowActionLink to={`/history/${entryId(entry)}`}>
            {entry.kind === "single" ? "View" : "Open"}
          </RowActionLink>
        </span>
      ),
    },
  ];

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

          <div className="mt-5">
            <DataTable<HistoryEntry>
              columns={columns}
              rows={visible}
              getRowId={entryId}
              onSelect={(id) => void navigate(`/history/${id}`)}
              emptyState={
                <p className="px-3 py-10 text-center text-sm text-disabled-foreground">
                  No checks match the current filters.
                </p>
              }
              footer={
                <Pagination
                  page={current + 1}
                  totalPages={pageCount}
                  total={entries.length}
                  pageSize={PAGE_SIZE}
                  itemNoun="checks"
                  onPageChange={(next) => setPage(next - 1)}
                />
              }
            />
          </div>
        </>
      )}
    </>
  );
}
