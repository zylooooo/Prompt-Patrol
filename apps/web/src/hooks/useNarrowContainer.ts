import { useCallback, useEffect, useRef, useState } from "react";

export function useNarrowContainer(maxWidth: number) {
  const [isNarrow, setIsNarrow] = useState(false);
  const observerRef = useRef<ResizeObserver | null>(null);

  useEffect(() => () => observerRef.current?.disconnect(), []);

  const ref = useCallback(
    (node: HTMLElement | null) => {
      observerRef.current?.disconnect();
      observerRef.current = null;
      if (!node || typeof ResizeObserver === "undefined") return;
      const measure = (width: number) =>
        setIsNarrow(width > 0 && width < maxWidth);
      measure(node.getBoundingClientRect().width);
      const observer = new ResizeObserver((entries) => {
        const width = entries[0]?.contentRect.width;
        if (width !== undefined) measure(width);
      });
      observer.observe(node);
      observerRef.current = observer;
    },
    [maxWidth],
  );

  return { ref, isNarrow };
}
