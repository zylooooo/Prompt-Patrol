import { useDetectorCapabilities, useDetectorStatus } from "../hooks/useChecks";
import type { DetectorStatus } from "../types";

// Before the first status answer: nothing is known yet, so claim nothing.
const CHECKING_LABEL = "checking detector";
// Ready, but the model name is still being fetched (or the API has not heard it yet).
const READY_LABEL = "detector ready";

const DOT: Record<DetectorStatus, string> = {
  ready: "bg-status-ready",
  loading: "bg-status-warming",
  unavailable: "bg-status-down",
};

const STATUS_TEXT: Record<DetectorStatus, string> = {
  ready: "Detector ready",
  loading: "Detector is starting up. Checks will work once it's ready.",
  unavailable: "Detector is unavailable. Checks won't go through until it's back.",
};

const SHORT_TEXT: Record<Exclude<DetectorStatus, "ready">, string> = {
  loading: "detector starting up",
  unavailable: "detector unavailable",
};

export default function ModelStatusBadge() {
  const caps = useDetectorCapabilities();
  const { data: reported, isError } = useDetectorStatus();

  const status: DetectorStatus = isError
    ? "unavailable"
    : (reported ?? "loading");
  // Anything but ready is spelled out, not left to the dot's colour alone. The model is named only once the
  // detector is ready and capabilities fetched after that name it, so a loading detector never shows a stale model.
  const known = isError || reported !== undefined;
  const label = !known
    ? CHECKING_LABEL
    : status !== "ready"
      ? SHORT_TEXT[status]
      : caps.isFetching || !caps.data?.modelVersion
        ? READY_LABEL
        : `${caps.data.modelVersion} · ${caps.data.calibrationVersion ?? "uncalibrated"}`;

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
