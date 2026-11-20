import { useDetectorCapabilities, useDetectorStatus } from "../hooks/useChecks";
import type { DetectorStatus, Strictness } from "../types";

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

// The threshold a check is judged against, rounded the way the result gauge
// shows it. The full calibration version stays in the hover text.
function describeThreshold(
  calibrationVersion: string | null,
  threshold: number | undefined,
): string {
  if (calibrationVersion === null) return "uncalibrated";
  return threshold === undefined
    ? "calibrated"
    : `flags above ${threshold.toFixed(2)}`;
}

const SHORT_TEXT: Record<Exclude<DetectorStatus, "ready">, string> = {
  loading: "detector starting up",
  unavailable: "detector unavailable",
};

interface ModelStatusBadgeProps {
  // The level picked on the page, so the threshold shown is the one a check
  // will use. Pages without a picker show the default level's.
  strictness?: Strictness;
}

export default function ModelStatusBadge({
  strictness = "standard",
}: ModelStatusBadgeProps) {
  const caps = useDetectorCapabilities();
  const { data: reported, isError } = useDetectorStatus();

  const status: DetectorStatus = isError
    ? "unavailable"
    : (reported ?? "loading");
  // Anything but ready is spelled out, not left to the dot's colour alone. The model is named only once the
  // detector is ready and capabilities fetched after that name it, so a loading detector never shows a stale model.
  const known = isError || reported !== undefined;
  const named =
    status === "ready" && !caps.isFetching && caps.data?.modelVersion
      ? caps.data
      : null;
  const label = !known
    ? CHECKING_LABEL
    : status !== "ready"
      ? SHORT_TEXT[status]
      : !named
        ? READY_LABEL
        : `${named.modelVersion} · ${describeThreshold(
            named.calibrationVersion,
            // A level the server doesn't offer (flag off) is checked at standard
            named.thresholds[strictness] ?? named.thresholds.standard,
          )}`;
  const title = named?.calibrationVersion
    ? `${STATUS_TEXT[status]}. Calibration ${named.calibrationVersion}`
    : STATUS_TEXT[status];

  return (
    <span
      title={title}
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
