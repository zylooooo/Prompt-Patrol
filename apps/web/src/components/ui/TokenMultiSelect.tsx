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
import { Check, ChevronDown, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

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

const GAP = 8;
const EDGE = 8;
const MIN_HEIGHT = 160;
const TRANSITION_MS = 160;
const TYPEAHEAD_RESET_MS = 700;

export default function TokenMultiSelect({
  choices,
  selected,
  onChange,
  placeholder,
  width = "w-64",
}: TokenMultiSelectProps) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  const { refs, floatingStyles, context } = useFloating({
    open,
    onOpenChange: setOpen,
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
            minWidth: `${rects.reference.width}px`,
          });
        },
      }),
    ],
  });

  const listRef = useRef<Array<HTMLElement | null>>([]);
  const labelsRef = useRef<Array<string | null>>([]);
  useEffect(() => {
    labelsRef.current = choices.map((c) => c.label);
    listRef.current.length = choices.length;
  }, [choices]);

  const click = useClick(context);
  const dismiss = useDismiss(context, {
    outsidePress: (event) => !boxRef.current?.contains(event.target as Node),
  });
  const role = useRole(context, { role: "listbox" });
  const listNav = useListNavigation(context, {
    listRef,
    activeIndex,
    onNavigate: setActiveIndex,
    loop: true,
    scrollItemIntoView: true,
  });
  const typeahead = useTypeahead(context, {
    listRef: labelsRef,
    activeIndex,
    onMatch: setActiveIndex,
    onTypingChange: setIsTyping,
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

  const setBoxRef = useCallback(
    (node: HTMLDivElement | null) => {
      boxRef.current = node;
      refs.setPositionReference(node);
    },
    [refs],
  );
  const setTriggerRef = useCallback(
    (node: HTMLButtonElement | null) => {
      triggerRef.current = node;
      refs.setReference(node);
    },
    [refs],
  );
  const setFloatingRef = useCallback(
    (node: HTMLDivElement | null) => refs.setFloating(node),
    [refs],
  );

  const labelFor = (value: string) =>
    choices.find((choice) => choice.value === value)?.label ?? value;

  const toggle = (value: string) =>
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value],
    );

  const onCommitKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (!open || activeIndex === null) return;
    if (event.key !== "Enter" && !(event.key === " " && !isTyping)) return;
    event.preventDefault();
    const choice = choices[activeIndex];
    if (choice) toggle(choice.value);
  };

  const allFloatingProps = getFloatingProps({ onKeyDown: onCommitKeyDown });
  const listboxId = allFloatingProps.id as string | undefined;
  const floatingProps = {
    ...allFloatingProps,
    role: undefined,
    id: undefined,
    "aria-orientation": undefined,
  };

  return (
    <div className={`relative ${width}`}>
      <div
        ref={setBoxRef}
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
                onMouseDown={(event) => event.preventDefault()}
                onClick={(event) => {
                  if (event.currentTarget === document.activeElement) {
                    triggerRef.current?.focus();
                  }
                  onChange(selected.filter((v) => v !== value));
                }}
                className="rounded-sm p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:bg-accent-soft focus-visible:text-foreground"
              >
                <X aria-hidden className="h-3 w-3" />
              </button>
            </span>
          ))}
        </span>

        <button
          ref={setTriggerRef}
          type="button"
          aria-label={placeholder}
          className="flex flex-1 items-center justify-between gap-2 self-stretch rounded-sm px-1 text-left focus-visible:bg-accent-soft"
          {...getReferenceProps({ onKeyDown: onCommitKeyDown })}
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

      {isMounted && (
        <FloatingPortal>
          <FloatingFocusManager
            context={context}
            modal={false}
            initialFocus={-1}
            returnFocus
          >
            <div
              ref={setFloatingRef}
              style={floatingStyles}
              className="z-50 max-w-[calc(100vw-2rem)]"
              {...floatingProps}
            >
              <div
                style={transitionStyles}
                className="flex max-h-[inherit] w-full flex-col overflow-hidden rounded-lg border border-border bg-surface py-1.5 shadow-lg"
              >
                <div
                  id={listboxId}
                  role="listbox"
                  aria-orientation="vertical"
                  aria-multiselectable="true"
                  aria-label={placeholder}
                  className="min-h-0 flex-1 overflow-y-auto"
                >
                  {choices.map((choice, index) => {
                    const isSelected = selected.includes(choice.value);
                    const isActive = activeIndex === index;
                    return (
                      <div
                        key={choice.value}
                        ref={(node) => {
                          listRef.current[index] = node;
                          return () => {
                            listRef.current[index] = null;
                          };
                        }}
                        role="option"
                        aria-selected={isSelected}
                        tabIndex={isActive ? 0 : -1}
                        className={`flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm outline-hidden ${
                          isActive
                            ? "bg-accent-soft"
                            : isSelected
                              ? "bg-surface-muted"
                              : "hover:bg-surface-muted"
                        } ${isSelected ? "font-medium text-foreground" : "text-foreground"}`}
                        {...getItemProps({
                          onClick: () => toggle(choice.value),
                        })}
                      >
                        <span
                          aria-hidden="true"
                          className={`flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[3px] border ${
                            isSelected
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-input-border"
                          }`}
                        >
                          {isSelected && <Check className="h-2.5 w-2.5" />}
                        </span>
                        {choice.label}
                      </div>
                    );
                  })}
                </div>

                {choices.length === 0 && (
                  <p
                    role="status"
                    className="shrink-0 px-3 py-2 text-sm text-disabled-foreground"
                  >
                    Nobody available.
                  </p>
                )}
              </div>
            </div>
          </FloatingFocusManager>
        </FloatingPortal>
      )}
    </div>
  );
}
