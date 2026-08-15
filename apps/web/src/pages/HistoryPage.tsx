import DataTable, {
  TABLE_ACTION_COLUMN_WIDTH,
  type DataTableColumn,
} from "../components/ui/DataTable";
import SegmentedToggle, {
  type SegmentedToggleOption,
} from "../components/ui/SegmentedToggle";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useHistory } from "../hooks/useChecks";
import VerdictChip from "../components/VerdictChip";
import { usePageTitle } from "../hooks/usePageTitle";
import PageHeader from "../components/ui/PageHeader";
import Pagination from "../components/ui/Pagination";
import Page, { PageFill } from "../components/ui/Page";
import SearchInput from "../components/ui/SearchInput";
import { fmtDateShort, truncate } from "../lib/format";
import { RowActionLink } from "../components/ui/RowAction";
import ModelStatusBadge from "../components/ModelStatusBadge";
import { entryId, type HistoryEntry, type Verdict } from "../types";
import Dropdown, { type DropdownOption } from "../components/ui/Dropdown";

type Filter = "all" | Verdict;
const PAGE_SIZE = 8;

const FILTER_TABS: SegmentedToggleOption<Filter>[] = [
  { value: "all", label: "All" },
  { value: "ai_generated", label: "Flagged" },
  { value: "uncertain", label: "Uncertain" },
  { value: "human_written", label: "Human" },
];

const DAY_RANGES: DropdownOption<number>[] = [
  { value: 7, label: "Last 7 days" },
  { value: 30, label: "Last 30 days" },
];

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
  usePageTitle("Past checks");
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
      width: "7rem",
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
        <span className="min-w-0 max-w-[18rem] truncate text-sm text-muted-foreground">
          {entry.kind === "single"
            ? truncate(entry.answerText ?? "Answer not retained", 60)
            : `${entry.fileName} · ${entry.rows.length} answers`}
        </span>
      ),
    },
    {
      id: "score",
      header: "Score",
      width: "6rem",
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
      width: "minmax(0,1.1fr)",
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
      width: TABLE_ACTION_COLUMN_WIDTH,
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
    <Page>
      <PageHeader
        title="Past checks"
        subtitle="Every check is stored with its score, verdict, and model version."
        actions={<ModelStatusBadge />}
      />

      {isPending ? (
        <section
          className="mt-8 flex shrink-0 flex-col gap-3 rounded-xl border border-border bg-surface p-7"
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
        <section className="mt-8 shrink-0 rounded-xl border border-border bg-surface p-12 text-center">
          <p className="text-lg font-medium text-foreground">No checks yet</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
            Checked answers will appear here. Run your first check from the
            Check answers page.
          </p>
        </section>
      ) : (
        <>
          <div className="mt-7 flex shrink-0 flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <SearchInput
                value={query}
                onChange={setAndResetPage(setQuery)}
                placeholder="Search answers…"
                ariaLabel="Search answers"
                wrapperClassName="w-64"
              />
              <SegmentedToggle
                options={FILTER_TABS}
                value={filter}
                onChange={setAndResetPage(setFilter)}
                ariaLabel="Filter by verdict"
              />
            </div>
            <Dropdown<number>
              value={days === 0 ? null : days}
              onChange={(next) => setAndResetPage(setDays)(next ?? 0)}
              options={DAY_RANGES}
              placeholder="All time"
              resetLabel="All time"
              ariaLabel="Time range"
            />
          </div>

          <PageFill className="mt-5 gap-4">
            <DataTable<HistoryEntry>
              fillHeight
              columns={columns}
              rows={visible}
              getRowId={entryId}
              onSelect={(id) => void navigate(`/history/${id}`)}
              emptyState={
                <p className="text-disabled-foreground">
                  No checks match the current filters.
                </p>
              }
            />
            <div className="shrink-0">
              <Pagination
                page={current + 1}
                totalPages={pageCount}
                total={entries.length}
                pageSize={PAGE_SIZE}
                itemNoun="checks"
                onPageChange={(next) => setPage(next - 1)}
              />
            </div>
          </PageFill>
        </>
      )}
    </Page>
  );
}
