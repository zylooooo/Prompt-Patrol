import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ToastContext } from "../hooks/useToast";

const TOAST_MS = 3500;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const showToast = useCallback((msg: string) => {
    setMessage(msg);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(null), TOAST_MS);
  }, []);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="fixed right-6 bottom-6 z-50"
      >
        {message && (
          <button
            type="button"
            onClick={() => setMessage(null)}
            className="animate-toastIn flex items-center gap-3 rounded-lg bg-primary py-3 pr-5 pl-4 text-sm text-primary-foreground shadow-lg transition focus:outline-hidden focus-visible:ring-2 focus-visible:ring-focus-ring/30"
          >
            <span
              aria-hidden
              className="h-4 w-[3px] rounded-full bg-accent-soft"
            />
            {message}
          </button>
        )}
      </div>
    </ToastContext.Provider>
  );
}
