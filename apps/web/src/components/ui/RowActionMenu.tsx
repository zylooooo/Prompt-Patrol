import { useCallback, useEffect, useRef, useState } from "react";
import {
  FloatingFocusManager,
  FloatingPortal,
  autoUpdate,
  flip,
  offset,
  shift,
  useClick,
  useDismiss,
  useFloating,
  useInteractions,
  useListNavigation,
  useRole,
  useTypeahead,
} from "@floating-ui/react";
import { MoreHorizontal } from "lucide-react";

export interface RowActionMenuItem {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  destructive?: boolean;
}

interface RowActionMenuProps {
  items: RowActionMenuItem[];
  ariaLabel: string;
  disabled?: boolean;
}

const GAP = 6;
const EDGE = 8;

/**
 * A row's less-frequent actions, tucked behind one icon button instead of
 * more text links than the column can hold. The item list grows with what
 * this row can do (role, status) without the column ever needing to.
 */
export default function RowActionMenu({
  items,
  ariaLabel,
  disabled = false,
}: RowActionMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const listRef = useRef<Array<HTMLElement | null>>([]);
  const labelsRef = useRef<Array<string | null>>(items.map((i) => i.label));

  useEffect(() => {
    labelsRef.current = items.map((i) => i.label);
    listRef.current.length = items.length;
  }, [items]);

  const { refs, floatingStyles, context } = useFloating({
    open: isOpen,
    onOpenChange: setIsOpen,
    placement: "bottom-end",
    whileElementsMounted: autoUpdate,
    middleware: [offset(GAP), flip({ padding: EDGE }), shift({ padding: EDGE })],
  });

  const disabledIndices = items.flatMap((item, i) => (item.disabled ? [i] : []));

  const click = useClick(context, { enabled: !disabled });
  const dismiss = useDismiss(context);
  const role = useRole(context, { role: "menu" });
  const listNav = useListNavigation(context, {
    listRef,
    activeIndex,
    onNavigate: setActiveIndex,
    disabledIndices,
    loop: true,
  });
  const typeahead = useTypeahead(context, {
    listRef: labelsRef,
    activeIndex,
    onMatch: setActiveIndex,
  });

  const { getReferenceProps, getFloatingProps, getItemProps } = useInteractions([
    click,
    dismiss,
    role,
    listNav,
    typeahead,
  ]);

  const setTriggerRef = useCallback(
    (node: HTMLButtonElement | null) => refs.setReference(node),
    [refs],
  );
  const setFloatingRef = useCallback(
    (node: HTMLDivElement | null) => refs.setFloating(node),
    [refs],
  );

  if (items.length === 0) return null;

  const activate = (item: RowActionMenuItem) => {
    if (item.disabled) return;
    setIsOpen(false);
    item.onClick();
  };

  return (
    <>
      <button
        ref={setTriggerRef}
        type="button"
        disabled={disabled}
        aria-label={ariaLabel}
        {...getReferenceProps()}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-primary-soft hover:text-primary focus-visible:bg-primary-soft disabled:pointer-events-none disabled:opacity-45"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
      </button>
      {isOpen && (
        <FloatingPortal>
          <FloatingFocusManager context={context} modal={false}>
            <div
              ref={setFloatingRef}
              style={floatingStyles}
              {...getFloatingProps()}
              className="z-50 min-w-[10rem] overflow-hidden rounded-xl border border-border bg-surface p-1.5 shadow-lg"
            >
              {items.map((item, index) => (
                <button
                  key={item.label}
                  ref={(node) => {
                    listRef.current[index] = node;
                  }}
                  type="button"
                  role="menuitem"
                  disabled={item.disabled}
                  {...getItemProps({ onClick: () => activate(item) })}
                  className={`flex w-full items-center rounded-md px-3 py-2 text-left text-[13px] font-medium outline-hidden transition-colors disabled:pointer-events-none disabled:opacity-45 ${
                    index === activeIndex ? "bg-surface-muted" : ""
                  } ${
                    item.destructive
                      ? "text-danger hover:bg-danger-soft"
                      : "text-foreground hover:bg-surface-muted"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </FloatingFocusManager>
        </FloatingPortal>
      )}
    </>
  );
}
