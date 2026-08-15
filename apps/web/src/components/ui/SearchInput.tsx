import { Search, X } from "lucide-react";
import type { CSSProperties, ChangeEvent, KeyboardEvent, Ref } from "react";

export type SearchInputSize = "md" | "sm";

interface SearchInputProps {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  ariaLabel?: string;
  maxLength?: number;
  size?: SearchInputSize;
  inputRef?: Ref<HTMLInputElement>;
  wrapperClassName?: string;
  wrapperStyle?: CSSProperties;
  hideClear?: boolean;
  onKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
  combobox?: {
    controls: string;
    activeOptionId?: string;
  };
}

export default function SearchInput({
  value,
  onChange,
  placeholder,
  ariaLabel,
  maxLength = 120,
  size = "md",
  inputRef,
  wrapperClassName,
  wrapperStyle,
  hideClear = false,
  onKeyDown,
  combobox,
}: SearchInputProps) {
  const filled = value.length > 0;
  const iconClass =
    size === "sm"
      ? "pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-disabled-foreground"
      : "pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-disabled-foreground";

  const inputClass =
    size === "sm"
      ? `w-full rounded-md border border-border py-1.5 pl-7 ${
          hideClear || !filled ? "pr-2" : "pr-7"
        } text-sm font-medium text-foreground outline-hidden transition-colors placeholder:font-normal placeholder:text-disabled-foreground focus-visible:bg-accent-soft ${
          filled ? "bg-modal-muted" : "bg-surface hover:bg-modal-muted"
        }`
      : `h-9 w-full rounded-lg border border-border pl-9 ${
          hideClear || !filled ? "pr-3" : "pr-9"
        } text-sm font-medium text-foreground outline-hidden transition-colors placeholder:font-normal placeholder:text-disabled-foreground focus-visible:bg-accent-soft ${
          filled ? "bg-modal-muted" : "bg-surface hover:bg-modal-muted"
        }`;

  const clearClass =
    size === "sm"
      ? "absolute right-1.5 top-1/2 -translate-y-1/2 inline-flex h-5 w-5 items-center justify-center rounded-md text-disabled-foreground transition-colors hover:bg-modal-muted hover:text-foreground"
      : "absolute right-2 top-1/2 -translate-y-1/2 inline-flex h-6 w-6 items-center justify-center rounded-md text-disabled-foreground transition-colors hover:bg-modal-muted hover:text-foreground";

  return (
    <label
      className={`relative min-w-0 ${wrapperClassName ?? "flex-1 sm:w-72 sm:flex-initial"}`}
      style={wrapperStyle}
    >
      <span className="sr-only">{ariaLabel ?? placeholder}</span>
      <Search className={iconClass} aria-hidden="true" />
      <input
        ref={inputRef}
        type="search"
        value={value}
        onChange={(e: ChangeEvent<HTMLInputElement>) =>
          onChange(e.target.value)
        }
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        maxLength={maxLength}
        className={inputClass}
        {...(combobox && {
          role: "combobox" as const,
          "aria-expanded": true,
          "aria-controls": combobox.controls,
          "aria-autocomplete": "list" as const,
          "aria-activedescendant": combobox.activeOptionId,
        })}
      />
      {filled && !hideClear && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Clear search"
          className={clearClass}
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      )}
    </label>
  );
}
