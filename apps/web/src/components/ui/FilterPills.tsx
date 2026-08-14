export interface FilterPillOption<T extends string> {
  id: T;
  label: string;
}

interface FilterPillsProps<T extends string> {
  options: readonly FilterPillOption<T>[];
  value: T;
  onChange: (next: T) => void;
  ariaLabel: string;
  className?: string;
}

const PILL_BASE =
  "h-9 rounded-md border px-3.5 text-sm transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30";

const PILL_ACTIVE = "border-primary bg-primary text-primary-foreground";

const PILL_IDLE =
  "border-border bg-surface text-muted-foreground hover:text-foreground";

export default function FilterPills<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className,
}: FilterPillsProps<T>) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={`flex flex-wrap items-center gap-2 ${className ?? ""}`.trim()}
    >
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => onChange(option.id)}
          aria-pressed={value === option.id}
          className={`${PILL_BASE} ${
            value === option.id ? PILL_ACTIVE : PILL_IDLE
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
