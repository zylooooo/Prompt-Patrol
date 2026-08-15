import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type AriaRole,
  type HTMLProps,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import {
  FloatingFocusManager,
  FloatingPortal,
  autoUpdate,
  flip,
  offset,
  shift,
  size,
  useClick,
  useDismiss,
  useFloating,
  useInteractions,
  useListNavigation,
  useRole,
  useTransitionStyles,
  useTypeahead,
} from "@floating-ui/react";
import SearchInput from "./SearchInput";
import { Check, ChevronDown, Filter, Plus } from "lucide-react";

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
  matchTriggerWidth?: boolean;
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
  "inline-flex items-center gap-2 rounded-lg border bg-surface px-3 text-sm font-medium transition-colors focus-visible:bg-accent-soft";

const TRIGGER_SIZE = {
  md: "h-9",
  lg: "h-11",
} as const satisfies Record<string, string>;

export type DropdownSize = keyof typeof TRIGGER_SIZE;

const TYPEAHEAD_RESET_MS = 700;
const TRANSITION_MS = 160;
const GAP = 8;
const EDGE = 8;
const MIN_HEIGHT = 160;

type Row<T> =
  | { kind: "create"; name: string; disabled: boolean }
  | { kind: "action"; disabled: boolean }
  | { kind: "reset"; disabled: false }
  | {
      kind: "option";
      option: DropdownOption<T>;
      group?: string;
      disabled: boolean;
    };

