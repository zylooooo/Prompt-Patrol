import type { Verdict } from '../lib/types'
import { VERDICT_TEXT } from '../lib/types'

const STYLES: Record<Verdict, { chip: string; dot: string }> = {
  ai_generated: { chip: 'bg-flag-bg text-flag', dot: 'bg-flag' },
  uncertain: { chip: 'bg-unsure-bg text-unsure', dot: 'bg-unsure' },
  human_written: { chip: 'bg-human-bg text-human', dot: 'bg-human' },
}

export default function VerdictChip({ verdict }: { verdict: Verdict }) {
  const style = STYLES[verdict]
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-[13px] font-medium whitespace-nowrap ${style.chip}`}
    >
      <span aria-hidden className={`h-[7px] w-[7px] rounded-full ${style.dot}`} />
      {VERDICT_TEXT[verdict]}
    </span>
  )
}
