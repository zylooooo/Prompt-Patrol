import type { DetectorInfo } from "../types";

export const UNCALIBRATED_NOTICE =
  "Demo detector · scores are uncalibrated and are not evidence of misconduct.";

export function isUncalibrated(detector: DetectorInfo): boolean {
  return detector.calibrationVersion === null;
}