export default function Dropdown<T>({
  value,
  onChange,
  options,
  placeholder,
  size: triggerSize = "md",
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
  matchTriggerWidth = false,
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
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const [query, setQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const searchable = Boolean(searchPlaceholder);

  const flatOptions = useMemo(
    () => (groups ? groups.flatMap((g) => g.options) : options),
    [groups, options],
  );
  const isEmpty = !isLoading && flatOptions.length === 0;
  const isDisabled = disabled || (isEmpty && !topAction && !createOption);
  const isMulti = multiValues !== undefined;

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

  const rows = useMemo<Row<T>[]>(() => {
    const next: Row<T>[] = [];
    if (creatableName)
      next.push({
        kind: "create",
        name: creatableName,
        disabled: Boolean(createOption?.disabled),
      });
    if (topAction && !trimmedQuery)
      next.push({ kind: "action", disabled: Boolean(topAction.disabled) });
    if (resetLabel && !trimmedQuery)
      next.push({ kind: "reset", disabled: false });
    if (filteredGroups) {
      for (const g of filteredGroups)
        for (const option of g.options)
          next.push({
            kind: "option",
            option,
            group: g.label,
            disabled: Boolean(option.disabled),
          });
    } else {
      for (const option of filteredOptions ?? [])
        next.push({
          kind: "option",
          option,
          disabled: Boolean(option.disabled),
        });
    }
    return next;
  }, [
    creatableName,
    createOption?.disabled,
    topAction,
    trimmedQuery,
    resetLabel,
    filteredGroups,
    filteredOptions,
  ]);

  const blocks = useMemo(() => {
    const out: { group?: string; items: { row: Row<T>; index: number }[] }[] =
      [];
    rows.forEach((row, index) => {
      const group = row.kind === "option" ? row.group : undefined;
      const last = out.at(-1);
      if (last && last.group === group) last.items.push({ row, index });
      else out.push({ group, items: [{ row, index }] });
    });
    return out;
  }, [rows]);

  const isOptionSelected = useCallback(
    (o: DropdownOption<T>): boolean =>
      isMulti
        ? (multiValues ?? []).some((v) => Object.is(o.value, v))
        : value !== null && Object.is(o.value, value),
    [isMulti, multiValues, value],
  );

  const selectedIndex = useMemo(() => {
    if (isMulti) return null;
    const i = rows.findIndex(
      (r) => r.kind === "option" && isOptionSelected(r.option),
    );
    return i === -1 ? null : i;
  }, [rows, isMulti, isOptionSelected]);

  const disabledIndices = useMemo(
    () => rows.flatMap((row, i) => (row.disabled ? [i] : [])),
    [rows],
  );

  const { refs, floatingStyles, context } = useFloating({
    open: isOpen,
    onOpenChange: (open) => {
      setIsOpen(open);
      if (!open) setQuery("");
    },
    placement: "bottom-start",
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(GAP),
      flip({ padding: EDGE }),
      shift({ padding: EDGE, crossAxis: true }),
      size({
        padding: EDGE,
        apply({ availableHeight, rects, elements }) {
          Object.assign(elements.floating.style, {
            maxHeight: `${Math.max(availableHeight, MIN_HEIGHT)}px`,
            ...(matchTriggerWidth
              ? { width: `${rects.reference.width}px` }
              : { minWidth: `${rects.reference.width}px` }),
          });
        },
      }),
    ],
  });

  const listRef = useRef<Array<HTMLElement | null>>([]);
  const labelsRef = useRef<Array<string | null>>([]);

  const rowLabels = useMemo(
    () =>
      rows.map((row) => {
        if (row.kind === "option") return row.option.label;
        if (row.kind === "reset") return resetLabel ?? null;
        if (row.kind === "action") return topAction?.label ?? null;
        return null;
      }),
    [rows, resetLabel, topAction],
  );

  useEffect(() => {
    labelsRef.current = rowLabels;
    listRef.current.length = rowLabels.length;
  }, [rowLabels]);

  const click = useClick(context, { enabled: !isDisabled && !isLoading });
  const dismiss = useDismiss(context);
  const role = useRole(context, {
    role: searchable ? "dialog" : "listbox",
  });
  const listNav = useListNavigation(context, {
    listRef,
    activeIndex,
    selectedIndex,
    onNavigate: setActiveIndex,
    disabledIndices,
    loop: true,
    virtual: searchable,
    scrollItemIntoView: true,
  });
  const typeahead = useTypeahead(context, {
    listRef: labelsRef,
    activeIndex,
    selectedIndex,
    onMatch: setActiveIndex,
    onTypingChange: setIsTyping,
    enabled: !searchable,
    resetMs: TYPEAHEAD_RESET_MS,
  });

  const { getReferenceProps, getFloatingProps, getItemProps } = useInteractions(
    [click, dismiss, role, listNav, typeahead],
  );

  const { isMounted, styles: transitionStyles } = useTransitionStyles(context, {
    duration: TRANSITION_MS,
    initial: ({ side }) => ({
      opacity: 0,
      transform: side === "top" ? "translateY(4px)" : "translateY(-4px)",
    }),
    common: ({ side }) => ({
      transformOrigin: side === "top" ? "bottom" : "top",
    }),
  });

  const setTriggerRef = useCallback(
    (node: HTMLButtonElement | null) => refs.setReference(node),
    [refs],
  );
  const setFloatingRef = useCallback(
    (node: HTMLDivElement | null) => refs.setFloating(node),
    [refs],
  );

  const selected =
    !isMulti && value !== null
      ? (flatOptions.find((o) => Object.is(o.value, value)) ?? null)
      : null;
  const multiSelected = isMulti
    ? flatOptions.filter((o) =>
        (multiValues ?? []).some((v) => Object.is(o.value, v)),
      )
    : [];

  const label = (() => {
    if (isLoading) return loadingLabel;
    if (isEmpty && emptyLabel) return emptyLabel;
    if (isMulti)
      return multiSelected.length > 0
        ? multiSelected.map((o) => o.label).join(", ")
        : placeholder;
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

  const close = () => setIsOpen(false);

  const select = (next: T | null) => {
    if (isMulti && next !== null) {
      onToggleValue?.(next);
      return;
    }
    onChange(next);
    setIsOpen(false);
  };

  const activateRow = (index: number | null) => {
    const row = index === null ? undefined : rows[index];
    if (!row || row.disabled) return;
    switch (row.kind) {
      case "create":
        createOption?.onCreate(row.name);
        setQuery("");
        setIsOpen(false);
        return;
      case "action":
        topAction?.onClick();
        setIsOpen(false);
        return;
      case "reset":
        select(null);
        return;
      case "option":
        select(row.option.value);
    }
  };

  const triggerStateClass = isDisabled
    ? "cursor-not-allowed border-border text-disabled-foreground"
    : selected || multiSelected.length > 0
      ? "border-accent-border text-accent hover:bg-accent-soft"
      : "border-border text-foreground hover:bg-surface-muted";

  const triggerClass = triggerClassName
    ? `${triggerClassName} ${className ?? ""}`.trim()
    : `${TRIGGER_BASE} ${TRIGGER_SIZE[triggerSize]} ${triggerStateClass} ${
        className ?? ""
      }`.trim();

  const title = disabled
    ? (disabledReason ?? undefined)
    : isEmpty
      ? (emptyLabel ?? undefined)
      : undefined;

  const hasResults = rows.some((r) => r.kind === "option");
  const menuLabel = ariaLabel ?? placeholder;

  const emptyMessage =
    creatableName !== null
      ? null
      : trimmedQuery
        ? hasResults
          ? null
          : noResultsLabel
        : isEmpty
          ? (emptyLabel ?? null)
          : null;

  const onCommitKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!isOpen) return;
    const isSpace = event.key === " " && !searchable && !isTyping;
    if (event.key !== "Enter" && !isSpace) return;
    event.preventDefault();
    if (activeIndex === null) {
      setIsOpen(false);
      return;
    }
    activateRow(activeIndex);
  };

  const allFloatingProps = getFloatingProps({ onKeyDown: onCommitKeyDown });
  const floatingId = allFloatingProps.id as string | undefined;
  const ownListboxId = useId();
  const listboxId = searchable ? ownListboxId : floatingId;
  const floatingProps = {
    ...allFloatingProps,
    role: searchable ? (allFloatingProps.role as AriaRole) : undefined,
    id: searchable ? floatingId : undefined,
    "aria-label": searchable ? menuLabel : undefined,
    "aria-orientation": undefined,
    "aria-activedescendant": undefined,
  };
  const optionId = (index: number) => `${ownListboxId}-opt-${index}`;
  const activeOptionId =
    activeIndex === null ? undefined : optionId(activeIndex);

  const renderRow = (row: Row<T>, index: number) => {
    const shared = {
      ref: (node: HTMLElement | null) => {
        listRef.current[index] = node;
        return () => {
          listRef.current[index] = null;
        };
      },
      active: activeIndex === index,
      disabled: row.disabled,
      focusable: !searchable,
      id: optionId(index),
      itemProps: getItemProps({ onClick: () => activateRow(index) }),
    };

    if (row.kind === "create")
      return (
        <Row key={`create-${row.name}`} {...shared} className="text-accent">
          <Plus className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="flex-1 truncate text-left">
            {createOption?.label?.(row.name) ?? `Create "${row.name}"`}
          </span>
        </Row>
      );

    if (row.kind === "action")
      return (
        <Row key="top-action" {...shared}>
          {topAction?.leading}
          <span className="flex-1 truncate text-left">{topAction?.label}</span>
        </Row>
      );

    if (row.kind === "reset")
      return (
        <Row key="reset" {...shared} selected={value === null}>
          {triggerLeading ?? (
            <Filter
              className="h-3.5 w-3.5 shrink-0 text-foreground"
              aria-hidden="true"
            />
          )}
          <span className="flex-1 truncate text-left">{resetLabel}</span>
          {value === null && (
            <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
          )}
        </Row>
      );

    const { option } = row;
    const isSelected = isOptionSelected(option);
    return (
      <Row
        key={`option-${String(option.value)}`}
        {...shared}
        selected={isSelected}
        trailing={renderOptionTrailing?.(option, isSelected, close)}
      >
        {option.leading}
        <span className="flex-1 truncate text-left">{option.label}</span>
        {isSelected && (
          <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
        )}
      </Row>
    );
  };

  return (
    <div className="relative">
      <button
        ref={setTriggerRef}
        type="button"
        disabled={isDisabled || isLoading}
        aria-label={menuLabel}
        title={title}
        className={triggerClass}
        {...getReferenceProps({ onKeyDown: onCommitKeyDown })}
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

      {isMounted && (
        <FloatingPortal>
          <FloatingFocusManager
            context={context}
            modal={false}
            initialFocus={searchable ? searchInputRef : -1}
            returnFocus
          >
            <div
              ref={setFloatingRef}
              style={floatingStyles}
              className={`z-50 max-w-[calc(100vw-2rem)] ${
                popoverClassName ?? (matchTriggerWidth ? "" : "w-60")
              }`}
              {...floatingProps}
            >
              <div
                style={transitionStyles}
                className="flex max-h-[inherit] w-full flex-col overflow-hidden rounded-xl border border-border bg-surface p-2 shadow-lg"
              >
                {searchPlaceholder !== undefined && (
                  <div className="mb-1 shrink-0 pb-1">
                    <SearchInput
                      value={query}
                      onChange={setQuery}
                      placeholder={searchPlaceholder}
                      size="sm"
                      inputRef={searchInputRef}
                      wrapperClassName="block w-full"
                      combobox={{
                        controls: listboxId ?? "",
                        activeOptionId,
                      }}
                    />
                  </div>
                )}

                <div
                  id={listboxId}
                  role="listbox"
                  aria-label={menuLabel}
                  aria-orientation="vertical"
                  aria-multiselectable={isMulti || undefined}
                  className="flex max-h-72 min-h-0 flex-1 flex-col gap-1 overflow-y-auto"
                >
                  {blocks.map((block, blockIndex) =>
                    block.group === undefined ? (
                      block.items.map(({ row, index }) => renderRow(row, index))
                    ) : (
                      <div
                        key={`group-${block.group}-${blockIndex}`}
                        role="group"
                        aria-label={block.group}
                        className="flex flex-col gap-1"
                      >
                        <p
                          aria-hidden="true"
                          className="px-3 pt-2 pb-1 text-[10px] font-semibold tracking-wider text-disabled-foreground uppercase"
                        >
                          {block.group}
                        </p>
                        {block.items.map(({ row, index }) =>
                          renderRow(row, index),
                        )}
                      </div>
                    ),
                  )}
                </div>

                {emptyMessage && (
                  <p
                    role="status"
                    className="shrink-0 px-3 py-6 text-center text-xs text-muted-foreground"
                  >
                    {emptyMessage}
                  </p>
                )}

                {footer && (
                  <div className="mt-1 shrink-0 border-t border-border px-3 pt-2 text-xs">
                    {footer}
                  </div>
                )}
              </div>
            </div>
          </FloatingFocusManager>
        </FloatingPortal>
      )}
    </div>
  );
}

function Row({
  ref,
  id,
  active,
  selected = false,
  disabled = false,
  focusable,
  itemProps,
  className,
  children,
  trailing,
}: {
  ref: (node: HTMLElement | null) => void;
  id: string;
  active: boolean;
  selected?: boolean;
  disabled?: boolean;
  focusable: boolean;
  itemProps: HTMLProps<HTMLDivElement>;
  className?: string;
  children: ReactNode;
  trailing?: ReactNode;
}) {
  const fill = disabled
    ? ""
    : active
      ? "bg-accent-soft"
      : selected
        ? "bg-surface-muted"
        : "hover:bg-surface-muted";

  const base = `flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm font-medium outline-hidden transition-colors ${
    disabled
      ? "cursor-not-allowed text-disabled-foreground"
      : "cursor-pointer text-foreground"
  } ${fill} ${className ?? ""}`;

  const row = (
    <div
      ref={ref}
      id={id}
      role="option"
      aria-selected={selected}
      aria-disabled={disabled || undefined}
      tabIndex={focusable ? (active ? 0 : -1) : undefined}
      className={trailing ? `flex-1 ${base}` : base}
      {...itemProps}
    >
      {children}
    </div>
  );

  if (!trailing) return row;

  return (
    <div role="presentation" className={`flex items-center rounded-md ${fill}`}>
      {row}
      <span className="pr-1">{trailing}</span>
    </div>
  );
}
