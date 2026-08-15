import { useEffect, useState } from "react";

export function useShowAfter(active: boolean, delayMs: number): boolean {
  const [elapsed, setElapsed] = useState(false);
  const [wasActive, setWasActive] = useState(active);

  if (wasActive !== active) {
    setWasActive(active);
    if (elapsed) setElapsed(false);
  }

  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => setElapsed(true), delayMs);
    return () => clearTimeout(timer);
  }, [active, delayMs]);

  return active && elapsed;
}
