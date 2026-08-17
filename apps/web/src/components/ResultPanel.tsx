import ScoreGauge from "./ScoreGauge";
import type { ReactNode } from "react";
import VerdictChip from "./VerdictChip";
import SignalsList from "./SignalsList";
import { ApiError } from "../api/client";
import { TextLink } from "./ui/TextButton";
import { fmtDateTime } from "../lib/format";
import LoadingState from "./ui/LoadingState";
import { SECTION_LABEL } from "./ui/section-label";
import { STRICTNESS_TEXT, type SingleCheck } from "../types";

interface ResultPanelProps {
  status: "idle" | "pending" | "error" | "success";
  result?: SingleCheck;
  error?: unknown;
  showSavedLink?: boolean;
}

const GENERIC_FAILURE = "The check failed. Nothing was saved. Try again.";

const FAILURE_TEXT: Record<string, string> = {
  detector_timeout:
    "The detector took too long to answer. Nothing was saved — try again in a moment.",
  detector_unavailable:
    "The detector is temporarily unavailable. Nothing was saved — try again shortly.",
  payload_too_large:
    "That answer is too long to screen. Shorten it and check again.",
};

function failureText(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC_FAILURE;
  if (error.code && error.code in FAILURE_TEXT) {
    return FAILURE_TEXT[error.code];
  }

  if (error.status >= 400 && error.status < 500 && error.message) {
    return error.message;
  }
  return GENERIC_FAILURE;
}

function MetaRow({ name, children }: { name: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between border-t border-border py-3 first:border-t-0">
      <span className="text-[13px] text-muted-foreground">{name}</span>
      <span className="text-right font-mono text-xs text-foreground">
        {children}
      </span>
    </div>
  );
}

export default function ResultPanel({
  status,
  result,
  error,
  showSavedLink = true,
}: ResultPanelProps) {
  return (
    <section
      className="flex flex-col rounded-xl bg-surface p-7 shadow-md"
      aria-live="polite"
    >
      <div className="flex items-center justify-between gap-4">
        <p className={SECTION_LABEL}>Result</p>
        {status === "success" && result && (
          <VerdictChip verdict={result.verdict} />
        )}
      </div>

      {status === "idle" && (
        <p className="mt-6 text-sm text-disabled-foreground">
          Results appear here after you check an answer.
        </p>
      )}

      {status === "pending" && (
        <LoadingState size="inline" label="Checking answer…" className="mt-4" />
      )}

      {status === "error" && (
        <p
          className="mt-6 rounded-md bg-danger-soft px-3.5 py-2.5 text-[13px] text-danger"
          role="alert"
        >
          {failureText(error)}
        </p>
      )}

      {status === "success" && result && (
        <>
          <div className="mt-5 flex items-baseline gap-2">
            <span className="font-mono text-[52px] leading-none font-medium text-foreground">
              {result.rawScore.toFixed(2)}
            </span>
            <span className="font-mono text-lg text-disabled-foreground">
              / 1.00
            </span>
          </div>
          <p className="mt-2 font-mono text-xs text-disabled-foreground">
            detector score
          </p>

          <div className="mt-6">
            <ScoreGauge
              rawScore={result.rawScore}
              threshold={result.detector.thresholdApplied}
              verdict={result.verdict}
            />
          </div>

          <div className="mt-6">
            <MetaRow name="Model">{result.detector.modelVersion}</MetaRow>
            <MetaRow name="Strictness">
              {STRICTNESS_TEXT[result.detector.strictnessApplied]}
            </MetaRow>
            <MetaRow name="Checked">{fmtDateTime(result.createdAt)}</MetaRow>
            {showSavedLink && (
              <MetaRow name="Saved">
                <TextLink to={`/history/${result.checkId}`}>
                  to history · view entry
                </TextLink>
              </MetaRow>
            )}
          </div>

          <div className="mt-5 border-t border-border pt-5">
            <SignalsList
              abstainReason={result.abstainReason}
              explanation={result.explanation}
            />
          </div>

          {result.verdict !== "uncertain" && (
            <p className="mt-6 text-xs text-disabled-foreground">
              Flags are prompts for review, not verdicts.
            </p>
          )}
        </>
      )}
    </section>
  );
}
