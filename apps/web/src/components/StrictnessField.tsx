import SegmentedToggle from "./ui/SegmentedToggle";
import { SECTION_LABEL } from "./ui/section-label";
import { useStrictnessLevels } from "../hooks/useChecks";
import { STRICTNESS_HINT, STRICTNESS_TEXT, type Strictness } from "../types";

interface StrictnessFieldProps {
  value: Strictness;
  onChange: (value: Strictness) => void;
}

export default function StrictnessField({
  value,
  onChange,
}: StrictnessFieldProps) {
  const levels = useStrictnessLevels();
  if (levels.length === 0) return null;

  return (
    <fieldset>
      <legend className={SECTION_LABEL}>Flagging strictness</legend>

      <div className="mt-3">
        <SegmentedToggle
          options={levels.map((level) => ({
            value: level,
            label: STRICTNESS_TEXT[level],
          }))}
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
