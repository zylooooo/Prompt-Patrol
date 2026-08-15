import { STRICTNESS_HINT, STRICTNESS_TEXT, type Strictness } from '../lib/types'

const LEVELS: Strictness[] = ['lenient', 'standard', 'strict']

interface StrictnessSliderProps {
  value: Strictness
  onChange: (value: Strictness) => void
}

// Three named levels, never a number. The server maps the level to a
// threshold calibrated for whichever model is serving, so a raw number from
// here would change meaning on every model swap. Radios instead of buttons so
// arrow keys work and screen readers see one group with three choices
export default function StrictnessSlider({ value, onChange }: StrictnessSliderProps) {
  return (
    <fieldset>
      <legend className="text-[11px] font-semibold tracking-[0.09em] text-ink-muted uppercase">
        Flagging strictness
      </legend>

      <div className="mt-3 flex rounded-lg border border-line bg-field p-1">
        {LEVELS.map((level) => (
          <label
            key={level}
            className={`flex-1 cursor-pointer rounded-md px-3 py-2 text-center text-[13px] transition-colors ${
              value === level ? 'bg-navy-800 font-semibold text-white' : 'text-ink-muted hover:text-ink'
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

      <p className="mt-2.5 text-xs text-ink-faint">{STRICTNESS_HINT[value]}</p>
    </fieldset>
  )
}
