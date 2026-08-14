import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Check, ChevronDown } from "lucide-react";

export interface DropdownOption<T> {
  value: T;
  label: string;
  leading?: ReactNode;
  disabled?: boolean;
}

interface DropdownProps<T> {
  value: T | null;
  onChange: (next: T | null) => void;
  options: DropdownOption<T>[];
  placeholder: string;
  triggerLeading?: ReactNode;
  ariaLabel?: string;
  disabled?: boolean;
  disabledReason?: string;
  isLoading?: boolean;
  loadingLabel?: string;
  emptyLabel?: string;
  className?: string;
  popoverClassName?: string;
  measureTriggerLabels?: boolean;
}

const TRIGGER_BASE =
  "inline-flex h-9 items-center gap-2 rounded-lg border bg-surface px-3 text-sm font-medium transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30";

export default function Dropdown<T>({
  value,
  onChange,
  options,
  placeholder,
  triggerLeading,
  ariaLabel,
  disabled = false,
  disabledReason,
  isLoading = false,
  loadingLabel = "Loading…",
  emptyLabel,
  className,
  popoverClassName,
  measureTriggerLabels = true,
}: DropdownProps<T>) {
  const [isOpen, setIsOpen] = useState(false);
  const [dropUp, setDropUp] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  const isEmpty = !isLoading && options.length === 0;
  const isDisabled = disabled || isEmpty;
  const selected =
    value !== null
      ? (options.find((o) => Object.is(o.value, value)) ?? null)
      : null;

  useEffect(() => {
    if (!isOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (
        !rootRef.current?.contains(target) &&
        !popoverRef.current?.contains(target)
      )
        setIsOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  useLayoutEffect(() => {
    if (!isOpen) return;
    const trigger = triggerRef.current;
    const popover = popoverRef.current;
    if (!trigger || !popover) return;
    const rect = trigger.getBoundingClientRect();
    const margin = 8;
    const spaceBelow = window.innerHeight - rect.bottom - margin;
    setDropUp(
      popover.offsetHeight > spaceBelow &&
        rect.top > window.innerHeight - rect.bottom,
    );
  }, [isOpen]);

  const label = (() => {
    if (isLoading) return loadingLabel;
    if (isEmpty && emptyLabel) return emptyLabel;
    return selected ? selected.label : placeholder;
  })();

  const candidateLabels = useMemo(() => {
    const labels = new Set<string>([placeholder]);
    if (loadingLabel) labels.add(loadingLabel);
    if (emptyLabel) labels.add(emptyLabel);
    for (const o of options) labels.add(o.label);
    return Array.from(labels);
  }, [placeholder, loadingLabel, emptyLabel, options]);

  const triggerStateClass = isDisabled
    ? "cursor-not-allowed border-border text-disabled-foreground"
    : selected
      ? "border-accent-border text-accent hover:bg-accent-soft"
      : "border-border text-foreground hover:bg-surface-muted";

  const title = disabled
    ? (disabledReason ?? undefined)
    : isEmpty
      ? (emptyLabel ?? undefined)
      : undefined;

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        disabled={isDisabled || isLoading}
        onClick={() => setIsOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label={ariaLabel ?? placeholder}
        title={title}
        className={`${TRIGGER_BASE} ${triggerStateClass} ${className ?? ""}`.trim()}
      >
        {selected?.leading ??
          (triggerLeading ? (
            <span
              className={
                isDisabled ? "text-disabled-foreground" : "text-foreground"
              }
              aria-hidden="true"
            >
              {triggerLeading}
            </span>
          ) : null)}
        <span
          className={`grid min-w-0 ${
            isDisabled ? "text-disabled-foreground" : "text-foreground"
          }`}
        >
          {measureTriggerLabels &&
            candidateLabels.map((l) => (
              <span
                key={`measure-${l}`}
                aria-hidden="true"
                className="invisible col-start-1 row-start-1 whitespace-nowrap"
              >
                {l}
              </span>
            ))}
          <span className="col-start-1 row-start-1 truncate text-left">
            {label}
          </span>
        </span>
        {!isEmpty && (
          <ChevronDown
            className={`ml-auto h-4 w-4 shrink-0 text-disabled-foreground transition-transform duration-200 ${
              isOpen ? "rotate-180" : ""
            }`}
            aria-hidden="true"
          />
        )}
      </button>

      {isOpen && (
        <div
          ref={popoverRef}
          role="listbox"
          aria-label={ariaLabel ?? placeholder}
          className={`absolute left-0 z-20 max-w-[calc(100vw-2rem)] animate-fadeIn rounded-xl border border-border bg-surface p-2 shadow-lg ${
            dropUp
              ? "bottom-full mb-2 origin-bottom"
              : "top-full mt-2 origin-top"
          } ${popoverClassName ?? "w-60"}`}
        >
          <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto">
            {options.map((o) => {
              const isSelected = value !== null && Object.is(o.value, value);
              return (
                <Row
                  key={String(o.value)}
                  isSelected={isSelected}
                  disabled={o.disabled}
                  onClick={() => {
                    onChange(o.value);
                    setIsOpen(false);
                  }}
                >
                  {o.leading}
                  <span className="flex-1 truncate text-left">{o.label}</span>
                  {isSelected && (
                    <Check
                      className="h-3.5 w-3.5 text-accent"
                      aria-hidden="true"
                    />
                  )}
                </Row>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function Row({
  isSelected,
  onClick,
  disabled,
  children,
}: {
  isSelected: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <li>
      <button
        type="button"
        role="option"
        aria-selected={isSelected}
        disabled={disabled}
        onClick={onClick}
        className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-foreground transition-colors focus:outline-hidden focus-visible:bg-surface-muted disabled:cursor-not-allowed disabled:text-disabled-foreground disabled:hover:bg-transparent ${
          isSelected
            ? "bg-surface-muted hover:bg-surface-muted"
            : "hover:bg-surface-muted"
        }`}
      >
        {children}
      </button>
    </li>
  );
}
