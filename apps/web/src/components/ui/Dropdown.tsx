import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import SearchInput from "./SearchInput";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronDown, Filter, Plus } from "lucide-react";
import { usePopoverPlacement } from "../../hooks/usePopoverPlacement";

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
  size?: DropdownSize;
  resetLabel?: string;
  triggerLeading?: ReactNode;
  ariaLabel?: string;
  disabled?: boolean;
  disabledReason?: string;
  isLoading?: boolean;
  loadingLabel?: string;
  emptyLabel?: string;
  footer?: ReactNode;
  className?: string;
  triggerClassName?: string;
  popoverClassName?: string;
  portal?: boolean;
  topAction?: {
    label: string;
    leading?: ReactNode;
    onClick: () => void;
    disabled?: boolean;
  };
  renderOptionTrailing?: (
    option: DropdownOption<T>,
    isSelected: boolean,
    close: () => void,
  ) => ReactNode;
  groups?: { label: string; options: DropdownOption<T>[] }[];
  multiValues?: T[];
  onToggleValue?: (value: T) => void;
  searchPlaceholder?: string;
  noResultsLabel?: string;
  createOption?: {
    onCreate: (name: string) => void;
    label?: (name: string) => string;
    disabled?: boolean;
  };
  measureTriggerLabels?: boolean;
}

const TRIGGER_BASE =
  "inline-flex items-center gap-2 rounded-lg border bg-surface px-3 text-sm font-medium transition-colors focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30";

const TRIGGER_SIZE = {
  md: "h-9",
  lg: "h-11",
} as const satisfies Record<string, string>;

export type DropdownSize = keyof typeof TRIGGER_SIZE;

const TYPEAHEAD_RESET_MS = 700;

