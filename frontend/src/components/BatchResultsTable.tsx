import { Fragment, useState } from 'react'
import type { BatchRun } from '../lib/types'
import { downloadCsv, serializeResultsCsv } from '../lib/csv'
import { truncate } from '../lib/format'
import VerdictChip from './VerdictChip'
import RowAction from './RowAction'
import SignalsList from './SignalsList'

function CountChip({ dotClass, children }: { dotClass: string; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1.5 text-[13px] text-ink-muted">
      <span aria-hidden className={`h-[7px] w-[7px] rounded-full ${dotClass}`} />
      {children}
    </span>
  )
}

export default function BatchResultsTable({ run }: { run: BatchRun }) {
  const [expanded, setExpanded] = useState<string | null>(null)

  function onDownload() {
    const base = run.fileName.replace(/\.csv$/i, '')
    downloadCsv(`${base}-results.csv`, serializeResultsCsv(run))
  }

  return (
    <section className="rounded-xl border border-line bg-surface p-7">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-display text-base font-medium text-ink">{run.fileName}</p>
        <div className="flex items-center gap-5">
          <CountChip dotClass="bg-flag">{run.counts.ai_generated} flagged</CountChip>
          <CountChip dotClass="bg-unsure">{run.counts.uncertain} uncertain</CountChip>
          <CountChip dotClass="bg-human">{run.counts.human_written} likely human</CountChip>
        </div>
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full min-w-[880px] border-collapse text-left">
          <thead>
            <tr className="border-b border-line">
              <th className="py-2.5 pr-4 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
                Reference
              </th>
              <th className="py-2.5 pr-4 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
                Answer
              </th>
              <th className="py-2.5 pr-4 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
                Score
              </th>
              <th className="py-2.5 pr-4 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
                Verdict
              </th>
              <th className="py-2.5 text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase" />
            </tr>
          </thead>
          <tbody>
            {run.rows.map((row) => (
              <Fragment key={row.checkId}>
                <tr className="border-b border-line last:border-b-0">
                  <td className="py-3.5 pr-4 font-mono text-[13px] whitespace-nowrap text-ink">
                    {row.externalRef}
                  </td>
                  <td className="max-w-[420px] py-3.5 pr-4 text-sm text-ink-muted">
                    {truncate(row.answerText ?? '')}
                  </td>
                  <td className="py-3.5 pr-4 font-mono text-[13px] text-ink">
                    {row.rawScore.toFixed(2)}
                  </td>
                  <td className="py-3.5 pr-4">
                    <VerdictChip verdict={row.verdict} />
                  </td>
                  <td className="py-3.5 text-right">
                    <RowAction
                      onClick={() => setExpanded(expanded === row.checkId ? null : row.checkId)}
                    >
                      {expanded === row.checkId ? 'Hide' : 'View'}
                    </RowAction>
                  </td>
                </tr>
                {expanded === row.checkId && (
                  <tr className="border-b border-line last:border-b-0">
                    <td colSpan={5} className="bg-navy-50 px-4 py-4">
                      <p className="text-sm leading-relaxed text-ink">{row.answerText}</p>
                      {row.questionText && (
                        <p className="mt-2 text-xs text-ink-faint">question: {row.questionText}</p>
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

      <div className="mt-5 flex items-center justify-between border-t border-line pt-4">
        <p className="text-[13px] text-ink-faint">
          Showing all {run.rows.length} · flagged first
        </p>
        <button
          onClick={onDownload}
          className="h-10 rounded-lg border border-line px-4 text-sm font-medium text-navy-800 transition-colors hover:bg-navy-50"
        >
          Download results (CSV)
        </button>
      </div>
    </section>
  )
}
