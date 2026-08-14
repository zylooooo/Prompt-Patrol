import {
  ABSTAIN_TEXT,
  CUE_TEXT,
  type AbstainReason,
  type Explanation,
} from "../api/types";

interface SignalsListProps {
  abstainReason: AbstainReason;
  explanation: Explanation | null;
}

export default function SignalsList({
  abstainReason,
  explanation,
}: SignalsListProps) {
  const lines = [
    ...(abstainReason ? [ABSTAIN_TEXT[abstainReason]] : []),
    ...(explanation?.cues ?? []).map((cue) => CUE_TEXT[cue]),
  ];
  if (lines.length === 0) return null;

  return (
    <div>
      <p className="text-[11px] font-semibold tracking-[0.09em] text-muted-foreground uppercase">
        Signals
      </p>
      <ul className="mt-2.5 flex flex-col gap-2">
        {lines.map((line) => (
          <li
            key={line}
            className="flex items-start gap-2.5 text-[13px] leading-snug text-foreground"
          >
            <span
              aria-hidden
              className="mt-[7px] h-[5px] w-[5px] shrink-0 rounded-full bg-accent"
            />
            {line}
          </li>
        ))}
      </ul>
    </div>
  );
}
