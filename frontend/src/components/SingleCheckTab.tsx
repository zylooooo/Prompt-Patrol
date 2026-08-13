import { useState } from 'react'
import { useCheckAnswer } from '../lib/hooks'
import { wordCount } from '../lib/format'
import { useToast } from '../lib/toastContext'
import { ANSWER_MIN_CHARS, type Strictness } from '../lib/types'
import ResultPanel from './ResultPanel'
import StrictnessSlider from './StrictnessSlider'

export default function SingleCheckTab() {
  const [answer, setAnswer] = useState('')
  const [context, setContext] = useState('')
  const [strictness, setStrictness] = useState<Strictness>('standard')
  const check = useCheckAnswer()
  const { showToast } = useToast()

  const words = wordCount(answer)
  // same floor the server enforces, so the button is disabled instead of the
  // request coming back as a 400
  const tooShort = answer.trim().length < ANSWER_MIN_CHARS

  function onSubmit() {
    if (tooShort || check.isPending) return
    check.mutate(
      {
        answerText: answer.trim(),
        questionText: context.trim() || undefined,
        strictness,
      },
      { onSuccess: () => showToast('Saved to history') },
    )
  }

  function onClear() {
    setAnswer('')
    setContext('')
    check.reset()
  }

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          onSubmit()
        }}
        className="rounded-xl border border-line bg-surface p-7"
      >
        <div className="flex items-center justify-between">
          <label
            htmlFor="answer"
            className="text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase"
          >
            Student answer
          </label>
          <span className="font-mono text-xs text-ink-faint">{words} words</span>
        </div>
        <textarea
          id="answer"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault()
              onSubmit()
            }
          }}
          rows={7}
          placeholder="Paste the student answer to screen."
          className="mt-3 w-full resize-y rounded-md border border-line bg-field px-4 py-3 text-sm leading-relaxed text-ink placeholder:text-ink-faint"
        />

        <div className="mt-5">
          <label
            htmlFor="context"
            className="text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase"
          >
            Question context
          </label>
          <input
            id="context"
            value={context}
            onChange={(e) => setContext(e.target.value)}
            placeholder="Paste the question (optional)"
            className="mt-3 h-11 w-full rounded-md border border-line bg-field px-3.5 text-sm text-ink placeholder:text-ink-faint"
          />
        </div>

        <div className="mt-6">
          <StrictnessSlider value={strictness} onChange={setStrictness} />
        </div>

        <div className="mt-7 flex items-center gap-3">
          <button
            type="submit"
            disabled={tooShort || check.isPending}
            className="h-11 rounded-lg bg-navy-800 px-6 text-sm font-semibold text-white transition-colors hover:bg-navy-700 disabled:opacity-50"
          >
            {check.isPending ? 'Checking…' : 'Check answer'}
          </button>
          <button
            type="button"
            onClick={onClear}
            className="h-11 rounded-lg border border-line px-5 text-sm text-ink-muted transition-colors hover:text-ink"
          >
            Clear
          </button>
        </div>
      </form>

      <ResultPanel status={check.status} result={check.data} />
    </div>
  )
}
