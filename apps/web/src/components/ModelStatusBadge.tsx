import { useDetectorCapabilities, useDetectorStatus } from "../hooks/useChecks";
import type { DetectorStatus } from "../types";

const UNKNOWN_LABEL = "demo detector · scores uncalibrated";

const DOT: Record<DetectorStatus, string> = {
  ready: "bg-status-ready",
  loading: "bg-status-warming",
  unavailable: "bg-status-down",
};

const STATUS_TEXT: Record<DetectorStatus, string> = {
  ready: "Detector ready",
  loading: "Detector starting up, checks will fail until it finishes",
  unavailable: "Detector unavailable, checks will fail",
};

export default function ModelStatusBadge() {
  const { data } = useDetectorCapabilities();
  const { data: reported, isError } = useDetectorStatus();

  const status: DetectorStatus = isError
    ? "unavailable"
    : (reported ?? "loading");
  const label = data ? `${data.modelVersion} · uncalibrated` : UNKNOWN_LABEL;

  return (
    <span
      title={STATUS_TEXT[status]}
      className="flex shrink-0 items-center gap-2 self-start rounded-full border border-border bg-surface px-3 py-1.5 font-mono text-xs whitespace-nowrap text-muted-foreground"
    >
      <span
        aria-hidden
        className={`h-[7px] w-[7px] rounded-full ${DOT[status]}`}
      />
      <span className="sr-only">{STATUS_TEXT[status]}. </span>
      {label}
    </span>
  );
}
