import { useCallback, useState } from "react";
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
  useRole,
} from "@floating-ui/react";
import { SECTION_LABEL } from "./ui/section-label";

interface Props {
  /** Display names, in the order the server lists the links. Non-empty. */
  names: string[];
  onEdit: () => void;
}

function spoken(names: string[]): string {
  return names.length === 1
    ? names[0]
    : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * A TA's supervisors in one table cell. The first name shows; the rest sit
 * behind a "+N" chip that opens a read-only list, so rows keep one height
 * however many instructors share the TA. Editing stays in SupervisorsDialog.
 */
export default function SupervisorList({ names, onEdit }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const { refs, floatingStyles, context } = useFloating({
    open: isOpen,
    onOpenChange: setIsOpen,
    placement: "bottom-start",
    whileElementsMounted: autoUpdate,
    middleware: [offset(6), flip({ padding: 8 }), shift({ padding: 8 })],
  });
  const setTriggerRef = useCallback(
    (node: HTMLButtonElement | null) => refs.setReference(node),
    [refs],
  );
  const setFloatingRef = useCallback(
    (node: HTMLDivElement | null) => refs.setFloating(node),
    [refs],
  );
  const { getReferenceProps, getFloatingProps } = useInteractions([
    useClick(context),
    useDismiss(context),
    useRole(context, { role: "dialog" }),
  ]);

  const first = (
    <span className="min-w-0 truncate text-[13px] text-muted-foreground">
      {names[0]}
    </span>
  );
  if (names.length === 1) return first;

  return (
    <span className="flex min-w-0 items-center gap-1.5">
      {first}
      <button
        ref={setTriggerRef}
        type="button"
        aria-label={`Supervised by ${spoken(names)}`}
        {...getReferenceProps()}
        className="shrink-0 rounded-full bg-secondary-soft px-2 py-0.5 text-xs font-medium text-secondary transition-colors hover:bg-primary-soft hover:text-primary focus-visible:bg-primary-soft focus-visible:text-primary aria-expanded:bg-primary-soft aria-expanded:text-primary"
      >
        +{names.length - 1}
      </button>
      {isOpen && (
        <FloatingPortal>
          <FloatingFocusManager context={context} modal={false}>
            <div
              ref={setFloatingRef}
              style={floatingStyles}
              aria-label={`Supervised by ${names.length}`}
              {...getFloatingProps()}
              className="z-50 w-max max-w-[18rem] min-w-[12rem] rounded-xl border border-border bg-surface p-1.5 shadow-lg outline-hidden"
            >
              <p className={`px-3 pt-2 pb-1 ${SECTION_LABEL}`}>
                Supervised by {names.length}
              </p>
              <ul className="max-h-60 overflow-y-auto">
                {names.map((name, i) => (
                  <li
                    key={`${i}-${name}`}
                    className="px-3 py-1.5 text-[13px] break-words text-foreground"
                  >
                    {name}
                  </li>
                ))}
              </ul>
              <div className="mt-1 border-t border-border pt-1">
                <button
                  type="button"
                  onClick={() => {
                    setIsOpen(false);
                    // Same as RowActionMenu: let the popover hand focus back
                    // before the dialog opens, or the chip takes it back.
                    window.setTimeout(onEdit, 0);
                  }}
                  className="flex w-full items-center rounded-md px-3 py-2 text-left text-[13px] font-medium text-foreground outline-hidden transition-colors hover:bg-surface-muted focus-visible:bg-surface-muted"
                >
                  Edit supervisors…
                </button>
              </div>
            </div>
          </FloatingFocusManager>
        </FloatingPortal>
      )}
    </span>
  );
}