export default function Dropdown<T>({
  value,
  onChange,
  options,
  placeholder,
  size = "md",
  resetLabel,
  triggerLeading,
  ariaLabel,
  disabled = false,
  disabledReason,
  isLoading = false,
  loadingLabel = "Loading…",
  emptyLabel,
  footer,
  className,
  triggerClassName,
  popoverClassName,
  portal = false,
  topAction,
  renderOptionTrailing,
  groups,
  multiValues,
  onToggleValue,
  searchPlaceholder,
  noResultsLabel = "No matches.",
  createOption,
  measureTriggerLabels = true,
}: DropdownProps<T>) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const { dropUp, maxHeight: inlineMaxHeight } = usePopoverPlacement(
    isOpen,
    triggerRef,
    popoverRef,
    { enabled: !portal },
  );
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const [coords, setCoords] = useState<{
    top: number;
    left: number;
    width: number;
  } | null>(null);

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
      if (e.key !== "Escape") return;
      setIsOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    const onScroll = (e: Event) => {
      if (popoverRef.current?.contains(e.target as Node)) return;
      setIsOpen(false);
    };
    const onResize = () => setIsOpen(false);
    if (portal) {
      window.addEventListener("scroll", onScroll, true);
      window.addEventListener("resize", onResize);
    }
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      if (portal) {
        window.removeEventListener("scroll", onScroll, true);
        window.removeEventListener("resize", onResize);
      }
    };
  }, [isOpen, portal]);

  const optionElements = useCallback(
    () =>
      Array.from(
        popoverRef.current?.querySelectorAll<HTMLButtonElement>(
          '[role="option"]:not([disabled])',
        ) ?? [],
      ),
    [],
  );

  const focusOptionAt = useCallback(
    (index: number) => {
      const options = optionElements();
      if (options.length === 0) return;
      options[
        ((index % options.length) + options.length) % options.length
      ]?.focus();
    },
    [optionElements],
  );

  const moveFocus = useCallback(
    (delta: number) => {
      const options = optionElements();
      if (options.length === 0) return;
      const current = options.indexOf(
        document.activeElement as HTMLButtonElement,
      );
      focusOptionAt(
        current === -1 ? (delta > 0 ? 0 : options.length - 1) : current + delta,
      );
    },
    [optionElements, focusOptionAt],
  );

  const focusOnOpenRef = useRef<"first" | "last" | null>(null);
  const typeahead = useRef({ buffer: "", at: 0 });

  useLayoutEffect(() => {
    if (!isOpen) {
      focusOnOpenRef.current = null;
      return;
    }
    if (searchPlaceholder) {
      searchInputRef.current?.focus();
      return;
    }
    const pending = focusOnOpenRef.current;
    focusOnOpenRef.current = null;
    if (pending) focusOptionAt(pending === "last" ? -1 : 0);
  }, [isOpen, searchPlaceholder, focusOptionAt]);

  const onTriggerKeyDown = (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    if (isOpen) {
      moveFocus(e.key === "ArrowDown" ? 1 : -1);
      return;
    }
    focusOnOpenRef.current = e.key === "ArrowDown" ? "first" : "last";
    setQuery("");
    setIsOpen(true);
  };

  const onPopoverKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      moveFocus(e.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      focusOptionAt(e.key === "Home" ? 0 : -1);
      return;
    }

    if (
      searchPlaceholder ||
      e.key.length !== 1 ||
      e.altKey ||
      e.ctrlKey ||
      e.metaKey
    )
      return;
    const now = Date.now();
    const state = typeahead.current;
    state.buffer =
      now - state.at > TYPEAHEAD_RESET_MS
        ? e.key.toLowerCase()
        : state.buffer + e.key.toLowerCase();
    state.at = now;
    const match = optionElements().find((el) =>
      (el.textContent ?? "").trim().toLowerCase().startsWith(state.buffer),
    );
    if (match) {
      e.preventDefault();
      match.focus();
    }
  };

  useLayoutEffect(() => {
    if (!portal || !isOpen) return;
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const margin = 8;
    const popover = popoverRef.current;
    const popoverH = popover?.offsetHeight ?? 0;
    const popoverW = Math.max(popover?.offsetWidth ?? 0, rect.width);
    const below = rect.bottom + margin;
    const fitsBelow = below + popoverH <= window.innerHeight - margin;
    let top = fitsBelow ? below : rect.top - margin - popoverH;
    top = Math.min(
      Math.max(top, margin),
      Math.max(margin, window.innerHeight - margin - popoverH),
    );
    let left = rect.left;
    if (left + popoverW > window.innerWidth - margin) {
      left = rect.right - popoverW;
    }
    left = Math.min(
      Math.max(left, margin),
      Math.max(margin, window.innerWidth - margin - popoverW),
    );
    setCoords({ top, left, width: rect.width });
  }, [portal, isOpen]);

  const flatOptions = useMemo(
    () => (groups ? groups.flatMap((g) => g.options) : options),
    [groups, options],
  );
  const isEmpty = !isLoading && flatOptions.length === 0;
  const isDisabled = disabled || (isEmpty && !topAction && !createOption);
  const isMulti = multiValues !== undefined;
  const selected =
    !isMulti && value !== null
      ? (flatOptions.find((o) => Object.is(o.value, value)) ?? null)
      : null;
  const multiSelected = isMulti
    ? flatOptions.filter((o) =>
        (multiValues ?? []).some((v) => Object.is(o.value, v)),
      )
    : [];
  const isOptionSelected = (o: DropdownOption<T>): boolean =>
    isMulti
      ? (multiValues ?? []).some((v) => Object.is(o.value, v))
      : value !== null && Object.is(o.value, value);

  const label = (() => {
    if (isLoading) return loadingLabel;
    if (isEmpty && emptyLabel) return emptyLabel;
    if (isMulti) {
      return multiSelected.length > 0
        ? multiSelected.map((o) => o.label).join(", ")
        : placeholder;
    }
    if (selected) return selected.label;
    return placeholder;
  })();

  const candidateLabels = useMemo(() => {
    const labels = new Set<string>([placeholder]);
    if (resetLabel) labels.add(resetLabel);
    if (isLoading || loadingLabel) labels.add(loadingLabel);
    if (emptyLabel) labels.add(emptyLabel);
    for (const o of flatOptions) labels.add(o.label);
    return Array.from(labels);
  }, [
    placeholder,
    resetLabel,
    isLoading,
    loadingLabel,
    emptyLabel,
    flatOptions,
  ]);

  const trimmedQuery = query.trim().toLowerCase();
  const matches = useCallback(
    (s: string) => s.toLowerCase().includes(trimmedQuery),
    [trimmedQuery],
  );

  const creatableName = useMemo(() => {
    if (!createOption) return null;
    const typed = query.trim();
    if (!typed) return null;
    const taken = flatOptions.some(
      (o) => o.label.trim().toLowerCase() === typed.toLowerCase(),
    );
    return taken ? null : typed;
  }, [createOption, query, flatOptions]);

  const filteredGroups = useMemo(() => {
    if (!groups) return null;
    if (!trimmedQuery) return groups;
    return groups
      .map((g) => ({
        ...g,
        options: g.options.filter((o) => matches(o.label)),
      }))
      .filter((g) => g.options.length > 0);
  }, [groups, trimmedQuery, matches]);

  const filteredOptions = useMemo(() => {
    if (groups) return null;
    if (!trimmedQuery) return options;
    return options.filter((o) => matches(o.label));
  }, [groups, options, trimmedQuery, matches]);

  const hasAnyResults =
    (filteredGroups?.length ?? 0) > 0 || (filteredOptions?.length ?? 0) > 0;

  const select = (next: T | null) => {
    if (isMulti && next !== null) {
      onToggleValue?.(next);
      return;
    }
    onChange(next);
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  const triggerStateClass = isDisabled
    ? "cursor-not-allowed border-border text-disabled-foreground"
    : selected || multiSelected.length > 0
      ? "border-accent-border text-accent hover:bg-accent-soft"
      : "border-border text-foreground hover:bg-surface-muted";

  const triggerClass = triggerClassName
    ? `${triggerClassName} ${className ?? ""}`.trim()
    : `${TRIGGER_BASE} ${TRIGGER_SIZE[size]} ${triggerStateClass} ${
        className ?? ""
      }`.trim();

  const title = disabled
    ? (disabledReason ?? undefined)
    : isEmpty
      ? (emptyLabel ?? undefined)
      : undefined;

  const popoverStyle: CSSProperties | undefined = portal
    ? {
        position: "fixed",
        top: coords?.top ?? 0,
        left: coords?.left ?? 0,
        minWidth: coords?.width,
        maxWidth: 360,
        visibility: coords ? "visible" : "hidden",
      }
    : inlineMaxHeight
      ? { maxHeight: inlineMaxHeight, overflowY: "auto" }
      : undefined;

  const popoverClass = portal
    ? `z-50 origin-top rounded-xl border border-border bg-surface p-2 shadow-lg ${
        popoverClassName ?? ""
      }`.trim()
    : `absolute left-0 z-20 max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-surface p-2 shadow-lg ${
        dropUp ? "bottom-full mb-2 origin-bottom" : "top-full mt-2 origin-top"
      } ${popoverClassName ?? "w-60"}`;

  const renderMenu = (menu: ReactNode) =>
    portal ? createPortal(menu, document.body) : menu;

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        disabled={isDisabled || isLoading}
        onClick={() => {
          setQuery("");
          setIsOpen((o) => !o);
        }}
        onKeyDown={onTriggerKeyDown}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label={ariaLabel ?? placeholder}
        title={title}
        className={triggerClass}
      >
        {selected?.leading ??
          (triggerLeading === false ? null : (
            <span
              className={
                isDisabled
                  ? "text-disabled-foreground"
                  : triggerClassName
                    ? ""
                    : "text-foreground"
              }
              aria-hidden="true"
            >
              {triggerLeading ?? (
                <Filter className="h-3.5 w-3.5" aria-hidden="true" />
              )}
            </span>
          ))}
        <span
          className={`grid min-w-0 ${
            isDisabled
              ? "text-disabled-foreground"
              : triggerClassName
                ? ""
                : "text-foreground"
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
        {(!isEmpty || topAction) && (
          <ChevronDown
            className={`ml-auto h-4 w-4 shrink-0 transition-transform duration-200 ${
              triggerClassName ? "opacity-70" : "text-disabled-foreground"
            } ${isOpen ? "rotate-180" : ""}`}
            aria-hidden="true"
          />
        )}
      </button>

      {renderMenu(
        <AnimatePresence>
          {isOpen && (
            <motion.div
              ref={popoverRef}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.16, ease: [0.4, 0, 0.2, 1] }}
              role="listbox"
              aria-label={ariaLabel ?? placeholder}
              onKeyDown={onPopoverKeyDown}
              style={popoverStyle}
              className={popoverClass}
            >
              {searchPlaceholder && (
                <div className="mb-1 pb-1">
                  <SearchInput
                    value={query}
                    onChange={setQuery}
                    placeholder={searchPlaceholder}
                    size="sm"
                    inputRef={searchInputRef}
                    wrapperClassName="block w-full"
                  />
                </div>
              )}
              <ul className="flex max-h-72 flex-col gap-1 overflow-y-auto">
                {creatableName && (
                  <li>
                    <button
                      type="button"
                      disabled={createOption?.disabled}
                      onClick={() => {
                        createOption?.onCreate(creatableName);
                        setQuery("");
                        setIsOpen(false);
                      }}
                      className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-accent transition-colors hover:bg-surface-muted focus:outline-hidden focus-visible:bg-surface-muted disabled:cursor-not-allowed disabled:text-disabled-foreground disabled:hover:bg-transparent"
                    >
                      <Plus className="h-3.5 w-3.5 shrink-0" aria-hidden />
                      <span className="flex-1 truncate text-left">
                        {createOption?.label?.(creatableName) ??
                          `Create "${creatableName}"`}
                      </span>
                    </button>
                  </li>
                )}
                {topAction && !trimmedQuery && (
                  <li>
                    <button
                      type="button"
                      disabled={topAction.disabled}
                      onClick={() => {
                        topAction.onClick();
                        setIsOpen(false);
                      }}
                      className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-foreground transition-colors hover:bg-surface-muted focus:outline-hidden focus-visible:bg-surface-muted disabled:cursor-not-allowed disabled:text-disabled-foreground disabled:hover:bg-transparent"
                    >
                      {topAction.leading}
                      <span className="flex-1 truncate text-left">
                        {topAction.label}
                      </span>
                    </button>
                  </li>
                )}
                {resetLabel && !trimmedQuery && (
                  <Row isSelected={value === null} onClick={() => select(null)}>
                    {triggerLeading ?? (
                      <Filter
                        className="h-3.5 w-3.5 shrink-0 text-foreground"
                        aria-hidden="true"
                      />
                    )}
                    <span className="flex-1 truncate text-left">
                      {resetLabel}
                    </span>
                    {value === null && (
                      <Check
                        className="h-3.5 w-3.5 text-accent"
                        aria-hidden="true"
                      />
                    )}
                  </Row>
                )}
                {filteredGroups
                  ? filteredGroups.map((g, gIdx) => (
                      <li key={`group-${g.label}-${gIdx}`}>
                        <p className="px-3 pt-2 pb-1 text-[10px] font-semibold tracking-wider text-disabled-foreground uppercase">
                          {g.label}
                        </p>
                        <ul className="flex flex-col gap-1">
                          {g.options.map((o) => {
                            const isSelected = isOptionSelected(o);
                            const trailing = renderOptionTrailing?.(
                              o,
                              isSelected,
                              () => setIsOpen(false),
                            );
                            return (
                              <Row
                                key={String(o.value)}
                                isSelected={isSelected}
                                onClick={() => select(o.value)}
                                disabled={o.disabled}
                                trailing={trailing}
                              >
                                {o.leading}
                                <span className="flex-1 truncate text-left">
                                  {o.label}
                                </span>
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
                      </li>
                    ))
                  : (filteredOptions ?? []).map((o) => {
                      const isSelected = isOptionSelected(o);
                      const trailing = renderOptionTrailing?.(
                        o,
                        isSelected,
                        () => setIsOpen(false),
                      );
                      return (
                        <Row
                          key={String(o.value)}
                          isSelected={isSelected}
                          onClick={() => select(o.value)}
                          disabled={o.disabled}
                          trailing={trailing}
                        >
                          {o.leading}
                          <span className="flex-1 truncate text-left">
                            {o.label}
                          </span>
                          {isSelected && (
                            <Check
                              className="h-3.5 w-3.5 text-accent"
                              aria-hidden="true"
                            />
                          )}
                        </Row>
                      );
                    })}
                {trimmedQuery && !hasAnyResults && !creatableName && (
                  <li>
                    <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                      {noResultsLabel}
                    </p>
                  </li>
                )}
                {!trimmedQuery && isEmpty && !creatableName && emptyLabel && (
                  <li>
                    <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                      {emptyLabel}
                    </p>
                  </li>
                )}
              </ul>
              {footer && (
                <div className="mt-1 border-t border-border px-3 pt-2 text-xs">
                  {footer}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>,
      )}
    </div>
  );
}

function Row({
  isSelected,
  onClick,
  disabled,
  children,
  trailing,
}: {
  isSelected: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
  trailing?: ReactNode;
}) {
  const baseRowClass = `flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-foreground transition-colors focus:outline-hidden focus-visible:bg-surface-muted disabled:cursor-not-allowed disabled:text-disabled-foreground disabled:hover:bg-transparent ${
    isSelected
      ? "bg-surface-muted hover:bg-surface-muted"
      : "hover:bg-surface-muted"
  }`;

  if (trailing) {
    return (
      <li
        className={`flex items-center rounded-md ${isSelected ? "bg-surface-muted" : "hover:bg-surface-muted"}`}
      >
        <button
          type="button"
          role="option"
          aria-selected={isSelected}
          disabled={disabled}
          onClick={onClick}
          className="flex flex-1 items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium text-foreground transition-colors focus:outline-hidden focus-visible:bg-surface-muted disabled:cursor-not-allowed disabled:text-disabled-foreground"
        >
          {children}
        </button>
        <span className="pr-1">{trailing}</span>
      </li>
    );
  }
  return (
    <li>
      <button
        type="button"
        role="option"
        aria-selected={isSelected}
        disabled={disabled}
        onClick={onClick}
        className={`w-full ${baseRowClass}`}
      >
        {children}
      </button>
    </li>
  );
}
