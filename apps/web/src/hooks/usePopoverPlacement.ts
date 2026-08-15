import { useLayoutEffect, useState, type RefObject } from "react";

export interface PopoverPlacement {
  dropUp: boolean;
  maxHeight: number | null;
}

const MARGIN = 8;
const CLOSED: PopoverPlacement = { dropUp: false, maxHeight: null };

export function usePopoverPlacement(
  isOpen: boolean,
  triggerRef: RefObject<HTMLElement | null>,
  popoverRef: RefObject<HTMLElement | null>,
  { enabled = true }: { enabled?: boolean } = {},
): PopoverPlacement {
  const [placement, setPlacement] = useState<PopoverPlacement>(CLOSED);

  useLayoutEffect(() => {
    if (!enabled || !isOpen) return;
    const trigger = triggerRef.current;
    const popover = popoverRef.current;
    if (!trigger || !popover) return;

    const measure = () => {
      const rect = trigger.getBoundingClientRect();
      const popoverH = popover.scrollHeight;
      const roomBelow = window.innerHeight - rect.bottom - MARGIN * 2;
      const roomAbove = rect.top - MARGIN * 2;
      const fitsBelow = popoverH <= roomBelow;
      const dropUp = !fitsBelow && roomAbove > roomBelow;
      const room = dropUp ? roomAbove : roomBelow;
      setPlacement({
        dropUp,
        maxHeight: popoverH > room ? Math.max(room, 160) : null,
      });
    };

    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [enabled, isOpen, triggerRef, popoverRef]);

  return enabled && isOpen ? placement : CLOSED;
}
