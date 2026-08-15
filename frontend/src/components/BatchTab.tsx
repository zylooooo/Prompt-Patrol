import { useEffect, useRef, useState } from 'react'
import { MAX_ROWS, parseAnswersCsv } from '../lib/csv'
import { useRunBatch } from '../lib/hooks'
import { useToast } from '../lib/toastContext'
import type { BatchRowInput, Strictness } from '../lib/types'
import BatchResultsTable from './BatchResultsTable'
import StrictnessSlider from './StrictnessSlider'

interface LoadedFile {
  name: string
  rows: BatchRowInput[]
}

export default function BatchTab() {
  const [file, setFile] = useState<LoadedFile | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [dragging, setDragging] = useState(false)
  const [strictness, setStrictness] = useState<Strictness>('standard')
  const inputRef = useRef<HTMLInputElement>(null)
  const resultsRef = useRef<HTMLDivElement>(null)
  const { showToast } = useToast()
  const batch = useRunBatch((done, total) => setProgress({ done, total }))

  useEffect(() => {
    if (batch.isSuccess) {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [batch.isSuccess])

  async function loadFile(f: File) {
    // a run in flight owns the progress state. Swapping the file mid-run would
    // blank the bar and re-enable Run, letting two runs proceed at once
    if (batch.isPending) return
    batch.reset()
    setProgress(null)
    try {
      const text = await f.text()
      const { rows, errors } = parseAnswersCsv(text)
      setErrors(errors)
      setFile(rows.length > 0 ? { name: f.name, rows } : null)
    } catch {
      setErrors(['That file could not be read. Try exporting it again as UTF-8 CSV.'])
      setFile(null)
    }
  }

  function onRun() {
    if (!file || batch.isPending) return
    setProgress({ done: 0, total: file.rows.length })
    batch.mutate(
      { fileName: file.name, rows: file.rows, strictness },
      { onSuccess: () => showToast('Batch complete. Saved to history.') },
    )
  }

  function onReset() {
    setFile(null)
    setErrors([])
    setProgress(null)
    batch.reset()
    if (inputRef.current) inputRef.current.value = ''
  }

  const shownErrors = errors.slice(0, 6)

  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-xl border border-line bg-surface p-7">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            const f = e.dataTransfer.files[0]
            if (f) void loadFile(f)
          }}
          className={`flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed px-6 py-9 text-center transition-colors ${
            dragging ? 'border-gold-500 bg-gold-100/40' : 'border-line bg-field'
          }`}
        >
          <p className="text-sm text-ink">
            Drop a CSV here, or{' '}
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="font-medium text-navy-800 underline-offset-2 hover:underline"
            >
              browse
            </button>
          </p>
          <p className="font-mono text-xs text-ink-faint">
            external_ref, answer_text, question_text (optional) · up to {MAX_ROWS} rows · UTF-8
          </p>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void loadFile(f)
            }}
          />
        </div>

        {shownErrors.length > 0 && (
          <div className="mt-4 rounded-md bg-flag-bg px-4 py-3" role="alert">
            {shownErrors.map((err) => (
              <p key={err} className="text-[13px] leading-relaxed text-flag">
                {err}
              </p>
            ))}
            {errors.length > shownErrors.length && (
              <p className="text-[13px] text-flag">…and {errors.length - shownErrors.length} more.</p>
            )}
          </div>
        )}

        {file && (
          <div className="mt-5 max-w-sm">
            <StrictnessSlider value={strictness} onChange={setStrictness} />
          </div>
        )}

        {file && (
          <div className="mt-4 flex items-center justify-between gap-4">
            <div className="flex items-baseline gap-2 rounded-md border border-line bg-field px-3 py-2">
              <span className="text-sm font-medium text-ink">{file.name}</span>
              <span className="text-[13px] text-ink-faint">· {file.rows.length} rows · parsed</span>
              <button
                onClick={onReset}
                className="ml-2 text-[13px] text-ink-muted underline-offset-2 hover:underline"
              >
                Remove
              </button>
            </div>
            <button
              onClick={onRun}
              disabled={batch.isPending}
              className="h-11 shrink-0 rounded-lg bg-navy-800 px-5 text-sm font-semibold text-white transition-colors hover:bg-navy-700 disabled:opacity-50"
            >
              {batch.isPending && progress
                ? `Checking ${progress.done} of ${progress.total}…`
                : `Run ${file.rows.length} checks`}
            </button>
          </div>
        )}

        {batch.isPending && progress && (
          <div
            className="mt-4"
            role="progressbar"
            aria-label="Batch progress"
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.done}
          >
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-navy-100">
              <div
                className="h-full rounded-full bg-navy-800 transition-all"
                style={{ width: `${(progress.done / progress.total) * 100}%` }}
              />
            </div>
          </div>
        )}

        <p role="status" className="sr-only">
          {batch.isPending && progress
            ? `Checked ${Math.floor((progress.done / progress.total) * 10) * 10} percent`
            : batch.isSuccess && batch.data
              ? `Batch complete. ${batch.data.counts.ai_generated} flagged, ${batch.data.counts.uncertain} uncertain, ${batch.data.counts.human_written} likely human.`
              : ''}
        </p>

        {batch.isError && (
          <p className="mt-4 rounded-md bg-flag-bg px-4 py-3 text-[13px] text-flag" role="alert">
            The batch run failed. Nothing was saved. Try again.
          </p>
        )}
      </section>

      {batch.isSuccess && batch.data && (
        <div ref={resultsRef}>
          <BatchResultsTable run={batch.data} />
        </div>
      )}
    </div>
  )
}
