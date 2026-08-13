import { Link } from 'react-router-dom'
import type { SingleCheck } from '../lib/types'
import { STRICTNESS_TEXT } from '../lib/types'
import { fmtDateTime } from '../lib/format'
import VerdictChip from './VerdictChip'
import ScoreGauge from './ScoreGauge'
import SignalsList from './SignalsList'

interface ResultPanelProps {
  status: 'idle' | 'pending' | 'error' | 'success'
  result?: SingleCheck
  showSavedLink?: boolean
}

function MetaRow({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-t border-line py-3 first:border-t-0">
      <span className="text-[13px] text-ink-muted">{name}</span>
      <span className="text-right font-mono text-xs text-ink">{children}</span>
    </div>
  )
}

export default function ResultPanel({ status, result, showSavedLink = true }: ResultPanelProps) {
  return (
    <section className="flex flex-col rounded-xl border border-line bg-surface p-7" aria-live="polite">
      <div className="flex items-center justify-between gap-4">
        <p className="text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">Result</p>
        {status === 'success' && result && <VerdictChip verdict={result.verdict} />}
      </div>

      {status === 'idle' && (
        <p className="mt-6 text-sm text-ink-faint">Results appear here after you check an answer.</p>
      )}

      {status === 'pending' && (
        <div className="mt-6 flex items-center gap-3 text-sm text-ink-muted">
          <span
            aria-hidden
            className="h-4 w-4 animate-spin rounded-full border-2 border-navy-100 border-t-navy-800"
          />
          Checking answer…
        </div>
      )}

      {status === 'error' && (
        <p className="mt-6 rounded-md bg-error-bg px-3.5 py-2.5 text-[13px] text-error" role="alert">
          The check failed. Nothing was saved. Try again.
        </p>
      )}

      {status === 'success' && result && (
        <>
          <div className="mt-5 flex items-baseline gap-2">
            <span className="font-mono text-[52px] leading-none font-medium text-ink">
              {result.rawScore.toFixed(2)}
            </span>
            <span className="font-mono text-lg text-ink-faint">/ 1.00</span>
          </div>
          <p className="mt-2 font-mono text-xs text-ink-faint">detector score</p>

          <div className="mt-6">
            <ScoreGauge
              rawScore={result.rawScore}
              threshold={result.detector.thresholdApplied}
              verdict={result.verdict}
            />
          </div>

          <div className="mt-6">
            <MetaRow name="Model">{result.detector.modelVersion}</MetaRow>
            <MetaRow name="Strictness">
              {STRICTNESS_TEXT[result.detector.strictnessApplied]}
            </MetaRow>
            <MetaRow name="Checked">{fmtDateTime(result.createdAt)}</MetaRow>
            {showSavedLink && (
              <MetaRow name="Saved">
                <Link
                  to={`/history/${result.checkId}`}
                  className="text-navy-800 underline-offset-2 hover:underline"
                >
                  to history · view entry
                </Link>
              </MetaRow>
            )}
          </div>

          <div className="mt-5 border-t border-line pt-5">
            <SignalsList abstainReason={result.abstainReason} explanation={result.explanation} />
          </div>

          {/* the uncertain signal already says this, no need for two disclaimers on one screen */}
          {result.verdict !== 'uncertain' && (
            <p className="mt-6 text-xs text-ink-faint">Flags are prompts for review, not verdicts.</p>
          )}
        </>
      )}
    </section>
  )
}
