import { ChevronDown, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

export interface Choice {
  value: string;
  label: string;
}

interface TokenMultiSelectProps {
  choices: Choice[];
  selected: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  width?: string;
}

export default function TokenMultiSelect({
  choices,
  selected,
  onChange,
  placeholder,
  width = "w-64",
}: TokenMultiSelectProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const popoverId = useId();

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (root.current && !root.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const labelFor = (value: string) =>
    choices.find((choice) => choice.value === value)?.label ?? value;

  const toggle = (value: string) =>
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value],
    );

  return (
    <div ref={root} className={`relative ${width}`}>
      <div
        className={`flex min-h-11 w-full items-center gap-1.5 rounded-md border bg-surface px-2 py-1.5 ${
          open ? "border-input-border-focus" : "border-input-border"
        }`}
      >
        <span className="flex flex-wrap items-center gap-1.5">
          {selected.map((value) => (
            <span
              key={value}
              className="flex items-center gap-1 rounded border border-border bg-surface-muted py-1 pr-1 pl-2 text-xs font-medium text-primary"
            >
              {labelFor(value)}
              <button
                type="button"
                aria-label={`Remove ${labelFor(value)}`}
                onClick={() => onChange(selected.filter((v) => v !== value))}
                className="rounded-sm p-0.5 text-muted-foreground transition-colors hover:text-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30"
              >
                <X aria-hidden className="h-3 w-3" />
              </button>
            </span>
          ))}
        </span>

        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={popoverId}
          className="flex flex-1 items-center justify-between gap-2 self-stretch rounded-sm px-1 text-left focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30"
        >
          {selected.length === 0 && (
            <span className="text-sm text-input-placeholder">
              {placeholder}
            </span>
          )}
          <ChevronDown
            aria-hidden
            className={`ml-auto h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>
      </div>

      {open && (
        <div
          id={popoverId}
          role="group"
          aria-label={placeholder}
          className="absolute z-20 mt-1.5 w-full rounded-lg border border-border bg-surface py-1.5 shadow-lg"
        >
          {choices.length === 0 && (
            <p className="px-3 py-2 text-sm text-disabled-foreground">
              Nobody available.
            </p>
          )}
          {choices.map((choice) => (
            <label
              key={choice.value}
              className={`flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm focus-within:ring-2 focus-within:ring-focus-ring/30 ${
                selected.includes(choice.value)
                  ? "bg-surface-muted font-medium text-foreground"
                  : "text-foreground"
              }`}
            >
              <input
                type="checkbox"
                checked={selected.includes(choice.value)}
                onChange={() => toggle(choice.value)}
                className="h-3.5 w-3.5 accent-primary"
              />
              {choice.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
