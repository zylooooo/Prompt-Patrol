import { useDetectorCapabilities } from "../hooks/useChecks";

const UNKNOWN_LABEL = "demo detector · scores uncalibrated";

export default function ModelStatusBadge() {
  const { data } = useDetectorCapabilities();
  const label = data ? `${data.modelVersion} · uncalibrated` : UNKNOWN_LABEL;

  return (
    <span className="flex shrink-0 items-center gap-2 self-start rounded-full border border-border bg-surface px-3 py-1.5 font-mono text-xs whitespace-nowrap text-muted-foreground">
      <span aria-hidden className="h-[7px] w-[7px] rounded-full bg-accent" />
      {label}
    </span>
  );
}
