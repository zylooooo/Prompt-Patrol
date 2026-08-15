import type { Verdict } from "../types";

const SEGMENTS = 20;

const FILL: Record<Verdict, string> = {
  ai_generated: "bg-flag",
  uncertain: "bg-unsure",
  human_written: "bg-human",
};

interface ScoreGaugeProps {
  rawScore: number;
  threshold: number | null;
  verdict: Verdict;
}

export default function ScoreGauge({
  rawScore,
  threshold,
  verdict,
}: ScoreGaugeProps) {
  const filled = Math.round(rawScore * SEGMENTS);
  return (
    <div>
      <div className="relative flex h-[18px] items-center gap-[3px]">
        {Array.from({ length: SEGMENTS }, (_, i) => (
          <span
            key={i}
            aria-hidden
            className={`h-2.5 flex-1 rounded-[2px] ${i < filled ? FILL[verdict] : "bg-primary-soft"}`}
          />
        ))}
        {threshold !== null && (
          <span
            aria-hidden
            className="absolute top-0 h-full w-[2px] rounded-full bg-primary"
            style={{ left: `${threshold * 100}%` }}
          />
        )}
      </div>
      <div className="mt-1.5 flex items-center justify-between font-mono text-[11px] text-disabled-foreground">
        <span>0</span>
        {threshold !== null && (
          <span>↑ flag threshold {threshold.toFixed(2)}</span>
        )}
        <span>1</span>
      </div>
    </div>
  );
}
