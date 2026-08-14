import {
  STRICTNESS_HINT,
  STRICTNESS_TEXT,
  type Strictness,
} from "../api/types";

const LEVELS: Strictness[] = ["lenient", "standard", "strict"];

interface StrictnessSliderProps {
  value: Strictness;
  onChange: (value: Strictness) => void;
}

export default function StrictnessSlider({
  value,
  onChange,
}: StrictnessSliderProps) {
  return (
    <fieldset>
      <legend className="text-[11px] font-semibold tracking-[0.09em] text-muted-foreground uppercase">
        Flagging strictness
      </legend>

      <div className="mt-3 flex rounded-lg border border-border bg-input-bg p-1">
        {LEVELS.map((level) => (
          <label
            key={level}
            className={`flex-1 cursor-pointer rounded-md px-3 py-2 text-center text-[13px] transition-colors focus-within:ring-2 focus-within:ring-focus-ring/30 ${
              value === level
                ? "bg-primary font-semibold text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <input
              type="radio"
              name="strictness"
              value={level}
              checked={value === level}
              onChange={() => onChange(level)}
              className="sr-only"
            />
            {STRICTNESS_TEXT[level]}
          </label>
        ))}
      </div>

      <p className="mt-2.5 text-xs text-disabled-foreground">
        {STRICTNESS_HINT[value]}
      </p>
    </fieldset>
  );
}
