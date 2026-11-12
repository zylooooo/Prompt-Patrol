import type { DetectorInfo } from "../types";

export const UNCALIBRATED_NOTICE =
  "Demo detector. Scores aren't calibrated and aren't evidence of misconduct.";

export function isUncalibrated(detector: DetectorInfo): boolean {
  return detector.calibrationVersion === null;
}
