import {
  STRICTNESS_HINT,
  STRICTNESS_TEXT,
  type Strictness,
} from "../api/types";
import SegmentedToggle, {
  type SegmentedToggleOption,
} from "./ui/SegmentedToggle";

const LEVELS: SegmentedToggleOption<Strictness>[] = (
  ["lenient", "standard", "strict"] as const
).map((level) => ({ value: level, label: STRICTNESS_TEXT[level] }));

interface StrictnessFieldProps {
  value: Strictness;
  onChange: (value: Strictness) => void;
}

export default function StrictnessField({
  value,
  onChange,
}: StrictnessFieldProps) {
  return (
    <fieldset>
      <legend className="text-[11px] font-semibold tracking-[0.09em] text-muted-foreground uppercase">
        Flagging strictness
      </legend>

      <div className="mt-3">
        <SegmentedToggle
          options={LEVELS}
          value={value}
          onChange={onChange}
          ariaLabel="Flagging strictness"
          size="lg"
          fullWidth
        />
      </div>

      <p className="mt-2.5 text-xs text-disabled-foreground">
        {STRICTNESS_HINT[value]}
      </p>
    </fieldset>
  );
}
