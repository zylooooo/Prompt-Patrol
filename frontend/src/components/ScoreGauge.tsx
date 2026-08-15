import type { Verdict } from '../lib/types'

const SEGMENTS = 20

const FILL: Record<Verdict, string> = {
  ai_generated: 'bg-flag',
  uncertain: 'bg-unsure',
  human_written: 'bg-human',
}

interface ScoreGaugeProps {
  rawScore: number
  // null before the server reports one, in which case the tick is left off
  // rather than drawn at a made-up position
  threshold: number | null
  verdict: Verdict
}

// Segmented 0 to 1 gauge with a tick at the flag threshold, per the Figma
// result panel. Deliberately not a percentage: the score is not a probability
export default function ScoreGauge({ rawScore, threshold, verdict }: ScoreGaugeProps) {
  const filled = Math.round(rawScore * SEGMENTS)
  return (
    <div>
      <div className="relative flex h-[18px] items-center gap-[3px]">
        {Array.from({ length: SEGMENTS }, (_, i) => (
          <span
            key={i}
            aria-hidden
            className={`h-2.5 flex-1 rounded-[2px] ${i < filled ? FILL[verdict] : 'bg-navy-100'}`}
          />
        ))}
        {threshold !== null && (
          <span
            aria-hidden
            className="absolute top-0 h-full w-[2px] rounded-full bg-navy-800"
            style={{ left: `${threshold * 100}%` }}
          />
        )}
      </div>
      <div className="mt-1.5 flex items-center justify-between font-mono text-[11px] text-ink-faint">
        <span>0</span>
        {threshold !== null && <span>↑ flag threshold {threshold.toFixed(2)}</span>}
        <span>1</span>
      </div>
    </div>
  )
}
