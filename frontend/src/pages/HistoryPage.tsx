import { useMemo, useState } from 'react'
import { RowActionLink } from '../components/RowAction'
import PageHeader from '../components/PageHeader'
import VerdictChip from '../components/VerdictChip'
import { useHistory } from '../lib/hooks'
import { fmtDateShort, truncate } from '../lib/format'
import { usePageTitle } from '../lib/usePageTitle'
import { entryId, type HistoryEntry, type Verdict } from '../lib/types'

type Filter = 'all' | Verdict
const PAGE_SIZE = 8

const FILTER_TABS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'ai_generated', label: 'Flagged' },
  { id: 'uncertain', label: 'Uncertain' },
  { id: 'human_written', label: 'Human' },
]

function matchesFilter(entry: HistoryEntry, filter: Filter): boolean {
  if (filter === 'all') return true
  return entry.kind === 'single' ? entry.verdict === filter : entry.counts[filter] > 0
}

function matchesQuery(entry: HistoryEntry, q: string): boolean {
  if (!q) return true
  const needle = q.toLowerCase()
  return entry.kind === 'single'
    ? (entry.answerText ?? '').toLowerCase().includes(needle)
    : entry.fileName.toLowerCase().includes(needle)
}

function matchesDays(entry: HistoryEntry, days: number): boolean {
  if (days === 0) return true
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000
  return new Date(entry.createdAt).getTime() >= cutoff
}

export default function HistoryPage() {
  usePageTitle('History')
  const { data, isPending } = useHistory()
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [days, setDays] = useState(0)
  const [page, setPage] = useState(0)

  const entries = useMemo(() => {
    return (data ?? []).filter(
      (e) => matchesFilter(e, filter) && matchesQuery(e, query) && matchesDays(e, days),
    )
  }, [data, filter, query, days])

  const pageCount = Math.max(1, Math.ceil(entries.length / PAGE_SIZE))
  const current = Math.min(page, pageCount - 1)
  const visible = entries.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE)

  function setAndResetPage<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v)
      setPage(0)
    }
  }

  const hasAny = (data ?? []).length > 0

  return (
    <>
      <PageHeader
        title="History"
        subtitle="Every check is stored with its score, verdict, and model version."
      />

      {isPending ? (
        <section
          className="mt-8 flex flex-col gap-3 rounded-xl border border-line bg-surface p-7"
          aria-busy="true"
          aria-label="Loading history"
        >
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded-md bg-navy-50" />
          ))}
        </section>
      ) : !hasAny ? (
        <section className="mt-8 rounded-xl border border-line bg-surface p-12 text-center">
          <p className="font-display text-lg font-medium text-ink">No checks yet</p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-muted">
            Checked answers will appear here. Run your first check from the Check answers page.
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
                className="h-9 w-64 rounded-md border border-line bg-surface px-3.5 text-sm text-ink placeholder:text-ink-faint"
              />
              {FILTER_TABS.map((option) => (
                <button
                  key={option.id}
                  onClick={() => setAndResetPage(setFilter)(option.id)}
                  aria-pressed={filter === option.id}
                  className={`h-9 rounded-md border px-3.5 text-sm transition-colors ${
                    filter === option.id
                      ? 'border-navy-800 bg-navy-800 text-white'
                      : 'border-line bg-surface text-ink-muted hover:text-ink'
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
              className="h-9 rounded-md border border-line bg-surface px-3 text-sm text-ink-muted"
            >
              <option value={0}>All time</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
            </select>
          </div>

          <section className="mt-5 rounded-xl border border-line bg-surface px-7 py-2">
            {/* only the table scrolls, so pagination stays put on a narrow window */}
            <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse text-left">
              <thead>
                <tr className="border-b border-line">
                  <th className="py-3 pr-4 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
                    Checked at
                  </th>
                  <th className="py-3 pr-4 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
                    Type
                  </th>
                  <th className="py-3 pr-4 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
                    Answer
                  </th>
                  <th className="py-3 pr-4 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
                    Score
                  </th>
                  <th className="py-3 pr-4 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
                    Verdict
                  </th>
                  <th className="py-3" />
                </tr>
              </thead>
              <tbody>
                {visible.map((entry) => (
                  <tr key={entryId(entry)} className="border-b border-line last:border-b-0">
                    <td className="py-4 pr-4 text-sm whitespace-nowrap text-ink">
                      {fmtDateShort(entry.createdAt)}
                    </td>
                    <td className="py-4 pr-4 text-sm text-ink-muted">
                      {entry.kind === 'single' ? 'Single' : 'Batch'}
                    </td>
                    <td className="max-w-[380px] py-4 pr-4 text-sm text-ink-muted">
                      {entry.kind === 'single'
                        ? truncate(entry.answerText ?? 'Answer not retained', 60)
                        : `${entry.fileName} · ${entry.rows.length} answers`}
                    </td>
                    <td className="py-4 pr-4 font-mono text-[13px] text-ink">
                      {entry.kind === 'single' ? entry.rawScore.toFixed(2) : '·'}
                    </td>
                    <td className="py-4 pr-4">
                      {entry.kind === 'single' ? (
                        <VerdictChip verdict={entry.verdict} />
                      ) : (
                        <span className="flex items-center gap-1.5 text-[13px] text-ink-muted">
                          <span aria-hidden className="h-[7px] w-[7px] rounded-full bg-flag" />
                          {entry.counts.ai_generated} flagged
                        </span>
                      )}
                    </td>
                    <td className="py-4 text-right">
                      <RowActionLink to={`/history/${entryId(entry)}`}>
                        {entry.kind === 'single' ? 'View' : 'Open'}
                      </RowActionLink>
                    </td>
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-10 text-center text-sm text-ink-faint">
                      No checks match the current filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
            </div>

            <div className="flex items-center justify-between border-t border-line py-3.5">
              <p className="text-[13px] text-ink-faint">
                Page {current + 1} of {pageCount} · {entries.length} checks stored
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(current - 1)}
                  disabled={current === 0}
                  className="h-9 rounded-md border border-line px-4 text-sm text-ink-muted transition-colors hover:text-ink disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  onClick={() => setPage(current + 1)}
                  disabled={current >= pageCount - 1}
                  className="h-9 rounded-md border border-line px-4 text-sm text-ink-muted transition-colors hover:text-ink disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          </section>
        </>
      )}
    </>
  )
}
