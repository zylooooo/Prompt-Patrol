import Button from "./ui/Button";
import { useState } from "react";
import ResultPanel from "./ResultPanel";
import { wordCount } from "../lib/format";
import { useToast } from "../hooks/useToast";
import StrictnessSlider from "./StrictnessSlider";
import { useCheckAnswer } from "../hooks/useChecks";
import { ANSWER_MIN_CHARS, type Strictness } from "../api/types";

const FIELD_CLASS =
  "w-full rounded-md border border-input-border bg-input-bg text-sm text-foreground placeholder:text-input-placeholder transition focus:outline-hidden focus:ring-2 focus:ring-focus-ring/30";

const LABEL_CLASS =
  "text-[11px] font-semibold tracking-[0.09em] text-muted-foreground uppercase";

export default function SingleCheckTab() {
  const [answer, setAnswer] = useState("");
  const [context, setContext] = useState("");
  const [strictness, setStrictness] = useState<Strictness>("standard");
  const check = useCheckAnswer();
  const { showToast } = useToast();

  const words = wordCount(answer);
  const tooShort = answer.trim().length < ANSWER_MIN_CHARS;

  function onSubmit() {
    if (tooShort || check.isPending) return;
    check.mutate(
      {
        answerText: answer.trim(),
        questionText: context.trim() || undefined,
        strictness,
      },
      { onSuccess: () => showToast("Saved to history") },
    );
  }

  function onClear() {
    setAnswer("");
    setContext("");
    check.reset();
  }

  return (
    <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
        className="rounded-xl border border-border bg-surface p-7"
      >
        <div className="flex items-center justify-between">
          <label htmlFor="answer" className={LABEL_CLASS}>
            Student answer
          </label>
          <span className="font-mono text-xs text-disabled-foreground">
            {words} words
          </span>
        </div>
        <textarea
          id="answer"
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={7}
          placeholder="Paste the student answer to screen."
          className={`mt-3 resize-y px-4 py-3 leading-relaxed ${FIELD_CLASS}`}
        />

        <div className="mt-5">
          <label htmlFor="context" className={LABEL_CLASS}>
            Question context
          </label>
          <input
            id="context"
            value={context}
            onChange={(e) => setContext(e.target.value)}
            placeholder="Paste the question (optional)"
            className={`mt-3 h-11 px-3.5 ${FIELD_CLASS}`}
          />
        </div>

        <div className="mt-6">
          <StrictnessSlider value={strictness} onChange={setStrictness} />
        </div>

        <div className="mt-7 flex items-center gap-3">
          <Button
            type="submit"
            size="lg"
            disabled={tooShort || check.isPending}
          >
            {check.isPending ? "Checking…" : "Check answer"}
          </Button>
          <Button variant="secondary" size="lg" onClick={onClear}>
            Clear
          </Button>
        </div>
      </form>

      <ResultPanel status={check.status} result={check.data} />
    </div>
  );
}
