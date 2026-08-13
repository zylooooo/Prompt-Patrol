import { Link, useParams } from 'react-router-dom'
import BatchResultsTable from '../components/BatchResultsTable'
import ResultPanel from '../components/ResultPanel'
import { useEntry } from '../lib/hooks'
import { fmtDateTime } from '../lib/format'
import { usePageTitle } from '../lib/usePageTitle'

export default function HistoryDetailPage() {
  usePageTitle('History entry')
  const { id } = useParams<{ id: string }>()
  const { data: entry, isPending } = useEntry(id)

  return (
    <>
      <Link to="/history" className="text-sm text-navy-800 underline-offset-2 hover:underline">
        ← History
      </Link>

      {isPending && <p className="mt-6 text-sm text-ink-faint">Loading entry…</p>}

      {!isPending && !entry && (
        <section className="mt-6 rounded-xl border border-line bg-surface p-12 text-center">
          <p className="font-display text-lg font-medium text-ink">Entry not found</p>
          <p className="mt-2 text-sm text-ink-muted">
            This check may have been removed from the stored history.
          </p>
        </section>
      )}

      {entry?.kind === 'single' && (
        <div className="mt-6 grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <section className="rounded-xl border border-line bg-surface p-7">
            <p className="text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
              Student answer
            </p>
            <p className="mt-3 text-sm leading-relaxed text-ink">
              {entry.answerText ?? 'The answer was not retained for this check.'}
            </p>
            {entry.questionText && (
              <>
                <p className="mt-6 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
                  Question context
                </p>
                <p className="mt-3 text-sm leading-relaxed text-ink-muted">{entry.questionText}</p>
              </>
            )}
          </section>
          <ResultPanel status="success" result={entry} showSavedLink={false} />
        </div>
      )}

      {entry?.kind === 'batch' && (
        <div className="mt-6 flex flex-col gap-5">
          <div>
            <h1 className="font-display text-[22px] font-bold text-ink">{entry.fileName}</h1>
            <p className="mt-1 font-mono text-xs text-ink-faint">
              {fmtDateTime(entry.createdAt)} · {entry.rows[0]?.detector.modelVersion ?? 'no rows'}
            </p>
          </div>
          <BatchResultsTable run={entry} />
        </div>
      )}
    </>
  )
}
